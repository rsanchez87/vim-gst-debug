"""Catalog of typical GStreamer errors: pattern -> cause -> recommended action.

Used two ways: as an offline heuristic (the baseline an LLM must beat) and as
optional hints for the LLM. Rules marked verified=False come from knowledge of
GStreamer's error strings and have not been reproduced locally yet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Rule:
    id: str
    patterns: tuple  # compiled; ALL must match some evidence item, the first anchors the line
    score: int  # specificity: a root cause outranks a generic wrapper
    cause: str  # may use {named groups} and {element}
    recommendation: str
    source: str = "log"  # "log" = evidence lines, "failure" = the test failure message
    verified: bool = True


def _r(id, patterns, score, cause, rec, source="log", verified=True) -> Rule:
    pats = patterns if isinstance(patterns, (list, tuple)) else [patterns]
    return Rule(id, tuple(re.compile(p, re.I) for p in pats), score, cause, rec, source, verified)


CATALOG = [
    # --- pipeline construction -------------------------------------------------
    _r("no-such-element", r'no element "(?P<name>[^"]+)"', 95,
       "Element '{name}' does not exist",
       "Check the element name; if it is a real element, install the plugin that provides it (gst-inspect-1.0 {name})."),
    _r("bad-property-value", r'could not set property "(?P<prop>[^"]+)" in element "(?P<el>[^"]+)" to "(?P<val>[^"]*)"', 92,
       "Invalid value '{val}' for property '{prop}' of '{el}'",
       "Check the allowed values (gst-inspect-1.0 {el}) and fix the pipeline."),
    _r("unknown-property", r'no property "(?P<prop>[^"]+)" in element "(?P<el>[^"]+)"', 92,
       "Element '{el}' has no property '{prop}'",
       "Check the property name and the plugin version (gst-inspect-1.0 {el})."),
    _r("caps-rejected", r"(?P<el>\S+) can't handle caps (?P<caps>.+)", 90,
       "{el} cannot handle the requested caps ({caps})",
       "Insert a converter or scaler before it, or relax the caps filter."),
    _r("link-failed", r"could not link (?P<a>\S+) to (?P<b>[^\s,]+)", 80,
       "{a} and {b} cannot be linked (incompatible pads)",
       "Check that both pads carry compatible media types; add a converter (videoconvert, audioconvert...) between them."),
    _r("delayed-link-failed", r"failed delayed linking some pad of (?P<a>.+?) to some pad of (?P<b>.+)$", 88,
       "A dynamic pad of {a} could not be linked to {b}",
       "The stream type produced by the demuxer/decoder does not match what {b} accepts: link the right branch or use a sink for that stream type."),
    # --- negotiation and linking at runtime -----------------------------------
    _r("not-negotiated", r"reason not-negotiated|not-negotiated \(-4\)|caps negotiation failed", 85,
       "Caps negotiation failed at {element}",
       "Compare the caps on both sides of {element} (GST_DEBUG=GST_CAPS:5) and add a converter or change the caps filter."),
    _r("not-linked", r"reason not-linked|not-linked \(-1\)", 75,
       "{element} pushed data to a pad that is not linked",
       "Link every pad: add a sink to the dangling branch, and check that dynamic pads (demuxers, decodebin) get linked."),
    # --- resources --------------------------------------------------------------
    _r("file-not-found", r"no such file|resource not found", 90,
       "The input file does not exist or is not reachable",
       "Check the path and permissions of the file given to the source element."),
    _r("is-directory", r"is a directory", 90,
       "The location points to a directory, not a file",
       "Pass a file path to the source element."),
    _r("permission-denied", r"permission denied|not authorized", 88,
       "Access denied to the resource", "Check file permissions or credentials.", verified=False),
    _r("connection-refused", r"connection refused", 90,
       "Connection refused by the remote host",
       "Check that the remote service is running and that host and port are correct."),
    _r("cannot-resolve-host", r"could not resolve (?:server )?name|name or service not known|temporary failure in name resolution", 90,
       "The host name cannot be resolved",
       "Check the host name in the URL and the DNS/network configuration.", verified=False),
    _r("address-in-use", r"address already in use", 88,
       "The network port is already in use",
       "Free the port (another process or pipeline is bound to it) or choose a different one."),
    _r("device-busy", r"device or resource busy|resource busy or not available", 88,
       "The device is busy",
       "Find and stop the process using the device, or select another device.", verified=False),
    _r("no-space", r"no space left", 90,
       "No space left on the target", "Free disk space or write to another location.", verified=False),
    _r("http-error", r"server returned (?P<code>\d{3})|(?:unauthorized|forbidden|not found) \((?P<code2>\d{3})\)", 85,
       "The HTTP server rejected the request",
       "Check the URL and credentials; the server answered with an error status.", verified=False),
    # --- media / stream ---------------------------------------------------------
    _r("missing-decoder", r"no suitable plugins found|missing a plug-?in|missing plugin", 90,
       "No plugin is available for this stream type",
       "Install the missing decoder/demuxer plugin or convert the media to a supported format."),
    _r("typefind-failed", r"could not determine type of stream|appears to be a text file|cannot decode plain text", 88,
       "The input is not recognized as media",
       "Check that the file really is a media file of a supported format (not text, HTML or corrupted)."),
    _r("empty-input", r"stream contains no data|can't typefind empty stream", 88,
       "The input stream is empty",
       "Check why the source produced no data (empty file, failed download or capture)."),
    _r("truncated-input", r"short read|truncated file|unexpected end of file", 85,
       "The input looks truncated",
       "Re-fetch or re-record the file and compare its size with the original."),
    _r("no-valid-frames", r"no valid frames (?:found|decoded)", 80,
       "Decoder {element} received no valid frames",
       "The data fed to the decoder is not valid for it: check the input and the elements upstream."),
    # --- performance / timing ---------------------------------------------------
    _r("queue-leaking", r"queue is full, leaking|leaking item", 70,
       "Buffers are dropped by a leaky queue: downstream is slower than the source",
       "Find the slowest downstream element and fix or speed it up; enlarge the queue only if the load is bursty, and check that dropping frames is acceptable here."),
    _r("backpressure", [r"queue is full, waiting for free space", r"too late"], 65,
       "Sustained backpressure: the downstream consumer is slower than the live source",
       "Find the slowest element after the queue (processing time, sleeps, CPU load); a bigger queue only delays the stall."),
    _r("eos-timeout", r"did not reach eos|timeout|timed out", 40,
       "The pipeline never finished within the time limit",
       "Look for stalls: full queues, a blocked element, or a source that never sends EOS (rerun with GST_DEBUG=queue_dataflow:5).",
       source="failure"),
    # --- generic wrappers: the real cause is somewhere else ---------------------
    _r("generic-stream-error", r"internal data stream error|streaming stopped, reason error", 25,
       "Generic stream error from {element}: the cause is not in this evidence",
       "Raise the debug level for {element} (GST_DEBUG=<category>:6) and rerun to see the underlying error."),
    _r("start-failed", r"failed to start|doesn't want to preroll", 20,
       "The pipeline failed to start",
       "Look at the first error before this line: start failures are usually a consequence."),
]


@dataclass
class Match:
    rule: Rule
    item: Optional[object]  # evidence Item, or None when matched on the failure message
    groups: dict
    refs: list  # ["E3", ...]

    @property
    def cause(self) -> str:
        return _fill(self.rule.cause, self)

    @property
    def recommendation(self) -> str:
        return _fill(self.rule.recommendation, self)


class _Safe(dict):
    def __missing__(self, key):
        return "?"


def _element(item) -> str:
    el = getattr(getattr(item, "line", None), "element", None)
    return el.split(":")[0] if el else "the element"


def _fill(text: str, m: "Match") -> str:
    values = {k: v for k, v in m.groups.items() if v is not None}
    values["element"] = _element(m.item)
    return text.format_map(_Safe(values))


def match(evidence, failure: Optional[str] = None) -> list:
    """All catalog rules that apply, best first (specific root causes before generic wrappers)."""
    items = [(i, it) for i, it in enumerate(evidence.items, 1) if it.kind != "context"]
    found = []
    for rule in CATALOG:
        if rule.source == "failure":
            if failure:
                m = rule.patterns[0].search(failure)
                if m and all(p.search(failure) for p in rule.patterns[1:]):
                    found.append(Match(rule, None, m.groupdict(), []))
            continue
        anchors = [(i, it, rule.patterns[0].search(it.line.message)) for i, it in items]
        anchors = [a for a in anchors if a[2]]
        if not anchors:
            continue
        if not all(any(p.search(it.line.message) for _, it in items) for p in rule.patterns[1:]):
            continue
        refs = [f"E{i}" for i, it in items if any(p.search(it.line.message) for p in rule.patterns)]
        i, it, m = anchors[0]
        found.append(Match(rule, it, m.groupdict(), refs[:4]))
    found.sort(key=lambda x: (-x.rule.score, x.item.line.number if x.item else 1 << 60))
    return found
