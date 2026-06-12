"""Per-brand listening: custom RSS feeds + Google News keyword queries."""

from pipeline import memory
from watch.listening import custom_feed_specs, google_news_rss_url, merge_feed_specs


def test_google_news_url_quotes_and_localizes():
    url = google_news_rss_url("adidas samba", region="india")
    assert url.startswith("https://news.google.com/rss/search?q=adidas+samba")
    assert "gl=IN" in url
    # default / unknown region -> US locale
    assert "gl=US" in google_news_rss_url("nike lawsuit")
    assert "gl=US" in google_news_rss_url("nike", region="global")


def test_custom_feed_specs_from_watch_list(temp_db):
    memory.add_watch(kind="rss_feed", ref="https://hypebeast.com/feed",
                     label="Hypebeast", vertical="lifestyle", db_path=temp_db)
    memory.add_watch(kind="news_query", ref="air jordan", label=None,
                     region="us", db_path=temp_db)
    memory.add_watch(kind="subreddit", ref="sneakers", db_path=temp_db)  # ignored

    specs = custom_feed_specs(db_path=temp_db)
    assert len(specs) == 2
    by_name = {s["name"]: s for s in specs}
    assert by_name["Hypebeast"]["url"] == "https://hypebeast.com/feed"
    assert by_name["Hypebeast"]["vertical"] == "lifestyle"
    q = by_name["News: air jordan"]
    assert "news.google.com/rss/search?q=air+jordan" in q["url"]
    # spec shape matches what NewsMonitor expects
    for s in specs:
        assert set(s.keys()) == {"url", "name", "vertical", "region"}


def test_merge_feed_specs_dedups_by_url():
    catalog = [{"url": "https://a/feed", "name": "A", "vertical": None, "region": None}]
    custom = [{"url": "https://a/feed", "name": "dup", "vertical": None, "region": None},
              {"url": "https://b/feed", "name": "B", "vertical": None, "region": None}]
    merged = merge_feed_specs(catalog, custom)
    assert [f["url"] for f in merged] == ["https://a/feed", "https://b/feed"]
    assert merged[0]["name"] == "A"               # catalog wins on collision


def test_deactivated_watch_rows_excluded(temp_db):
    wid = memory.add_watch(kind="rss_feed", ref="https://x/feed", db_path=temp_db)
    assert len(custom_feed_specs(db_path=temp_db)) == 1
    memory.remove_watch(wid, db_path=temp_db)
    assert custom_feed_specs(db_path=temp_db) == []
