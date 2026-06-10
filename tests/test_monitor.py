"""News monitor tests — RSS parsed from a static string, no network needed."""

import feedparser

from pipeline import monitor
from pipeline.monitor import NewsMonitor

SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Test Feed</title>
  <item>
    <title>RBI holds repo rate at 6.5%</title>
    <link>https://example.com/rbi-rate</link>
    <description>The central bank kept rates unchanged.</description>
    <author>desk@example.com</author>
    <pubDate>Tue, 10 Jun 2025 09:30:00 GMT</pubDate>
  </item>
  <item>
    <title>GDP grows 7.2% in Q4</title>
    <link>https://example.com/gdp-q4</link>
    <description>Latest figures released.</description>
    <pubDate>Tue, 10 Jun 2025 08:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Headline with no link should be dropped</title>
    <description>no link here</description>
  </item>
</channel></rss>"""


def test_to_iso_handles_struct_time_string_and_none():
    parsed = feedparser.parse(SAMPLE_RSS)
    st = parsed.entries[0].published_parsed
    iso = monitor._to_iso(st)
    assert iso is not None and iso.startswith("2025-06-10")
    assert monitor._to_iso("2026-06-10T09:30:00Z").startswith("2026-06-10")
    assert monitor._to_iso(None) is None


def test_parse_rss_entries_normalizes_and_drops_linkless():
    parsed = feedparser.parse(SAMPLE_RSS)
    arts = NewsMonitor().parse_rss_entries(parsed)
    assert len(arts) == 2  # linkless item dropped
    first = arts[0]
    assert first["source"] == "rss"
    assert first["source_name"] == "Test Feed"
    assert first["url"] == "https://example.com/rbi-rate"
    assert first["title"] == "RBI holds repo rate at 6.5%"
    assert first["published_at"].startswith("2025-06-10")


def test_parse_newsapi_payload():
    payload = {
        "articles": [
            {"url": "https://n/1", "title": "Story one",
             "description": "d1", "content": "c1", "author": "A",
             "source": {"name": "NewsCorp"}, "publishedAt": "2026-06-10T07:00:00Z"},
            {"url": None, "title": "no url"},  # dropped
        ]
    }
    arts = NewsMonitor().parse_newsapi_payload(payload)
    assert len(arts) == 1
    assert arts[0]["source"] == "newsapi"
    assert arts[0]["source_name"] == "NewsCorp"
    assert arts[0]["published_at"].startswith("2026-06-10")


def test_persist_dedups_by_url(temp_db):
    parsed = feedparser.parse(SAMPLE_RSS)
    mon = NewsMonitor(db_path=temp_db)
    arts = mon.parse_rss_entries(parsed)

    first = mon.persist(arts)
    assert first["new"] == 2 and first["duplicate"] == 0

    # re-persisting the same batch should be all duplicates (UNIQUE url)
    second = mon.persist(arts)
    assert second["new"] == 0 and second["duplicate"] == 2


def test_parse_rss_entries_stamps_vertical_region():
    parsed = feedparser.parse(SAMPLE_RSS)
    arts = NewsMonitor().parse_rss_entries(
        parsed, vertical="politics", region="india", source_name="Override Name"
    )
    assert all(a["vertical"] == "politics" and a["region"] == "india" for a in arts)
    assert arts[0]["source_name"] == "Override Name"  # spec name overrides feed title


def test_persist_writes_vertical_region(temp_db):
    from pipeline import memory
    parsed = feedparser.parse(SAMPLE_RSS)
    mon = NewsMonitor(db_path=temp_db)
    arts = mon.parse_rss_entries(parsed, vertical="finance", region="us")
    mon.persist(arts)
    with memory.get_conn(temp_db) as conn:
        row = conn.execute("SELECT vertical, region FROM articles LIMIT 1").fetchone()
    assert row["vertical"] == "finance"
    assert row["region"] == "us"


def test_monitor_accepts_spec_dicts():
    spec = {"url": "http://x/feed", "name": "X", "vertical": "sports", "region": "us"}
    mon = NewsMonitor(rss_feeds=[spec])
    assert mon.feeds[0]["vertical"] == "sports"
    # plain strings still work (back-compat)
    mon2 = NewsMonitor(rss_feeds=["http://y/feed"])
    assert mon2.feeds[0]["url"] == "http://y/feed"
    assert mon2.feeds[0]["vertical"] is None


def test_fetch_newsapi_no_key_returns_empty(monkeypatch):
    import types
    monkeypatch.setattr(monitor, "settings", types.SimpleNamespace(news_api_key=""))
    assert NewsMonitor(rss_feeds=[]).fetch_newsapi("anything") == []
