"""Tests for Telegram formatting. Pure functions only — no network.

The interesting cases are escaping (real HN titles contain <, &, ") and the quiet path,
which is a designed feature rather than an empty state.
"""
from digest import notify as N


def _item(title="Vercel ships X", score=8, action="learn", category="devops",
          sources=None, why="new primitive for your stack", url="https://v.com/x"):
    return {"title": title, "score": score, "action": action, "category": category,
            "sources": sources or ["rss:Vercel"], "why": why, "url": url}


def test_digest_contains_core_fields():
    text = N.format_digest([_item()])
    assert "8/10" in text
    assert "devops" in text
    assert "https://v.com/x" in text
    assert "new primitive for your stack" in text


def test_html_special_chars_are_escaped():
    """Real titles break naive HTML: '<script>' would inject, '&' would 400 the API."""
    text = N.format_digest([_item(title="Rust & C++ <regex> parser")])
    assert "&amp;" in text and "&lt;regex&gt;" in text
    assert "<regex>" not in text


def test_empty_digest_renders_the_quiet_state():
    """A quiet evening is a feature, not an error — it must produce a real message."""
    text = N.format_digest([])
    assert text == N.format_quiet()
    assert "Nothing major today" in text


def test_quiet_message_is_not_alarming():
    q = N.format_quiet()
    assert "fail" not in q.lower() and "error" not in q.lower()


def test_failure_message_is_distinct_from_quiet():
    """The whole point: a broken run must never read like a slow news day."""
    f = N.format_failure("scoring failed: 0/101 candidates scored")
    assert "failed" in f.lower()
    assert "Nothing major today" not in f
    assert "0/101" in f


def test_cross_source_shown_collapsed():
    text = N.format_digest([_item(sources=["hn", "lobsters", "rss:Vercel"])])
    assert "hn+lobsters+rss" in text


def test_long_digest_truncated_below_telegram_limit():
    items = [_item(title=f"Item {i} " + "x" * 300) for i in range(30)]
    assert len(N.format_digest(items)) <= N.MAX_LEN


def test_singular_plural_header():
    assert "1 item\n" in N.format_digest([_item()]) + "\n"
    assert "2 items" in N.format_digest([_item(), _item()])


def test_send_without_credentials_returns_false(monkeypatch):
    """Missing config must degrade quietly, not crash a run that already succeeded."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert N.credentials() is None
    assert N.send("hi") is False


def test_dry_run_never_sends(monkeypatch):
    monkeypatch.setattr(N, "send", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("send() must not be called during a dry run")))
    assert N.send_digest([_item()], dry_run=True) is True
    assert N.send_failure("boom", dry_run=True) is True