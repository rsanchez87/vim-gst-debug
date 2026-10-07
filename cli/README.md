# gstlog

Turn a multi-GB GStreamer debug log into a few KB of evidence, and (optionally) ask any
OpenAI-compatible LLM for a diagnosis. Standard library only, Python >= 3.9.

Intended location in `vim-gst-debug`: a top-level `cli/` folder (Vim ignores unknown
top-level directories, so plugin loading is unaffected).

```
log (GBs) -> parse -> ERROR/WARN + context -> dedupe by signature -> redact -> LLM -> JSON
                                                                  \-> offline heuristic (fallback)
```

## Install

```bash
cd cli && pip install -e .          # or run in place: python3 -m gstlog ...
```

## Use

```bash
# 1. What would be extracted? (no LLM involved)
gstlog evidence pipeline.log

# 2. What exactly would be sent to the provider? Sends NOTHING.
export DEEPSEEK_API_KEY=...          # your own key, never passed on the command line
gstlog analyze pipeline.log --pipeline "gst-launch-1.0 ..." --junit results.xml \
       --preset deepseek --dry-run

# 3. Diagnose
gstlog analyze pipeline.log --pipeline pipeline.txt --junit results.xml --preset deepseek
gstlog analyze pipeline.log --format md        # Markdown for a CI job summary

# 4. Measure it on a set of cases (log + pipeline.txt + junit.xml per directory)
gstlog eval ../gst-cases --expected examples/expected.tsv --preset deepseek
gstlog eval ../gst-cases --expected examples/expected.tsv --provider heuristic   # baseline

# Harder cases: the cause is not in an ERROR (07, 08) or is buried in a WARN (09)
gstlog eval ../hard --expected ../hard/expected.tsv --preset deepseek
gstlog eval ../hard --expected ../hard/expected.tsv --provider heuristic
```

With no LLM configured, `analyze` and `eval` use the offline heuristic (a keyword baseline the
LLM has to beat). If the LLM call fails or returns an invalid answer, it falls back to the
heuristic and says so in the `source` field.

## Providers

One adapter speaks the OpenAI chat-completions protocol. Presets:

| Preset | Base URL | Model | Key env var |
|---|---|---|---|
| `deepseek` | https://api.deepseek.com | `deepseek-chat` (override with `--model`) | `DEEPSEEK_API_KEY` |
| `openai` | https://api.openai.com/v1 | required | `OPENAI_API_KEY` |
| `ollama` | http://localhost:11434/v1 | required | none |
| `custom` | `--base-url` (e.g. a company gateway) | required | optional, `--api-key-env NAME` |

Model names change often: check your provider's current list. If the provider rejects
`response_format=json_object`, pass `--no-json-mode`; the answer is validated either way.
Supporting a non-OpenAI protocol means adding one `Provider` subclass in `gstlog/llm.py`.

## Privacy

- The raw log is never sent: only the evidence block (default budget 6 KB).
- Redaction is on by default (IPs except loopback, emails, `/home/<user>`, URL credentials).
  It is best effort and does **not** make sending logs to a third party compliant.
  Check your company policy first, and use `--dry-run` to review what leaves the machine.
- The API key is read only from an environment variable and is never printed.

## Limitations (v0)

- GStreamer timestamps are relative to process start; there is no anchoring to a test report
  time yet, so `--window` is relative to the first problem in the log.
- Evidence = ERROR/WARN lines + a short list of hand-picked trouble phrases found at DEBUG/INFO
  level (`queue is full`, `leaking`, `buffer too late`...; see `gstlog/evidence.py`). That covers
  stalls and silent frame loss in the bundled hard cases, but the phrase list is small: failures
  that leave no such phrase still need a new selector.
- Verified only against a mock OpenAI-compatible server (see `tests/`), not yet against the
  real DeepSeek API.

## Test

```bash
pip install pytest && pytest
```
