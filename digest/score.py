"""LLM significance scoring — the make-or-break step (roadmap 1.4).

Provider-agnostic: talks to any OpenAI-compatible endpoint. Defaults to NVIDIA NIM.
Swap providers with two env vars, no code change:

    NIM     LLM_BASE_URL=https://integrate.api.nvidia.com/v1  LLM_MODEL=meta/llama-3.3-70b-instruct
    Groq    LLM_BASE_URL=https://api.groq.com/openai/v1       LLM_MODEL=llama-3.3-70b-versatile
    Gemini  LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
                                                              LLM_MODEL=gemini-2.5-flash

Deviation from 02_ARCHITECTURE.md ("one call"): we batch in chunks of 30. A 70B model asked
for 120 JSON objects in one response truncates mid-array and costs the whole night. Four
smaller calls fail partially instead of totally, for the same token spend.

The system prompt below is the EXECUTABLE copy of 04_RUBRIC.md. When you tune it, record the
change and its effect in the tuning log in 04_RUBRIC.md — otherwise you will go in circles.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone

log = logging.getLogger("digest.score")

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"

# Reasoning models emit a thinking trace BEFORE the answer, and those tokens count
# against max_tokens. Too low a budget = the model thinks until truncation and never
# emits JSON, which looks exactly like a quiet day. Default high; tune per model.
BATCH_SIZE = int(os.environ.get("LLM_BATCH_SIZE", 25))
MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", 16384))
MAX_RETRIES = 3
TIMEOUT = 300          # a 550B reasoning pass over 25 items is not fast

THRESHOLD = 7          # only items scoring >= 7 ever reach me (04_RUBRIC.md)
MAX_DIGEST = 7         # hard cap on digest length
VALID_ACTIONS = {"learn", "aware", "skip"}
VALID_CATEGORIES = {"ai", "backend", "frontend", "devops", "security", "testing"}

SYSTEM_PROMPT = """You are a senior staff engineer acting as a STRICT tech-significance
filter for ONE specific developer.

DEVELOPER PROFILE:
- Full-stack engineer: React, TypeScript, Node, Supabase/Postgres
- Works across Full Stack, DevOps, and AI
- Goal: stay aware of genuinely important shifts, NOT hype

Score each item 1-10 on durable significance:
  9-10 Paradigm shift; changes how many devs work within 12 months
  7-8  Important in its niche; worth learning now if it fits the profile
  5-6  Useful but incremental
  1-4  Noise: minor release, opinion, rehash, pure marketing/funding

ANCHORS — calibrate against these:
  10  React or Postgres ships something that changes how you write code daily
   9  A new primitive in your stack: Supabase/Vercel/Node feature you would adopt
   8  Security disclosure in a dependency you likely run; major framework release
   7  Notable tool with real adoption, adjacent to your work
   5  A model release you would only read about
   3  Industry news, lawsuits, funding, regulation, opinion
   1  Off-topic: hardware, retrocomputing, science, politics

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
You MUST return exactly one object for every input id."""


# ---- provider ---------------------------------------------------------------

def get_client():
    """Build an OpenAI-compatible client from env. Lazy import so collect/process
    stay usable without the SDK installed."""
    from openai import OpenAI

    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        raise RuntimeError("LLM_API_KEY is not set (get one at build.nvidia.com)")
    return OpenAI(
        base_url=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
        api_key=api_key,
        timeout=TIMEOUT,
    )


def model_name() -> str:
    return os.environ.get("LLM_MODEL", DEFAULT_MODEL)


def extra_body() -> dict:
    """Provider-specific params as JSON, e.g. to toggle reasoning:
        LLM_EXTRA_BODY={"chat_template_kwargs":{"thinking":false}}
    Kept in env rather than code so a chat-template change never needs a redeploy."""
    raw = os.environ.get("LLM_EXTRA_BODY", "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("LLM_EXTRA_BODY is not valid JSON, ignoring: %s", e)
        return {}


# ---- payload ----------------------------------------------------------------

def to_payload(candidates: list[dict], now: datetime | None = None) -> list[dict]:
    """Compact representation sent to the model. Short keys = fewer tokens.
    Titles are truncated: we score on the headline + signal, never article bodies."""
    now = now or datetime.now(timezone.utc)
    out = []
    for i, c in enumerate(candidates):
        kinds = sorted({s.split(":", 1)[0] for s in c["sources"]})
        item = {
            "id": i,
            "title": c["title"][:180],
            "src": "+".join(kinds),
            "age_h": round((now - c["published_at"]).total_seconds() / 3600),
        }
        # Vendor feeds have no crowd signal. Sending eng:0 reads as "nobody cares"
        # and buries changelogs — the best source for "did my actual stack change".
        if kinds != ["rss"]:
            item["eng"] = c["engagement"]
        out.append(item)
    return out


THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
THINK_OPEN = re.compile(r"<think>", re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """Remove <think>...</think> traces. If a trace was opened but never closed the
    response was truncated mid-thought, so there is no answer to salvage."""
    text = THINK_BLOCK.sub(" ", text)
    if THINK_OPEN.search(text):
        raise ValueError("response truncated inside an unclosed reasoning trace "
                         "(raise LLM_MAX_TOKENS or lower LLM_BATCH_SIZE)")
    return text


def extract_json_array(text: str) -> list[dict]:
    """Pull the verdict array out of a reasoning model's output.

    Naive first-[ to last-] slicing is WRONG here: a reasoning trace deliberating over
    a list will contain brackets of its own, and the resulting span silently mis-parses.
    Instead: strip traces, then try to decode an array at EVERY '[' and keep only arrays
    that actually look like verdicts (objects carrying id + score). Largest one wins.
    """
    text = strip_reasoning(text)
    decoder = json.JSONDecoder()
    best: list[dict] | None = None

    for i, ch in enumerate(text):
        if ch != "[":
            continue
        try:
            value, _ = decoder.raw_decode(text[i:])
        except ValueError:
            continue
        if not isinstance(value, list) or not value:
            continue
        if not all(isinstance(v, dict) for v in value):
            continue
        if not any("id" in v and "score" in v for v in value):
            continue                      # an incidental array from the reasoning trace
        if best is None or len(value) > len(best):
            best = value

    if best is None:
        raise ValueError("no verdict array found in response")
    return best


def validate(rows: list[dict], valid_ids: set[int]) -> dict[int, dict]:
    """Coerce and drop garbage. A malformed row must never crash the run, the model must
    never smuggle a low score past the threshold with action='learn', and categories must
    stay a fixed enum so per-category mute/toggles are possible in phase 4."""
    clean: dict[int, dict] = {}
    for row in rows:
        try:
            rid = int(row["id"])
            if rid not in valid_ids or rid in clean:
                continue
            score = max(1, min(10, int(row["score"])))
            action = str(row.get("action", "skip")).lower().strip()
            if action not in VALID_ACTIONS:
                action = "skip"
            if score < THRESHOLD:          # enforce the rubric rule ourselves
                action = "skip"
            category = str(row.get("category") or "").lower().strip()
            if category not in VALID_CATEGORIES:
                log.warning("model invented category %r, coercing to 'other'", category)
                category = "other"
            clean[rid] = {
                "score": score,
                "category": category,
                "why": str(row.get("why") or "")[:200],
                "action": action,
            }
        except (KeyError, TypeError, ValueError) as e:
            log.warning("dropping malformed row %r: %s", row, e)
    return clean


# ---- the call ---------------------------------------------------------------

def _log_reasoning_cost(resp, content: str) -> None:
    """Surface the failure mode that looks like a quiet day: the model spent its whole
    budget thinking and never got to the answer."""
    usage = getattr(resp, "usage", None)
    details = getattr(usage, "completion_tokens_details", None)
    thinking = getattr(details, "reasoning_tokens", None) if details else None
    if thinking:
        log.info("reasoning tokens: %s of %s completion tokens",
                 thinking, getattr(usage, "completion_tokens", "?"))
    if not content.strip():
        log.error("model returned empty content%s — raise LLM_MAX_TOKENS (now %d) "
                  "or lower LLM_BATCH_SIZE (now %d)",
                  f" after {thinking} reasoning tokens" if thinking else "",
                  MAX_TOKENS, BATCH_SIZE)


def score_batch(client, batch: list[dict]) -> tuple[dict[int, dict], str]:
    """One LLM call for one batch. Returns (validated results, raw text for the archive)."""
    valid_ids = {item["id"] for item in batch}
    user_msg = json.dumps(batch, ensure_ascii=False)
    raw = ""

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=model_name(),
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0,       
                max_tokens=MAX_TOKENS,
                extra_body=extra_body(),
            )
            msg = resp.choices[0].message
            raw = msg.content or ""
            _log_reasoning_cost(resp, raw)
            results = validate(extract_json_array(raw), valid_ids)
            missing = valid_ids - results.keys()
            if missing:
                log.warning("batch returned %d/%d items", len(results), len(valid_ids))
            return results, raw
        except Exception as e:
            log.warning("scoring attempt %d/%d failed: %s", attempt, MAX_RETRIES, e)
            if attempt == MAX_RETRIES:
                log.error("batch failed permanently, scoring 0 items")
                return {}, raw
            time.sleep(2 ** attempt)   # 2s, 4s
    return {}, raw


def score(candidates: list[dict], client=None) -> tuple[list[dict], list[str]]:
    """Score every candidate. Returns (candidates + score fields, raw responses).

    Fail-safe: a dead batch yields unscored items rather than an exception. Unscored
    items get score 0 and are simply never selected.
    """
    if not candidates:
        return [], []

    client = client or get_client()
    payload = to_payload(candidates)

    # Bind ids to candidates ONCE. Do not re-derive this alignment by position when
    # merging results back: any re-sort in between silently attaches plausible-looking
    # scores to the wrong articles, and the digest still reads fine. Worst kind of bug.
    by_id = {p["id"]: c for p, c in zip(payload, candidates)}

    results: dict[int, dict] = {}
    raws: list[str] = []

    for start in range(0, len(payload), BATCH_SIZE):
        batch = payload[start:start + BATCH_SIZE]
        log.info("scoring batch %d-%d of %d", start, start + len(batch), len(payload))
        batch_results, raw = score_batch(client, batch)
        results.update(batch_results)
        raws.append(raw)
        time.sleep(2)

    unscored = {"score": 0, "category": "unscored", "why": "", "action": "skip"}
    scored = [{**c, **results.get(pid, unscored)} for pid, c in by_id.items()]

    log.info("scored %d/%d candidates", len(results), len(candidates))
    return scored, raws


def select(scored: list[dict], threshold: int = THRESHOLD, cap: int = MAX_DIGEST) -> list[dict]:
    """Top items above the bar, best first. Never pads: on a slow evening the correct
    output is an empty list, and the quiet state is a feature (05_CONVENTIONS.md)."""
    keep = [s for s in scored if s["score"] >= threshold and s["action"] != "skip"]
    keep.sort(key=lambda s: (s["score"], len(s["sources"]), s["engagement"]), reverse=True)
    return keep[:cap]
