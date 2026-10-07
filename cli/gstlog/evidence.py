"""Reduce a huge GStreamer log to a compact, deduplicated evidence block.

The LLM never sees the raw log: only ERROR/WARN lines (deduplicated by
signature, with counts) plus a few lines of context before the first one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from gstlog.parse import LEVEL_RANK, LogLine

_NUM = re.compile(r"0x[0-9a-fA-F]+|\d+")
MAX_LINE_CHARS = 300


def signature(line: LogLine) -> tuple:
    words = _NUM.sub("#", line.message).split()[:6]
    return (line.level, line.category, line.func, " ".join(words))


@dataclass
class Item:
    line: LogLine
    count: int = 1
    context: bool = False

    def render(self, ref: str) -> str:
        tag = "ctx" if self.context else f"x{self.count}"
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
        return [i for i in self.items if not i.context]


def extract(
    lines: list,
    min_level: str = "WARN",
    context: int = 6,
    max_bytes: int = 6000,
    window: Optional[float] = None,
) -> Evidence:
    threshold = LEVEL_RANK[min_level]
    severe = [l for l in lines if l.rank <= threshold]
    ev = Evidence(total_lines=len(lines), severe_lines=len(severe))
    if not severe:
        return ev

    first = severe[0]
    if window is not None:
        severe = [l for l in severe if l.seconds <= first.seconds + window]

    ctx = [l for l in lines if l.number < first.number and l.thread == first.thread and l.rank > threshold]
    items = [Item(l, context=True) for l in ctx[-context:]] if context > 0 else []

    dedup: dict = {}
    for l in severe:
        sig = signature(l)
        if sig in dedup:
            dedup[sig].count += 1
        else:
            dedup[sig] = Item(l)
            items.append(dedup[sig])

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
