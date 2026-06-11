"""Tests for the robustness layer: cost ledger + budget guard, grounding
shield, posted-draft corpus flywheel, backups, staleness warnings."""

import json
import os
from types import SimpleNamespace

from conftest import StubClient, patch_settings
from pipeline import llm, memory, poster
from pipeline.grounding import GroundingChecker, build_source_block
from style.corpus import file_posted_draft


class UsageClient:
    """Stub that mimics a real SDK response, usage included."""

    def __init__(self, payload="{}", input_tokens=1000, output_tokens=500):
        self.payload, self.inp, self.out = payload, input_tokens, output_tokens
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(text=self.payload)],
            usage=SimpleNamespace(input_tokens=self.inp, output_tokens=self.out))


# ------------------------------------------------------------- cost ledger
def test_tracked_create_logs_cost(temp_db, monkeypatch):
    # llm.memory IS the memory module — capture originals to avoid recursion
    orig_log, orig_cost = memory.log_claude_call, memory.cost_today
    monkeypatch.setattr(memory, "log_claude_call",
                        lambda *a, **k: orig_log(*a, db_path=temp_db))
    monkeypatch.setattr(memory, "cost_today",
                        lambda db_path=None: orig_cost(db_path=temp_db))
    llm.tracked_create(UsageClient(), "decision", model="claude-sonnet-4-6",
                       messages=[])
    spent = orig_cost(db_path=temp_db)
    # 1000 in * $3/M + 500 out * $15/M = 0.003 + 0.0075 = 0.0105
    assert spent == 0.0105
    with memory.get_conn(temp_db) as conn:
        row = dict(conn.execute("SELECT * FROM claude_logs").fetchone())
    assert row["module"] == "decision" and row["input_tokens"] == 1000


def test_tracked_create_skips_ledger_for_stubs(temp_db, monkeypatch):
    orig_cost = memory.cost_today
    monkeypatch.setattr(memory, "cost_today",
                        lambda db_path=None: orig_cost(db_path=temp_db))
    llm.tracked_create(StubClient("{}"), "decision", model="m", messages=[])
    assert orig_cost(db_path=temp_db) == 0.0


def test_budget_guard_blocks_and_alerts_once(temp_db, monkeypatch):
    patch_settings(monkeypatch, llm, daily_budget_usd=0.01)
    orig_get, orig_set = memory.kv_get, memory.kv_set
    monkeypatch.setattr(memory, "cost_today",
                        lambda db_path=None: 0.02)  # already over
    monkeypatch.setattr(memory, "kv_get",
                        lambda k, default=None, db_path=None: orig_get(k, default, db_path=temp_db))
    monkeypatch.setattr(memory, "kv_set",
                        lambda k, v, db_path=None: orig_set(k, v, db_path=temp_db))
    sent = []
    monkeypatch.setattr("pipeline.poster.TelegramNotifier.send",
                        lambda self, text, chat_id=None: sent.append(text) or True)
    client = UsageClient()
    for _ in range(3):
        try:
            llm.tracked_create(client, "decision", model="m", messages=[])
            assert False, "should have raised"
        except llm.BudgetExceeded:
            pass
    assert client.calls == []          # no API call ever made
    assert len(sent) == 1              # alert fired exactly once
    assert "budget" in sent[0].lower()


def test_budget_zero_disables_cap(monkeypatch):
    patch_settings(monkeypatch, llm, daily_budget_usd=0)
    monkeypatch.setattr(llm.memory, "cost_today", lambda db_path=None: 999.0)
    llm.tracked_create(StubClient("{}"), "decision", model="m", messages=[])  # no raise


# --------------------------------------------------------------- grounding
def test_grounding_flags_unsupported_claims():
    payload = json.dumps({"ungrounded_claims": ["GDP grew 9.1%"]})
    checker = GroundingChecker(client=StubClient(payload))
    out = checker.check("GDP grew 9.1% — wow", "Headline: GDP grows 7.2%")
    assert out == {"checked": True, "ungrounded_claims": ["GDP grew 9.1%"]}
    # auditor failure -> draft proceeds unflagged, checked=False
    out = GroundingChecker(client=StubClient("garbage")).check("d", "s")
    assert out["checked"] is False and out["ungrounded_claims"] == []


def test_build_source_block_includes_context():
    block = build_source_block({"title": "T", "description": "D", "angle": "A"},
                               context="Past stance: X")
    assert "T" in block and "Past stance: X" in block


class SeqStub:
    def __init__(self, *payloads):
        from conftest import _Msg
        self._Msg = _Msg
        self.payloads = list(payloads)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._Msg(self.payloads.pop(0) if self.payloads else "{}")


def test_generate_checked_grounding_forces_review(temp_db):
    from pipeline.generator import ContentGenerator

    draft = json.dumps({"text": "GDP grew 9.1% says the ministry",
                        "hashtags": [], "emotion": "surprise", "note": ""})
    flag = json.dumps({"ungrounded_claims": ["GDP grew 9.1%"]})
    stub = SeqStub(draft, flag)
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    gen = ContentGenerator(client=stub)
    best = gen.generate_checked(
        {"title": "GDP grows 7.2%"}, {}, "hot_take", scorer=None,
        grounding=GroundingChecker(client=stub),
        account_id=acct, persist=True, db_path=temp_db)
    assert best["ungrounded_claims"] == ["GDP grew 9.1%"]
    assert best["needs_review"] is True
    saved = memory.get_post(best["post_id"], db_path=temp_db)
    assert saved["meta_json"]["ungrounded_claims"] == ["GDP grew 9.1%"]
    # and the human-facing surfaces shout about it
    alert = poster.format_draft_alert(saved)
    assert "VERIFY BEFORE POSTING" in alert and "GDP grew 9.1%" in alert


def test_grounding_clean_draft_stays_clean(temp_db):
    from pipeline.generator import ContentGenerator

    draft = json.dumps({"text": "GDP grew 7.2%.", "hashtags": [],
                        "emotion": "neutral", "note": ""})
    clean = json.dumps({"ungrounded_claims": []})
    stub = SeqStub(draft, clean)
    best = ContentGenerator(client=stub).generate_checked(
        {"title": "GDP grows 7.2%"}, {}, "hot_take", scorer=None,
        grounding=GroundingChecker(client=stub))
    assert best["ungrounded_claims"] == []
    assert best["needs_review"] is False


# ---------------------------------------------------------------- flywheel
def _posted_with_perf(db, content="my posted take", likes=200):
    acct = memory.upsert_account(handle="me", db_path=db)
    pid = memory.save_post(acct, "hot_take", content, db_path=db)
    memory.mark_posted(pid, db_path=db)
    memory.record_engagement(pid, likes=likes, retweets=10, replies=2, db_path=db)
    return acct, pid


def test_flywheel_files_posted_draft_with_numbers(temp_db):
    acct, pid = _posted_with_perf(temp_db)
    assert file_posted_draft(pid, db_path=temp_db) is True
    samples = memory.get_voice_samples(acct, kind="own", db_path=temp_db)
    assert len(samples) == 1
    assert samples[0]["origin"] == "approved_draft"
    assert samples[0]["likes"] == 200
    # re-perf updates numbers in place, no duplicate sample
    memory.record_engagement(pid, likes=500, retweets=80, replies=9, db_path=temp_db)
    assert file_posted_draft(pid, db_path=temp_db) is True
    samples = memory.get_voice_samples(acct, kind="own", db_path=temp_db)
    assert len(samples) == 1 and samples[0]["likes"] == 500


def test_flywheel_threads_file_per_tweet(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    pid = memory.save_post(acct, "thread", "one\n\n———\n\ntwo",
                           meta={"tweets": ["one", "two"]}, db_path=temp_db)
    memory.mark_posted(pid, db_path=temp_db)
    memory.record_engagement(pid, likes=50, db_path=temp_db)
    file_posted_draft(pid, db_path=temp_db)
    assert len(memory.get_voice_samples(acct, kind="own", db_path=temp_db)) == 2


def test_flywheel_skips_unposted_or_unmeasured(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    pid = memory.save_post(acct, "hot_take", "draft only", db_path=temp_db)
    assert file_posted_draft(pid, db_path=temp_db) is False  # not posted
    memory.mark_posted(pid, db_path=temp_db)
    assert file_posted_draft(pid, db_path=temp_db) is False  # no engagement
    assert memory.get_voice_samples(acct, db_path=temp_db) == []


# ----------------------------------------------------------------- backups
def test_backup_creates_and_prunes(temp_db, tmp_path):
    memory.upsert_account(handle="me", db_path=temp_db)
    paths = [memory.backup_db(db_path=temp_db, out_dir=str(tmp_path), keep=2)
             for _ in range(3)]
    survivors = sorted(p.name for p in tmp_path.glob("agent-*.db"))
    assert len(survivors) == 2
    # newest backup is a valid, openable copy with our data
    import sqlite3
    conn = sqlite3.connect(paths[-1])
    n = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    conn.close()
    assert n == 1


# --------------------------------------------------------------- staleness
def test_stale_draft_warns_fresh_does_not(temp_db):
    from datetime import datetime, timedelta, timezone

    acct = memory.upsert_account(handle="me", db_path=temp_db)
    pid = memory.save_post(acct, "hot_take", "old take", db_path=temp_db)
    old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    with memory.get_conn(temp_db) as conn:
        conn.execute("UPDATE posts SET created_at = ? WHERE id = ?", (old, pid))
    alert = poster.format_draft_alert(memory.get_post(pid, db_path=temp_db))
    assert "h old" in alert and "moment" in alert
    fresh_pid = memory.save_post(acct, "hot_take", "fresh take", db_path=temp_db)
    fresh_alert = poster.format_draft_alert(memory.get_post(fresh_pid, db_path=temp_db))
    assert "moment" not in fresh_alert
