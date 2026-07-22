"""Normalize URLs, dedupe/cluster across sources, cheap pre-filter before the LLM.

Pure functions, no network. The pre-filter's whole job is to cut ~300 raw candidates
down to ~120 BEFORE we spend any LLM tokens (see 05_CONVENTIONS: token budget). It must
stay *cheap* — no model calls, just heuristics. The LLM does the real judgement in 1.4.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import log as _ln
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"ref", "ref_src", "ref_url", "fbclid", "gclid", "mc_cid", "mc_eid", "source"}

# Per-source engagement floors for single-source items. RSS has no floor: vendor feeds are
# curated by inclusion. Multi-source items bypass floors entirely (agreement = signal).
_FLOORS = {"hn": 20, "reddit": 30, "lobsters": 5}

MAX_CANDIDATES = 120
MAX_AGE_DAYS = 3


def canonical_url(url: str) -> str:
    """Strip tracking params, drop www., trailing slash, fragment — so the same story
    from different sources collapses to one key."""
    try:
        p = urlparse(url.strip())
    except Exception:
        return url
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    q = [
        (k, v) for k, v in parse_qsl(p.query)
        if k not in _TRACKING_KEYS and not k.startswith(_TRACKING_PREFIXES)
    ]
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), host, path, "", urlencode(q), ""))


def dedupe(items: list[dict]) -> list[dict]:
    """Cluster by canonical URL. Merge sources[], keep max engagement + earliest published."""
    clusters: dict[str, dict] = {}
    for it in items:
        key = canonical_url(it["url"])
        c = clusters.get(key)
        if c is None:
            clusters[key] = {
                "title": it["title"],
                "url": it["url"],
                "canonical_url": key,
                "source": it["source"],
                "sources": [it["source"]],
                "engagement": it["engagement"],
                "published_at": it["published_at"],
            }
        else:
            if it["source"] not in c["sources"]:
                c["sources"].append(it["source"])
            c["engagement"] = max(c["engagement"], it["engagement"])
            c["published_at"] = min(c["published_at"], it["published_at"])
    return list(clusters.values())


def _source_kind(source: str) -> str:
    return source.split(":", 1)[0]


def _passes_floor(item: dict) -> bool:
    if len(item["sources"]) > 1:        # cross-source agreement always passes
        return True
    kind = _source_kind(item["source"])
    if kind == "rss":
        return True
    return item["engagement"] >= _FLOORS.get(kind, 0)


def _cheap_rank(item: dict, now: datetime) -> float:
    src_bonus = 100 * (len(item["sources"]) - 1)          # cross-source is the strongest cheap signal
    eng = 10 * _ln(item["engagement"] + 1)
    age_h = (now - item["published_at"]).total_seconds() / 3600
    recency = max(0.0, 48 - age_h)                         # newer better; flat penalty past 48h
    rss_base = 40 if _source_kind(item["source"]) == "rss" else 0
    return src_bonus + eng + recency + rss_base


def prefilter(
    items: list[dict],
    max_candidates: int = MAX_CANDIDATES,
    max_age_days: int = MAX_AGE_DAYS,
) -> list[dict]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_age_days)
    kept = [i for i in items if i["published_at"] >= cutoff and _passes_floor(i)]
    kept.sort(key=lambda i: _cheap_rank(i, now), reverse=True)
    return kept[:max_candidates]


def process(raw_items: list[dict]) -> list[dict]:
    """collect_all() output -> pre-filtered candidate list ready for scoring."""
    return prefilter(dedupe(raw_items))
