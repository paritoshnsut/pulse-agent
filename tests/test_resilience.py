"""Operational-resilience hardening: SQLite concurrency pragmas, parallel feed
fetch, and the corpus source-diversity cap (anti-overfit)."""

import sqlite3
import threading
import time

from conftest import patch_settings
from pipeline import memory, monitor
from style.corpus import diversify_by_source


# ----------------------------------------------------- sqlite concurrency
def test_connection_sets_busy_timeout_and_synchronous(temp_db):
    with memory.get_conn(temp_db) as conn:
        # busy_timeout is returned in milliseconds
        bt = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert bt == int(memory.settings.db_busy_timeout_s * 1000)
        # synchronous NORMAL == 1
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1
        # WAL persisted from schema.sql
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_busy_timeout_absorbs_write_contention(temp_db):
    """A writer holding the DB briefly should make a second writer WAIT (the
    busy_timeout queue), not raise 'database is locked'."""
    memory.upsert_account(handle="me", db_path=temp_db)
    errors = []

    def hold_write():
        # open a raw connection, begin a write, sleep, commit
        c = sqlite3.connect(temp_db, timeout=30)
        c.execute("BEGIN IMMEDIATE")
        c.execute("UPDATE accounts SET niche = 'x' WHERE handle = 'me'")
        time.sleep(0.4)
        c.commit(); c.close()

    t = threading.Thread(target=hold_write)
    t.start()
    time.sleep(0.05)  # ensure the holder has the write lock
    try:
        # this would raise 'database is locked' WITHOUT busy_timeout; with it,
        # it queues behind the holder and succeeds
        memory.upsert_account(handle="me", niche="y", db_path=temp_db)
    except sqlite3.OperationalError as exc:  # pragma: no cover
        errors.append(str(exc))
    t.join()
    assert not errors, f"write contention not absorbed: {errors}"


# --------------------------------------------------------- parallel fetch
def test_fetch_rss_runs_concurrently_and_isolates_failures(monkeypatch):
    feeds = [{"url": f"http://feed/{i}", "name": f"F{i}",
              "vertical": "politics", "region": "india"} for i in range(8)]
    m = monitor.NewsMonitor(rss_feeds=feeds)

    def fake_fetch_one(spec):
        time.sleep(0.1)  # simulate network wait so the pool genuinely fans out
        if spec["url"].endswith("3"):
            return []  # _fetch_one already swallows its own exceptions
        return [{"url": spec["url"] + "/a", "title": "t"}]

    monkeypatch.setattr(m, "_fetch_one", fake_fetch_one)
    started = time.monotonic()
    out = m.fetch_rss()
    elapsed = time.monotonic() - started
    assert len(out) == 7                       # 8 feeds, feed 3 returned empty
    # 8 × 0.1s sequentially = 0.8s; concurrent (12 workers) finishes near 0.1s
    assert elapsed < 0.4, f"feeds not fetched concurrently ({elapsed:.2f}s)"


def test_fetch_rss_empty_feeds_returns_empty():
    assert monitor.NewsMonitor(rss_feeds=[]).fetch_rss() == []


# ------------------------------------------------------- diversity cap
def _s(source, i):
    return {"content": f"piece {i}", "source": source, "origin": "manual",
            "added_at": f"2026-06-{i:02d}"}


def test_diversify_caps_dominant_source():
    # 9 from one columnist, 2 from others; cap at 50% of a 6-item set -> max 3
    samples = [_s("Columnist A", i) for i in range(9)] + \
              [_s("Outlet B", 20), _s("Outlet C", 21)]
    out = diversify_by_source(samples, limit=6, cap_fraction=0.5)
    from collections import Counter
    counts = Counter(s["source"] for s in out)
    assert counts["Columnist A"] == 3            # capped at floor(6*0.5)
    assert "Outlet B" in counts and "Outlet C" in counts
    assert len(out) == 5                          # can't reach 6 without more sources


def test_diversify_respects_limit_and_order():
    samples = [_s(f"src{i}", i) for i in range(20)]  # all distinct sources
    out = diversify_by_source(samples, limit=10, cap_fraction=0.5)
    assert len(out) == 10
    assert out[0]["content"] == "piece 0"   # order preserved (newest-first caller)


def test_diversify_falls_back_to_origin_when_no_source():
    samples = [{"content": f"p{i}", "source": None, "origin": "manual"}
               for i in range(8)]
    out = diversify_by_source(samples, limit=8, cap_fraction=0.5)
    assert len(out) == 4   # all share origin 'manual' -> capped at 4


def test_retrain_applies_diversity_cap(temp_db, monkeypatch):
    import json
    from conftest import StubClient
    from style.corpus import CorpusManager

    patch_settings(monkeypatch, __import__("style.corpus", fromlist=["settings"]),
                   corpus_source_cap_fraction=0.5, corpus_max_inspiration=4)
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    memory.add_voice_samples(acct, [{"content": f"my own post {i} about econ?",
                                     "kind": "own"} for i in range(6)], db_path=temp_db)
    # 5 inspiration pieces all from one outlet -> cap should keep only 2 (50% of 4)
    memory.add_voice_samples(acct, [{"content": f"editorial {i}", "kind": "inspiration",
                                     "source": "The Same Paper"} for i in range(5)],
                             db_path=temp_db)
    payload = json.dumps({"sarcasm_level": "high", "signature_phrases": [],
                          "topics_preferred": [], "things_to_avoid": []})
    mgr = CorpusManager(client=StubClient(payload), db_path=temp_db)
    out = mgr.retrain(acct)
    assert out["inspiration_used"] == 2   # 5 from one source capped to floor(4*0.5)
