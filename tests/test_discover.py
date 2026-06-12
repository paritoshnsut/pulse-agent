"""Autonomous discovery (watch/discover.py): query derivation from account
topics, YouTube results parsing (ytInitialData walk, relative-time + views ->
velocity), Reddit site-wide search reuse, and the watcher's dedup + transcript
behavior."""

from datetime import datetime, timezone

from pipeline import memory
from watch import discover as dc

NOW = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------- queries
def test_account_queries_from_topics():
    acct = {"topics": ["politics", "policy", "economy", "elections",
                       "governance"], "niche": "x"}
    assert dc.account_queries(acct) == ["politics", "policy", "economy",
                                        "elections"]      # capped at 4


def test_account_queries_falls_back_to_niche():
    acct = {"topics": [], "niche": "political commentary: data-backed takes"}
    assert dc.account_queries(acct) == ["political commentary"]
    assert dc.account_queries({"topics": None, "niche": None}) == []


def test_all_queries_dedup_across_accounts(monkeypatch):
    from conftest import patch_settings
    a = {"topics": ["politics", "economy"]}
    b = {"topics": ["Economy", "cricket"]}      # 'economy' dedups case-insensitively
    out = dc.all_queries([a, b], max_total=10)
    assert out == ["politics", "economy", "cricket"]
    assert dc.all_queries([a, b], max_total=2) == ["politics", "economy"]


# ------------------------------------------------------- youtube results parse
def _video(vid, title, when="3 hours ago", views="12,345 views", owner="Some Channel"):
    return {"videoRenderer": {
        "videoId": vid,
        "title": {"runs": [{"text": title}]},
        "ownerText": {"runs": [{"text": owner}]},
        "publishedTimeText": {"simpleText": when},
        "viewCountText": {"simpleText": views},
    }}


def test_parse_youtube_results_walks_nested_layout():
    # videoRenderers buried at arbitrary depth — the walk must find them
    data = {"contents": {"sectionList": [
        {"items": [_video("abc12345678", "Budget reaction")]},
        {"deeper": {"x": [_video("def12345678", "Policy explainer",
                                 when="2 days ago", views="1.2M views")]}},
        {"promoRenderer": {"title": "ad, not a video"}},
    ]}}
    arts = dc.parse_youtube_results(data, "politics", now=NOW)
    assert len(arts) == 2
    a = arts[0]
    assert a["source"] == "yt_search"
    assert a["url"] == "https://www.youtube.com/watch?v=abc12345678"
    assert a["title"] == "Budget reaction"
    assert a["source_name"] == "YouTube · Some Channel"
    assert a["published_at"].startswith("2026-06-12T09:00")     # 3 hours ago
    assert a["raw_json"] == {"videoId": "abc12345678", "query": "politics",
                             "views": 12345}
    # 12,345 views over 3h -> solid velocity; 1.2M over 2 days even higher
    assert 0 < a["velocity_hint"] <= 10
    assert arts[1]["raw_json"]["views"] == 1_200_000


def test_parse_youtube_skips_unparseable_entries():
    data = {"a": [_video(None, "no id"), {"videoRenderer": {"videoId": "x" * 11}}]}
    assert dc.parse_youtube_results(data, "q", now=NOW) == []


def test_rel_time_and_views_helpers():
    assert dc._rel_time_to_iso("Streamed 2 hours ago", NOW).startswith("2026-06-12T10:00")
    assert dc._rel_time_to_iso("1 day ago", NOW).startswith("2026-06-11T12:00")
    assert dc._rel_time_to_iso("LIVE now", NOW) is None
    assert dc._views_to_int("1.2M views") == 1_200_000
    assert dc._views_to_int("87K views") == 87_000
    assert dc._views_to_int("943 views") == 943
    assert dc._views_to_int("") is None
    # velocity needs both views and a timestamp
    assert dc.views_velocity(None, NOW.isoformat()) is None
    assert dc.views_velocity(10_000, None) is None
    fast = dc.views_velocity(1_000_000, dc._rel_time_to_iso("1 hour ago", NOW), NOW)
    slow = dc.views_velocity(500, dc._rel_time_to_iso("2 days ago", NOW), NOW)
    assert fast > slow


# -------------------------------------------------------------- reddit search
def test_reddit_search_marks_source(monkeypatch):
    payload = {"data": {"children": [{"data": {
        "permalink": "/r/india/comments/x/post/", "title": "Big policy move",
        "subreddit": "india", "score": 240,
        "created_utc": NOW.timestamp() - 3600, "author": "u1",
    }}]}}

    class R:
        def raise_for_status(self): pass
        def json(self): return payload
    monkeypatch.setattr(dc.requests, "get", lambda *a, **k: R())
    arts = dc.reddit_search("policy")
    assert len(arts) == 1
    assert arts[0]["source"] == "reddit_search"
    assert "[found searching: policy]" in arts[0]["description"]
    assert arts[0]["velocity_hint"] > 0          # 240 upvotes in 1h


# ------------------------------------------------------------------- watcher
def test_discovery_watcher_end_to_end(temp_db):
    memory.upsert_account(handle="me", topics=["politics", "economy"],
                          db_path=temp_db)
    memory.upsert_account(handle="other", topics=["economy"], db_path=temp_db)

    yt_calls, rd_calls = [], []

    def fake_yt(q):
        yt_calls.append(q)
        vid = (q + "00000000000")[:11]          # stable per query -> dedupable
        return dc.parse_youtube_results(
            {"x": [_video(vid, f"video about {q}")]}, q, now=NOW)

    def fake_reddit(q):
        rd_calls.append(q)
        return []

    w = dc.DiscoveryWatcher(db_path=temp_db, yt_fetch=fake_yt,
                            reddit_fetch=fake_reddit,
                            transcript_fetcher=lambda url: "claim one claim two")
    out = w.run()
    # one search per unique topic across both accounts (rule #8)
    assert yt_calls == rd_calls == ["politics", "economy"]
    assert out["new"] == 2 and out["transcribed"] == 2
    # discovered videos carry transcripts -> video_reaction-able
    arts = [a for a in memory.get_unprocessed_articles(db_path=temp_db)
            if a["source"] == "yt_search"]
    assert len(arts) == 2 and all(a["content"] for a in arts)

    # second run: same results -> all duplicates, no re-transcription
    out2 = dc.DiscoveryWatcher(db_path=temp_db, yt_fetch=fake_yt,
                               reddit_fetch=fake_reddit,
                               transcript_fetcher=lambda url: "x").run()
    assert out2["new"] == 0 and out2["duplicate"] == 2 and out2["transcribed"] == 0


def test_discovery_no_accounts_is_noop(temp_db):
    out = dc.DiscoveryWatcher(db_path=temp_db,
                              yt_fetch=lambda q: [], reddit_fetch=lambda q: []).run()
    assert out == {"queries": 0, "new": 0, "duplicate": 0, "transcribed": 0}


def test_discovered_video_gets_video_reaction_treatment(temp_db):
    """The transcript_excerpt gate accepts yt_search, so discovered videos flow
    into the same video_reaction path as watched channels."""
    from pipeline.context import transcript_excerpt
    art = {"source": "yt_search", "content": "the minister claimed gdp doubled"}
    assert "gdp doubled" in transcript_excerpt(art)
    assert transcript_excerpt({"source": "trends", "content": "x"}) is None
