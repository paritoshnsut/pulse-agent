"""Watch-layer tests — all parsing is pure; no network required."""

import feedparser
import pytest

from watch import reddit, trends, youtube
from watch.twitter import TwitterWatcher


# ------------------------------------------------------------------ reddit
def test_reddit_velocity_monotonic_and_bounded():
    slow = reddit.velocity_from_upvotes(5, age_hours=10)     # 0.5/hr
    fast = reddit.velocity_from_upvotes(2000, age_hours=1)   # 2000/hr
    assert 0.0 <= slow <= fast <= 10.0
    assert fast > 8.0           # a viral post scores high
    assert slow < 3.0           # a slow one scores low


def test_reddit_velocity_floors_age():
    # brand new post: age floored at 0.25h, so not infinite
    v = reddit.velocity_from_upvotes(10, age_hours=0.0)
    assert v <= 10.0


def test_reddit_parse_listing_shape_and_skips_stickied():
    payload = {"data": {"children": [
        {"data": {"title": "Big political news", "permalink": "/r/india/x",
                  "subreddit": "india", "score": 500, "created_utc": 1_700_000_000,
                  "author": "u1", "url_overridden_by_dest": "https://news.site/a"}},
        {"data": {"title": "pinned", "permalink": "/r/india/s", "stickied": True,
                  "subreddit": "india", "score": 1, "created_utc": 1_700_000_000}},
    ]}}
    arts = reddit.parse_listing(payload, vertical="politics", region="india")
    assert len(arts) == 1  # stickied dropped
    a = arts[0]
    assert a["source"] == "reddit"
    assert a["source_name"] == "r/india"
    assert a["url"] == "https://news.site/a"   # external link preferred
    assert a["vertical"] == "politics"
    assert a["velocity_hint"] is not None


def test_reddit_falls_back_to_thread_url_for_image_posts():
    payload = {"data": {"children": [
        {"data": {"title": "meme", "permalink": "/r/x/m", "subreddit": "x",
                  "score": 10, "created_utc": 1_700_000_000,
                  "url_overridden_by_dest": "https://i.redd.it/pic.jpg"}},
    ]}}
    arts = reddit.parse_listing(payload)
    assert arts[0]["url"].startswith("https://www.reddit.com/r/x/m")


# ----------------------------------------------------------------- youtube
YT_FEED = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Channel</title>
  <entry><title>New video on the budget</title>
    <link href="https://youtube.com/watch?v=abc"/>
    <published>2026-06-10T08:00:00+00:00</published>
    <author><name>Example</name></author></entry>
</feed>"""


def test_youtube_parse_channel():
    parsed = feedparser.parse(YT_FEED)
    arts = youtube.parse_channel(parsed, vertical="politics", region="india")
    assert len(arts) == 1
    assert arts[0]["source"] == "youtube"
    assert arts[0]["source_name"] == "Example Channel"
    assert arts[0]["url"] == "https://youtube.com/watch?v=abc"
    assert arts[0]["vertical"] == "politics"


# ------------------------------------------------------------------ trends
def test_trends_traffic_to_velocity():
    assert trends._traffic_to_velocity(None) is None
    low = trends._traffic_to_velocity("1,000+")
    high = trends._traffic_to_velocity("2M+")
    assert 0.0 <= low < high <= 10.0


def test_trends_parse():
    feed = """<?xml version="1.0"?><rss version="2.0"><channel><title>Trends</title>
    <item><title>Election results</title><link>https://g.co/x</link>
    <pubDate>Tue, 10 Jun 2025 09:00:00 GMT</pubDate></item></channel></rss>"""
    arts = trends.parse_trends(feedparser.parse(feed), region="india")
    assert len(arts) == 1
    assert arts[0]["source"] == "trends"
    assert arts[0]["region"] == "india"
    assert arts[0]["title"] == "Election results"


# --------------------------------------------------------------- wikipedia
def test_wikipedia_storm_detection(monkeypatch):
    # 6 edits to one page, 1 to another; threshold 5 -> one storm
    fake = {"query": {"recentchanges":
            [{"title": "Hot Topic", "timestamp": "t"} for _ in range(6)]
            + [{"title": "Quiet Page", "timestamp": "t"}]}}

    class FakeResp:
        def raise_for_status(self): ...
        def json(self): return fake

    monkeypatch.setattr(trends.requests, "get", lambda *a, **k: FakeResp())
    w = trends.WikipediaWatcher(storm_threshold=5)
    arts = w.fetch()
    assert len(arts) == 1
    assert "Hot Topic" in arts[0]["title"]
    assert arts[0]["source"] == "wikipedia"
    assert arts[0]["velocity_hint"] is not None


# ------------------------------------------------------------------ twitter
def test_twitter_disabled_returns_empty():
    w = TwitterWatcher(enabled=False)
    assert w.fetch() == []
    assert w.run()["total"] == 0


def test_twitter_enabled_without_impl_raises():
    w = TwitterWatcher(enabled=True)
    with pytest.raises(NotImplementedError):
        w.fetch()
