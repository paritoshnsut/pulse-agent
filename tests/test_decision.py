"""Decision scorer tests — scoring math is exact; Claude calls are stubbed."""

import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from conftest import StubClient
from pipeline import decision


def _agent(payload="{}"):
    return decision.DecisionAgent(client=StubClient(payload))


def test_recency_decay_curve():
    a = _agent()
    now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
    fresh = (now - timedelta(minutes=0)).isoformat()
    hour_old = (now - timedelta(minutes=60)).isoformat()

    v0, w0 = a.recency_scores(fresh, now=now)
    assert v0 == pytest.approx(10.0, abs=1e-6)

    v60, w60 = a.recency_scores(hour_old, now=now)
    assert v60 == pytest.approx(10.0 * math.exp(-1), abs=1e-3)  # ~3.679

    # unknown date -> neutral, never punished
    assert a.recency_scores(None, now=now) == (5.0, 5.0)
    assert a.recency_scores("not-a-date", now=now) == (5.0, 5.0)


def test_composite_weighting():
    a = _agent()
    all_seven = {k: 8.0 for k in
                 ("velocity", "relevance", "corroboration", "reaction_potential",
                  "memory_leverage", "window_urgency", "historical_perf")}
    assert a.composite(all_seven) == 8.0  # weights sum to 1.0

    mixed = {"velocity": 10, "relevance": 9, "corroboration": 10,
             "reaction_potential": 9, "memory_leverage": 5,
             "window_urgency": 10, "historical_perf": 5}
    # 10*.2 + 9*.2 + 10*.15 + 9*.15 + 5*.1 + 10*.1 + 5*.1 = 8.65
    assert a.composite(mixed) == pytest.approx(8.65, abs=1e-6)


def test_tier_thresholds():
    a = _agent()
    assert a.tier(9.0) == "FIRE"
    assert a.tier(8.5) == "FIRE"        # boundary inclusive
    assert a.tier(8.49) == "WARM"
    assert a.tier(6.5) == "WARM"
    assert a.tier(4.5) == "COOL"
    assert a.tier(4.49) == "SKIP"


def test_judge_parses_fenced_json():
    payload = "```json\n{\"relevance\": 8, \"reaction_potential\": 7, " \
              "\"angle\": \"base effect\", \"reasoning\": \"fits niche\"}\n```"
    out = _agent(payload).judge({"title": "x", "description": "y"}, {"niche": "econ"})
    assert out["relevance"] == 8.0
    assert out["reaction_potential"] == 7.0
    assert out["angle"] == "base effect"


def test_judge_handles_garbage_json():
    out = _agent("not json at all").judge({"title": "x"}, {"niche": "econ"})
    assert out["relevance"] == 5.0  # neutral fallback
    assert out["reaction_potential"] == 5.0


def test_hot_relevant_recent_without_receipts_is_warm(temp_db):
    """The new model on purpose: a perfect solo story with no corroboration
    and no memory receipts tops out in WARM — FIRE is reserved for stories
    that are structurally big or that this account is positioned to win."""
    from pipeline import memory
    now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
    acct_id = memory.upsert_account(handle="me", db_path=temp_db)
    payload = json.dumps({"relevance": 10, "reaction_potential": 10,
                          "angle": "a", "topic": "gdp-growth", "reasoning": "r"})
    article = {"id": 999, "title": "GDP grows at record pace this quarter",
               "published_at": now.isoformat()}
    sig = _agent(payload).score_article(article, {"id": acct_id}, now=now,
                                        db_path=temp_db)
    # vel 2.0 + rel 2.0 + corr(neutral 5)*.15=0.75 + react 1.5 + lev 0
    # + window 1.0 + hist 0.5 = 7.75
    assert sig["score"] == pytest.approx(7.75, abs=0.01)
    assert sig["tier"] == "WARM"
    assert sig["corroboration"] == 5.0      # fresh scoop: unknown, not punished
    assert sig["memory_leverage"] == 0.0    # genuinely no receipts
    assert sig["freshness_mult"] == 1.0 and sig["source_weight"] == 1.0


def test_corroborated_story_with_receipts_fires(temp_db):
    from pipeline import memory
    now = datetime.now(timezone.utc)
    acct_id = memory.upsert_account(handle="me", db_path=temp_db)
    # receipts: two past stances on the topic
    memory.log_stance(acct_id, "gdp-growth", "thinks gdp headline hides weak base",
                      db_path=temp_db)
    memory.log_stance(acct_id, "gdp-growth", "thinks growth quality matters most",
                      db_path=temp_db)
    # four other outlets carrying the same story
    for i, outlet in enumerate(["Mint", "The Hindu", "NDTV", "Reuters"]):
        memory.insert_article({
            "source": "rss", "source_name": outlet, "url": f"https://t/c{i}",
            "title": "GDP grows at record pace this quarter",
            "published_at": now.isoformat()}, db_path=temp_db)
    art_id, _ = memory.insert_article({
        "source": "rss", "source_name": "Indian Express", "url": "https://t/self",
        "title": "GDP grows at record pace this quarter",
        "published_at": now.isoformat()}, db_path=temp_db)
    payload = json.dumps({"relevance": 9, "reaction_potential": 9,
                          "angle": "a", "topic": "gdp-growth", "reasoning": "r"})
    article = memory.get_article(art_id, db_path=temp_db)
    sig = _agent(payload).score_article(article, {"id": acct_id}, now=now,
                                        db_path=temp_db)
    # vel 2.0 + rel 1.8 + corr(5 outlets -> 10)*.15=1.5 + react 1.35
    # + leverage(2 stances -> 5.0)*.1=0.5 + window 1.0 + hist 0.5 = 8.65
    assert sig["corroboration"] == 10.0
    assert sig["memory_leverage"] == 5.0
    assert sig["score"] == pytest.approx(8.65, abs=0.01)
    assert sig["tier"] == "FIRE"


def test_run_scores_and_marks_processed(temp_db):
    from pipeline import memory
    acct_id = memory.upsert_account(handle="me", db_path=temp_db)
    account = memory.get_account(acct_id, db_path=temp_db)
    now = datetime.now(timezone.utc).isoformat()
    aid, _ = memory.insert_article(
        {"source": "rss", "url": "http://x/1", "title": "Test story",
         "description": "d", "vertical": "finance", "region": "india",
         "published_at": now}, db_path=temp_db)

    payload = json.dumps({"relevance": 3, "reaction_potential": 2,
                          "angle": "", "reasoning": "generic"})
    tally = _agent(payload).run(account, db_path=temp_db)

    assert tally["FIRE"] + tally["WARM"] + tally["COOL"] + tally["SKIP"] == 1
    # per-account queue is now empty for this account (it recorded the score)
    assert memory.get_unscored_for_account(account, db_path=temp_db) == []


# ======================================================= keyword pre-filter

def test_topic_words_parsed_from_topics_and_niche():
    from pipeline.decision import _account_topic_words
    account = {
        "topics": '["economic policy", "BJP criticism", "fiscal data"]',
        "niche": "skeptical of govt spin",
    }
    words = _account_topic_words(account)
    assert "economic" in words
    assert "policy" in words
    assert "bjp" in words
    assert "criticism" in words
    assert "fiscal" in words
    assert "skeptical" in words
    assert "govt" in words
    # stopwords filtered out
    assert "of" not in words


def test_topic_words_empty_when_no_profile():
    from pipeline.decision import _account_topic_words
    assert _account_topic_words({}) == frozenset()
    assert _account_topic_words({"topics": "[]", "niche": ""}) == frozenset()


def test_prefilter_passes_matching_article():
    from pipeline.decision import _account_topic_words, _passes_keyword_prefilter
    account = {"topics": '["economic policy"]', "niche": ""}
    words = _account_topic_words(account)
    art = {"title": "RBI cuts rate amid economic slowdown", "description": ""}
    assert _passes_keyword_prefilter(art, words) is True


def test_prefilter_blocks_unrelated_article():
    from pipeline.decision import _account_topic_words, _passes_keyword_prefilter
    account = {"topics": '["economic policy", "BJP criticism"]', "niche": ""}
    words = _account_topic_words(account)
    art = {"title": "Virat Kohli scores century in IPL final", "description": "Cricket match recap"}
    assert _passes_keyword_prefilter(art, words) is False


def test_prefilter_passes_when_no_topics_defined():
    from pipeline.decision import _passes_keyword_prefilter
    # empty topic bag → never filter (fail-safe: score everything)
    art = {"title": "Completely unrelated content", "description": ""}
    assert _passes_keyword_prefilter(art, frozenset()) is True


def test_prefilter_match_is_case_insensitive():
    from pipeline.decision import _account_topic_words, _passes_keyword_prefilter
    account = {"topics": '["GDP growth"]', "niche": ""}
    words = _account_topic_words(account)
    art = {"title": "gdp GROWTH slows in Q4", "description": ""}
    assert _passes_keyword_prefilter(art, words) is True


def test_run_increments_pre_filtered_and_marks_scored(temp_db):
    """Pre-filtered articles must be marked scored (not re-queued) and
    must not trigger a Claude call."""
    from pipeline import memory
    import json as _json

    acct_id = memory.upsert_account(
        handle="econbot",
        topics=_json.dumps(["economic policy", "fiscal data"]),
        niche="India macro commentary",
        db_path=temp_db,
    )
    account = memory.get_account(acct_id, db_path=temp_db)
    now = datetime.now(timezone.utc).isoformat()

    # this article has zero overlap with the account's topics
    memory.insert_article(
        {"source": "rss", "url": "http://x/cricket1",
         "title": "Rohit Sharma hits double century in Test match",
         "description": "Cricket news", "vertical": None, "region": None,
         "published_at": now},
        db_path=temp_db,
    )

    judge_calls = []
    agent = _agent("{}")
    original_judge = agent.judge

    def tracking_judge(article, acct):
        judge_calls.append(article)
        return original_judge(article, acct)

    agent.judge = tracking_judge
    tally = agent.run(account, db_path=temp_db)

    assert tally["pre_filtered"] == 1
    assert len(judge_calls) == 0           # Claude was never called
    assert memory.get_unscored_for_account(account, db_path=temp_db) == []
