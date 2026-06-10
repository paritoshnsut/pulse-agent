"""Content generator tests — Claude calls stubbed; style enforcement asserted exactly."""

import json

import pytest

from conftest import StubClient
from pipeline import generator
from pipeline.generator import ContentGenerator

GENOME = {
    "sentence_length": "short, punchy", "avg_post_length": "180 chars",
    "sarcasm_level": "high", "tone": "combative", "emoji_usage": "none",
    "hashtag_style": "2-3, lowercase, at end", "uses_rhetorical_questions": True,
    "caps_for_emphasis": True, "hinglish_mix": 0.2,
    "signature_phrases": ["let that sink in"], "things_to_avoid": ["formal language"],
}
SIGNAL = {"title": "GDP grows 7.2%", "source_name": "Mint",
          "description": "Services led; manufacturing flat.", "angle": "base effect",
          "id": 1, "article_id": 1}


def _gen(payload):
    return ContentGenerator(client=StubClient(payload))


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        _gen("{}").generate(SIGNAL, GENOME, "nonexistent_format")


def test_hot_take_basic_shape():
    payload = json.dumps({"text": "GDP up 7.2%. Services carried it, manufacturing flat. base effect doing heavy lifting.",
                          "hashtags": ["gdp", "economy"], "note": ""})
    d = _gen(payload).generate(SIGNAL, GENOME, "hot_take")
    assert d["format"] == "hot_take"
    assert not d["empty"]
    assert d["char_count"] == len(d["content"])


def test_enforce_style_strips_emoji_when_none():
    g = _gen("{}")
    out = g.enforce_style("Big news today 🔥🚀 huge", {"emoji_usage": "none"})
    assert "🔥" not in out and "🚀" not in out
    assert "Big news today" in out


def test_enforce_style_keeps_emoji_when_allowed():
    g = _gen("{}")
    out = g.enforce_style("nice 🔥", {"emoji_usage": "frequent"})
    assert "🔥" in out


def test_enforce_style_lowercases_hashtags():
    g = _gen("{}")
    out = g.enforce_style("big news #Economy #GDP", {"hashtag_style": "lowercase, at end"})
    assert "#economy" in out and "#gdp" in out


def test_attach_hashtags_respects_cap_and_case():
    g = _gen("{}")
    # cap is 2 from "2-3, lowercase"
    out = g._attach_hashtags("body text", ["GDP", "Economy", "RBI", "India"], GENOME)
    tags = [w for w in out.split() if w.startswith("#")]
    assert len(tags) == 2
    assert all(t == t.lower() for t in tags)


def test_attach_hashtags_skipped_for_no_tag_voice():
    g = _gen("{}")
    out = g._attach_hashtags("body", ["x"], {"hashtag_style": "rarely uses hashtags"})
    assert "#" not in out


def test_truncate_to_x_limit():
    g = _gen("{}")
    long = "word " * 100  # 500 chars
    cut, was = g._truncate(long.strip())
    assert was is True
    assert len(cut) <= generator.X_CHAR_LIMIT


def test_thread_returns_list_and_renders():
    payload = json.dumps({"tweets": ["Hook tweet here.", "Second point.", "Third and final."],
                          "hashtags": [], "note": ""})
    d = _gen(payload).generate(SIGNAL, GENOME, "thread")
    assert isinstance(d["tweets"], list)
    assert len(d["tweets"]) == 3
    assert "———" in d["content"]  # tweets joined by the thread marker


def test_empty_text_flagged_empty():
    payload = json.dumps({"text": "", "hashtags": [], "note": "no credible contradiction in this story"})
    d = _gen(payload).generate(SIGNAL, GENOME, "contradiction")
    assert d["empty"] is True
    assert "contradiction" in d["note"]


# ---- generate_checked with a stubbed scorer (no Claude needed for the scorer) ----
class StubScorer:
    """Returns a scripted sequence of composite scores."""
    def __init__(self, scores):
        self._scores = list(scores)
        self.calls = 0

    def score(self, text, genome):
        composite = self._scores[min(self.calls, len(self._scores) - 1)]
        self.calls += 1
        return {"composite": composite, "axes": {"tone": composite},
                "mechanical": {"emoji_ok": True}, "weakest_axis": "tone",
                "weakest_axis_feedback": "sharpen the sarcasm"}


def test_generate_checked_passes_first_try():
    payload = json.dumps({"text": "sharp on-voice take. base effect carrying it.", "hashtags": [], "note": ""})
    scorer = StubScorer([85])
    out = _gen(payload).generate_checked(SIGNAL, GENOME, "hot_take", scorer=scorer)
    assert out["persona_score"] == 85
    assert out["needs_review"] is False
    assert scorer.calls == 1  # no retry needed


def test_generate_checked_retries_then_passes():
    payload = json.dumps({"text": "a take here", "hashtags": [], "note": ""})
    scorer = StubScorer([55, 88])  # first below gate, second passes
    out = _gen(payload).generate_checked(SIGNAL, GENOME, "hot_take", scorer=scorer, max_retries=2)
    assert scorer.calls == 2
    assert out["persona_score"] == 88
    assert out["needs_review"] is False


def test_generate_checked_flags_when_never_passes():
    payload = json.dumps({"text": "off voice", "hashtags": [], "note": ""})
    scorer = StubScorer([40, 45, 50])  # never reaches 70
    out = _gen(payload).generate_checked(SIGNAL, GENOME, "hot_take", scorer=scorer, max_retries=2)
    assert scorer.calls == 3  # initial + 2 retries
    assert out["needs_review"] is True
    assert out["persona_score"] == 50  # best of the three


def test_generate_checked_persists(temp_db):
    from datetime import datetime, timezone
    from pipeline import memory
    acct_id = memory.upsert_account(handle="me", db_path=temp_db)
    # seed a real article + signal so the FK references resolve
    aid, _ = memory.insert_article(
        {"source": "rss", "url": "http://x/gdp", "title": "GDP grows 7.2%",
         "published_at": datetime.now(timezone.utc).isoformat()}, db_path=temp_db)
    sid = memory.insert_signal(
        {"article_id": aid, "account_id": acct_id, "score": 9.0, "tier": "FIRE",
         "velocity": 10, "relevance": 9, "reaction_potential": 9, "window_urgency": 10,
         "historical_perf": 5, "angle": "base effect", "reasoning": "x"}, db_path=temp_db)
    signal = {"id": sid, "article_id": aid, "title": "GDP grows 7.2%",
              "source_name": "Mint", "description": "d", "angle": "base effect"}

    payload = json.dumps({"text": "on voice take", "hashtags": [], "note": ""})
    scorer = StubScorer([90])
    out = _gen(payload).generate_checked(
        signal, GENOME, "hot_take", scorer=scorer,
        account_id=acct_id, persist=True, db_path=temp_db,
    )
    assert "post_id" in out
    saved = memory.get_post(out["post_id"], db_path=temp_db)
    assert saved["persona_score"] == 90
    assert saved["status"] == "draft"
    assert saved["format"] == "hot_take"
