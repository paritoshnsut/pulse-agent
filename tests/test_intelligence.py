"""Tests for the intelligence layer: fatigue, timing, briefing, counter-
narrative, emotion calibration, hook variants. No keys, no network."""

import json
from datetime import datetime, timedelta, timezone

from conftest import StubClient, patch_settings
from pipeline import briefing, counter, fatigue, memory, poster, timing
from style import learning


def _iso(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def _account(db, handle="me"):
    return memory.upsert_account(handle=handle, db_path=db)


def _signal(db, acct_id, title="RBI holds rates", topic="rbi-rate-policy",
            tier="FIRE", url=None):
    art_id, _ = memory.insert_article(
        {"source": "rss", "url": url or f"https://t/{title.replace(' ', '-')}",
         "title": title, "published_at": memory._now()}, db_path=db)
    sig_id = memory.insert_signal(
        {"article_id": art_id, "account_id": acct_id, "score": 9.0,
         "tier": tier, "topic": topic, "angle": "the angle"}, db_path=db)
    return sig_id, art_id


def _posted_with_perf(db, acct_id, sig_id, art_id, posted_at, likes,
                      emotion=None, status="posted"):
    pid = memory.save_post(acct_id, "hot_take", "content here", signal_id=sig_id,
                           article_id=art_id,
                           meta={"emotion": emotion} if emotion else None,
                           db_path=db)
    memory.set_post_status(pid, status, db_path=db)
    if status == "posted":
        with memory.get_conn(db) as conn:
            conn.execute("UPDATE posts SET posted_at = ? WHERE id = ?", (posted_at, pid))
        memory.record_engagement(pid, likes=likes, db_path=db)
    return pid


# ------------------------------------------------------------------ fatigue
def test_fatigue_counts_only_audience_facing(temp_db):
    acct = _account(temp_db)
    for i in range(4):
        sig, art = _signal(temp_db, acct, title=f"RBI story {i}", url=f"https://t/f{i}")
        pid = memory.save_post(acct, "hot_take", "x", signal_id=sig, db_path=temp_db)
        # 2 approved, 1 posted, 1 rejected -> 3 audience-facing
        memory.set_post_status(pid, ["approved", "approved", "posted", "rejected"][i],
                               db_path=temp_db)
    fresh = fatigue.topic_freshness(acct, "rbi-rate-policy", db_path=temp_db)
    assert fresh["recent_posts"] == 3
    assert fresh["fatigued"] is True  # default max is 3
    assert fatigue.is_fatigued(acct, "different-topic", db_path=temp_db) is False
    assert fatigue.is_fatigued(acct, None, db_path=temp_db) is False  # no slug, no verdict


# ------------------------------------------------------------------- timing
def test_timing_defaults_until_enough_samples(temp_db):
    acct = _account(temp_db)
    res = timing.best_windows(acct, db_path=temp_db)
    assert res["learned"] is False
    assert res["windows"] == list(timing.DEFAULT_WINDOWS)
    assert "defaults" in timing.describe_windows(acct, db_path=temp_db)


def test_timing_learns_best_hours(temp_db, monkeypatch):
    patch_settings(monkeypatch, timing, timing_min_samples=8, tz_offset_min=0)
    acct = _account(temp_db)
    # 8 posts: hours 20-21 UTC get big engagement, hour 3 gets nothing
    for i in range(4):
        sig, art = _signal(temp_db, acct, title=f"s{i}", url=f"https://t/t{i}")
        _posted_with_perf(temp_db, acct, sig, art,
                          f"2026-06-0{i+1}T20:30:00+00:00", likes=500)
    for i in range(2):
        sig, art = _signal(temp_db, acct, title=f"u{i}", url=f"https://t/u{i}")
        _posted_with_perf(temp_db, acct, sig, art,
                          f"2026-06-0{i+1}T21:10:00+00:00", likes=400)
    for i in range(2):
        sig, art = _signal(temp_db, acct, title=f"v{i}", url=f"https://t/v{i}")
        _posted_with_perf(temp_db, acct, sig, art,
                          f"2026-06-0{i+1}T03:00:00+00:00", likes=2)
    res = timing.best_windows(acct, db_path=temp_db)
    assert res["learned"] is True and res["samples"] == 8
    assert (20, 22) in res["windows"]  # adjacent top hours merged


def test_merge_adjacent_hours():
    assert timing._merge_adjacent([20, 21, 8]) == [(8, 9), (20, 22)]
    assert timing._merge_adjacent([]) == []


def test_approved_package_includes_timing_line(temp_db, monkeypatch):
    patch_settings(monkeypatch, poster, ai_label="", cards_enabled=False)
    acct = _account(temp_db)
    pid = memory.save_post(acct, "hot_take", "text", db_path=temp_db)
    msg = poster.format_approved_package(memory.get_post(pid, db_path=temp_db),
                                         db_path=temp_db)
    assert "best posting windows" in msg


# ----------------------------------------------------------------- briefing
def test_briefing_includes_all_sections(temp_db):
    acct_id = _account(temp_db)
    account = memory.get_account(acct_id, db_path=temp_db)
    # a COOL idea from today, undrafted
    _signal(temp_db, acct_id, title="Mid-tier policy story", tier="COOL",
            url="https://t/cool")
    # an approved-but-unposted draft
    pid = memory.save_post(acct_id, "hot_take", "x", db_path=temp_db)
    memory.set_post_status(pid, "approved", db_path=temp_db)
    memory.insert_prediction(acct_id, "X will happen by Q3", db_path=temp_db)
    text = briefing.build(account, db_path=temp_db)
    assert "Ideas bank" in text and "Mid-tier policy story" in text
    assert "Outbox: 1" in text
    assert "1 open prediction" in text
    assert "Last 24h" in text and "best posting windows" in text


def test_briefing_ideas_exclude_drafted_and_old(temp_db):
    acct_id = _account(temp_db)
    sig, _ = _signal(temp_db, acct_id, title="Drafted idea", tier="COOL",
                     url="https://t/c1")
    memory.save_post(acct_id, "hot_take", "x", signal_id=sig, db_path=temp_db)
    old_sig, _ = _signal(temp_db, acct_id, title="Old idea", tier="COOL",
                         url="https://t/c2")
    with memory.get_conn(temp_db) as conn:
        conn.execute("UPDATE signals SET created_at = ? WHERE id = ?",
                     (_iso(hours=30), old_sig))
    assert briefing._cool_ideas(acct_id, db_path=temp_db) == []


# ---------------------------------------------------------- counter-narrative
COVERAGE_TITLES = ["RBI rates take one", "RBI rates take two", "RBI rates take three"]

GAP = json.dumps({"consensus": "everyone says inflation is beaten",
                  "missing_angle": "nobody asks who pays for the pause",
                  "worth": True})
DRAFT = json.dumps({"text": "The take nobody wants: someone pays for this pause.",
                    "hashtags": [], "emotion": "outrage", "note": ""})
SCORE = json.dumps({"vocabulary": 90, "sentence_rhythm": 90, "tone": 90,
                    "stance_consistency": 90, "emotional_register": 90,
                    "weakest_axis": "tone", "weakest_axis_feedback": ""})


class SeqStub:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        from conftest import _Msg
        self.calls.append(kwargs)
        return _Msg(self.payloads.pop(0) if self.payloads else "{}")


def _counter_setup(db, with_coverage=True):
    acct_id = _account(db)
    memory.save_style_dna(acct_id, genome_a={"tone": "combative"}, db_path=db)
    sig, art = _signal(db, acct_id, title="RBI rates decision shocks markets")
    if with_coverage:
        for i, t in enumerate(COVERAGE_TITLES):
            memory.insert_article({"source": "rss", "url": f"https://t/cov{i}",
                                   "title": t, "published_at": memory._now()},
                                  db_path=db)
    return acct_id, sig


def test_counter_drafts_when_gap_found(temp_db):
    acct_id, sig = _counter_setup(temp_db)
    det = counter.CounterNarrativeDetector(client=SeqStub(GAP, DRAFT, SCORE),
                                           db_path=temp_db)
    tally = det.run()
    assert tally == {"targets": 1, "no_gap": 0, "drafted": 1}
    drafts = memory.get_posts(account_id=acct_id, status="draft", db_path=temp_db)
    assert len(drafts) == 1 and drafts[0]["format"] == "counter_narrative"
    # the consensus + missing angle reached the generation prompt
    gen_prompt = det._client.calls[1]["messages"][0]["content"]
    assert "nobody asks who pays" in gen_prompt
    assert "everyone says inflation is beaten" in gen_prompt
    # second run: signal already countered -> no targets, no spend
    assert det.run()["targets"] == 0


def test_counter_no_gap_marks_seen_and_never_respends(temp_db):
    _counter_setup(temp_db)
    no_gap = json.dumps({"consensus": "c", "missing_angle": "", "worth": False})
    stub = SeqStub(no_gap)
    det = counter.CounterNarrativeDetector(client=stub, db_path=temp_db)
    assert det.run()["no_gap"] == 1
    assert det.run()["targets"] == 0  # kv 'seen' marker holds
    assert len(stub.calls) == 1


def test_counter_skips_thin_coverage(temp_db):
    _counter_setup(temp_db, with_coverage=False)
    stub = SeqStub()
    assert counter.CounterNarrativeDetector(client=stub, db_path=temp_db).run()["targets"] == 0
    assert stub.calls == []


def test_counter_narrative_not_choosable_by_decision():
    from pipeline.generator import CHOOSABLE_FORMATS, FORMATS
    assert "counter_narrative" in FORMATS
    assert "counter_narrative" not in CHOOSABLE_FORMATS


# ----------------------------------------------------------------- emotion
def test_generator_captures_emotion():
    from pipeline.generator import ContentGenerator
    stub = StubClient(json.dumps({"text": "post", "hashtags": [],
                                  "emotion": "Outrage", "note": ""}))
    draft = ContentGenerator(client=stub).generate({"title": "t"}, {}, "hot_take")
    assert draft["emotion"] == "outrage"
    assert "emotion" in stub.messages.calls[0]["messages"][0]["content"]


def test_learning_correlates_and_prefers_emotions(temp_db):
    acct_id = _account(temp_db)
    memory.save_style_dna(acct_id, genome_a={"things_to_avoid": []}, db_path=temp_db)
    for i in range(6):  # outrage always approved
        pid = memory.save_post(acct_id, "hot_take", f"o{i}",
                               meta={"emotion": "outrage"}, db_path=temp_db)
        memory.set_post_status(pid, "approved", db_path=temp_db)
    for i in range(6):  # humour always rejected
        pid = memory.save_post(acct_id, "hot_take", f"h{i}",
                               meta={"emotion": "humour"}, db_path=temp_db)
        memory.set_post_status(pid, "rejected", db_path=temp_db)
    judged = json.dumps({"avoid": [], "emphasize": [], "summary": ""})
    report = learning.ReviewLearner(client=StubClient(judged)).apply_learning(
        acct_id, db_path=temp_db)
    assert report["updated"] is True
    lp = memory.get_style_dna(acct_id, db_path=temp_db)["genome_a"]["learned_preferences"]
    assert lp["emotion_approval_rates"] == {"outrage": 1.0, "humour": 0.0}
    assert lp["preferred_emotions"][0] == "outrage"
    # and the generator surfaces it
    from pipeline.generator import _style_rules
    rules = _style_rules({"learned_preferences": lp})
    assert "outrage" in rules and "Emotional registers that land" in rules


# -------------------------------------------------------------- hook variants
def test_alt_hooks_generated_and_styled():
    from pipeline.generator import ContentGenerator
    stub = StubClient(json.dumps({"hooks": ["Hook one 🔥", "Hook two?"]}))
    genome = {"emoji_usage": "none"}
    hooks = ContentGenerator(client=stub).alt_hooks("draft text", {"title": "t"}, genome)
    assert hooks == ["Hook one", "Hook two?"]  # emoji stripped per voice


def test_alt_hooks_failure_is_empty():
    from pipeline.generator import ContentGenerator
    assert ContentGenerator(client=StubClient("garbage")).alt_hooks(
        "d", {"title": "t"}, {}) == []


def test_draft_alert_shows_alt_hooks(temp_db):
    acct = _account(temp_db)
    pid = memory.save_post(acct, "hot_take", "body", db_path=temp_db)
    memory.update_post_meta(pid, {"alt_hooks": ["Try this opener"]}, db_path=temp_db)
    msg = poster.format_draft_alert(memory.get_post(pid, db_path=temp_db))
    assert "alt hooks" in msg and "1. Try this opener" in msg
