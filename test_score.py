"""Tests for the scoring layer. The LLM is faked — these verify OUR handling of its
output, which is where the real bugs live: truncated JSON, fenced JSON, hallucinated
ids, out-of-range scores, and the model trying to sneak a low score past the threshold.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from digest import score as S

NOW = datetime.now(timezone.utc)


def _cand(title, sources, eng=100, age_h=2):
    return {"title": title, "url": f"https://ex.com/{abs(hash(title))}",
            "canonical_url": f"https://ex.com/{abs(hash(title))}",
            "source": sources[0], "sources": sources, "engagement": eng,
            "published_at": NOW - timedelta(hours=age_h)}


class FakeClient:
    """Mimics the OpenAI-compatible surface: client.chat.completions.create(...)"""
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=r))])


def test_extract_json_from_markdown_fence():
    text = 'Sure!\n```json\n[{"id":0,"score":8,"category":"ai","why":"x","action":"learn"}]\n```\nHope that helps'
    assert S.extract_json_array(text)[0]["score"] == 8


def test_extract_raises_on_garbage():
    with pytest.raises(ValueError):
        S.extract_json_array("I cannot comply with that request.")


def test_validate_forces_skip_below_threshold():
    """The model must not smuggle a 4 into the digest by labelling it 'learn'."""
    rows = [{"id": 0, "score": 4, "category": "ai", "why": "x", "action": "learn"}]
    assert S.validate(rows, {0})[0]["action"] == "skip"


def test_validate_clamps_and_drops():
    rows = [
        {"id": 0, "score": 47, "category": "ai", "why": "x", "action": "learn"},   # clamped to 10
        {"id": 99, "score": 9, "category": "ai", "why": "x", "action": "learn"},   # hallucinated id
        {"id": 1, "score": "nope", "category": "ai", "why": "x", "action": "learn"},  # unparseable
        {"id": 2, "score": 8, "category": "ai", "why": "x", "action": "banana"},   # bad action
    ]
    out = S.validate(rows, {0, 1, 2})
    assert out[0]["score"] == 10
    assert 99 not in out and 1 not in out
    assert out[2]["action"] == "skip"


def test_score_survives_total_batch_failure():
    """A dead provider must yield an empty digest, never an exception."""
    client = FakeClient(*[RuntimeError("503")] * S.MAX_RETRIES)
    S.time.sleep = lambda _: None
    scored, _ = S.score([_cand("a", ["hn"])], client=client)
    assert scored[0]["score"] == 0
    assert S.select(scored) == []


def test_score_retries_then_succeeds():
    good = '[{"id":0,"score":9,"category":"devops","why":"fits your stack","action":"learn"}]'
    client = FakeClient(RuntimeError("timeout"), good)
    S.time.sleep = lambda _: None
    scored, _ = S.score([_cand("a", ["hn"])], client=client)
    assert scored[0]["score"] == 9 and client.calls == 2


def test_batching_splits_large_candidate_sets():
    n = S.BATCH_SIZE + 5
    cands = [_cand(f"item {i}", ["hn"]) for i in range(n)]
    r1 = str([{"id": i, "score": 5, "category": "x", "why": "w", "action": "skip"}
              for i in range(S.BATCH_SIZE)]).replace("'", '"')
    r2 = str([{"id": i, "score": 5, "category": "x", "why": "w", "action": "skip"}
              for i in range(S.BATCH_SIZE, n)]).replace("'", '"')
    client = FakeClient(r1, r2)
    scored, raws = S.score(cands, client=client)
    assert client.calls == 2 and len(raws) == 2
    assert all(s["score"] == 5 for s in scored)


def test_select_never_pads_and_caps():
    scored = [{**_cand(f"i{i}", ["hn"]), "score": 9, "category": "ai", "why": "w",
               "action": "learn"} for i in range(12)]
    assert len(S.select(scored)) == S.MAX_DIGEST      # capped at 7
    assert S.select([]) == []                          # quiet day stays quiet


def test_select_ranks_cross_source_above_single_source():
    a = {**_cand("single", ["hn"], eng=5000), "score": 8, "category": "ai", "why": "w", "action": "learn"}
    b = {**_cand("multi", ["hn", "lobsters"], eng=10), "score": 8, "category": "ai", "why": "w", "action": "learn"}
    assert S.select([a, b])[0]["title"] == "multi"


def test_scores_bind_to_correct_candidates():
    """Regression guard: ids are positional, so a re-sort between payload build and
    result merge would attach plausible scores to the wrong articles — silently."""
    cands = [_cand("alpha", ["hn"]), _cand("beta", ["hn"]), _cand("gamma", ["hn"])]
    reply = ('[{"id":0,"score":9,"category":"a","why":"about alpha","action":"learn"},'
             '{"id":1,"score":8,"category":"b","why":"about beta","action":"aware"},'
             '{"id":2,"score":7,"category":"c","why":"about gamma","action":"learn"}]')
    scored, _ = S.score(cands, client=FakeClient(reply))
    for item in scored:
        assert item["title"] in item["why"], f"{item['title']} got why={item['why']!r}"


def test_partial_response_leaves_others_unscored_not_shifted():
    """Model returns only 2 of 3 items: the missing one must be unscored, and the
    present ones must keep their own scores rather than shifting up a slot."""
    cands = [_cand("alpha", ["hn"]), _cand("beta", ["hn"]), _cand("gamma", ["hn"])]
    reply = ('[{"id":0,"score":9,"category":"a","why":"about alpha","action":"learn"},'
             '{"id":2,"score":7,"category":"c","why":"about gamma","action":"learn"}]')
    scored, _ = S.score(cands, client=FakeClient(reply))
    by_title = {s["title"]: s for s in scored}
    assert by_title["alpha"]["score"] == 9
    assert by_title["beta"]["score"] == 0 and by_title["beta"]["category"] == "unscored"
    assert by_title["gamma"]["score"] == 7


# --- reasoning-model output handling ----------------------------------------

def test_strips_think_block():
    text = ('<think>Let me weigh these. Items [1, 2, 3] look incremental. '
            'Compare scores [7,8] vs [4,5].</think>\n'
            '[{"id":0,"score":9,"category":"ai","why":"real shift","action":"learn"}]')
    out = S.extract_json_array(text)
    assert len(out) == 1 and out[0]["score"] == 9


def test_reasoning_trace_brackets_do_not_corrupt_the_parse():
    """The bug this replaced: first-[ to last-] slicing across a reasoning trace.
    Here the trace contains a decoy array BEFORE the real verdicts."""
    text = ('Thinking: candidate ids [0, 1, 2] need ranking. '
            'Rough ordering [{"note":"id 1 is clickbait"},{"note":"id 0 is a real shift"}]. '
            'Final answer:\n'
            '[{"id":0,"score":9,"category":"ai","why":"real","action":"learn"},'
            '{"id":1,"score":2,"category":"frontend","why":"clickbait","action":"skip"}]')
    out = S.extract_json_array(text)
    assert len(out) == 2, f"picked up the decoy array instead: {out}"
    assert {r["id"] for r in out} == {0, 1}


def test_unclosed_think_block_raises_not_silently_parses():
    """Truncated mid-thought must fail loudly — it means max_tokens is too low."""
    with pytest.raises(ValueError, match="LLM_MAX_TOKENS"):
        S.extract_json_array('<think>Item [0] seems important, but [1] is')


def test_empty_content_after_reasoning_is_survivable():
    """Model burns the whole budget thinking. Must yield an unscored item, not a crash,
    and must not be mistaken for a legitimate quiet day downstream."""
    S.time.sleep = lambda _: None
    scored, _ = S.score([_cand("a", ["hn"])], client=FakeClient("", "", ""))
    assert scored[0]["score"] == 0 and scored[0]["category"] == "unscored"


def test_extra_body_parses_and_survives_garbage(monkeypatch):
    monkeypatch.setenv("LLM_EXTRA_BODY", '{"chat_template_kwargs":{"thinking":false}}')
    assert S.extra_body()["chat_template_kwargs"]["thinking"] is False
    monkeypatch.setenv("LLM_EXTRA_BODY", "not json{{")
    assert S.extra_body() == {}
