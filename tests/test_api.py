"""Web API tests — TestClient against a temp DB, stubbed Claude, no network."""

import json

import pytest
from fastapi.testclient import TestClient

from conftest import StubClient, patch_settings
from pipeline import memory


@pytest.fixture()
def client(temp_db, monkeypatch):
    """Authed TestClient wired to the temp DB, with Telegram/cards off."""
    from api import main as api_main
    from pipeline import poster

    monkeypatch.setattr(api_main, "DB", temp_db)
    patch_settings(monkeypatch, api_main, app_password="family-secret")
    patch_settings(monkeypatch, poster, telegram_bot_token="", telegram_chat_id="",
                   cards_enabled=False, ai_label="")
    c = TestClient(api_main.app)
    token = c.post("/api/login", json={"password": "family-secret"}).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def _seed_draft(db, content="RBI holds rates. let that sink in"):
    acct_id = memory.upsert_account(handle="me", niche="econ", db_path=db)
    pid = memory.save_post(acct_id, "hot_take", content, persona_score=84,
                           meta={"alt_hooks": ["Try this opener"]}, db_path=db)
    return acct_id, pid


# ---------------------------------------------------------------------- auth
def test_login_rejects_wrong_password(client):
    bare = TestClient(client.app)
    assert bare.post("/api/login", json={"password": "nope"}).status_code == 401
    assert bare.get("/api/accounts").status_code == 401
    assert bare.get("/api/status").status_code == 401


def test_index_serves_dashboard(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Pulse" in r.text
    # built React app when frontend/dist exists; build-free fallback otherwise
    assert "/assets/" in r.text or "preact" in r.text


# ------------------------------------------------------------------ accounts
def test_account_create_and_list(client, temp_db):
    r = client.post("/api/accounts", json={
        "handle": "@bhai", "niche": "cricket takes", "topics": ["cricket"]})
    assert r.status_code == 200
    assert r.json()["handle"] == "bhai"  # @ stripped
    accounts = client.get("/api/accounts").json()
    assert len(accounts) == 1
    assert accounts[0]["has_voice"] is False


def test_voice_training_endpoint(client, temp_db, monkeypatch):
    from api import main as api_main

    acct = client.post("/api/accounts", json={"handle": "me"}).json()
    # too few posts -> 400, no Claude call
    r = client.post(f"/api/accounts/{acct['id']}/style", json={"posts": ["one", "two"]})
    assert r.status_code == 400

    payload = json.dumps({"sentence_length": "short", "sarcasm_level": "high",
                          "tone": "combative", "signature_phrases": [],
                          "topics_preferred": [], "things_to_avoid": []})
    monkeypatch.setattr(api_main, "StyleDNAExtractor",
                        lambda: __import__("style.dna", fromlist=["StyleDNAExtractor"])
                        .StyleDNAExtractor(client=StubClient(payload)))
    posts = [f"post number {i} with some words?" for i in range(10)]
    r = client.post(f"/api/accounts/{acct['id']}/style", json={"posts": posts})
    assert r.status_code == 200
    assert r.json()["genome_a"]["sarcasm_level"] == "high"
    assert client.get(f"/api/accounts/{acct['id']}/style").json()["sample_count"] == 10
    assert client.get("/api/accounts").json()[0]["has_voice"] is True


def test_corpus_endpoints(client, temp_db, monkeypatch):
    from style import corpus as corpus_mod

    acct = client.post("/api/accounts", json={"handle": "me",
                                              "topics": ["rbi policy"]}).json()
    # add own samples with an analytics suffix
    r = client.post(f"/api/accounts/{acct['id']}/corpus",
                    json={"text": "tweet a | 120 30\ntweet b", "kind": "own"}).json()
    assert r["added"] == 2 and r["corpus"]["own"] == 2
    # inspiration is one piece
    r = client.post(f"/api/accounts/{acct['id']}/corpus",
                    json={"text": "An editorial.\n\nMore of it.",
                          "kind": "inspiration"}).json()
    assert r["corpus"]["inspiration"] == 1

    # a matching article -> suggestion appears in corpus stats
    memory.insert_article({"source": "rss", "url": "https://t/sg",
                           "title": "RBI policy outlook editorial",
                           "published_at": memory._now()}, db_path=temp_db)
    stats = client.get(f"/api/accounts/{acct['id']}/corpus").json()
    assert stats["counts"]["own"] == 2
    assert len(stats["suggestions"]) == 1
    sid = stats["suggestions"][0]["id"]
    client.post(f"/api/suggestions/{sid}/accept?account_id={acct['id']}")
    assert client.get(f"/api/accounts/{acct['id']}/corpus").json()["counts"]["inspiration"] == 2

    # retrain (Claude stubbed at the manager level)
    monkeypatch.setattr(corpus_mod.CorpusManager, "retrain",
                        lambda self, account_id, blend=None: {
                            "trained_on": 2, "inspiration_used": 2,
                            "genome_a": {}, "corpus": {}})
    assert client.post(f"/api/accounts/{acct['id']}/retrain").json()["trained_on"] == 2


# --------------------------------------------------------------- review lane
def test_full_review_lifecycle(client, temp_db, monkeypatch):
    from pipeline import updater as updater_mod

    monkeypatch.setattr(updater_mod.MemoryUpdater, "on_posted",
                        lambda self, pid, db_path=None: {"ok": True, "topic": "rbi",
                                                         "stance": "s", "prediction": None})
    acct_id, pid = _seed_draft(temp_db)

    drafts = client.get("/api/drafts").json()
    assert len(drafts) == 1
    assert drafts[0]["meta_json"]["alt_hooks"] == ["Try this opener"]

    r = client.post(f"/api/drafts/{pid}/approve").json()
    assert r["texts"] == ["RBI holds rates. let that sink in"]
    assert r["intent_urls"][0].startswith("https://x.com/intent/post?text=")
    assert "best posting windows" in r["timing"]
    assert memory.get_post(pid, db_path=temp_db)["status"] == "approved"
    assert client.get("/api/drafts?status=approved").json()[0]["id"] == pid

    r = client.post(f"/api/drafts/{pid}/posted",
                    json={"url": "https://x.com/me/status/1"}).json()
    assert r["memory"]["topic"] == "rbi"
    p = memory.get_post(pid, db_path=temp_db)
    assert p["status"] == "posted" and p["posted_url"] == "https://x.com/me/status/1"

    client.post(f"/api/drafts/{pid}/perf", json={"likes": 120, "retweets": 30})
    rows = memory.get_post_engagement(acct_id, db_path=temp_db)
    assert rows[0]["likes"] == 120


def test_reject_and_missing_draft(client, temp_db):
    _, pid = _seed_draft(temp_db)
    assert client.post(f"/api/drafts/{pid}/reject").json()["ok"] is True
    assert memory.get_post(pid, db_path=temp_db)["status"] == "rejected"
    assert client.post("/api/drafts/999/approve").status_code == 404


# ---------------------------------------------------- ideas/briefing/analytics
def test_briefing_ideas_analytics_status(client, temp_db):
    acct_id, pid = _seed_draft(temp_db)
    memory.set_post_status(pid, "approved", db_path=temp_db)

    assert "Morning briefing" in client.get(f"/api/briefing/{acct_id}").json()["text"]
    assert client.get(f"/api/ideas/{acct_id}").json() == []
    a = client.get(f"/api/analytics/{acct_id}").json()
    assert a["stats"]["approved"] == 1
    assert a["historical_perf"]["overall"] > 5.0
    assert a["timing"]["learned"] is False
    st = client.get("/api/status").json()
    assert st["accounts"] == 1 and st["outbox"] == 1 and st["auth_enabled"] is True


# -------------------------------------------------------------------- watch
def test_watch_add_list_remove(client):
    wid = client.post("/api/watch", json={
        "kind": "subreddit", "ref": "india", "label": "r/india"}).json()["id"]
    assert any(w["ref"] == "india" for w in client.get("/api/watch").json())
    client.delete(f"/api/watch/{wid}")
    assert all(w["ref"] != "india" for w in client.get("/api/watch").json())


# ----------------------------------------------------------------- evergreen
def test_evergreen_endpoint(client, temp_db, monkeypatch):
    from pipeline import evergreen as evergreen_mod

    acct = client.post("/api/accounts", json={"handle": "me"}).json()
    pid = memory.save_post(acct["id"], "evergreen", "standing take", db_path=temp_db)
    monkeypatch.setattr(evergreen_mod.EvergreenGenerator, "generate_for",
                        lambda self, account, topic=None: {"post_id": pid, "empty": False})
    # api imported the class directly — patch it there too
    from api import main as api_main
    monkeypatch.setattr(api_main, "EvergreenGenerator", evergreen_mod.EvergreenGenerator)
    r = client.post("/api/evergreen", json={"account_id": acct["id"], "topic": "fiscal"})
    assert r.status_code == 200 and r.json()["content"] == "standing take"
