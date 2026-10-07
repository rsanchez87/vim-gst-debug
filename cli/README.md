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

With no LLM configured, `analyze` and `eval` use the offline heuristic: a catalog of typical
GStreamer errors (`gstlog rules` lists it) that the LLM has to beat. If the LLM call fails or returns an invalid answer, it falls back to the
heuristic and says so in the `source` field.

## Catalog and hints

`gstlog/catalog.py` maps typical GStreamer error messages to a cause and a recommended action
(missing element, bad property, caps not negotiated, file not found, connection refused, port in
use, missing decoder, truncated input, leaky queue, backpressure...). It is used twice:

- as the offline heuristic (`--provider heuristic`, and the fallback when the LLM fails);
- as hints appended to the LLM prompt, labelled as possibly wrong. `--no-hints` turns them off, so
  you can measure whether they help or bias the model.

Rules marked `verified: no` in `gstlog rules` come from knowledge of GStreamer's error strings and
were not reproduced locally.

## Evaluation sets (heuristic results measured; LLM results are yours to measure)

| Set | Cases | Heuristic | Notes |
|---|---|---|---|
| `gst-cases` | 6 | 6/6 | cause is in an ERROR/WARN line |
| `hard` | 3 | 3/3 | no ERROR (stall, frame loss) or a buried WARN |
| `typical` | 10 | 10/10 | rules were written from these messages: not independent |
| `holdout` | 5 | **2/5** | errors NOT used to write rules |

Read the holdout line, not the others. In `holdout` the heuristic gave one wrong answer with `high`
confidence (`h2`: an output directory that does not exist is reported as a missing input file) and
one generic answer that only passed because an element name contains "demux". A string catalog is
brittle: it is a baseline, not a replacement for the LLM. The pass criterion is also a keyword check,
so read the actual answers.

```bash
gstlog eval ../holdout --expected ../holdout/expected.tsv --provider heuristic
gstlog eval ../holdout --expected ../holdout/expected.tsv --preset deepseek               # with hints
gstlog eval ../holdout --expected ../holdout/expected.tsv --preset deepseek --no-hints    # without
```

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
- The catalog was written from messages produced by GStreamer 1.24.2 with a few plugins; other
  versions and plugins word errors differently, and a keyword can match in the wrong context
  (`No such file` also appears when an *output* directory is missing).
- Verified only against a mock OpenAI-compatible server (see `tests/`), not yet against the
  real DeepSeek API.

## Test

```bash
pip install pytest && pytest
```

## Results so far (DeepSeek `deepseek-chat`, 2026-10-07)

| Set | Heuristic | LLM + hints | LLM, no hints |
|---|---|---|---|
| holdout (5), pipeline + report | 2/5 | 5/5 | 5/5 |
| holdout (5), log only (`--blind`) | 2/5 | 4/5 | 4/5 |
| hard (3), log only | n/a | 3/3 | not measured |

Findings (8 synthetic cases: enough to show the method, not to quote a rate):

- Hints do not change pass rates but change recommendations. With a specific, correct rule
  (queue leaking/backpressure) the advice improves ("enlarging the queue only delays the stall").
  With a generic rule (`link-failed`) they can mislead: for an invalid caps format the hint made the
  model suggest a converter, while without hints it pointed at the caps filter.
- The LLM's `confidence` is not calibrated: the one wrong holdout answer (`h3`) was `high`. Its cause
  (an invalid format name) is probably not derivable from the log alone.
- The catalog heuristic can be wrong with `high` confidence (`h2`, holdout): it is a baseline.
