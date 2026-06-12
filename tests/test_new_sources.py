"""
Tests for Build 15: Google News RSS, PIB/wire feeds in sources catalog,
Wikipedia article summary enrichment, and Telegram channel post ingestion.
All are pure-logic or transport-injectable — no real network calls.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import feedparser

from pipeline import memory
from sources import feeds_for, source_weight_for
from watch import gnews as gn
from watch import trends as tr


# ============================================================ Google News RSS

def _fake_feed(entries):
    """Build a minimal feedparser-like dict."""
    fd = MagicMock(spec=feedparser.FeedParserDict)
    fd.entries = entries
    return fd


def _entry(title, url, source_title="NDTV", published=None):
    e = MagicMock()
    e.get = lambda k, d=None: {
        "title": title, "link": url,
        "summary": f"Summary of {title}",
        "published_parsed": published,
        "source": {"title": source_title},
    }.get(k, d)
    return e


def test_parse_gnews_shape():
    entries = [_entry("Budget 2026 passes", "https://ndtv.com/budget")]
    arts = gn.parse_gnews(_fake_feed(entries), "economy")
    assert len(arts) == 1
    a = arts[0]
    assert a["source"] == "gnews"
    assert a["source_name"] == "NDTV"
    assert a["url"] == "https://ndtv.com/budget"
    assert a["raw_json"]["query"] == "economy"


def test_parse_gnews_skips_missing_url_or_title():
    bad1 = _entry("No URL", None)
    bad2 = _entry(None, "https://x.com/notitle")
    good = _entry("Real Story", "https://thehindu.com/real")
    arts = gn.parse_gnews(_fake_feed([bad1, bad2, good]), "politics")
    assert len(arts) == 1
    assert arts[0]["title"] == "Real Story"


def test_gnews_watcher_derives_queries_from_account_topics(monkeypatch, temp_db):
    memory.upsert_account(handle="pol", topics=["policy", "economy"], db_path=temp_db)

    fetched_queries = []

    def fake_parse(url, agent=None):
        q = url.split("q=")[1].split("&")[0]
        from urllib.parse import unquote_plus
        fetched_queries.append(unquote_plus(q))
        return _fake_feed([])

    monkeypatch.setattr(gn.feedparser, "parse", fake_parse)
    w = gn.GoogleNewsWatcher(db_path=temp_db)
    w.run()
    assert "policy" in fetched_queries
    assert "economy" in fetched_queries


def test_gnews_watcher_deduplicates_across_accounts(monkeypatch, temp_db):
    memory.upsert_account(handle="a", topics=["policy"], db_path=temp_db)
    memory.upsert_account(handle="b", topics=["Policy"], db_path=temp_db)  # same, different case

    fetched_queries = []
    monkeypatch.setattr(gn.feedparser, "parse",
                        lambda url, agent=None: (fetched_queries.append(url), _fake_feed([]))[1])
    gn.GoogleNewsWatcher(db_path=temp_db).run()
    # "policy" and "Policy" should dedup to one fetch
    assert len(fetched_queries) == 1


def test_gnews_watcher_noop_with_no_accounts(monkeypatch, temp_db):
    calls = []
    monkeypatch.setattr(gn.feedparser, "parse",
                        lambda *a, **k: (calls.append(1), _fake_feed([]))[1])
    result = gn.GoogleNewsWatcher(db_path=temp_db).run()
    assert calls == []
    assert result == {"new": 0, "duplicate": 0, "total": 0}


# ============================================================ sources catalog

def test_politics_india_includes_pib_and_wire_agencies():
    feeds = feeds_for(["politics"], ["india"])
    urls = [f["url"] for f in feeds]
    names = [f["name"] for f in feeds]
    assert any("aninews" in u for u in urls), "ANI missing"
    assert any("thewire" in u for u in urls), "The Wire missing"
    assert any("theprint" in u for u in urls), "The Print missing"
    assert any("pib.gov.in" in u for u in urls), "PIB missing"
    assert any("altnews" in u for u in urls), "Alt News missing"


def test_gnews_source_weight_is_full():
    art = {"source": "gnews", "url": "https://news.google.com/x"}
    assert source_weight_for(art) == 1.0


def test_telegram_channel_source_weight_is_full():
    art = {"source": "telegram_channel", "url": "https://t.me/channel/1"}
    assert source_weight_for(art) == 1.0


# ============================================================ Wikipedia summary

def test_wiki_fetch_summary_returns_extract(monkeypatch):
    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"extract": "India passed the budget in parliament today."}

    monkeypatch.setattr(tr.requests, "get", lambda *a, **k: R())
    result = tr._fetch_wiki_summary("Indian_budget", lang="en")
    assert "budget in parliament" in result


def test_wiki_fetch_summary_returns_none_on_404(monkeypatch):
    class R:
        status_code = 404
        def raise_for_status(self): pass
        def json(self): return {}

    monkeypatch.setattr(tr.requests, "get", lambda *a, **k: R())
    assert tr._fetch_wiki_summary("NonExistent_Page") is None


def test_wiki_fetch_summary_returns_none_on_network_error(monkeypatch):
    monkeypatch.setattr(tr.requests, "get",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("timeout")))
    assert tr._fetch_wiki_summary("Anything") is None  # must not raise


def test_wikipedia_watcher_populates_content(monkeypatch):
    """WikipediaWatcher.fetch() now calls _fetch_wiki_summary per storm."""
    watcher = tr.WikipediaWatcher(storm_threshold=2)

    # Fake recentchanges: "Narendra Modi" edited 3 times → storm
    fake_changes = [{"title": "Narendra Modi"}] * 3
    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            # First call: recentchanges API
            # Second call: summary API
            return self._payload
        _payload = {"query": {"recentchanges": fake_changes}}

    call_count = [0]
    def fake_get(url, **kwargs):
        call_count[0] += 1
        r = R()
        if "rest_v1" in url:
            r._payload = {"extract": "Narendra Modi is the Prime Minister of India."}
        else:
            r._payload = {"query": {"recentchanges": fake_changes}}
        return r

    monkeypatch.setattr(tr.requests, "get", fake_get)
    arts = watcher.fetch()
    assert len(arts) == 1
    assert arts[0]["content"] is not None
    assert "Prime Minister" in arts[0]["content"]


# ============================================================ Telegram channel ingest

def test_telegram_channel_post_ingested_when_watched(temp_db):
    from pipeline.telegram_bot import TelegramCommander

    # Add a watch entry for the channel
    memory.add_watch(kind="telegram_channel", ref="@bjpitcell", label="BJP IT Cell",
                     db_path=temp_db)

    updates_sent = []

    def fake_transport(method, payload=None):
        if method == "getUpdates":
            return {"result": [{
                "update_id": 1001,
                "channel_post": {
                    "message_id": 42,
                    "chat": {"id": -1001234567890, "username": "bjpitcell",
                             "title": "BJP IT Cell", "type": "channel"},
                    "date": 1718000000,
                    "text": "Big announcement: PM Modi launches new scheme today.",
                }
            }]}
        updates_sent.append((method, payload))
        return {}

    commander = TelegramCommander(transport=fake_transport, db_path=temp_db)
    commander.poll_once()

    arts = memory.get_unprocessed_articles(db_path=temp_db)
    tg_arts = [a for a in arts if a["source"] == "telegram_channel"]
    assert len(tg_arts) == 1
    assert "PM Modi" in tg_arts[0]["title"]
    assert tg_arts[0]["source_name"] == "Telegram: BJP IT Cell"


def test_telegram_channel_post_ignored_when_not_watched(temp_db):
    from pipeline.telegram_bot import TelegramCommander

    # No watch entries for telegram_channel

    def fake_transport(method, payload=None):
        if method == "getUpdates":
            return {"result": [{
                "update_id": 1002,
                "channel_post": {
                    "message_id": 99,
                    "chat": {"id": -9999, "username": "somerandochannel",
                             "title": "Random", "type": "channel"},
                    "date": 1718000001,
                    "text": "Not relevant.",
                }
            }]}
        return {}

    TelegramCommander(transport=fake_transport, db_path=temp_db).poll_once()
    arts = memory.get_unprocessed_articles(db_path=temp_db)
    assert not any(a["source"] == "telegram_channel" for a in arts)


def test_telegram_channel_post_deduplicates(temp_db):
    """Same message_id arriving twice should not create two articles."""
    from pipeline.telegram_bot import TelegramCommander

    memory.add_watch(kind="telegram_channel", ref="@testchannel", label="Test",
                     db_path=temp_db)

    post = {
        "update_id": 2001,
        "channel_post": {
            "message_id": 77,
            "chat": {"id": -1001111111111, "username": "testchannel",
                     "title": "Test Channel", "type": "channel"},
            "date": 1718000002,
            "text": "Breaking news item.",
        }
    }

    def fake_transport(method, payload=None):
        return {"result": [post]} if method == "getUpdates" else {}

    c = TelegramCommander(transport=fake_transport, db_path=temp_db)
    c.poll_once()
    c.poll_once()   # second poll: same post — must dedup

    arts = [a for a in memory.get_unprocessed_articles(db_path=temp_db)
            if a["source"] == "telegram_channel"]
    assert len(arts) == 1
