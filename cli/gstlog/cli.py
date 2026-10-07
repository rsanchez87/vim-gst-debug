"""gstlog command line: evidence | analyze | eval."""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

from gstlog import llm
from gstlog.analyze import SYSTEM_PROMPT, analyze, build_user_prompt, hint_lines
from gstlog.catalog import CATALOG
from gstlog.evidence import extract
from gstlog.parse import LEVEL_RANK, parse_file


def _add_evidence_args(p):
    p.add_argument("--min-level", default="WARN", choices=["ERROR", "WARN", "FIXME"])
    p.add_argument("--context", type=int, default=6, help="lines of context before the first problem")
    p.add_argument("--max-bytes", type=int, default=6000, help="evidence size budget")
    p.add_argument("--window", type=float, default=None,
                   help="only keep problems within N seconds after the first one")


def _add_provider_args(p):
    p.add_argument("--provider", choices=["auto", "heuristic", "llm"], default="auto")
    p.add_argument("--preset", choices=sorted(llm.PRESETS), help="deepseek | openai | ollama | custom")
    p.add_argument("--base-url", help="OpenAI-compatible base URL (e.g. a company gateway)")
    p.add_argument("--model")
    p.add_argument("--api-key-env", help="name of the env var holding the key (never the key itself)")
    p.add_argument("--no-json-mode", action="store_true", help="do not send response_format=json_object")
    p.add_argument("--no-redact", action="store_true", help="send log text without redaction")
    p.add_argument("--no-hints", action="store_true", help="do not send catalog hints to the LLM")


def _evidence(path, args):
    return extract(parse_file(path), args.min_level, args.context, args.max_bytes, args.window)


def _resolve_provider(args):
    if args.provider == "heuristic":
        return None
    try:
        provider = llm.build_provider(args.preset, args.base_url, args.model,
                                      args.api_key_env, json_mode=not args.no_json_mode)
    except llm.LLMError as e:
        if args.provider == "llm":
            raise
        print(f"note: {e}; using the offline heuristic", file=sys.stderr)
        return None
    if provider is None:
        if args.provider == "llm":
            raise llm.LLMError("no LLM configured: use --preset deepseek (and set DEEPSEEK_API_KEY)")
        print("note: no LLM configured; using the offline heuristic", file=sys.stderr)
    return provider


def _read_arg(value):
    if value and os.path.isfile(value):
        with open(value, encoding="utf-8", errors="replace") as f:
            return f.read()
    return value


def _read_file(path):
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    return None


def _junit_failure(path):
    if not path or not os.path.isfile(path):
        return None
    for node in ET.parse(path).getroot().iter("failure"):
        return node.get("message") or (node.text or "").strip()
    return None


def _print_diagnosis(d, fmt):
    if fmt == "json":
        print(json.dumps(d, indent=2))
    elif fmt == "md":
        print(f"### Diagnosis ({d['confidence']} confidence)\n\n{d['summary']}\n\n"
              f"**Root cause:** {d.get('root_cause', '')}\n\n**Recommendation:** {d['recommendation']}\n\n"
              f"_Source: {d['source']}; evidence: {', '.join(d['evidence']) or 'n/a'}_")
    else:
        print(f"summary:        {d['summary']}\nroot cause:     {d.get('root_cause', '')}\n"
              f"confidence:     {d['confidence']}"
              + (f"  (LLM said {d['llm_confidence']}: {d['confidence_note']})" if d.get("confidence_note") else "")
              + f"\nevidence:       {', '.join(d['evidence']) or 'n/a'}\n"
              f"recommendation: {d['recommendation']}\nsource:         {d['source']}")


def cmd_evidence(args):
    ev = _evidence(args.log, args)
    if args.format == "jsonl":
        for i, item in enumerate(ev.items, 1):
            print(json.dumps({"ref": f"E{i}", "count": item.count, "kind": item.kind,
                              "line": item.line.number, "level": item.line.level,
                              "category": item.line.category, "raw": item.line.raw}))
    else:
        print(ev.text)
    print(f"# {ev.total_lines} parsed lines, {ev.severe_lines} at {args.min_level} or worse, "
          f"{len(ev.items)} evidence items", file=sys.stderr)
    return 0


def cmd_analyze(args):
    ev = _evidence(args.log, args)
    pipeline = _read_arg(args.pipeline)
    failure = args.failure or _junit_failure(args.junit)
    provider = _resolve_provider(args)
    if args.dry_run:
        if provider is None:
            print("dry run: no LLM configured, nothing would be sent")
            return 0
        hints = None if args.no_hints else hint_lines(ev, failure)
        prompt = build_user_prompt(ev, pipeline, failure, not args.no_redact, hints)
        print(json.dumps(provider.request_preview(SYSTEM_PROMPT, prompt), indent=2))
        return 0
    _print_diagnosis(analyze(ev, provider, pipeline, failure, not args.no_redact, not args.no_hints), args.format)
    return 0


def cmd_rules(args):
    print(f"{'id':22} {'score':>5}  {'source':7} verified")
    for r in sorted(CATALOG, key=lambda r: -r.score):
        print(f"{r.id:22} {r.score:>5}  {r.source:7} {'yes' if r.verified else 'no'}")
    return 0


def _passes(expected, d):
    text = " ".join([d["summary"], d.get("root_cause", ""), d["recommendation"]]).lower()
    return all(any(alt.strip() and alt.strip().lower() in text for alt in group.split("|"))
               for group in expected.split(";"))


def cmd_eval(args):
    expected = {}
    with open(args.expected, encoding="utf-8") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                name, req = line.rstrip("\n").split("\t", 1)
                expected[name] = req
    provider = _resolve_provider(args)
    rows, passed = [], 0
    for name in sorted(os.listdir(args.cases)):
        d = os.path.join(args.cases, name)
        log = os.path.join(d, "gst.log")
        if name not in expected or not os.path.isfile(log):
            continue
        ev = _evidence(log, args)
        # --blind: log evidence only, as if the CI report carried no failure message
        pipeline = None if args.blind else _read_file(os.path.join(d, "pipeline.txt"))
        failure = None if args.blind else _junit_failure(os.path.join(d, "junit.xml"))
        diag = analyze(ev, provider, pipeline, failure, not args.no_redact, not args.no_hints)
        ok = _passes(expected[name], diag)
        passed += ok
        hints = None if args.no_hints or provider is None else hint_lines(ev, failure)
        sent = len(build_user_prompt(ev, pipeline, failure, not args.no_redact, hints))
        rows.append((name, diag["confidence"], "PASS" if ok else "FAIL", os.path.getsize(log), sent,
                     diag["source"][:40]))
    print(f"{'case':26} {'conf':7} {'result':6} {'log bytes':>10} {'sent bytes':>10}  source")
    for r in rows:
        print(f"{r[0]:26} {r[1]:7} {r[2]:6} {r[3]:>10} {r[4]:>10}  {r[5]}")
    by_conf = {}
    for r in rows:
        by_conf.setdefault(r[1], [0, 0])[0 if r[2] == "PASS" else 1] += 1
    print("\nconfidence vs result: " + ", ".join(
        f"{c}: {v[0]} pass / {v[1]} fail" for c, v in sorted(by_conf.items())))
    print(f"{passed}/{len(rows)} passed")
    return 0 if rows and passed == len(rows) else 1


def build_parser():
    ap = argparse.ArgumentParser(prog="gstlog", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("evidence", help="print the compact evidence extracted from a log")
    p.add_argument("log")
    p.add_argument("--format", choices=["text", "jsonl"], default="text")
    _add_evidence_args(p)
    p.set_defaults(func=cmd_evidence)

    p = sub.add_parser("analyze", help="diagnose a failure from a log")
    p.add_argument("log")
    p.add_argument("--pipeline", help="pipeline description, or a file containing it")
    p.add_argument("--failure", help="test failure message")
    p.add_argument("--junit", help="JUnit XML to take the failure message from")
    p.add_argument("--format", choices=["text", "json", "md"], default="text")
    p.add_argument("--dry-run", action="store_true", help="print exactly what would be sent, send nothing")
    _add_evidence_args(p)
    _add_provider_args(p)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("rules", help="list the catalog of known GStreamer error patterns")
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser("eval", help="run all cases in a directory against expected answers")
    p.add_argument("cases")
    p.add_argument("--expected", required=True, help="TSV: case<TAB>term|alt;term|alt")
    p.add_argument("--blind", action="store_true",
                   help="ignore pipeline.txt and junit.xml: diagnose from the log evidence alone")
    _add_evidence_args(p)
    _add_provider_args(p)
    p.set_defaults(func=cmd_eval)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (llm.LLMError, OSError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
