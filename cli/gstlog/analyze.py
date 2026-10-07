"""Turn evidence into a diagnosis: LLM first, offline heuristic as fallback."""

from __future__ import annotations

import json
import re
from typing import Optional

from gstlog.catalog import match
from gstlog.evidence import Evidence
from gstlog.llm import LLMError, Provider
from gstlog.redact import redact

SYSTEM_PROMPT = (
    "You diagnose failing GStreamer pipelines. You receive the pipeline description, the "
    "test failure message and a short, deduplicated excerpt of the GStreamer debug log "
    "(items E1, E2, ...; [xN] means an ERROR/WARN line repeated N times, [ctx] is context "
    "before the first problem, [sig xN] is a DEBUG/INFO line with a classic trouble phrase such "
    "as 'queue is full' or 'leaking', repeated N times: not an error by itself, but it can be "
    "the cause when the failure raises no ERROR/WARN). Identify the most likely root cause using ONLY this evidence. If the "
    "evidence only shows a symptom, say so. Answer with a single JSON object with keys: "
    '"summary" (1-2 sentences), "root_cause" (short phrase), "confidence" ("high", '
    '"medium" or "low"), "evidence" (list of item ids such as "E1" that support it), '
    '"recommendation" (one concrete action).'
)

CONFIDENCE = {"high", "medium", "low"}


def hint_lines(evidence: Evidence, failure: Optional[str] = None, limit: int = 3) -> list:
    return [f"{m.cause} [{m.rule.id}]. Suggested action: {m.recommendation}"
            for m in match(evidence, failure)[:limit]]


def build_user_prompt(evidence: Evidence, pipeline: Optional[str], failure: Optional[str],
                      do_redact: bool = True, hints: Optional[list] = None) -> str:
    parts = []
    if pipeline:
        parts.append(f"Pipeline:\n{pipeline.strip()}")
    if failure:
        parts.append(f"Test failure message:\n{failure.strip()[:500]}")
    if hints:
        parts.append("Hints from a catalog of common GStreamer errors (they may be wrong; "
                     "verify them against the evidence):\n" + "\n".join(f"- {h}" for h in hints))
    parts.append("Log evidence:\n" + (evidence.text or "(no ERROR/WARN or trouble-phrase lines found)"))
    text = "\n\n".join(parts)
    return redact(text) if do_redact else text


def _parse_answer(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("answer is not a JSON object")
    for key in ("summary", "confidence", "recommendation"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"missing or empty field {key!r}")
    data["confidence"] = data["confidence"].strip().lower()
    if data["confidence"] not in CONFIDENCE:
        raise ValueError("confidence must be high, medium or low")
    ev = data.get("evidence", [])
    data["evidence"] = [str(e) for e in ev] if isinstance(ev, list) else []
    data.setdefault("root_cause", "")
    return data


def heuristic(evidence: Evidence, failure: Optional[str] = None) -> dict:
    """Offline diagnosis from the catalog: the baseline an LLM has to beat."""
    matches = match(evidence, failure)
    if matches:
        m = matches[0]
        from_severe = m.item is not None and m.item.kind == "severe"
        if m.rule.score >= 85 and from_severe:
            confidence = "high"
        elif m.rule.score >= 60:
            confidence = "medium"
        else:
            confidence = "low"
        detail = f" Evidence: {m.item.line.message[:140]}" if m.item else ""
        return {"summary": f"{m.cause}.{detail}", "root_cause": m.cause, "confidence": confidence,
                "evidence": m.refs, "recommendation": m.recommendation}
    severe = evidence.severe
    if not severe:
        return {"summary": "No ERROR/WARN lines or known trouble phrases found in the log.",
                "root_cause": "unknown", "confidence": "low", "evidence": [],
                "recommendation": "Raise GST_DEBUG for the suspect category and retry."}
    first = severe[0].line
    return {"summary": f"First problem: {first.message[:200]}", "root_cause": "unclassified",
            "confidence": "low", "evidence": ["E1"],
            "recommendation": f"Inspect {first.file}:{first.src_line} ({first.func})."}


def analyze(evidence: Evidence, provider: Optional[Provider], pipeline: Optional[str] = None,
            failure: Optional[str] = None, do_redact: bool = True, use_hints: bool = True) -> dict:
    if provider is None:
        return {**heuristic(evidence, failure), "source": "heuristic"}
    hints = hint_lines(evidence, failure) if use_hints else None
    prompt = build_user_prompt(evidence, pipeline, failure, do_redact, hints)
    try:
        answer = _parse_answer(provider.complete(SYSTEM_PROMPT, prompt))
        return {**answer, "source": f"llm:{provider.name}"}
    except (LLMError, ValueError, json.JSONDecodeError) as e:
        return {**heuristic(evidence, failure), "source": f"heuristic (LLM failed: {e})"}
