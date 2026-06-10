"""Multi-account + watch-list + real-velocity tests."""

import json
from datetime import datetime, timezone

from conftest import StubClient
from pipeline import decision, memory


def _article(url, title, vertical, region, vel=None, db_path=None):
    return memory.insert_article({
        "source": "rss", "url": url, "title": title, "vertical": vertical,
        "region": region, "velocity_hint": vel,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }, db_path=db_path)


# --------------------------------------------------- account vertical scoping
def test_account_stores_and_parses_verticals(temp_db):
    aid = memory.upsert_account(handle="markets", verticals=["finance"],
                                regions=["india", "us"], db_path=temp_db)
    acct = memory.get_account(aid, db_path=temp_db)
    assert acct["verticals"] == ["finance"]
    assert acct["regions"] == ["india", "us"]


def test_unscored_queue_filters_by_vertical(temp_db):
    aid = memory.upsert_account(handle="markets", verticals=["finance"],
                                regions=["india"], db_path=temp_db)
    acct = memory.get_account(aid, db_path=temp_db)
    _article("http://x/fin", "Markets move", "finance", "india", db_path=temp_db)
    _article("http://x/pol", "Election news", "politics", "india", db_path=temp_db)
    _article("http://x/ent", "Movie premiere", "entertainment", "india", db_path=temp_db)

    queue = memory.get_unscored_for_account(acct, db_path=temp_db)
    titles = {a["title"] for a in queue}
    assert titles == {"Markets move"}  # only its vertical


def test_unscored_queue_filters_by_region(temp_db):
    aid = memory.upsert_account(handle="india_only", verticals=["finance"],
                                regions=["india"], db_path=temp_db)
    acct = memory.get_account(aid, db_path=temp_db)
    _article("http://x/in", "India markets", "finance", "india", db_path=temp_db)
    _article("http://x/us", "US markets", "finance", "us", db_path=temp_db)
    queue = memory.get_unscored_for_account(acct, db_path=temp_db)
    assert {a["title"] for a in queue} == {"India markets"}


def test_empty_verticals_sees_everything(temp_db):
    aid = memory.upsert_account(handle="generalist", db_path=temp_db)  # no scoping
    acct = memory.get_account(aid, db_path=temp_db)
    _article("http://x/a", "A", "finance", "india", db_path=temp_db)
    _article("http://x/b", "B", "politics", "us", db_path=temp_db)
    assert len(memory.get_unscored_for_account(acct, db_path=temp_db)) == 2


def test_two_accounts_each_score_same_article_once(temp_db):
    a1 = memory.upsert_account(handle="acct1", verticals=["finance"], db_path=temp_db)
    a2 = memory.upsert_account(handle="acct2", verticals=["finance"], db_path=temp_db)
    acct1 = memory.get_account(a1, db_path=temp_db)
    acct2 = memory.get_account(a2, db_path=temp_db)
    aid, _ = _article("http://x/shared", "Shared story", "finance", "india", db_path=temp_db)

    # both see it initially
    assert len(memory.get_unscored_for_account(acct1, db_path=temp_db)) == 1
    assert len(memory.get_unscored_for_account(acct2, db_path=temp_db)) == 1

    # acct1 scores it
    memory.mark_scored(a1, aid, db_path=temp_db)
    assert len(memory.get_unscored_for_account(acct1, db_path=temp_db)) == 0  # done for acct1
    assert len(memory.get_unscored_for_account(acct2, db_path=temp_db)) == 1  # still pending for acct2


# --------------------------------------------------------------- watch list
def test_watch_list_dedups_by_kind_ref(temp_db):
    id1 = memory.add_watch("subreddit", "india", "r/india", "politics", "india", db_path=temp_db)
    id2 = memory.add_watch("subreddit", "india", "r/india", "politics", "india", db_path=temp_db)
    assert id1 == id2  # same source, not duplicated
    assert len(memory.get_watch(kind="subreddit", db_path=temp_db)) == 1


def test_watch_list_filter_by_kind(temp_db):
    memory.add_watch("subreddit", "india", db_path=temp_db)
    memory.add_watch("trends_geo", "IN", db_path=temp_db)
    assert len(memory.get_watch(kind="subreddit", db_path=temp_db)) == 1
    assert len(memory.get_watch(db_path=temp_db)) == 2


# ----------------------------------------------------- real velocity in score
def test_real_velocity_hint_used_over_recency(temp_db):
    aid = memory.upsert_account(handle="x", db_path=temp_db)
    acct = memory.get_account(aid, db_path=temp_db)
    # high velocity_hint should drive the velocity subscore regardless of recency
    art = {"id": 1, "title": "viral", "published_at": datetime.now(timezone.utc).isoformat(),
           "velocity_hint": 9.5}
    payload = json.dumps({"relevance": 5, "reaction_potential": 5, "angle": "", "reasoning": ""})
    sig = decision.DecisionAgent(client=StubClient(payload)).score_article(art, acct)
    assert sig["velocity"] == 9.5
    assert sig["velocity_is_real"] is True


def test_recency_used_when_no_hint(temp_db):
    aid = memory.upsert_account(handle="x", db_path=temp_db)
    acct = memory.get_account(aid, db_path=temp_db)
    art = {"id": 1, "title": "t", "published_at": datetime.now(timezone.utc).isoformat()}
    payload = json.dumps({"relevance": 5, "reaction_potential": 5, "angle": "", "reasoning": ""})
    sig = decision.DecisionAgent(client=StubClient(payload)).score_article(art, acct)
    assert sig["velocity_is_real"] is False
    assert sig["velocity"] > 9.0  # fresh -> high recency velocity


def test_stale_articles_skipped(temp_db):
    from datetime import timedelta
    aid = memory.upsert_account(handle="x", db_path=temp_db)
    acct = memory.get_account(aid, db_path=temp_db)
    old = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
    _article("http://x/old", "Old news", "finance", "india", db_path=temp_db)
    # patch the article's published_at to be old
    with memory.get_conn(temp_db) as conn:
        conn.execute("UPDATE articles SET published_at = ? WHERE url = 'http://x/old'", (old,))
    payload = json.dumps({"relevance": 9, "reaction_potential": 9, "angle": "a", "reasoning": "r"})
    tally = decision.DecisionAgent(client=StubClient(payload)).run(acct, db_path=temp_db)
    assert tally["stale_skipped"] == 1
    assert tally["FIRE"] == 0  # never scored
