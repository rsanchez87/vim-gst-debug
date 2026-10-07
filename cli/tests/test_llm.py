import json

import pytest

from conftest import completion
from gstlog.analyze import analyze
from gstlog.cli import main
from gstlog.evidence import extract
from gstlog.llm import LLMError, build_provider
from gstlog.parse import parse_file

GOOD = {"summary": "File missing.", "root_cause": "input file not found", "confidence": "high",
        "evidence": ["E3"], "recommendation": "Check the path."}


def _provider(server, **kw):
    return build_provider("custom", base_url=server.url, model="m", key_env="K", env={"K": "secret-key", **kw})


def test_request_shape_matches_openai_protocol(server, logfile):
    server.reply = (200, completion(json.dumps(GOOD)))
    ev = extract(parse_file(logfile))
    out = analyze(ev, _provider(server), pipeline="filesrc location=/home/alice/clip.mp4 ! fakesink")
    req = server.requests[0]
    assert req["path"] == "/chat/completions" and req["auth"] == "Bearer secret-key"
    assert req["body"]["model"] == "m" and req["body"]["response_format"] == {"type": "json_object"}
    assert req["body"]["temperature"] == 0 and "json" in req["body"]["messages"][0]["content"].lower()
    sent = req["body"]["messages"][1]["content"]
    assert "alice" not in sent and "10.1.2.3" not in sent  # redacted before leaving
    assert out["source"].startswith("llm:") and out["confidence"] == "high"


def test_accepts_fenced_json(server, logfile):
    server.reply = (200, completion("```json\n" + json.dumps(GOOD) + "\n```"))
    assert analyze(extract(parse_file(logfile)), _provider(server))["source"].startswith("llm:")


@pytest.mark.parametrize("reply", [
    (401, {"error": "bad key"}),
    (200, b"<html>gateway</html>"),
    (200, completion("not json at all")),
    (200, completion(json.dumps({"summary": "x"}))),
    (200, completion(json.dumps({**GOOD, "confidence": "certain"}))),
    (200, {"unexpected": True}),
])
def test_falls_back_to_heuristic(server, logfile, reply):
    server.reply = reply
    out = analyze(extract(parse_file(logfile)), _provider(server))
    assert out["source"].startswith("heuristic (LLM failed") and out["recommendation"]


def test_unreachable_server_falls_back(logfile):
    p = build_provider("custom", base_url="http://127.0.0.1:1", model="m", key_env=None, env={})
    assert analyze(extract(parse_file(logfile)), p)["source"].startswith("heuristic (LLM failed")


def test_provider_config():
    assert build_provider(env={}) is None
    p = build_provider("deepseek", env={"DEEPSEEK_API_KEY": "k"})
    assert p.base_url == "https://api.deepseek.com" and p.model == "deepseek-chat"
    with pytest.raises(LLMError, match="DEEPSEEK_API_KEY"):
        build_provider("deepseek", env={})
    with pytest.raises(LLMError, match="model"):
        build_provider("ollama", env={})
    assert build_provider("ollama", model="llama3", env={}).base_url.endswith("/v1")


def test_dry_run_sends_nothing(server, logfile, capsys, monkeypatch):
    monkeypatch.setenv("K", "secret-key")
    rc = main(["analyze", logfile, "--dry-run", "--preset", "custom", "--base-url", server.url,
               "--model", "m", "--api-key-env", "K"])
    out = capsys.readouterr().out
    assert rc == 0 and server.requests == []
    assert "secret-key" not in out and "alice" not in out and "/chat/completions" in out


def test_cli_end_to_end_with_mock(server, logfile, capsys, monkeypatch):
    monkeypatch.setenv("K", "secret-key")
    server.reply = (200, completion(json.dumps(GOOD)))
    rc = main(["analyze", logfile, "--provider", "llm", "--preset", "custom", "--base-url", server.url,
               "--model", "m", "--api-key-env", "K", "--format", "json"])
    assert rc == 0 and json.loads(capsys.readouterr().out)["confidence"] == "high"
