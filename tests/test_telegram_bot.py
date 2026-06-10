"""Telegram commander tests — fake transport, full phone flow, no network."""

import pytest

from conftest import patch_settings
from pipeline import memory, poster, telegram_bot
from pipeline.telegram_bot import TelegramCommander


class FakeTransport:
    """Scriptable Telegram API: getUpdates returns queued updates once."""

    def __init__(self, updates=None):
        self.updates = list(updates or [])
        self.calls = []

    def __call__(self, method, payload):
        self.calls.append((method, payload))
        if method == "getUpdates":
            out, self.updates = self.updates, []
            return {"ok": True, "result": out}
        return {"ok": True, "result": {}}

    def sent_texts(self):
        return [p["text"] for m, p in self.calls if m == "sendMessage"]


def _update(update_id, text, chat_id=111):
    return {"update_id": update_id,
            "message": {"chat": {"id": chat_id}, "text": text}}


@pytest.fixture()
def commander(temp_db, monkeypatch):
    """Commander wired to a temp DB, configured Telegram, one seeded draft."""
    for mod in (telegram_bot, poster):
        patch_settings(monkeypatch, mod, telegram_bot_token="tok",
                       telegram_chat_id="111", telegram_channel_id="", ai_label="",
                       cards_enabled=False)
    # /posted triggers the memory updater (a Claude call) — stub it so tests
    # never touch the network even when a real key sits in .env.
    from pipeline import updater as updater_mod
    monkeypatch.setattr(updater_mod.MemoryUpdater, "on_posted",
                        lambda self, pid, db_path=None: {"ok": False, "error": "stubbed"})
    acct_id = memory.upsert_account(handle="me", db_path=temp_db)
    pid = memory.save_post(acct_id, "hot_take", "RBI holds rates. let that sink in",
                           persona_score=84, db_path=temp_db)
    transport = FakeTransport()
    c = TelegramCommander(transport=transport, db_path=temp_db)
    return c, transport, pid


# --------------------------------------------------------------- commands
def test_help_and_unknown(commander):
    c, _, _ = commander
    assert "/approve" in c.handle("/help")
    assert "Unknown command" in c.handle("/dance")


def test_list_and_show(commander):
    c, _, pid = commander
    assert f"#{pid}" in c.handle("/list")
    assert "RBI holds rates" in c.handle(f"/show {pid}")
    assert "No draft #999" in c.handle("/show 999")


def test_approve_returns_package_and_sets_status(commander):
    c, _, pid = commander
    reply = c.handle(f"/approve {pid}")
    assert "x.com/intent/post" in reply
    assert f"/posted {pid}" in reply
    assert memory.get_post(pid, db_path=c.db_path)["status"] == "approved"


def test_reject_sets_status(commander):
    c, _, pid = commander
    assert "rejected" in c.handle(f"/reject {pid}")
    assert memory.get_post(pid, db_path=c.db_path)["status"] == "rejected"


def test_posted_with_url_closes_lifecycle(commander):
    c, _, pid = commander
    c.handle(f"/approve {pid}")
    reply = c.handle(f"/posted {pid} https://x.com/me/status/1")
    assert "marked posted" in reply
    p = memory.get_post(pid, db_path=c.db_path)
    assert p["status"] == "posted"
    assert p["posted_url"] == "https://x.com/me/status/1"
    assert p["posted_at"] is not None


def test_outbox_shows_approved_unposted(commander):
    c, _, pid = commander
    assert "Outbox empty" in c.handle("/outbox")
    c.handle(f"/approve {pid}")
    assert f"#{pid}" in c.handle("/outbox")
    c.handle(f"/posted {pid}")
    assert "Outbox empty" in c.handle("/outbox")


def test_perf_records_engagement(commander):
    c, _, pid = commander
    reply = c.handle(f"/perf {pid} 120 30 4 20000")
    assert "120 likes" in reply
    acct = memory.list_active_accounts(db_path=c.db_path)[0]
    rows = memory.get_post_engagement(acct["id"], db_path=c.db_path)
    assert rows[0]["likes"] == 120 and rows[0]["retweets"] == 30
    assert rows[0]["replies"] == 4 and rows[0]["views"] == 20000


def test_bad_args_do_not_crash(commander):
    c, _, _ = commander
    assert "Couldn't parse" in c.handle("/approve notanumber")
    assert "Couldn't parse" in c.handle("/perf")


# ---------------------------------------------------------------- polling
def test_poll_once_handles_command_and_advances_offset(commander):
    c, transport, pid = commander
    transport.updates = [_update(41, f"/approve {pid}")]
    assert c.poll_once() == 1
    assert memory.get_post(pid, db_path=c.db_path)["status"] == "approved"
    # reply went back to the chat
    assert any("x.com/intent/post" in t for t in transport.sent_texts())
    # offset persisted: next poll asks past update 41
    assert memory.kv_get(telegram_bot.OFFSET_KEY, db_path=c.db_path) == "41"
    c.poll_once()
    last_get = [p for m, p in transport.calls if m == "getUpdates"][-1]
    assert last_get["offset"] == 42


def test_poll_once_ignores_strangers(commander):
    c, transport, pid = commander
    transport.updates = [_update(50, f"/approve {pid}", chat_id=666)]
    assert c.poll_once() == 0
    assert memory.get_post(pid, db_path=c.db_path)["status"] == "draft"
    # offset still advances so the stranger's message isn't refetched forever
    assert memory.kv_get(telegram_bot.OFFSET_KEY, db_path=c.db_path) == "50"


def test_poll_once_noop_when_unconfigured(temp_db, monkeypatch):
    patch_settings(monkeypatch, telegram_bot, telegram_bot_token="", telegram_chat_id="")
    t = FakeTransport([_update(1, "/list")])
    assert TelegramCommander(transport=t, db_path=temp_db).poll_once() == 0
    assert t.calls == []
