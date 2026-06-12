"""One-paste voice onboarding tests: feed discovery, entry extraction, the
import → corpus → auto-retrain → niche-autofill flow, and the API endpoint.
All network is stubbed — no test touches the internet."""

from types import SimpleNamespace

import pytest

from pipeline import memory
from style import importer

LONG = ("This paragraph carries genuine written voice with opinions and "
        "rhythm, repeated enough times to clear the thin-entry bar. " * 4)


def _feed(entries):
    return SimpleNamespace(entries=entries)


def _entry(title="A post", text=LONG, link="https://blog.x/p1", html=False):
    body = f"<p>{text}</p>" if html else text
    return {"title": title, "summary": body, "link": link}


def _fake_parse(monkeypatch, feeds: dict):
    """feedparser.parse stub: known URLs return entries, others are empty."""
    import feedparser
    monkeypatch.setattr(feedparser, "parse",
                        lambda url: _feed(feeds.get(url, [])))


# ---------------------------------------------------------------- discovery
def test_discover_feed_url_is_already_a_feed(monkeypatch):
    _fake_parse(monkeypatch, {"https://me.substack.com/feed": [_entry()]})
    assert importer.discover_feed("https://me.substack.com/feed") \
        == "https://me.substack.com/feed"


def test_discover_feed_via_link_tag(monkeypatch):
    _fake_parse(monkeypatch, {"https://blog.x/the-real-feed.xml": [_entry()]})
    html = ('<html><head><link rel="alternate" type="application/rss+xml" '
            'href="/the-real-feed.xml"></head></html>')
    import requests
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: SimpleNamespace(text=html))
    assert importer.discover_feed("https://blog.x") \
        == "https://blog.x/the-real-feed.xml"


def test_discover_feed_via_common_path(monkeypatch):
    _fake_parse(monkeypatch, {"https://blog.x/feed": [_entry()]})
    import requests
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: SimpleNamespace(text="<html></html>"))
    assert importer.discover_feed("blog.x") == "https://blog.x/feed"


def test_discover_feed_none_when_nothing(monkeypatch):
    _fake_parse(monkeypatch, {})
    import requests
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: SimpleNamespace(text="<html></html>"))
    assert importer.discover_feed("https://no-feed.example") is None


# --------------------------------------------------------------- extraction
def test_extract_entries_strips_html_and_skips_thin(monkeypatch):
    entries = [
        _entry(title="Real <b>post</b>", text=LONG, html=True),
        _entry(title="Too thin", text="short note"),
        {"title": "Content field", "link": "https://blog.x/p3",
         "content": [{"value": f"<div>{LONG}</div>"}]},
    ]
    _fake_parse(monkeypatch, {"https://blog.x/feed": entries})
    out = importer.extract_entries("https://blog.x/feed")
    assert len(out) == 2                              # thin entry skipped
    assert out[0]["title"] == "Real post"
    assert "<" not in out[0]["text"]
    assert all(len(e["text"]) <= importer.MAX_SAMPLE_CHARS for e in out)


# ------------------------------------------------------------------- import
def _stub_retrain(monkeypatch, topics=("fintech", "markets", "rbi policy")):
    calls = []

    def fake_retrain(self, account_id, blend=None):
        calls.append(account_id)
        return {"genome_a": {"topics_preferred": list(topics)},
                "trained_on": 6, "inspiration_used": 0,
                "corpus": {"own": 6, "inspiration": 0}}
    monkeypatch.setattr(importer.CorpusManager, "retrain", fake_retrain)
    return calls


def test_import_voice_full_flow_trains_and_autofills_niche(temp_db, monkeypatch):
    entries = [_entry(title=f"Post {i}", text=f"{LONG} variant {i}",
                      link=f"https://blog.x/p{i}") for i in range(6)]
    _fake_parse(monkeypatch, {"https://blog.x/feed": entries})
    calls = _stub_retrain(monkeypatch)
    acct = memory.upsert_account(handle="founder", db_path=temp_db)

    out = importer.import_voice(acct, "https://blog.x/feed", db_path=temp_db)
    assert out["ok"] and out["imported"] == 6 and out["trained"] is True
    assert calls == [acct]
    samples = memory.get_voice_samples(acct, kind="own", db_path=temp_db)
    assert len(samples) == 6
    assert all(s["origin"] == "import:blog.x" for s in samples)
    assert samples[0]["content"].startswith("Post")   # title + body together
    # blank niche/topics were filled from the judged genome
    account = memory.get_account(acct, db_path=temp_db)
    assert account["niche"] == "fintech, markets, rbi policy"
    assert account["topics"] == ["fintech", "markets", "rbi policy"]


def test_import_voice_never_overwrites_explicit_niche(temp_db, monkeypatch):
    entries = [_entry(link=f"https://blog.x/p{i}", text=f"{LONG} v{i}")
               for i in range(6)]
    _fake_parse(monkeypatch, {"https://blog.x/feed": entries})
    _stub_retrain(monkeypatch)
    acct = memory.upsert_account(handle="founder", niche="climate tech",
                                 topics=["solar"], db_path=temp_db)
    out = importer.import_voice(acct, "https://blog.x/feed", db_path=temp_db)
    assert out["ok"] and "niche" not in out
    account = memory.get_account(acct, db_path=temp_db)
    assert account["niche"] == "climate tech" and account["topics"] == ["solar"]


def test_import_voice_is_idempotent(temp_db, monkeypatch):
    entries = [_entry(link=f"https://blog.x/p{i}", text=f"{LONG} v{i}")
               for i in range(6)]
    _fake_parse(monkeypatch, {"https://blog.x/feed": entries})
    _stub_retrain(monkeypatch)
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    importer.import_voice(acct, "https://blog.x/feed", db_path=temp_db)
    again = importer.import_voice(acct, "https://blog.x/feed", db_path=temp_db)
    assert again["imported"] == 0 and again["duplicates"] == 6
    assert len(memory.get_voice_samples(acct, kind="own", db_path=temp_db)) == 6


def test_import_voice_no_feed_is_clear_error(temp_db, monkeypatch):
    _fake_parse(monkeypatch, {})
    import requests
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: SimpleNamespace(text="<html></html>"))
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    out = importer.import_voice(acct, "https://no-feed.example", db_path=temp_db)
    assert out["ok"] is False and "feed" in out["error"]


def test_import_voice_retrain_failure_is_soft(temp_db, monkeypatch):
    entries = [_entry(link=f"https://blog.x/p{i}", text=f"{LONG} v{i}")
               for i in range(6)]
    _fake_parse(monkeypatch, {"https://blog.x/feed": entries})

    def boom(self, account_id, blend=None):
        raise RuntimeError("claude down")
    monkeypatch.setattr(importer.CorpusManager, "retrain", boom)
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    out = importer.import_voice(acct, "https://blog.x/feed", db_path=temp_db)
    assert out["ok"] and out["imported"] == 6        # the corpus still landed
    assert out["trained"] is False and "claude down" in out["train_error"]


# ----------------------------------------------------------------------- api
@pytest.fixture()
def api_client(temp_db, monkeypatch):
    from fastapi.testclient import TestClient

    from api import main as api_main
    from conftest import patch_settings

    patch_settings(monkeypatch, api_main, app_password="",
                   supabase_url="", supabase_jwt_secret="")
    monkeypatch.setattr(api_main, "DB", temp_db)
    return TestClient(api_main.app)


def test_import_voice_endpoint(api_client, temp_db, monkeypatch):
    entries = [_entry(link=f"https://blog.x/p{i}", text=f"{LONG} v{i}")
               for i in range(6)]
    _fake_parse(monkeypatch, {"https://blog.x/feed": entries})
    _stub_retrain(monkeypatch)
    acct = api_client.post("/api/accounts", json={"handle": "me"}).json()["id"]
    r = api_client.post(f"/api/accounts/{acct}/import-voice",
                        json={"url": "https://blog.x/feed"})
    assert r.status_code == 200
    body = r.json()
    assert body["imported"] == 6 and body["trained"] is True
    # an unusable URL is a clean 422 with the human-readable reason
    _fake_parse(monkeypatch, {})
    import requests
    monkeypatch.setattr(requests, "get",
                        lambda *a, **k: SimpleNamespace(text="<html></html>"))
    r = api_client.post(f"/api/accounts/{acct}/import-voice",
                        json={"url": "https://no-feed.example"})
    assert r.status_code == 422 and "feed" in r.json()["detail"]


def test_drafts_endpoint_includes_why(api_client, temp_db):
    acct = api_client.post("/api/accounts", json={"handle": "me"}).json()["id"]
    art_id, _ = memory.insert_article(
        {"title": "RBI holds rates at 6.5%", "url": "https://news.x/rbi",
         "source": "newsapi", "source_name": "Reuters", "description": "d"},
        db_path=temp_db)
    sig_id = memory.insert_signal(
        {"article_id": art_id, "account_id": acct, "score": 8.7, "tier": "FIRE",
         "angle": "the base-effect angle nobody mentions",
         "topic": "rbi-rate-policy", "format": "hot_take"}, db_path=temp_db)
    memory.save_post(acct, "hot_take", "Rates held. Look at the base effect.",
                     signal_id=sig_id, article_id=art_id, db_path=temp_db)
    drafts = api_client.get("/api/drafts").json()
    assert len(drafts) == 1
    why = drafts[0]["why"]
    assert why["score"] == 8.7 and why["tier"] == "FIRE"
    assert why["angle"].startswith("the base-effect")
    assert why["source_name"] == "Reuters"
    assert why["source_title"] == "RBI holds rates at 6.5%"
    assert why["source_url"] == "https://news.x/rbi"
