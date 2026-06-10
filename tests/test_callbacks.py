"""Callback generator tests — sequenced stub client, temp DB, no network."""

import json

from conftest import _Msg
from pipeline import callbacks, memory
from pipeline.callbacks import CallbackWatcher, rank_candidates


class SeqStubClient:
    """Like StubClient but returns payloads in sequence — one resolution flows
    through three different calls (verify -> generator -> persona scorer)."""

    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Msg(self.payloads.pop(0) if self.payloads else "{}")


VERIFY_CONFIRMED = json.dumps({"resolution": "confirmed", "article_index": 1,
                               "outcome": "RBI cut the repo rate by 25bps"})
VERIFY_UNRESOLVED = json.dumps({"resolution": "unresolved", "article_index": None,
                                "outcome": ""})
DRAFT = json.dumps({"text": "Called it. RBI cut today.", "hashtags": [], "note": ""})
SCORE = json.dumps({"vocabulary": 90, "sentence_rhythm": 90, "tone": 90,
                    "stance_consistency": 90, "emotional_register": 90,
                    "weakest_axis": "tone", "weakest_axis_feedback": ""})


def _seed(db, made_at="2026-06-01T00:00:00+00:00", with_dna=True):
    acct_id = memory.upsert_account(handle="me", topics=["rbi"], db_path=db)
    if with_dna:
        memory.save_style_dna(acct_id, genome_a={"tone": "combative"}, db_path=db)
    pred_id = memory.insert_prediction(
        acct_id, "RBI will cut the repo rate by March 2027",
        topic="rbi-rate-policy", db_path=db)
    # backdate made_at so the fetched_after cursor lets candidates through
    with memory.get_conn(db) as conn:
        conn.execute("UPDATE predictions_tracker SET made_at = ? WHERE id = ?",
                     (made_at, pred_id))
    return acct_id, pred_id


def _add_article(db, title, description="", url=None):
    art_id, _ = memory.insert_article({
        "source": "rss", "url": url or f"https://t/{title[:20].replace(' ', '-')}",
        "title": title, "description": description,
        "published_at": memory._now()}, db_path=db)
    return art_id


# ---------------------------------------------------------------- prefilter
def test_rank_candidates_requires_min_hits_and_ranks():
    kws = ["rbi", "repo", "rate", "cut"]
    arts = [
        {"title": "RBI cuts repo rate in surprise move", "description": ""},   # 4 hits
        {"title": "RBI press conference scheduled", "description": ""},        # 1 hit
        {"title": "Rate cut speculation grows at RBI", "description": ""},     # 3 hits
    ]
    out = rank_candidates(arts, kws, min_hits=2, cap=3)
    assert [a["title"][:7] for a in out] == ["RBI cut", "Rate cu"]


def test_rank_candidates_caps_and_handles_short_keyword_lists():
    arts = [{"title": f"rbi story {i}", "description": ""} for i in range(5)]
    assert len(rank_candidates(arts, ["rbi"], min_hits=2, cap=2)) == 2  # min_hits clamped to len(kws)


# --------------------------------------------------------------------- verify
def test_verify_strict_fallbacks():
    pred = {"prediction": "p", "made_at": "2026-06-01T00:00:00+00:00"}
    cands = [{"title": "t", "description": "", "source_name": "s", "published_at": ""}]
    w = CallbackWatcher(client=SeqStubClient("garbage"))
    assert w.verify(pred, cands)["resolution"] == "unresolved"
    # out-of-range index is rejected even if resolution says confirmed
    bad = json.dumps({"resolution": "confirmed", "article_index": 9, "outcome": "x"})
    assert CallbackWatcher(client=SeqStubClient(bad)).verify(pred, cands)["resolution"] == "unresolved"


# ----------------------------------------------------------------- lifecycle
def test_confirmed_prediction_resolves_and_drafts(temp_db):
    acct_id, pred_id = _seed(temp_db)
    _add_article(temp_db, "RBI cuts repo rate by 25bps",
                 "Central bank moves earlier than expected")
    w = CallbackWatcher(client=SeqStubClient(VERIFY_CONFIRMED, DRAFT, SCORE),
                        db_path=temp_db)
    tally = w.run()
    assert tally == {"checked": 1, "no_candidates": 0, "unresolved": 0,
                     "confirmed": 1, "refuted": 0, "expired": 0}
    # prediction closed with the outcome
    assert memory.get_open_predictions(acct_id, db_path=temp_db) == []
    with memory.get_conn(temp_db) as conn:
        row = dict(conn.execute("SELECT * FROM predictions_tracker WHERE id = ?",
                                (pred_id,)).fetchone())
    assert row["status"] == "confirmed"
    assert "25bps" in row["outcome"]
    # callback draft persisted and in the normal review lane
    drafts = memory.get_posts(account_id=acct_id, status="draft", db_path=temp_db)
    assert len(drafts) == 1
    assert drafts[0]["format"] == "callback"
    assert drafts[0]["content"] == "Called it. RBI cut today."


def test_refuted_prediction_also_drafts(temp_db):
    acct_id, pred_id = _seed(temp_db)
    _add_article(temp_db, "RBI hikes repo rate, defying cut expectations")
    refuted = json.dumps({"resolution": "refuted", "article_index": 1,
                          "outcome": "RBI hiked instead of cutting"})
    w = CallbackWatcher(client=SeqStubClient(refuted, DRAFT, SCORE), db_path=temp_db)
    assert w.run()["refuted"] == 1
    drafts = memory.get_posts(account_id=acct_id, status="draft", db_path=temp_db)
    assert len(drafts) == 1 and drafts[0]["format"] == "callback"


def test_unresolved_keeps_prediction_open_and_advances_cursor(temp_db):
    acct_id, pred_id = _seed(temp_db)
    _add_article(temp_db, "RBI repo rate decision due next week")
    stub = SeqStubClient(VERIFY_UNRESOLVED)
    w = CallbackWatcher(client=stub, db_path=temp_db)
    assert w.run()["unresolved"] == 1
    assert len(memory.get_open_predictions(acct_id, db_path=temp_db)) == 1
    assert len(stub.calls) == 1  # verify only — no draft spend
    # cursor advanced: same article is never re-judged
    assert w.run()["no_candidates"] == 1
    assert len(stub.calls) == 1


def test_no_candidates_means_zero_model_calls(temp_db):
    _seed(temp_db)
    _add_article(temp_db, "Completely unrelated cricket final tonight")
    stub = SeqStubClient()
    assert CallbackWatcher(client=stub, db_path=temp_db).run()["no_candidates"] == 1
    assert stub.calls == []


def test_old_prediction_expires_without_model_calls(temp_db):
    acct_id, pred_id = _seed(temp_db, made_at="2025-01-01T00:00:00+00:00")
    stub = SeqStubClient()
    assert CallbackWatcher(client=stub, db_path=temp_db).run()["expired"] == 1
    assert stub.calls == []
    with memory.get_conn(temp_db) as conn:
        row = dict(conn.execute("SELECT * FROM predictions_tracker WHERE id = ?",
                                (pred_id,)).fetchone())
    assert row["status"] == "expired" and "expired unresolved" in row["outcome"]


def test_resolves_but_skips_draft_without_dna(temp_db):
    acct_id, pred_id = _seed(temp_db, with_dna=False)
    _add_article(temp_db, "RBI cuts repo rate by 25bps")
    w = CallbackWatcher(client=SeqStubClient(VERIFY_CONFIRMED), db_path=temp_db)
    assert w.run()["confirmed"] == 1
    assert memory.get_open_predictions(acct_id, db_path=temp_db) == []
    assert memory.get_posts(account_id=acct_id, db_path=temp_db) == []


def test_callback_prompt_carries_prediction_and_outcome(temp_db):
    _seed(temp_db)
    _add_article(temp_db, "RBI cuts repo rate by 25bps")
    stub = SeqStubClient(VERIFY_CONFIRMED, DRAFT, SCORE)
    CallbackWatcher(client=stub, db_path=temp_db).run()
    gen_prompt = stub.calls[1]["messages"][0]["content"]
    assert "RBI will cut the repo rate by March 2027" in gen_prompt  # the claim, verbatim
    assert "CONFIRMED" in gen_prompt
    assert "YOUR MEMORY" in gen_prompt  # outcome travels via the memory block
    assert "callback post" in gen_prompt  # the format instruction
