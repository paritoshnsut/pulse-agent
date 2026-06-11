"""Tests for the integrity layer: stance arc guard, backlash risk simulator,
and richer feedback (redo-with-steer + reject reasons feeding the learner)."""

import json

from conftest import StubClient, _Msg
from pipeline import feedback, memory
from pipeline.integrity import StanceArcGuard, RiskSimulator


class SeqStub:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Msg(self.payloads.pop(0) if self.payloads else "{}")


# ------------------------------------------------------------------ arc guard
def test_arc_guard_no_past_stances_is_free(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    stub = SeqStub()
    out = StanceArcGuard(client=stub).check("RBI should cut rates now", acct,
                                            "rbi-rate-policy", "RBI holds",
                                            db_path=temp_db)
    assert out == {"checked": False, "conflicts": []}
    assert stub.calls == []  # cold start: no spend


def test_arc_guard_flags_reversal(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    memory.log_stance(acct, "rbi-rate-policy",
                      "thinks rate CUTS are reckless with inflation this high",
                      db_path=temp_db)
    payload = json.dumps({"conflicts": [
        {"past": "rate cuts are reckless", "now": "RBI should cut now"}]})
    out = StanceArcGuard(client=SeqStub(payload)).check(
        "Honestly RBI should just cut rates already", acct, "rbi-rate-policy",
        "RBI decision", db_path=temp_db)
    assert out["checked"] is True
    assert out["conflicts"][0]["now"] == "RBI should cut now"


def test_arc_guard_consistent_draft_clean(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    memory.log_stance(acct, "rbi-rate-policy", "rate cuts are reckless now",
                      db_path=temp_db)
    out = StanceArcGuard(client=SeqStub(json.dumps({"conflicts": []}))).check(
        "Another reckless rate cut would be a mistake", acct, "rbi-rate-policy",
        db_path=temp_db)
    assert out["checked"] is True and out["conflicts"] == []


def test_arc_guard_fails_safe(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    memory.log_stance(acct, "rbi-rate-policy", "cuts are reckless", db_path=temp_db)
    out = StanceArcGuard(client=SeqStub("garbage")).check(
        "cut rates", acct, "rbi-rate-policy", db_path=temp_db)
    assert out == {"checked": False, "conflicts": []}


# -------------------------------------------------------------------- risk
def test_risk_levels_and_vectors():
    payload = json.dumps({"risk_level": "high",
                          "vectors": ["screenshot without the data", "looks partisan"]})
    out = RiskSimulator(client=SeqStub(payload)).assess("Spicy attack post")
    assert out["risk_level"] == "high" and len(out["vectors"]) == 2

    clean = RiskSimulator(client=SeqStub(json.dumps({"risk_level": "low", "vectors": []})))
    assert clean.assess("Mild take")["risk_level"] == "low"

    bad = RiskSimulator(client=SeqStub(json.dumps({"risk_level": "nuclear"})))
    assert bad.assess("x")["risk_level"] == "low"  # invalid -> low

    assert RiskSimulator(client=SeqStub("garbage")).assess("x")["checked"] is False


# ----------------------------------------------- wiring into generate_checked
def test_generate_checked_arc_and_risk_force_review(temp_db):
    from pipeline.generator import ContentGenerator

    acct = memory.upsert_account(handle="me", db_path=temp_db)
    memory.log_stance(acct, "gdp", "growth is overstated", db_path=temp_db)

    draft = json.dumps({"text": "Actually growth is real and strong",
                        "hashtags": [], "emotion": "pride", "note": ""})
    arc = json.dumps({"conflicts": [{"past": "growth overstated", "now": "growth is strong"}]})
    risk = json.dumps({"risk_level": "high", "vectors": ["flip-flop screenshot"]})
    stub = SeqStub(draft, arc, risk)
    best = ContentGenerator(client=stub).generate_checked(
        {"title": "GDP up", "topic": "gdp"}, {}, "hot_take", scorer=None,
        arc_guard=StanceArcGuard(client=stub), risk=RiskSimulator(client=stub),
        account_id=acct, persist=True, db_path=temp_db)
    assert best["stance_conflicts"] and best["risk_level"] == "high"
    assert best["needs_review"] is True
    saved = memory.get_post(best["post_id"], db_path=temp_db)
    assert saved["meta_json"]["stance_conflicts"][0]["now"] == "growth is strong"
    assert saved["meta_json"]["risk_vectors"] == ["flip-flop screenshot"]
    # both warnings surface to the human
    from pipeline import poster
    alert = poster.format_draft_alert(saved)
    assert "CONTRADICTS YOUR PAST STANCE" in alert
    assert "backlash risk (high)" in alert


# -------------------------------------------------------- redo with steer
def test_regenerate_with_steer_rewrites_and_records(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    memory.save_style_dna(acct, genome_a={"tone": "combative", "emoji_usage": "none"},
                          db_path=temp_db)
    pid = memory.save_post(acct, "hot_take", "Rates held. Not ideal.",
                           meta={"ungrounded_claims": ["stale"], "emotion": "neutral"},
                           db_path=temp_db)
    rewritten = json.dumps({"text": "Rates held AGAIN. Savers robbed. Disgraceful.",
                            "hashtags": [], "emotion": "outrage"})
    import pipeline.feedback as fb
    monkey = ContentGeneratorPatch(rewritten)
    orig = fb.ContentGenerator
    fb.ContentGenerator = lambda *a, **k: monkey
    try:
        out = feedback.regenerate_with_steer(pid, "make it more savage", db_path=temp_db)
    finally:
        fb.ContentGenerator = orig
    assert out["ok"] is True and "savage" not in out["content"].lower()
    saved = memory.get_post(pid, db_path=temp_db)
    assert "Disgraceful" in saved["content"]
    assert saved["status"] == "draft" and saved["needs_review"] == 1
    assert saved["meta_json"].get("redone_with") == "make it more savage"
    assert "ungrounded_claims" not in saved["meta_json"]  # stale warning cleared
    # the steer was recorded for the learning loop
    assert "make it more savage" in memory.get_recent_feedback_notes(acct, db_path=temp_db)


def test_regenerate_guards(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    pid = memory.save_post(acct, "hot_take", "x", db_path=temp_db)
    # no voice trained
    assert feedback.regenerate_with_steer(pid, "sharper", db_path=temp_db)["ok"] is False
    # missing draft
    assert feedback.regenerate_with_steer(999, "sharper", db_path=temp_db)["ok"] is False
    # empty instruction
    memory.save_style_dna(acct, genome_a={"tone": "x"}, db_path=temp_db)
    assert feedback.regenerate_with_steer(pid, "  ", db_path=temp_db)["ok"] is False


def test_record_reject_reason(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    pid = memory.save_post(acct, "hot_take", "x", db_path=temp_db)
    feedback.record_reject(pid, "too preachy", db_path=temp_db)
    feedback.record_reject(pid, "", db_path=temp_db)  # blank ignored
    notes = memory.get_recent_feedback_notes(acct, db_path=temp_db)
    assert notes == ["too preachy"]


def test_learning_judge_includes_steers():
    from style.learning import ReviewLearner
    stub = StubClient(json.dumps({"avoid": [], "emphasize": [], "summary": ""}))
    learner = ReviewLearner(client=stub)
    learner.judge([{"format": "hot_take", "content": "a"}],
                  [{"format": "hot_take", "content": "b"}],
                  {"approval_rate": 0.5, "by_format": {},
                   "avg_len_approved": 1, "avg_len_rejected": 2,
                   "question_rate_approved": 0, "question_rate_rejected": 0},
                  steers=["more savage", "lead with the number"])
    prompt = stub.messages.calls[0]["messages"][0]["content"]
    assert "EXPLICIT STEERS" in prompt and "more savage" in prompt


class ContentGeneratorPatch:
    """Minimal stand-in for ContentGenerator.rewrite used by the redo test."""
    def __init__(self, payload):
        self._payload = json.loads(payload)

    def rewrite(self, draft_text, instruction, genome, is_thread=False):
        text = self._payload["text"]
        return {"text": text, "content": text,
                "hashtags": self._payload.get("hashtags", []),
                "emotion": self._payload.get("emotion", ""),
                "empty": not text, "char_count": len(text)}
