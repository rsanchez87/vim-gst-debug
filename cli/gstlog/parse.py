"""Parse the standard GStreamer debug line into fields.

    0:00:00.059592 434 0x5620512a94b0 ERROR  GST_PIPELINE gst/parse/grammar.y:630:gst_parse_element_make:<el> msg
    ts             pid thread         level  category     file:lineno:function:<element> message

Lines that do not match (multi-line messages, noise) are skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Iterator, Optional

LEVEL_RANK = {
    "ERROR": 0, "WARN": 1, "FIXME": 2, "INFO": 3,
    "DEBUG": 4, "LOG": 5, "TRACE": 6, "MEMDUMP": 7,
}

_LINE = re.compile(
    r"^(?P<ts>\d+:\d{2}:\d{2}\.\d+)\s+(?P<pid>\d+)\s+(?P<thread>0x[0-9a-fA-F]+)\s+"
    r"(?P<level>[A-Z]+)\s+(?P<category>\S+)\s+(?P<file>\S+?):(?P<src_line>\d+):"
    r"(?P<func>[^:\s]*):(?:<(?P<element>[^>]*)>)?\s?(?P<message>.*)$"
)


@dataclass
class LogLine:
    number: int  # 1-based line number in the file
    ts: str
    seconds: float
    pid: int
    thread: str
    level: str
    category: str
    file: str
    src_line: int
    func: str
    element: Optional[str]
    message: str
    raw: str

    @property
    def rank(self) -> int:
        return LEVEL_RANK.get(self.level, 99)


def _seconds(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_lines(lines: Iterable[str]) -> Iterator[LogLine]:
    for number, raw in enumerate(lines, start=1):
        raw = raw.rstrip("\n")
        m = _LINE.match(raw)
        if not m:
            continue
        g = m.groupdict()
        yield LogLine(
            number=number, ts=g["ts"], seconds=_seconds(g["ts"]), pid=int(g["pid"]),
            thread=g["thread"], level=g["level"], category=g["category"], file=g["file"],
            src_line=int(g["src_line"]), func=g["func"], element=g["element"],
            message=g["message"], raw=raw,
        )


def parse_file(path: str) -> list[LogLine]:
    with open(path, encoding="utf-8", errors="replace") as f:
        return list(parse_lines(f))
