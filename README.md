# Tech Radar — the brain

A personal tech-significance digest. It sweeps high-signal sources every night, scores each
item against a rubric tuned to **one specific developer's** stack, and pushes only what
genuinely matters. Every item gets one verdict:

- 📖 **learn** — sit down and study this (new primitive, breaking change, something to adopt)
- 👁 **aware** — just know it happened, no action needed

**The one thing that matters:** curation is the product, not the app. The hard part is
telling a real shift from hype. Ranking quality (the sources + the rubric) beats UI polish
and features, always. On a slow evening the correct output is *nothing* — "nothing major
today" is a designed feature, never padded to hit a count.

## How it works

```
collect ──▶ process ──▶ score ──▶ select ──▶ archive ──▶ notify
 sources    dedupe +     LLM       ≥ 7 &      per-run     Telegram
 (4 kinds)  pre-filter   rubric    top 7      JSON        (optional)
            → ~120       → 1-10
```

| Stage | File | What it does |
|-------|------|--------------|
| **collect** | [digest/collect.py](digest/collect.py) | Pulls from Hacker News (Algolia), Reddit, Lobsters, and vendor RSS feeds. Each source is isolated in try/except — one dead source never breaks the run. Every collector emits the same normalized shape. |
| **process** | [digest/process.py](digest/process.py) | Canonicalizes URLs (strips tracking params, `www.`, fragments), dedupes/clusters across sources, then a cheap heuristic pre-filter cuts ~300 raw items down to ~120 **before** any tokens are spent. Cross-source agreement is the strongest cheap signal. |
| **score** | [digest/score.py](digest/score.py) | The make-or-break step. Sends compact items to an LLM in batches of 25 with the significance rubric as the system prompt. Returns `score` (1-10), `category`, `why`, `action`. Provider-agnostic (any OpenAI-compatible endpoint). |
| **select** | [digest/score.py](digest/score.py) | Keeps items scoring **≥ 7**, best first, capped at 7. The threshold is enforced in code — `validate()` overwrites `action` to `skip` for anything below the bar, so the model can't smuggle a low score through. |
| **archive** | [digest/archive.py](digest/archive.py) | Writes the full run to `archive/YYYY-MM-DD.json` (candidates + scores + raw responses). Two jobs: it's the tuning ledger for replay, and the nightly commit is the keepalive that stops GitHub from disabling the cron. |
| **notify** | [digest/notify.py](digest/notify.py) | Telegram delivery. Three first-class message types: `digest`, `quiet` ("nothing major today"), and `failure` (the run broke — said loudly so it never looks like a quiet day). |
| **run** | [digest/run.py](digest/run.py) | Orchestrator that wires the stages together and handles the flags below. |

### The rubric is the IP

The full significance rubric — developer profile, 1-10 anchors, calibration, and the tuning
log — lives in [docs/04_RUBRIC.md](docs/04_RUBRIC.md). The system prompt in `score.py` is the
executable copy. **Never tune blind:** change the prompt, `--replay` the same archived
candidate set, diff the picks against the previous run, and record the change and its effect
in the tuning log so you don't go in circles.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then fill in the keys you need
```

You need an LLM key for scoring. Default provider is **NVIDIA NIM** (`nvapi-` key from
[build.nvidia.com](https://build.nvidia.com), account-wide across models). The provider is
swappable with two env vars — see [.env.example](.env.example) for Groq / Gemini / Llama
baselines. Telegram delivery (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`) is optional; the
run prints to the terminal without it.

> **Reasoning-model gotcha:** Nemotron 3 Ultra emits a `<think>` trace before the answer, and
> those tokens count against `LLM_MAX_TOKENS`. Too small a budget = the model thinks until
> truncation and emits nothing — which looks *exactly* like a quiet day. If digests come back
> mysteriously empty, raise `LLM_MAX_TOKENS` or lower `LLM_BATCH_SIZE` before blaming the rubric.

## Usage

```bash
# Full nightly run: collect → process → score → select → archive
python -m digest.run

# Collect + pre-filter only, spend zero tokens (eyeball the candidates)
python -m digest.run --no-llm

# Cap candidates while iterating on the prompt (cheaper)
python -m digest.run --limit 30

# Re-score an archived night after a rubric change, tagged so A/B runs don't clobber
python -m digest.run --replay 2026-07-24 --tag ultra

# Deliver to Telegram (or preview the message without sending)
python -m digest.run --send
python -m digest.run --dry-run

# Tests
python -m pytest tests/ -q
```

| Flag | Effect |
|------|--------|
| `--no-llm` | Stop after the pre-filter. No LLM call, no tokens. |
| `--replay YYYY-MM-DD` | Re-score an archived candidate set instead of collecting fresh. |
| `--limit N` | Cap candidates before scoring. |
| `--threshold N` | Override the default score bar (7). |
| `--tag NAME` | Archive suffix, e.g. `--tag ultra` — keeps A/B model runs in separate files. |
| `--send` | Deliver the result to Telegram. |
| `--dry-run` | Print the Telegram message instead of sending it. |
| `--no-archive` | Skip writing the run JSON. |

## Stack

- **Brain:** Python 3.12 (`digest/`)
- **LLM scoring:** any OpenAI-compatible endpoint; default `nvidia/nemotron-3-ultra-550b-a55b` on NVIDIA NIM
- **Delivery:** Telegram (phase 1) → Expo push (phase 3)
- **Storage:** Supabase (Postgres + RLS) — phase 2
- **Scheduling:** GitHub Actions nightly cron — phase 1.7
- **App:** Expo / React Native, Android — phase 3

## Project status

**Phase 1** — produce a great 3-7 item digest and deliver it to Telegram. The collect →
process → score → select → archive → notify pipeline is built and tested. The exit criterion
is taste, not code: *"I'd be happy to receive this daily."* Several real digests need to look
good before the nightly cron and Supabase persistence go in.

Not built yet: `.github/workflows/nightly.yml` (1.7), `store.py` and Supabase schema
(phase 2), the Expo app (phase 3).

## Design rules that are not negotiable

- **Fail-safe collectors.** Every source in try/except. One dead source ≠ a broken run.
- **Quiet days stay quiet.** Zero items is correct output on a slow evening. Never pad.
- **Threshold ≥ 7 is enforced in code**, not trusted to the model.
- **A dead scorer must never look like a quiet day.** If 0 candidates score, the run fails
  loudly (exit 1 + a failure message), it does not silently ship an empty digest.
- **Token budget.** The pre-filter must cut candidates before the LLM call (~120 cap).
- **Secrets server-side only.** LLM keys, `service_role`, and Telegram tokens live in `.env`
  and Actions secrets. The mobile app ships the anon key only. Never commit `.env`.

See [CLAUDE.md](CLAUDE.md) for the full working notes, gotchas, and per-phase roadmap.

## Layout

```
digest/
  collect.py    HN, Reddit, Lobsters, RSS — each isolated + fail-safe
  process.py    canonical URLs, dedupe/cluster, cheap pre-filter to ~120
  score.py      LLM rubric call, batched, reasoning-model aware
  archive.py    per-run JSON: tuning ledger + Actions keepalive
  notify.py     Telegram: digest / quiet / failure messages
  run.py        orchestrator (flags above)
docs/
  04_RUBRIC.md  the significance rubric + tuning log (the core IP)
archive/        per-run JSON, committed nightly (keepalive)
tests/          pytest suite
```
