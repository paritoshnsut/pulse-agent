"""watch/reddit_auth.py: OAuth token fetch, caching, expiry, and keyless fallback."""

import time

import pytest

from watch import reddit_auth as ra


class _FakeResp:
    def raise_for_status(self): pass
    def json(self): return {"access_token": "tok123", "expires_in": 3600}


# ---------------------------------------------------------- token lifecycle

def test_token_fetched_on_first_call(monkeypatch):
    calls = []
    monkeypatch.setattr(ra.requests, "post", lambda *a, **k: (calls.append(1), _FakeResp())[1])
    auth = ra.RedditAuth("cid", "secret", "testuser")
    h = auth.headers()
    assert h["Authorization"] == "Bearer tok123"
    assert len(calls) == 1


def test_token_cached_on_second_call(monkeypatch):
    calls = []
    monkeypatch.setattr(ra.requests, "post", lambda *a, **k: (calls.append(1), _FakeResp())[1])
    auth = ra.RedditAuth("cid", "secret", "testuser")
    auth.headers()
    auth.headers()          # should use the cached token
    assert len(calls) == 1


def test_token_refreshes_when_expired(monkeypatch):
    count = [0]
    def fake_post(*a, **k):
        count[0] += 1
        return _FakeResp()
    monkeypatch.setattr(ra.requests, "post", fake_post)
    auth = ra.RedditAuth("cid", "secret", "testuser")
    auth.headers()
    auth._expires_at = time.time() - 1   # force expiry
    auth.headers()                        # must re-fetch
    assert count[0] == 2


# ---------------------------------------------------------- credential absence

def test_no_credentials_returns_keyless_headers():
    auth = ra.RedditAuth("", "", "")
    h = auth.headers()
    assert "Authorization" not in h
    assert "User-Agent" in h


def test_no_credentials_base_url_is_www():
    auth = ra.RedditAuth("", "", "")
    assert auth.base_url == ra.WWW_BASE


def test_with_credentials_base_url_is_oauth():
    auth = ra.RedditAuth("cid", "secret", "u")
    assert auth.base_url == ra.OAUTH_BASE


# ---------------------------------------------------------- error resilience

def test_token_error_falls_back_to_keyless_headers(monkeypatch):
    def bad_post(*a, **k):
        raise RuntimeError("network error")
    monkeypatch.setattr(ra.requests, "post", bad_post)
    auth = ra.RedditAuth("cid", "secret", "u")
    h = auth.headers()          # must not raise
    assert "Authorization" not in h
    assert "User-Agent" in h


# ---------------------------------------------------------- integration: reddit.py

def test_reddit_watcher_uses_oauth_url_when_auth_configured(monkeypatch):
    """RedditWatcher passes an OAuth URL to requests.get when auth is set."""
    from watch.reddit import RedditWatcher, parse_listing
    from pipeline import memory

    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers", {})

        class R:
            def raise_for_status(self): pass
            def json(self): return {"data": {"children": []}}
        return R()

    auth = ra.RedditAuth("cid", "secret", "u")
    auth._token = "mytok"
    auth._expires_at = time.time() + 9999

    monkeypatch.setattr("watch.reddit.requests.get", fake_get)
    monkeypatch.setattr(memory, "get_watch",
                        lambda kind, db_path=None: [{"ref": "india"}])

    w = RedditWatcher(auth=auth)
    w.fetch()

    assert "oauth.reddit.com" in captured["url"]
    assert captured["headers"].get("Authorization") == "Bearer mytok"


def test_reddit_watcher_uses_www_when_no_credentials(monkeypatch):
    from watch.reddit import RedditWatcher
    from pipeline import memory

    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url

        class R:
            def raise_for_status(self): pass
            def json(self): return {"data": {"children": []}}
        return R()

    monkeypatch.setattr("watch.reddit.requests.get", fake_get)
    monkeypatch.setattr(memory, "get_watch",
                        lambda kind, db_path=None: [{"ref": "india"}])

    w = RedditWatcher(auth=ra.RedditAuth("", "", ""))
    w.fetch()

    assert "www.reddit.com" in captured["url"]
    assert "oauth.reddit.com" not in captured["url"]


# ---------------------------------------------------------- integration: discover.py

def test_discover_reddit_search_uses_oauth_url(monkeypatch):
    from watch import discover as dc

    captured = {}

    class R:
        def raise_for_status(self): pass
        def json(self): return {"data": {"children": []}}

    def fake_get(url, **kwargs):
        captured["url"] = url
        return R()

    monkeypatch.setattr(dc.requests, "get", fake_get)

    auth = ra.RedditAuth("cid", "secret", "u")
    auth._token = "disctok"
    auth._expires_at = time.time() + 9999

    dc.reddit_search("politics india", auth=auth)

    assert "oauth.reddit.com" in captured["url"]
