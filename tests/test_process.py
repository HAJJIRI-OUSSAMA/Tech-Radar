"""Tests for the pure pipeline logic — where a silent bug drops good items."""
from datetime import datetime, timedelta, timezone

from digest import process as P

NOW = datetime.now(timezone.utc)


def _raw(title, url, source, eng, age_h):
    return {"title": title, "url": url, "source": source, "engagement": eng,
            "published_at": NOW - timedelta(hours=age_h)}


def test_canonical_url_strips_tracking_and_www():
    assert P.canonical_url("https://www.ex.com/a/?utm_source=hn&ref=x") == "https://ex.com/a"
    assert P.canonical_url("https://ex.com/a#frag") == "https://ex.com/a"


def test_canonical_url_keeps_meaningful_query():
    assert "id=42" in P.canonical_url("https://ex.com/item?id=42&utm_medium=x")


def test_dedupe_merges_sources_and_keeps_max_engagement():
    items = [_raw("X", "https://ex.com/x?utm_source=a", "hn", 300, 2),
             _raw("X", "https://www.ex.com/x/", "reddit:r/devops", 1200, 5)]
    c = P.dedupe(items)[0]
    assert set(c["sources"]) == {"hn", "reddit:r/devops"}
    assert c["engagement"] == 1200
    assert c["published_at"] == NOW - timedelta(hours=5)   # earliest wins


def test_prefilter_drops_low_engagement_single_source():
    assert P.prefilter(P.dedupe([_raw("meh", "https://ex.com/m", "hn", 3, 1)])) == []


def test_prefilter_keeps_rss_with_zero_engagement():
    kept = P.prefilter(P.dedupe([_raw("Vercel ships X", "https://v.com/x", "rss:Vercel", 0, 1)]))
    assert len(kept) == 1


def test_cross_source_bypasses_engagement_floor():
    """Two weak sources agreeing beats one strong source. This is the core prior."""
    items = [_raw("X", "https://ex.com/x", "hn", 2, 1), _raw("X", "https://ex.com/x", "lobsters", 1, 1)]
    assert len(P.prefilter(P.dedupe(items))) == 1


def test_prefilter_drops_stale_items():
    assert P.prefilter(P.dedupe([_raw("old", "https://ex.com/o", "hn", 900, 24 * 9)])) == []


def test_prefilter_respects_cap():
    items = [_raw(f"t{i}", f"https://ex.com/{i}", "hn", 500, 1) for i in range(200)]
    assert len(P.prefilter(P.dedupe(items))) == P.MAX_CANDIDATES
