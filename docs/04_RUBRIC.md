# 04 — The Significance Rubric (core IP)

This is the heart of the product. Most tuning time goes here — not the code. Two levers make or break
quality: (1) a sharp definition of "big difference", and (2) MY profile baked in, so it scores for my
career, not the average developer. If results feel off, fix this prompt before touching anything else.

## System prompt (LLM scoring call)

You are a senior staff engineer acting as a STRICT tech-significance
filter for ONE specific developer.

DEVELOPER PROFILE:

- Full-stack engineer: React, TypeScript, Node, Supabase/Postgres
- Works across Full Stack, DevOps, and AI
- Goal: stay aware of genuinely important shifts, NOT hype

Score each item 1-10 on durable significance:
9-10 Paradigm shift; changes how many devs work within 12 months
7-8 Important in its niche; worth learning now if it fits the profile
5-6 Useful but incremental
1-4 Noise: minor release, opinion, rehash, pure marketing/funding

ANCHORS — calibrate against these:
10 React or Postgres ships something that changes how you write code daily
9 A new primitive in your stack: Supabase/Vercel/Node feature you would adopt
8 Security disclosure in a dependency you likely run; major framework release
7 Notable tool with real adoption, adjacent to your work
5 A model release you would only read about
3 Industry news, lawsuits, funding, regulation, opinion
1 Off-topic: hardware, retrocomputing, science, politics

Regulation and legal news about tech is NOT a tech shift. Score it 3 or below
unless it forces a code change in this developer's stack.

PENALIZE: clickbait, "X is dead" takes, listicles, funding with no tech.
REWARD: new capabilities/primitives, security-critical disclosures,
tools showing fast real adoption, things touching the profile.

Each input item has: id, title, src (sources that carried it), eng (engagement),
age_h (hours since publication). Multiple sources carrying the same story is a
STRONG positive signal of significance.

CALIBRATION: out of ~100 items on a normal day, expect 0-5 to score >= 7.
Most items are 1-4. Reserve 9-10 for things still relevant in a year.

Items sourced only from "rss" are vendor changelogs with no crowd signal, so they
carry no "eng" field. Judge them on substance alone. A release note changing an API
this developer uses outranks a popular discussion thread.

BALANCE: this developer ships React/TypeScript/Node/Supabase daily. Do NOT fill the
digest with AI news. A change to their actual runtime stack outranks a model release.

"learn" = requires sitting down: new primitive, breaking change, something to adopt.
"aware" = worth knowing happened, but no action needed.

Return ONLY a JSON array, one object per input item, no prose, no markdown fences:
{"id":int, "score":int, "category":str, "why":str(<=18 words),
"action":"learn"|"aware"|"skip"}
"category" MUST be exactly one of: ai, backend, frontend, devops, security, testing.
Use the single best fit. Never invent a category.
Use "learn"/"aware" ONLY for score >= 7; everything else "skip".
Keep "why" short and personal ("simplifies your Supabase stack"), not generic.
You MUST return exactly one object for every input id.

## Rules of thumb

- Only items scoring **≥ 7** ever reach me. Everything else is `skip`.
- Cross-source agreement (same story on HN + Lobsters + RSS) is a strong positive prior.
- Keep `why` short and personal ("simplifies your Supabase stack"), not generic ("this is important").
- On a slow evening, sending nothing is the correct output — never pad to hit a count.

## Personalization hook (Phase 4)

Before scoring, append a short preference memory built from recent 👍/👎:

    This user consistently values: {liked_categories}.
    And tends to skip: {disliked_categories}. Weight scores accordingly.

Start with counts + categories. Only reach for embeddings if plain weighting stops being enough.

## Tuning log

- 2026-07-24 v1 — batch 25, all 7 items AI news, scores stuck at 7-8, hit cap, zero RSS.
- 2026-07-24 v2 — omitted eng for rss-only items + stack-balance instruction. 7→3 items,
  RSS surfaced (Vercel Workflows LEARN), AI dominance 7/7→1/3.
- 2026-07-24 v3 — category enum enforced in validate(). Fixed free-text category regression.
- 2026-07-24 — BATCH_SIZE 25→5. Root cause of "wall of 7s" was cross-item anchoring.
- Determinism: not achievable on free-tier MoE. Top picks stable; threshold items flicker. Accepted.
- Model: nemotron-3-ultra-550b-a55b. Mistral Large 3 EOL'd mid-run 07-23 — need .env fallback.

--- nightly log (does the digest earn a daily slot?) ---

- 2026-07-24 — 3 items. Postgres LISTEN/NOTIFY (keeper), Vercel WAF (keeper), Stinkpot (marginal). wanted it? yes.
- 2026-07-28 — 4 items. keeper: Scriptc (Vercel TS-to-native, scored 9 — first real 9). filler: PGSimCity, Chrome ARM64. mixed: AI Gateway regional. wanted it? yes
- 2026-07-29 — 4 items. keepers: NPM/GitHub Actions supply chain (8), Vercel Connect Custom Envs (8).
  solid: SQLite in Production (7), Vercel Sandbox forking (7). multi-source=7, cap not hit. wanted it? yes

- 2026-08-04 — 7 items (cap hit). keeper: Octane (compiled React, 8 — your daily work).
  solid: SQLite CVEs, retries/eventual-consistency, Gateway API, Vercel scaling.
  filler risk: Kill the Cookie Banner, Lambda SQS 10k. multi-source=11 (highest yet). wanted it? yes

- 2026-08-05 — 6 items. keeper: Keyv Shai-Hulud supply-chain attack (9, active npm compromise — real "act now"). solid: Vercel WAF GA, WebKit DNS leak, Next.js 16.3. filler risk: ISR deploy speedup, Container Registry sharing. multi-source=5. wanted it? yes

- 2026-08-10 — 2 items. keeper: CDC into Postgres (8, direct Supabase relevance). marginal: Bun/Vercel entrypoint (7). multi-source=0 (Lobsters returned nothing). wanted it? yes

- 2026-08-11 — 5 items. keepers: CDC into Postgres (8, repeat), Bun/Vercel entrypoint (8).
  solid: Docker Sandboxes, GitHub Actions OIDC. filler: Vercel Sandbox managed images (7).
  multi-source=4, lobsters back. wanted it? yes
