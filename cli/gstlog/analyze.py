"""Turn evidence into a diagnosis: LLM first, offline heuristic as fallback."""

from __future__ import annotations

import json
import re
from typing import Optional

from gstlog.evidence import Evidence
from gstlog.llm import LLMError, Provider
from gstlog.redact import redact

SYSTEM_PROMPT = (
    "You diagnose failing GStreamer pipelines. You receive the pipeline description, the "
    "test failure message and a short, deduplicated excerpt of the GStreamer debug log "
    "(items E1, E2, ...; [xN] means the line repeated N times, [ctx] is context before the "
    "first problem). Identify the most likely root cause using ONLY this evidence. If the "
    "evidence only shows a symptom, say so. Answer with a single JSON object with keys: "
    '"summary" (1-2 sentences), "root_cause" (short phrase), "confidence" ("high", '
    '"medium" or "low"), "evidence" (list of item ids such as "E1" that support it), '
    '"recommendation" (one concrete action).'
)

CONFIDENCE = {"high", "medium", "low"}


def build_user_prompt(evidence: Evidence, pipeline: Optional[str], failure: Optional[str],
                      do_redact: bool = True) -> str:
    parts = []
    if pipeline:
        parts.append(f"Pipeline:\n{pipeline.strip()}")
    if failure:
        parts.append(f"Test failure message:\n{failure.strip()[:500]}")
    parts.append("Log evidence:\n" + (evidence.text or "(no ERROR/WARN lines found)"))
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


# keyword -> (root cause, recommendation); the baseline the LLM must beat.
_RULES = [
    (r'no element "([^"]+)"', "Element does not exist",
     "Install the plugin that provides the element, or fix the element name in the pipeline."),
    (r"no such file|resource not found", "Input file not found",
     "Check that the file path exists and is readable by the process."),
    (r"connection refused|failed to connect", "Connection refused",
     "Check that the remote service is running and the host/port are correct."),
    (r"text file|could not determine type|not a (media|valid)", "Input is not decodable media",
     "Verify the input really is a media file of a supported format."),
    (r"can't handle caps|not-negotiated|not negotiated", "Caps cannot be negotiated",
     "Insert a converter/scaler, or relax the caps between the two elements."),
    (r"could not link", "Elements cannot be linked",
     "Check that the pads are compatible (media type), or add a converter between them."),
]


def heuristic(evidence: Evidence) -> dict:
    severe = evidence.severe
    if not severe:
        return {"summary": "No ERROR/WARN lines found in the log.", "root_cause": "unknown",
                "confidence": "low", "evidence": [],
                "recommendation": "Raise GST_DEBUG for the suspect category and retry."}
    blob = " ".join(i.line.message for i in severe).lower()
    for pattern, cause, rec in _RULES:
        m = re.search(pattern, blob)
        if m:
            idx = next((n for n, it in enumerate(evidence.items, 1)
                        if not it.context and re.search(pattern, it.line.message.lower())), 1)
            detail = f" ({m.group(1)})" if m.groups() else ""
            return {"summary": f"{cause}{detail}: {severe[0].line.message[:160]}",
                    "root_cause": cause, "confidence": "medium", "evidence": [f"E{idx}"],
                    "recommendation": rec}
    first = severe[0].line
    return {"summary": f"First problem: {first.message[:200]}", "root_cause": "unclassified",
            "confidence": "low", "evidence": ["E1"],
            "recommendation": f"Inspect {first.file}:{first.src_line} ({first.func})."}


def analyze(evidence: Evidence, provider: Optional[Provider], pipeline: Optional[str] = None,
            failure: Optional[str] = None, do_redact: bool = True) -> dict:
    if provider is None:
        return {**heuristic(evidence), "source": "heuristic"}
    prompt = build_user_prompt(evidence, pipeline, failure, do_redact)
    try:
        answer = _parse_answer(provider.complete(SYSTEM_PROMPT, prompt))
        return {**answer, "source": f"llm:{provider.name}"}
    except (LLMError, ValueError, json.JSONDecodeError) as e:
        return {**heuristic(evidence), "source": f"heuristic (LLM failed: {e})"}
