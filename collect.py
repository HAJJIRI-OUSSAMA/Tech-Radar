"""Source collectors. One function per source, each isolated and fail-safe.

Every collector returns a list of normalized items:
    {"title": str, "url": str, "source": str, "engagement": int, "published_at": datetime}

Design note: we normalize at the collector edge (each source knows its own schema best)
rather than inside process.py. process.py owns URL canonicalization, dedupe/cluster and
the pre-filter. Rationale: keeps process.py decoupled from every source's raw JSON, so
adding a source is a one-file change.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import feedparser
import requests

log = logging.getLogger("digest.collect")

TIMEOUT = 15
# Reddit rejects generic UAs; keep this descriptive. Put a real contact before shipping.
USER_AGENT = "tech-radar/0.1 (personal tech-significance digest; contact: you@example.com)"

SUBREDDITS = ["programming", "devops", "MachineLearning", "netsec"]

# Start small; expand only as a feed earns its place. High-signal only: vendor changelogs
# and release notes, not opinion blogs. (Which feeds first is an open question in 06_PROGRESS.)
RSS_FEEDS = {
    "Vercel": "https://vercel.com/atom",
    "OpenAI": "https://openai.com/blog/rss.xml",
    "AWS What's New": "https://aws.amazon.com/about-aws/whats-new/recent/feed/",
    "GitHub": "https://github.blog/feed/",
    "Kubernetes": "https://kubernetes.io/feed.xml",
    "HashiCorp": "https://www.hashicorp.com/blog/feed.xml",
}

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT})


# ---- helpers ---------------------------------------------------------------

def _get_json(url: str, **kwargs):
    r = _session.get(url, timeout=TIMEOUT, **kwargs)
    r.raise_for_status()
    return r.json()


def _ts(epoch: float | None) -> datetime:
    """Unix epoch -> aware UTC datetime; None -> now (so undated items aren't dropped)."""
    if epoch is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(float(epoch), tz=timezone.utc)


def _parse_iso(s: str | None) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


# ---- collectors ------------------------------------------------------------

def collect_hn(min_points: int = 75) -> list[dict]:
    """Hacker News via Algolia: curated front page + recent high-point stories (last 48h)."""
    items: dict[str, dict] = {}

    def _add(hit: dict) -> None:
        oid = hit.get("objectID")
        if not oid:
            return
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={oid}"
        items[oid] = {
            "title": hit.get("title") or "",
            "url": url,
            "source": "hn",
            "engagement": int(hit.get("points") or 0),
            "published_at": _ts(hit.get("created_at_i")),
        }

    fp = _get_json(
        "https://hn.algolia.com/api/v1/search",
        params={"tags": "front_page", "hitsPerPage": 50},
    )
    for hit in fp.get("hits", []):
        _add(hit)

    since = int(datetime.now(timezone.utc).timestamp()) - 48 * 3600
    recent = _get_json(
        "https://hn.algolia.com/api/v1/search_by_date",
        params={
            "tags": "story",
            "numericFilters": f"points>{min_points},created_at_i>{since}",
            "hitsPerPage": 50,
        },
    )
    for hit in recent.get("hits", []):
        _add(hit)

    return [i for i in items.values() if i["title"] and i["url"]]


def collect_reddit(subreddits: list[str] | None = None, limit: int = 25) -> list[dict]:
    """Reddit hot posts per subreddit. Each sub is isolated so one 429 doesn't kill the rest."""
    subreddits = subreddits or SUBREDDITS
    out: list[dict] = []
    for sub in subreddits:
        try:
            data = _get_json(
                f"https://www.reddit.com/r/{sub}/hot.json", params={"limit": limit}
            )
            for child in data.get("data", {}).get("children", []):
                d = child.get("data", {})
                if d.get("stickied"):
                    continue
                url = (
                    d.get("url_overridden_by_dest")
                    or d.get("url")
                    or f"https://www.reddit.com{d.get('permalink', '')}"
                )
                out.append({
                    "title": d.get("title") or "",
                    "url": url,
                    "source": f"reddit:r/{sub}",
                    "engagement": int(d.get("score") or 0),
                    "published_at": _ts(d.get("created_utc")),
                })
        except Exception as e:  # per-sub fail-safe
            log.warning("reddit r/%s failed: %s", sub, e)
    return [i for i in out if i["title"] and i["url"]]


def collect_lobsters() -> list[dict]:
    """Lobsters hottest. Text posts fall back to their comments URL."""
    data = _get_json("https://lobste.rs/hottest.json")
    out = []
    for s in data:
        url = s.get("url") or s.get("comments_url") or ""
        out.append({
            "title": s.get("title") or "",
            "url": url,
            "source": "lobsters",
            "engagement": int(s.get("score") or 0),
            "published_at": _parse_iso(s.get("created_at")),
        })
    return [i for i in out if i["title"] and i["url"]]


def collect_rss(feeds: dict[str, str] | None = None, per_feed: int = 12) -> list[dict]:
    """Vendor changelogs / release notes. No crowd signal, so engagement=0 (curated by inclusion)."""
    feeds = feeds or RSS_FEEDS
    out = []
    for name, feed_url in feeds.items():
        try:
            parsed = feedparser.parse(feed_url, agent=USER_AGENT)
            for entry in parsed.entries[:per_feed]:
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                published = (
                    datetime(*pub[:6], tzinfo=timezone.utc)
                    if pub else datetime.now(timezone.utc)
                )
                out.append({
                    "title": entry.get("title") or "",
                    "url": entry.get("link") or "",
                    "source": f"rss:{name}",
                    "engagement": 0,
                    "published_at": published,
                })
        except Exception as e:  # per-feed fail-safe
            log.warning("rss %s failed: %s", name, e)
    return [i for i in out if i["title"] and i["url"]]


COLLECTORS = {
    "hn": collect_hn,
    "reddit": collect_reddit,
    "lobsters": collect_lobsters,
    "rss": collect_rss,
}


def collect_all() -> list[dict]:
    """Run every collector fail-safe. One dead source never breaks the nightly run."""
    items: list[dict] = []
    for name, fn in COLLECTORS.items():
        try:
            got = fn()
            log.info("collected %3d from %s", len(got), name)
            items.extend(got)
        except Exception as e:  # whole-source fail-safe
            log.warning("collector %s failed entirely: %s", name, e)
    return items
