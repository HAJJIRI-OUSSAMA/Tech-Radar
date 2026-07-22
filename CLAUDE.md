# Tech Radar — the brain

Personal tech-significance digest. Sweeps high-signal sources nightly, scores each item
against a rubric, and pushes only what genuinely matters. One verdict per item: **learn**
(sit down and study it) or **aware** (just know it happened).

Full context in `docs/01_SPEC.md` … `docs/06_PROGRESS.md`. Read `06_PROGRESS.md` before
major work and update it when something meaningful ships.

## The one thing that matters

**Curation is the product, not the app.** The hard part is telling a real shift from hype.
If the digest surfaces mediocre items, the whole thing fails. Ranking quality (sources +
the rubric in `docs/04_RUBRIC.md`) beats UI polish and new features, always.

## Working style

- Code-first. Real runnable code, not pseudocode. Files for anything over ~15 lines.
- Concise. Short rationale, then the code. The user is a full-stack engineer who shipped a
  multi-tenant biometric platform — skip beginner explanations.
- Push back. Over-engineering is the main risk after curation, especially in the feedback loop.
- Don't drift from the stack in `docs/02_ARCHITECTURE.md` without arguing for it explicitly.
- One phase at a time per `docs/03_ROADMAP.md`. Each phase de-risks the next.
- User writes French and English; reply in whichever they use. Code comments in English.

## Stack

Python 3.12 brain · Supabase (Postgres + RLS) · GitHub Actions cron · Expo/React Native
(Android only) · Telegram delivery in phase 1, Expo push in phase 3.

LLM scoring runs on NVIDIA NIM via any OpenAI-compatible endpoint.
Model: `nvidia/nemotron-3-ultra-550b-a55b`. Provider is swappable with two env vars.

## Current state — phase 1, step 1.4 complete

```
digest/
  collect.py    HN (Algolia), Reddit, Lobsters, RSS — each isolated + fail-safe
  process.py    canonical URLs, dedupe/cluster, cheap pre-filter to ~120
  score.py      LLM rubric call, batched, reasoning-model aware
  archive.py    per-run JSON: tuning ledger + Actions keepalive
  run.py        orchestrator with --no-llm / --replay / --limit / --tag
tests/          24 tests, all passing (pytest)
```

Not built yet: `notify.py` (Telegram, 1.5), `.github/workflows/nightly.yml` (1.7),
`store.py` (phase 2), the Expo app (phase 3).

**Next step is 1.5, Telegram delivery — but only after several real digests look good.**
The roadmap exit criterion is "I'd be happy to receive this daily." Transport is ~20 lines
and can wait; the rubric cannot.

## Hard rules

- **Fail-safe collectors.** Every source in try/except. One dead source ≠ broken run.
- **Quiet days stay quiet.** Zero items is correct output on a slow evening. Never pad to
  hit a count. The "nothing major today" path is a feature.
- **Threshold ≥ 7 is enforced in code**, not trusted to the model. `validate()` overwrites
  `action` to `skip` for any score below the bar.
- **Token budget.** Pre-filter must cut candidates before the LLM call. Cap ~120.
- **Secrets server-side only.** `service_role`, LLM keys, and Telegram tokens live in `.env`
  and GitHub Actions secrets. The mobile app ships the **anon key** only. Never commit `.env`.
- **RLS on from day one** for `devices` and `feedback`. `items` is read-only to clients.
- **Public repo.** Never use `pull_request_target` (runs fork code with access to secrets).
  Set `permissions:` explicitly in workflows. Never dump env into `archive/`.

## Gotchas already hit

- **Reasoning models break naive JSON parsing.** Nemotron emits a thinking trace before the
  answer. First-`[`-to-last-`]` slicing corrupts on brackets inside the trace.
  `extract_json_array` strips `<think>` blocks and scans for verdict-shaped arrays. Don't
  "simplify" it back.
- **Reasoning tokens count against `max_tokens`.** Too low a budget = the model thinks until
  truncation and emits nothing, which looks exactly like a quiet day. Check logs before
  blaming the rubric.
- **Scored ids bind to candidates once**, via an explicit map in `score()`. Never re-derive
  that alignment positionally — a silent misalignment attaches plausible scores to the wrong
  articles and the digest still reads fine.
- **Actions disables cron after 60 days** with no commits on a public repo. The nightly
  `archive/` commit is the keepalive. Don't gitignore `archive/`.
- **Supabase free tier pauses after 7 days idle.** The nightly write is the keepalive.
- **Reddit 403s from datacenter IPs.** Fine locally; may need OAuth once on Actions.

## Commands

```bash
python -m digest.run --limit 25 --tag ultra     # full run
python -m digest.run --no-llm                   # collect + filter only, zero tokens
python -m digest.run --replay 2026-07-22 --tag llama70b   # re-score archived candidates
python -m pytest tests/ -q
```

## Rubric tuning workflow

Never tune blind. Change the prompt in `score.py`, then `--replay` the same archived
candidate set and diff the picks against the previous run. Record every change and its
effect in the tuning log in `docs/04_RUBRIC.md` so you don't go in circles.

Open question: is Ultra actually better here than a smaller model? The task is taste, not
multi-step reasoning. Replay one night across `nvidia/nemotron-3-ultra-550b-a55b`,
`moonshotai/kimi-k2.6`, and `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` and compare.

## Known gap

`process.dedupe` clusters by canonical URL only, so the same story under two different URLs
(github.com/foo/bar vs foo.github.io/bar) never registers as cross-source agreement — the
strongest signal in both the pre-filter and the rubric. If `multi-source` counts come back
low on real runs, cluster titles with `nvidia/nemotron-3-embed-1b` before scoring.
