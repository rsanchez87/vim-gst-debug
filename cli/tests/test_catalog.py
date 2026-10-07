import pytest

from conftest import completion
from gstlog.analyze import analyze, heuristic, hint_lines
from gstlog.catalog import CATALOG, match
from gstlog.evidence import extract
from gstlog.llm import build_provider
from gstlog.parse import parse_lines


def evidence(*specs):
    """specs: (level, message[, element]) -> Evidence built through the real extractor."""
    raw = []
    for n, spec in enumerate(specs):
        level, msg, *el = spec
        tag = f"<{el[0]}> " if el else " "
        raw.append(f"0:00:00.{n:03d}000000 10 0xaaa {level:5} cat file.c:1:fn:{tag}{msg}")
    return extract(list(parse_lines(raw)), context=0)


# (level, message as GStreamer emits it, expected best rule)
CASES = [
    ("ERROR", 'no element "foo"', "no-such-element"),
    ("ERROR", 'could not set property "pattern" in element "videotestsrc" to "999"', "bad-property-value"),
    ("ERROR", 'no property "x" in element "videotestsrc"', "unknown-property"),
    ("ERROR", "could not link videoconvert0 to fakesink0, videoconvert0 can't handle caps video/x-raw", "caps-rejected"),
    ("ERROR", "could not link audiotestsrc0 to videoconvert0", "link-failed"),
    ("WARN", "warning: failed delayed linking some pad of GstAviDemux named avidemux0 to some pad of GstAudioConvert named audioconvert0", "delayed-link-failed"),
    ("WARN", "error: streaming stopped, reason not-negotiated (-4)", "not-negotiated"),
    ("WARN", "error: streaming stopped, reason not-linked (-1)", "not-linked"),
    ("WARN", 'error: No such file "/data/missing.mp4"', "file-not-found"),
    ("WARN", 'error: "/tmp" is a directory.', "is-directory"),
    ("WARN", "error: Permission denied", "permission-denied"),
    ("WARN", "error: Failed to connect to host '127.0.0.1:1': Connection refused", "connection-refused"),
    ("WARN", "error: Could not resolve server name", "cannot-resolve-host"),
    ("WARN", "error: bind failed: Error binding to address 0.0.0.0:5601: Address already in use", "address-in-use"),
    ("WARN", "error: Device or resource busy", "device-busy"),
    ("WARN", "error: No space left on device", "no-space"),
    ("WARN", "error: Server returned 404 Not Found", "http-error"),
    ("WARN", "error: no suitable plugins found:", "missing-decoder"),
    ("WARN", "error: This appears to be a text file", "typefind-failed"),
    ("WARN", "error: Can't typefind empty stream", "empty-input"),
    ("WARN", "Short read at offset 800, only got 8200/9423 bytes (truncated file?)", "truncated-input"),
    ("WARN", "error: no valid frames found", "no-valid-frames"),
    ("DEBUG", "queue is full, leaking item 0x7f on downstream end", "queue-leaking"),
    ("WARN", "error: Internal data stream error.", "generic-stream-error"),
    ("WARN", "error: Failed to start", "start-failed"),
]


@pytest.mark.parametrize("level,msg,rule_id", CASES)
def test_rule_matches_real_message(level, msg, rule_id):
    ms = match(evidence((level, msg)))
    assert ms and ms[0].rule.id == rule_id


def test_every_rule_is_tested():
    tested = {rid for _, _, rid in CASES} | {"backpressure", "eos-timeout"}
    assert {r.id for r in CATALOG} == tested
    assert len({r.id for r in CATALOG}) == len(CATALOG)


def test_backpressure_needs_both_phrases():
    both = evidence(("DEBUG", "queue is full, waiting for free space"), ("DEBUG", "buffer too late!, returning anyway"))
    one = evidence(("DEBUG", "queue is full, waiting for free space"))
    assert match(both)[0].rule.id == "backpressure"
    assert not match(one)


def test_root_cause_beats_generic_wrappers():
    ev = evidence(("WARN", 'error: No such file "/x"'), ("WARN", "error: Failed to start"),
                  ("WARN", "error: Internal data stream error."))
    assert [m.rule.id for m in match(ev)] == ["file-not-found", "generic-stream-error", "start-failed"]


def test_delayed_link_beats_not_linked():
    ev = evidence(("WARN", "warning: failed delayed linking some pad of A to some pad of B"),
                  ("WARN", "error: streaming stopped, reason not-linked (-1)"))
    assert match(ev)[0].rule.id == "delayed-link-failed"


def test_failure_message_only_rule_is_lowest_priority():
    ev = evidence(("DEBUG", "queue is full, leaking item 0x1 on downstream end"))
    ms = match(ev, failure="Timeout: pipeline did not reach EOS within 5 s")
    assert [m.rule.id for m in ms] == ["queue-leaking", "eos-timeout"]
    assert heuristic(ev, "Timeout: pipeline did not reach EOS")["confidence"] == "medium"


def test_generic_error_is_honest_about_missing_cause():
    d = heuristic(evidence(("WARN", "error: Internal data stream error.", "souphttpsrc0:src")))
    assert d["confidence"] == "low" and "souphttpsrc0" in d["root_cause"] and "not in this evidence" in d["root_cause"]


def test_confidence_levels():
    assert heuristic(evidence(("ERROR", 'no element "foo"')))["confidence"] == "high"
    assert heuristic(evidence(("DEBUG", "queue is full, leaking item 0x1 on downstream end")))["confidence"] == "medium"
    assert heuristic(evidence(("WARN", "something unexpected")))["root_cause"] == "unclassified"
    assert heuristic(evidence())["root_cause"] == "unknown"


def test_hints_are_sent_unless_disabled(server):
    server.reply = (200, completion('{"summary":"s","confidence":"low","recommendation":"r"}'))
    p = build_provider("custom", base_url=server.url, model="m", env={})
    ev = evidence(("ERROR", 'no element "foo"'))
    analyze(ev, p)
    analyze(ev, p, use_hints=False)
    with_hints, without = (r["body"]["messages"][1]["content"] for r in server.requests)
    assert "Hints from a catalog" in with_hints and "no-such-element" in with_hints
    assert "Hints from a catalog" not in without
    assert hint_lines(ev)[0].startswith("Element 'foo' does not exist")
