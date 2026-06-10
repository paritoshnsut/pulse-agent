"""Image card + format-choice tests. Pillow tests skip if it isn't installed."""

import json

import pytest

from conftest import StubClient, patch_settings
from pipeline import memory, poster

PIL = pytest.importorskip("PIL", reason="Pillow not installed")
from PIL import Image, ImageDraw  # noqa: E402

from image import cards  # noqa: E402


# ---------------------------------------------------------------- rendering
def test_body_font_size_scales_down_with_length():
    assert cards.body_font_size("short") == 56
    assert cards.body_font_size("x" * 200) == 46
    assert cards.body_font_size("x" * 300) == 38


def test_wrap_to_width_wraps_and_breaks_long_words():
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font = cards._load_font(40)
    lines = cards.wrap_to_width(draw, "a few normal words " * 6, font, 400)
    assert len(lines) > 1
    assert all(draw.textlength(ln, font=font) <= 400 for ln in lines)
    # a single absurd word still gets hard-broken inside the width
    lines = cards.wrap_to_width(draw, "x" * 300, font, 400)
    assert len(lines) > 1
    assert all(draw.textlength(ln, font=font) <= 400 for ln in lines)
    # paragraph breaks survive
    assert "" in cards.wrap_to_width(draw, "one\n\ntwo", font, 400)


def test_render_card_writes_correct_png(tmp_path, monkeypatch):
    patch_settings(monkeypatch, cards, cards_dir=str(tmp_path), ai_label="🤖 AI-assisted")
    path = cards.render_card("RBI holds rates 🔥 again. let that sink in",
                             handle="markets_take")
    assert path.startswith(str(tmp_path)) and path.endswith(".png")
    with Image.open(path) as img:
        assert img.size == (cards.W, cards.H)


def test_render_card_survives_very_long_text(tmp_path, monkeypatch):
    patch_settings(monkeypatch, cards, cards_dir=str(tmp_path))
    path = cards.render_card("word " * 300, handle="me")
    with Image.open(path) as img:
        assert img.size == (cards.W, cards.H)


# ------------------------------------------------------------ poster wiring
def _post_row(db):
    acct_id = memory.upsert_account(handle="markets_take", db_path=db)
    pid = memory.save_post(acct_id, "hot_take", "RBI holds rates. let that sink in",
                           db_path=db)
    return memory.get_post(pid, db_path=db)


def test_make_card_disabled_returns_none(temp_db, monkeypatch):
    patch_settings(monkeypatch, poster, cards_enabled=False)
    assert poster.make_card(_post_row(temp_db), db_path=temp_db) is None


def test_make_card_renders_with_handle(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, poster, cards_enabled=True)
    patch_settings(monkeypatch, cards, cards_dir=str(tmp_path))
    path = poster.make_card(_post_row(temp_db), db_path=temp_db)
    assert path and path.endswith(".png")


def test_make_card_uses_first_tweet_for_threads(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, poster, cards_enabled=True)
    patch_settings(monkeypatch, cards, cards_dir=str(tmp_path))
    acct_id = memory.upsert_account(handle="me", db_path=temp_db)
    pid = memory.save_post(acct_id, "thread", "one\n\n———\n\ntwo",
                           meta={"tweets": ["hook tweet", "second"]}, db_path=temp_db)
    # rendering succeeds; the hook (not the whole thread) is what gets drawn
    assert poster.make_card(memory.get_post(pid, db_path=temp_db),
                            db_path=temp_db) is not None


def test_send_photo_uses_multipart_transport(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, poster, telegram_bot_token="tok",
                   telegram_chat_id="111")
    calls = []

    def photo_transport(method, payload, file_path):
        calls.append((method, payload, file_path))
        return {"ok": True}

    n = poster.TelegramNotifier(transport=lambda m, p: {"ok": True},
                                photo_transport=photo_transport)
    assert n.send_photo("/tmp/x.png", caption="c") is True
    assert calls[0][0] == "sendPhoto"
    assert calls[0][1]["chat_id"] == "111" and calls[0][2] == "/tmp/x.png"


# ----------------------------------------------------------- format choice
def test_judge_validates_format_choice():
    from pipeline.decision import DecisionAgent

    def _judge(fmt):
        payload = json.dumps({"relevance": 5, "reaction_potential": 5,
                              "angle": "", "topic": "t", "format": fmt,
                              "reasoning": ""})
        return DecisionAgent(client=StubClient(payload)).judge(
            {"title": "x"}, {"niche": "n"})

    assert _judge("thread")["format"] == "thread"
    assert _judge("data_story")["format"] == "data_story"
    assert _judge("callback")["format"] == "hot_take"   # watcher-only, rejected
    assert _judge("nonsense")["format"] == "hot_take"
    assert _judge("")["format"] == "hot_take"


def test_format_flows_into_signal_row(temp_db):
    from pipeline.decision import DecisionAgent

    acct_id = memory.upsert_account(handle="me", db_path=temp_db)
    memory.insert_article({"source": "rss", "url": "https://t/f",
                           "title": "Budget numbers out",
                           "published_at": memory._now()}, db_path=temp_db)
    payload = json.dumps({"relevance": 10, "reaction_potential": 10,
                          "angle": "a", "topic": "union-budget",
                          "format": "data_story", "reasoning": "r"})
    DecisionAgent(client=StubClient(payload)).run(
        memory.get_account(acct_id, db_path=temp_db), db_path=temp_db)
    sig = memory.get_signals_by_tier("FIRE", db_path=temp_db)[0]
    assert sig["format"] == "data_story"


def test_new_formats_registered_and_choosable():
    from pipeline.generator import CHOOSABLE_FORMATS, FORMATS

    for fmt in ("explainer", "prediction", "quote_context"):
        assert fmt in FORMATS and fmt in CHOOSABLE_FORMATS
        assert FORMATS[fmt][1] is False  # all single posts
    assert "callback" in FORMATS and "callback" not in CHOOSABLE_FORMATS
