"""Memory updater (System 4) tests — stub client, temp DB, failure-safe paths."""

import json

from conftest import StubClient
from pipeline import memory
from pipeline.updater import MemoryUpdater


FILED = {"topic": "rbi-rate-policy",
         "stance": "thinks the hold quietly punishes savers",
         "prediction": "RBI will cut rates by March 2027",
         "horizon": "by March 2027"}


def _seed_posted(db, with_article=True, with_signal=True):
    """account + (article) + (signal w/ topic hint) + a posted post."""
    acct_id = memory.upsert_account(handle="me", db_path=db)
    art_id = sig_id = None
    if with_article:
        art_id, _ = memory.insert_article({
            "source": "rss", "url": "https://t/story", "title": "RBI holds rates",
            "published_at": "2026-06-09T00:00:00+00:00"}, db_path=db)
    if with_signal and art_id:
        sig_id = memory.insert_signal({
            "article_id": art_id, "account_id": acct_id, "score": 9.0,
            "tier": "FIRE", "topic": "rbi-rate-policy"}, db_path=db)
    pid = memory.save_post(acct_id, "hot_take",
                           "Rates held AGAIN. Savers lose. RBI will cut by March 2027, watch.",
                           signal_id=sig_id, article_id=art_id, db_path=db)
    memory.mark_posted(pid, url="https://x.com/me/status/9", db_path=db)
    return acct_id, pid


# ----------------------------------------------------------------- extract
def test_extract_normalizes_topic_and_nulls():
    up = MemoryUpdater(client=StubClient(json.dumps(
        {"topic": "RBI Rate Policy", "stance": "s", "prediction": None, "horizon": None})))
    out = up.extract("post text")
    assert out["topic"] == "rbi-rate-policy"
    assert out["prediction"] is None and out["horizon"] is None


def test_extract_falls_back_to_hint_on_garbage():
    up = MemoryUpdater(client=StubClient("not json"))
    out = up.extract("post text", topic_hint="fiscal-deficit")
    assert out["topic"] == "fiscal-deficit"
    assert out["stance"] == "" and out["prediction"] is None


def test_extract_prompt_carries_story_and_hint():
    stub = StubClient(json.dumps(FILED))
    MemoryUpdater(client=stub).extract(
        "my post", article={"title": "RBI holds rates", "description": "d"},
        topic_hint="rbi-rate-policy")
    prompt = stub.messages.calls[0]["messages"][0]["content"]
    assert "RBI holds rates" in prompt and "rbi-rate-policy" in prompt


# --------------------------------------------------------------- on_posted
def test_on_posted_files_stance_event_and_prediction(temp_db):
    acct_id, pid = _seed_posted(temp_db)
    report = MemoryUpdater(client=StubClient(json.dumps(FILED))).on_posted(
        pid, db_path=temp_db)
    assert report["ok"] is True

    stances = memory.find_stances(acct_id, ["savers"], db_path=temp_db)
    assert len(stances) == 1
    assert stances[0]["topic"] == "rbi-rate-policy"
    assert stances[0]["source_url"] == "https://x.com/me/status/9"

    preds = memory.get_open_predictions(acct_id, db_path=temp_db)
    assert len(preds) == 1
    assert preds[0]["prediction"] == FILED["prediction"]
    assert preds[0]["post_id"] == pid and preds[0]["status"] == "open"

    events = memory.find_events(["rbi"], db_path=temp_db)
    assert len(events) == 1 and events[0]["summary"] == "RBI holds rates"


def test_on_posted_event_dedupes_with_decision_seed(temp_db):
    acct_id, pid = _seed_posted(temp_db)
    # decision.run already logged this story when the signal fired
    memory.seed_event("rbi-rate-policy", "RBIs holds rates",
                      source_url="https://x.com/me/status/9", db_path=temp_db)
    MemoryUpdater(client=StubClient(json.dumps(FILED))).on_posted(pid, db_path=temp_db)
    assert len(memory.find_events(["rbi"], db_path=temp_db)) == 1


def test_on_posted_without_article_or_prediction(temp_db):
    acct_id, pid = _seed_posted(temp_db, with_article=False, with_signal=False)
    filed = {"topic": "general-take", "stance": "a position",
             "prediction": None, "horizon": None}
    report = MemoryUpdater(client=StubClient(json.dumps(filed))).on_posted(
        pid, db_path=temp_db)
    assert report["ok"] is True and report["prediction_id"] is None
    assert memory.get_open_predictions(acct_id, db_path=temp_db) == []
    # event falls back to the post content as summary
    assert "Rates held AGAIN" in memory.find_events(["general"], db_path=temp_db)[0]["summary"]


def test_on_posted_never_raises(temp_db):
    class Boom:
        @property
        def messages(self):
            raise RuntimeError("api down")

    report = MemoryUpdater(client=Boom()).on_posted(999, db_path=temp_db)
    assert report["ok"] is False and "no post" in report["error"]
    _, pid = _seed_posted(temp_db)
    report = MemoryUpdater(client=Boom()).on_posted(pid, db_path=temp_db)
    assert report["ok"] is False and "api down" in report["error"]


def test_resolve_prediction_lifecycle(temp_db):
    acct_id = memory.upsert_account(handle="me", db_path=temp_db)
    pred_id = memory.insert_prediction(acct_id, "X will happen", topic="t",
                                       db_path=temp_db)
    assert len(memory.get_open_predictions(acct_id, db_path=temp_db)) == 1
    memory.resolve_prediction(pred_id, outcome="X happened", db_path=temp_db)
    assert memory.get_open_predictions(acct_id, db_path=temp_db) == []
