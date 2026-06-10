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
    all_five = {k: 8.0 for k in
                ("velocity", "relevance", "reaction_potential", "window_urgency", "historical_perf")}
    assert a.composite(all_five) == 8.0  # weights sum to 1.0

    mixed = {"velocity": 10, "relevance": 9, "reaction_potential": 9,
             "window_urgency": 10, "historical_perf": 5}
    # 10*.3 + 9*.25 + 9*.2 + 10*.15 + 5*.1 = 9.05
    assert a.composite(mixed) == pytest.approx(9.05, abs=1e-6)


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


def test_score_article_produces_fire_for_hot_relevant_recent():
    now = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)
    payload = json.dumps({"relevance": 9, "reaction_potential": 9,
                          "angle": "the base effect nobody mentions",
                          "reasoning": "directly in niche, contrarian angle"})
    article = {"id": 1, "title": "GDP grows 7.2%", "description": "...",
               "published_at": now.isoformat()}
    account = {"id": 1, "niche": "econ policy", "topics": "[]"}
    sig = _agent(payload).score_article(article, account, now=now)
    assert sig["tier"] == "FIRE"
    assert sig["angle"]
    assert sig["historical_perf"] == 5.0  # placeholder until engagement data


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
