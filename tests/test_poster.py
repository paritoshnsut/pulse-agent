"""Poster (manual posting dispatch) tests — fake transport, no keys, no network."""

from urllib.parse import quote

from conftest import patch_settings
from pipeline import poster


class FakeTransport:
    """Records Telegram API calls; returns ok. Stands in for default_transport."""

    def __init__(self):
        self.calls = []

    def __call__(self, method, payload):
        self.calls.append((method, payload))
        return {"ok": True, "result": []}


def _post(content="RBI holds rates. let that sink in", fmt="hot_take", **kw):
    base = {"id": 7, "format": fmt, "content": content, "persona_score": 84.0,
            "needs_review": 0, "status": "draft", "meta_json": {}}
    base.update(kw)
    return base


# ---------------------------------------------------------- postable text
def test_postable_texts_appends_ai_label(monkeypatch):
    patch_settings(monkeypatch, poster, ai_label="🤖 AI-assisted")
    texts = poster.postable_texts(_post())
    assert len(texts) == 1
    assert texts[0].endswith("🤖 AI-assisted")
    assert texts[0].startswith("RBI holds rates")


def test_postable_texts_label_disabled(monkeypatch):
    patch_settings(monkeypatch, poster, ai_label="")
    assert poster.postable_texts(_post()) == ["RBI holds rates. let that sink in"]


def test_postable_texts_thread_label_on_last_only(monkeypatch):
    patch_settings(monkeypatch, poster, ai_label="🤖 AI-assisted")
    p = _post(fmt="thread", meta_json={"tweets": ["one", "two", "three"]})
    texts = poster.postable_texts(p)
    assert len(texts) == 3
    assert "AI-assisted" not in texts[0] and "AI-assisted" not in texts[1]
    assert texts[2].endswith("🤖 AI-assisted")


def test_postable_texts_thread_falls_back_to_content_split(monkeypatch):
    patch_settings(monkeypatch, poster, ai_label="")
    p = _post(fmt="thread", content=f"one{poster.THREAD_SEP}two", meta_json={})
    assert poster.postable_texts(p) == ["one", "two"]


# ------------------------------------------------------------- intent url
def test_x_intent_url_encodes_everything():
    url = poster.x_intent_url("hello #tag & ₹110?")
    assert url.startswith("https://x.com/intent/post?text=")
    assert quote("hello #tag & ₹110?", safe="") in url
    assert "#" not in url.split("text=")[1]  # fully percent-encoded


# ------------------------------------------------------------- formatting
def test_format_draft_alert_has_commands_and_content():
    msg = poster.format_draft_alert(_post(), "RBI policy decision")
    assert "#7" in msg and "persona=84" in msg
    assert "re: RBI policy decision" in msg
    assert "RBI holds rates" in msg
    assert "/approve 7" in msg and "/reject 7" in msg


def test_format_approved_package_single(monkeypatch):
    patch_settings(monkeypatch, poster, ai_label="")
    msg = poster.format_approved_package(_post())
    assert "x.com/intent/post" in msg
    assert "/posted 7" in msg and "/perf 7" in msg
    assert "over the limit" not in msg  # under the cap, no warning


def test_format_approved_package_warns_over_limit(monkeypatch):
    patch_settings(monkeypatch, poster, ai_label="")
    msg = poster.format_approved_package(_post(content="x" * 300))
    assert "over the limit" in msg


def test_format_approved_package_thread_numbers_parts(monkeypatch):
    patch_settings(monkeypatch, poster, ai_label="")
    p = _post(fmt="thread", meta_json={"tweets": ["one", "two"]})
    msg = poster.format_approved_package(p)
    assert "thread of 2" in msg
    assert "[1/2] one" in msg and "[2/2] two" in msg
    assert msg.count("x.com/intent/post") == 2


# ---------------------------------------------------------------- telegram
def test_notifier_unconfigured_is_clean_noop(monkeypatch):
    patch_settings(monkeypatch, poster, telegram_bot_token="", telegram_chat_id="")
    t = FakeTransport()
    n = poster.TelegramNotifier(transport=t)
    assert n.configured is False
    assert n.notify_draft(_post()) is False
    assert t.calls == []


def test_notifier_sends_draft_alert(monkeypatch):
    patch_settings(monkeypatch, poster,
                   telegram_bot_token="tok", telegram_chat_id="111")
    t = FakeTransport()
    assert poster.TelegramNotifier(transport=t).notify_draft(_post(), "headline") is True
    method, payload = t.calls[0]
    assert method == "sendMessage"
    assert payload["chat_id"] == "111"
    assert "/approve 7" in payload["text"]


def test_channel_publish_only_when_channel_configured(monkeypatch):
    patch_settings(monkeypatch, poster, telegram_bot_token="tok",
                   telegram_chat_id="111", telegram_channel_id="")
    t = FakeTransport()
    assert poster.TelegramNotifier(transport=t).publish_to_channel(_post()) is False
    patch_settings(monkeypatch, poster, telegram_bot_token="tok",
                   telegram_chat_id="111", telegram_channel_id="@mychannel")
    assert poster.TelegramNotifier(transport=t).publish_to_channel(_post()) is True
    assert t.calls[-1][1]["chat_id"] == "@mychannel"


def test_dispatch_approved_returns_texts_and_urls(monkeypatch):
    patch_settings(monkeypatch, poster, telegram_bot_token="", ai_label="",
                   cards_enabled=False)
    out = poster.dispatch_approved(_post(), notifier=poster.TelegramNotifier(FakeTransport()))
    assert out["texts"] == ["RBI holds rates. let that sink in"]
    assert out["intent_urls"][0].startswith("https://x.com/intent/post?text=")
    assert out["telegram"] is False and out["channel"] is False
    assert out["card"] is None and out["card_sent"] is False
