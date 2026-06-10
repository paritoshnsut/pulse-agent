"""Tests for the last three formats: video_reaction (keyless transcripts),
achievement (choosable), evergreen (stance-memory driven, on demand)."""

import json

from conftest import _Msg, patch_settings
from pipeline import memory, poster, telegram_bot
from pipeline.context import transcript_excerpt
from pipeline.evergreen import EvergreenGenerator
from pipeline.generator import CHOOSABLE_FORMATS, FORMATS
from watch import youtube


class SeqStub:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Msg(self.payloads.pop(0) if self.payloads else "{}")


# ------------------------------------------------------------------ registry
def test_all_twelve_formats_now_registered():
    assert set(FORMATS) >= {
        "hot_take", "contradiction", "data_story", "thread", "callback",
        "explainer", "prediction", "quote_context", "counter_narrative",
        "video_reaction", "achievement", "evergreen",
    }
    assert "achievement" in CHOOSABLE_FORMATS
    for special in ("callback", "counter_narrative", "video_reaction", "evergreen"):
        assert special not in CHOOSABLE_FORMATS


# ------------------------------------------------------------ video reaction
def test_video_id_from_url_variants():
    assert youtube.video_id_from_url(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube.video_id_from_url("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube.video_id_from_url(
        "https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert youtube.video_id_from_url("https://example.com/notavideo") is None


def test_watcher_stores_transcript_for_new_videos(temp_db, monkeypatch):
    fetched = []

    def fake_transcript(url):
        fetched.append(url)
        return "the minister claimed inflation is done"

    w = youtube.YouTubeWatcher(db_path=temp_db, transcript_fetcher=fake_transcript)
    art = {"source": "youtube", "source_name": "ch", "url": "https://youtu.be/dQw4w9WgXcQ",
           "title": "Big claim video", "published_at": memory._now()}
    monkeypatch.setattr(w, "fetch", lambda: [art])
    tally = w.run()
    assert tally["new"] == 1 and tally["transcribed"] == 1
    aid = memory.insert_article(art, db_path=temp_db)[0]
    assert "inflation is done" in memory.get_article(aid, db_path=temp_db)["content"]
    # duplicate run: no second transcript fetch
    tally = w.run()
    assert tally["duplicate"] == 1 and tally["transcribed"] == 0
    assert len(fetched) == 1


def test_transcript_excerpt_rules():
    assert transcript_excerpt(None) is None
    assert transcript_excerpt({"source": "rss", "content": "text"}) is None
    assert transcript_excerpt({"source": "youtube", "content": ""}) is None
    block = transcript_excerpt({"source": "youtube", "content": "word " * 600},
                               max_chars=100)
    assert block.startswith("Transcript of the video")
    assert "…" in block and len(block) < 200


# ---------------------------------------------------------------- evergreen
DRAFT = json.dumps({"text": "My standing take on fiscal policy: show me the line item.",
                    "hashtags": [], "emotion": "validation", "note": ""})
SCORE = json.dumps({"vocabulary": 90, "sentence_rhythm": 90, "tone": 90,
                    "stance_consistency": 90, "emotional_register": 90,
                    "weakest_axis": "tone", "weakest_axis_feedback": ""})


def _voiced_account(db, with_stances=True):
    acct_id = memory.upsert_account(handle="me", topics=["markets"], db_path=db)
    memory.save_style_dna(acct_id, genome_a={"tone": "combative"}, db_path=db)
    if with_stances:
        for _ in range(3):
            memory.log_stance(acct_id, "fiscal-deficit", "thinks the math never adds up",
                              db_path=db)
        memory.log_stance(acct_id, "rbi-rate-policy", "thinks savers pay", db_path=db)
    return memory.get_account(acct_id, db_path=db)


def test_pick_topic_prefers_most_recurring_stance(temp_db):
    acct = _voiced_account(temp_db)
    picked = EvergreenGenerator(db_path=temp_db).pick_topic(acct)
    assert picked["topic"] == "fiscal-deficit"
    assert picked["stance"] == "thinks the math never adds up"


def test_pick_topic_repeat_guard_and_fallback(temp_db):
    acct = _voiced_account(temp_db, with_stances=False)
    # no stances -> falls back to account topics
    assert EvergreenGenerator(db_path=temp_db).pick_topic(acct)["topic"] == "markets"


def test_generate_for_persists_and_tags_topic(temp_db):
    acct = _voiced_account(temp_db)
    gen = EvergreenGenerator(client=SeqStub(DRAFT, SCORE), db_path=temp_db)
    draft = gen.generate_for(acct)
    assert draft["format"] == "evergreen" and draft.get("post_id")
    saved = memory.get_post(draft["post_id"], db_path=temp_db)
    assert saved["meta_json"]["evergreen_topic"] == "fiscal-deficit"
    # the stance reached the prompt; the format forbids news pegs
    prompt = gen._client.calls[0]["messages"][0]["content"]
    assert "math never adds up" in prompt and "No news peg" in prompt
    # repeat guard: next auto-pick moves to the second topic
    assert EvergreenGenerator(db_path=temp_db).pick_topic(acct)["topic"] == "rbi-rate-policy"


def test_generate_for_explicit_topic_and_no_dna(temp_db):
    acct = _voiced_account(temp_db)
    gen = EvergreenGenerator(client=SeqStub(DRAFT, SCORE), db_path=temp_db)
    draft = gen.generate_for(acct, topic="union budget")
    assert memory.get_post(draft["post_id"],
                           db_path=temp_db)["meta_json"]["evergreen_topic"] == "union-budget"
    bare = memory.upsert_account(handle="bare", db_path=temp_db)
    assert EvergreenGenerator(db_path=temp_db).generate_for(
        memory.get_account(bare, db_path=temp_db)) is None


def test_evergreen_telegram_command(temp_db, monkeypatch):
    for mod in (telegram_bot, poster):
        patch_settings(monkeypatch, mod, telegram_bot_token="tok",
                       telegram_chat_id="111", telegram_channel_id="", ai_label="",
                       cards_enabled=False)
    acct_id = memory.upsert_account(handle="me", db_path=temp_db)
    pid = memory.save_post(acct_id, "evergreen", "standing take", db_path=temp_db)

    from pipeline import evergreen as evergreen_mod
    seen = {}

    def fake_generate(self, account, topic=None):
        seen["handle"], seen["topic"] = account["handle"], topic
        return {"post_id": pid, "empty": False, "format": "evergreen"}

    monkeypatch.setattr(evergreen_mod.EvergreenGenerator, "generate_for", fake_generate)
    c = telegram_bot.TelegramCommander(transport=lambda m, p: {"ok": True, "result": []},
                                       db_path=temp_db)
    reply = c.handle("/evergreen fiscal policy")
    assert "🌲 evergreen drafted" in reply and "standing take" in reply
    assert seen == {"handle": "me", "topic": "fiscal policy"}
    assert "/evergreen" in c.handle("/help")
