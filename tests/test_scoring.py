"""Tests for the 7-factor scoring upgrade: corroboration, memory leverage,
topic-level historical_perf, freshness multiplier, source weights."""

import json
from datetime import datetime, timedelta, timezone

from conftest import StubClient
from pipeline import fatigue, memory
from pipeline.decision import (DecisionAgent, corroboration_score,
                               memory_leverage_score, _outlet)
from sources import source_weight_for
from style import learning

NOW = datetime.now(timezone.utc)


def _art(db, title, outlet, url, age_min=0):
    aid, _ = memory.insert_article({
        "source": "rss", "source_name": outlet, "url": url, "title": title,
        "published_at": (NOW - timedelta(minutes=age_min)).isoformat()},
        db_path=db)
    return memory.get_article(aid, db_path=db)


STORY = "RBI cuts repo rate in surprise move"


# --------------------------------------------------------------- corroboration
def test_corroboration_scales_with_distinct_outlets(temp_db):
    me = _art(temp_db, STORY, "Indian Express", "https://t/self", age_min=120)
    assert corroboration_score(me, now=NOW, db_path=temp_db) == 0.0  # old + alone
    for i, outlet in enumerate(["Mint", "NDTV"]):
        _art(temp_db, STORY, outlet, f"https://t/c{i}")
    assert corroboration_score(me, now=NOW, db_path=temp_db) == 5.0   # 3 of 5 sat
    for i, outlet in enumerate(["The Hindu", "Reuters"]):
        _art(temp_db, STORY, outlet, f"https://t/d{i}")
    assert corroboration_score(me, now=NOW, db_path=temp_db) == 10.0  # saturated


def test_corroboration_fresh_scoop_is_neutral_not_zero(temp_db):
    me = _art(temp_db, STORY, "Indian Express", "https://t/self", age_min=10)
    assert corroboration_score(me, now=NOW, db_path=temp_db) == 5.0


def test_corroboration_ignores_self_echo_and_unrelated(temp_db):
    me = _art(temp_db, STORY, "Times of India — Top Stories", "https://t/self",
              age_min=120)
    # same publisher, different feed: NOT independent corroboration
    _art(temp_db, STORY, "Times of India — India", "https://t/same-pub")
    # unrelated story: no shared keywords
    _art(temp_db, "Cricket final tonight in Ahmedabad", "Mint", "https://t/cricket")
    assert corroboration_score(me, now=NOW, db_path=temp_db) == 0.0


def test_outlet_normalization():
    assert _outlet("Times of India — Top Stories") == "times of india"
    assert _outlet("Politico - Politics") == "politico"
    assert _outlet(None) == "unknown"


# ------------------------------------------------------------- memory leverage
def test_memory_leverage_components(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    art = {"title": STORY}
    assert memory_leverage_score(art, acct, db_path=temp_db) == 0.0  # no receipts

    memory.log_stance(acct, "rbi-rate-policy", "thinks repo holds punish savers",
                      db_path=temp_db)
    assert memory_leverage_score(art, acct, db_path=temp_db) == 2.5  # 1 stance

    memory.insert_prediction(acct, "RBI will cut the repo rate by March",
                             topic="rbi-rate-policy", db_path=temp_db)
    assert memory_leverage_score(art, acct, db_path=temp_db) == 6.5  # + prediction

    memory.seed_event("rbi-rate-policy", "RBI held repo rate at 6.5%",
                      source_url="https://t/e1", db_path=temp_db)
    assert memory_leverage_score(art, acct, db_path=temp_db) == 7.0  # + event


def test_memory_leverage_caps_at_ten(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    for i in range(4):
        memory.log_stance(acct, "rbi-rate-policy", f"repo rate stance {i}",
                          db_path=temp_db)
        memory.seed_event("rbi-rate-policy", f"repo rate event {i}",
                          source_url=f"https://t/e{i}", db_path=temp_db)
    memory.insert_prediction(acct, "repo rate will fall", db_path=temp_db)
    # stances capped at 2 (5.0) + prediction 4.0 + events capped at 2 (1.0) = 10
    assert memory_leverage_score({"title": STORY}, acct, db_path=temp_db) == 10.0


# ----------------------------------------------------- freshness + source weight
def test_freshness_multiplier_bands(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)

    def _approve_one(i):
        aid, _ = memory.insert_article({"source": "rss", "url": f"https://t/f{i}",
                                        "title": f"s{i}"}, db_path=temp_db)
        sid = memory.insert_signal({"article_id": aid, "account_id": acct,
                                    "score": 9, "tier": "FIRE",
                                    "topic": "rbi-rate-policy"}, db_path=temp_db)
        pid = memory.save_post(acct, "hot_take", "x", signal_id=sid, db_path=temp_db)
        memory.set_post_status(pid, "approved", db_path=temp_db)

    assert fatigue.freshness_multiplier(acct, "rbi-rate-policy", db_path=temp_db) == 1.0
    _approve_one(0)
    assert fatigue.freshness_multiplier(acct, "rbi-rate-policy", db_path=temp_db) == 1.0
    _approve_one(1)
    assert fatigue.freshness_multiplier(acct, "rbi-rate-policy", db_path=temp_db) == 0.85
    _approve_one(2)
    assert fatigue.freshness_multiplier(acct, "rbi-rate-policy", db_path=temp_db) == 0.6
    assert fatigue.freshness_multiplier(acct, None, db_path=temp_db) == 1.0


def test_source_weights():
    assert source_weight_for({"source": "rss", "url": "https://thehindu.com/x"}) == 1.0
    assert source_weight_for({"source": "reddit", "url": "https://reddit.com/x"}) == 0.9
    assert source_weight_for({"source": "rss",
                              "url": "https://finance.yahoo.com/news/x"}) == 0.85
    assert source_weight_for({"source": "trends", "url": ""}) == 0.9
    assert source_weight_for({}) == 1.0  # unknown is never punished


def test_multipliers_applied_to_composite(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    # saturate the topic: 3 approved posts -> freshness floor 0.6
    for i in range(3):
        aid, _ = memory.insert_article({"source": "rss", "url": f"https://t/g{i}",
                                        "title": f"s{i}"}, db_path=temp_db)
        sid = memory.insert_signal({"article_id": aid, "account_id": acct,
                                    "score": 9, "tier": "FIRE",
                                    "topic": "rbi-rate-policy"}, db_path=temp_db)
        pid = memory.save_post(acct, "hot_take", "x", signal_id=sid, db_path=temp_db)
        memory.set_post_status(pid, "approved", db_path=temp_db)
    payload = json.dumps({"relevance": 10, "reaction_potential": 10, "angle": "a",
                          "topic": "rbi-rate-policy", "reasoning": "r"})
    art = {"id": 777, "source": "reddit", "title": STORY,
           "published_at": NOW.isoformat(), "velocity_hint": 10.0}
    sig = DecisionAgent(client=StubClient(payload)).score_article(
        art, {"id": acct}, now=NOW, db_path=temp_db)
    assert sig["freshness_mult"] == 0.6
    assert sig["source_weight"] == 0.9
    # raw composite gets cut nearly in half — saturated topic, social source
    raw = DecisionAgent(client=StubClient(payload)).composite(
        {k: sig[k] for k in ("velocity", "relevance", "corroboration",
                             "reaction_potential", "memory_leverage",
                             "window_urgency", "historical_perf")})
    assert sig["score"] == round(raw * 0.6 * 0.9, 3)


# ----------------------------------------------------- topic-level historical_perf
def test_historical_perf_topic_beats_vertical(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    art_id, _ = memory.insert_article({"source": "rss", "url": "https://t/h1",
                                       "title": "t", "vertical": "finance"},
                                      db_path=temp_db)
    sid = memory.insert_signal({"article_id": art_id, "account_id": acct,
                                "score": 9, "tier": "FIRE",
                                "topic": "rbi-rate-policy"}, db_path=temp_db)
    for _ in range(12):  # this topic always gets approved
        pid = memory.save_post(acct, "hot_take", "x", signal_id=sid,
                               article_id=art_id, db_path=temp_db)
        memory.set_post_status(pid, "approved", db_path=temp_db)
    hp = learning.historical_performance(acct, db_path=temp_db)
    assert hp["by_topic"]["rbi-rate-policy"] > 7.0
    assert hp["by_vertical"]["finance"] == hp["by_topic"]["rbi-rate-policy"]

    # the decision agent prefers topic over vertical over overall
    agent = DecisionAgent(client=StubClient(json.dumps(
        {"relevance": 5, "reaction_potential": 5, "angle": "",
         "topic": "rbi-rate-policy", "reasoning": ""})))
    sig = agent.score_article({"id": 1, "title": "t", "vertical": "politics"},
                              {"id": acct}, db_path=temp_db,
                              hist_perf={"overall": 5.0,
                                         "by_vertical": {"politics": 6.0},
                                         "by_topic": {"rbi-rate-policy": 9.0}})
    assert sig["historical_perf"] == 9.0
    sig = agent.score_article({"id": 1, "title": "t", "vertical": "politics"},
                              {"id": acct}, db_path=temp_db,
                              hist_perf={"overall": 5.0,
                                         "by_vertical": {"politics": 6.0},
                                         "by_topic": {}})
    assert sig["historical_perf"] == 6.0


def test_new_subscores_persist_to_signal_row(temp_db):
    acct_id = memory.upsert_account(handle="me", db_path=temp_db)
    account = memory.get_account(acct_id, db_path=temp_db)
    memory.insert_article({"source": "rss", "url": "https://t/p1",
                           "title": STORY, "published_at": NOW.isoformat()},
                          db_path=temp_db)
    payload = json.dumps({"relevance": 8, "reaction_potential": 8, "angle": "a",
                          "topic": "rbi-rate-policy", "reasoning": "r"})
    DecisionAgent(client=StubClient(payload)).run(account, db_path=temp_db)
    with memory.get_conn(temp_db) as conn:
        row = dict(conn.execute("SELECT * FROM signals").fetchone())
    assert row["corroboration"] is not None
    assert row["memory_leverage"] == 0.0
