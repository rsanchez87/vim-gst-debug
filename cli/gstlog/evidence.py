"""Reduce a huge GStreamer log to a compact, deduplicated evidence block.

The LLM never sees the raw log. It gets, within a size budget:
  * context  - a few lines before the first problem (same thread)
  * severe   - ERROR/WARN lines, deduplicated by signature, with counts
  * signal   - DEBUG/INFO lines whose text is a classic distress phrase (queue full,
               leaking, buffer too late...). Many real failures raise no ERROR/WARN.
Known harmless noise is dropped first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from gstlog.parse import LEVEL_RANK, LogLine

_NUM = re.compile(r"0x[0-9a-fA-F]+|\d+")
MAX_LINE_CHARS = 300

# Emitted by GStreamer's own debug serialization in almost every run: never the cause.
NOISE = [re.compile(r"No value transform to serialize field")]

# Phrases that signal trouble even when logged at DEBUG/INFO level, strongest first.
SIGNAL_PATTERNS = [
    (re.compile(r"queue is full|leaking", re.I), 3),
    (re.compile(r"too late|underrun|overrun|dropping|short read|truncated (?:file|data|stream)|timed out|not enough data|\blost\b", re.I), 2),
]
# Routine chatter that matches the phrases above but is never the cause.
SIGNAL_SKIP_CATEGORIES = {"GST_BUS", "GST_CLOCK", "GST_MESSAGE"}


def _signal_weight(line: LogLine) -> int:
    if line.category in SIGNAL_SKIP_CATEGORIES:
        return 0
    return max((w for p, w in SIGNAL_PATTERNS if p.search(line.message)), default=0)


def signature(line: LogLine) -> tuple:
    words = _NUM.sub("#", line.message).split()[:6]
    return (line.level, line.category, line.func, " ".join(words))


def _is_noise(line: LogLine) -> bool:
    return any(p.search(line.message) for p in NOISE)


@dataclass
class Item:
    line: LogLine
    kind: str = "severe"  # "context" | "severe" | "signal"
    count: int = 1

    def render(self, ref: str) -> str:
        tag = {"context": "ctx", "severe": f"x{self.count}", "signal": f"sig x{self.count}"}[self.kind]
        return f"{ref} [{tag}] L{self.line.number} {self.line.raw[:MAX_LINE_CHARS]}"


@dataclass
class Evidence:
    items: list = field(default_factory=list)
    total_lines: int = 0
    severe_lines: int = 0
    truncated: bool = False

    @property
    def text(self) -> str:
        out = [item.render(f"E{i}") for i, item in enumerate(self.items, 1)]
        if self.truncated:
            out.append("... (evidence truncated to the size budget)")
        return "\n".join(out)

    @property
    def severe(self) -> list:
        return [i for i in self.items if i.kind == "severe"]

    @property
    def signals(self) -> list:
        return [i for i in self.items if i.kind == "signal"]


def extract(
    lines: list,
    min_level: str = "WARN",
    context: int = 6,
    max_bytes: int = 6000,
    window: Optional[float] = None,
    max_signals: int = 8,
) -> Evidence:
    threshold = LEVEL_RANK[min_level]
    usable = [l for l in lines if not _is_noise(l)]
    severe = [l for l in usable if l.rank <= threshold]
    ev = Evidence(total_lines=len(lines), severe_lines=len(severe))
    items: list = []

    if severe:
        first = severe[0]
        if window is not None:
            severe = [l for l in severe if l.seconds <= first.seconds + window]
        ctx = [l for l in usable
               if l.number < first.number and l.thread == first.thread and l.rank > threshold]
        if context > 0:
            items += [Item(l, "context") for l in ctx[-context:]]
        dedup: dict = {}
        for l in severe:
            sig = signature(l)
            if sig in dedup:
                dedup[sig].count += 1
            else:
                dedup[sig] = Item(l, "severe")
                items.append(dedup[sig])

    signals: dict = {}
    for l in usable:
        if l.rank > threshold:
            w = _signal_weight(l)
            if not w:
                continue
            sig = signature(l)
            if sig in signals:
                signals[sig][0].count += 1
            else:
                signals[sig] = (Item(l, "signal"), w)
    best = sorted(signals.values(), key=lambda t: (-t[1], t[0].line.number))[:max_signals]
    items += [it for it, _ in sorted(best, key=lambda t: t[0].line.number)]

    used = 0
    for i, item in enumerate(items):
        size = len(item.render("E00")) + 1
        if used + size > max_bytes:
            ev.truncated = True
            items = items[:i]
            break
        used += size
    ev.items = items
    return ev
