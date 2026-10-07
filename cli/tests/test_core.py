from gstlog.evidence import extract
from gstlog.parse import parse_file, parse_lines
from gstlog.redact import redact


def test_parse_fields_and_skips_garbage(logfile):
    lines = parse_file(logfile)
    assert len(lines) == 6  # the non-log line is skipped
    first = lines[0]
    assert (first.level, first.category, first.func, first.element) == ("INFO", "filesrc", "gst_file_src_start", "filesrc0")
    assert first.file == "gstfilesrc.c" and first.src_line == 465 and first.seconds == 0.1


def test_parse_without_element():
    (l,) = parse_lines(["0:00:01.5 1 0x1 ERROR GST_PIPELINE grammar.y:630:gst_parse_element_make: no element \"x\""])
    assert l.element is None and l.message == 'no element "x"'


def test_evidence_dedupes_and_keeps_context(logfile):
    ev = extract(parse_file(logfile), context=2)
    severe = ev.severe
    assert [i.count for i in severe] == [1, 2, 1]  # the two "No value transform N" collapse
    assert any(i.context for i in ev.items) and ev.text.startswith("E1 [ctx]")


def test_evidence_budget_truncates(logfile):
    ev = extract(parse_file(logfile), max_bytes=200)
    assert ev.truncated and "truncated" in ev.text


def test_window_drops_late_problems(logfile):
    ev = extract(parse_file(logfile), window=0.0)
    assert len(ev.severe) == 1


def test_redact():
    out = redact('open /home/alice/x from 10.1.2.3 and 127.0.0.1 mail a@b.com rtsp://u:p@cam/s')
    assert "alice" not in out and "10.1.2.3" not in out and "a@b.com" not in out and "u:p" not in out
    assert "127.0.0.1" in out and "/home/<user>" in out
