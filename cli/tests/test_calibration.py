import json

from conftest import completion
from gstlog.analyze import analyze, calibrate, evidence_ceiling
from gstlog.llm import build_provider
from test_catalog import evidence


def diag(conf="high", refs=("E1",)):
    return {"summary": "s", "root_cause": "r", "confidence": conf, "evidence": list(refs), "recommendation": "x"}


def test_ceiling_tiers():
    assert evidence_ceiling(evidence(("ERROR", 'no element "foo"')))[0] == "high"
    assert evidence_ceiling(evidence(("ERROR", "could not link a0 to b0")))[0] == "medium"
    assert evidence_ceiling(evidence(("DEBUG", "queue is full, leaking item 0x1 on downstream end")))[0] == "medium"
    assert evidence_ceiling(evidence(("WARN", "error: Internal data stream error.")))[0] == "low"
    assert evidence_ceiling(evidence(("WARN", "something nobody has seen before")))[0] == "low"
    assert evidence_ceiling(evidence())[0] == "low"


def test_high_is_capped_by_weak_evidence():
    ev = evidence(("ERROR", "could not link videotestsrc0 to capsfilter0"))
    out = calibrate(diag("high"), ev)
    assert out["confidence"] == "medium" and out["llm_confidence"] == "high"
    assert "capped to medium" in out["confidence_note"]


def test_strong_evidence_keeps_high():
    out = calibrate(diag("high"), evidence(("ERROR", 'no element "foo"')))
    assert out["confidence"] == "high" and out["confidence_note"] == ""


def test_never_raises_confidence():
    assert calibrate(diag("low"), evidence(("ERROR", 'no element "foo"')))["confidence"] == "low"


def test_invalid_citations_are_dropped_and_penalised():
    out = calibrate(diag("high", ("E1", "E99")), evidence(("ERROR", 'no element "foo"')))
    assert out["evidence"] == ["E1"] and out["confidence"] == "medium"


def test_no_citations_lowers_one_level():
    out = calibrate(diag("high", ()), evidence(("ERROR", 'no element "foo"')))
    assert out["confidence"] == "medium" and "no cited evidence" in out["confidence_note"]


def test_analyze_applies_calibration_to_llm_answers(server):
    answer = {"summary": "s", "root_cause": "r", "confidence": "high", "evidence": ["E1"], "recommendation": "x"}
    server.reply = (200, completion(json.dumps(answer)))
    p = build_provider("custom", base_url=server.url, model="m", env={})
    out = analyze(evidence(("WARN", "something nobody has seen before")), p)
    assert out["confidence"] == "low" and out["llm_confidence"] == "high"
