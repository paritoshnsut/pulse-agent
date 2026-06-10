"""Approve/reject learning loop tests — deterministic half asserted exactly."""

import json

from conftest import StubClient
from pipeline import memory
from style import learning


def _post(status, fmt="hot_take", content="some draft text here", score=80.0,
          vertical=None):
    return {"status": status, "format": fmt, "content": content,
            "persona_score": score, "vertical": vertical}


def _seed_reviewed(db, n_approved, n_rejected, vertical="politics"):
    """Insert an account plus actioned drafts (optionally tied to an article
    so the vertical join has something to find). Returns account_id."""
    acct_id = memory.upsert_account(handle="me", db_path=db)
    art_id, _ = memory.insert_article(
        {"source": "rss", "url": "https://x.test/a", "title": "t",
         "vertical": vertical}, db_path=db)
    for i in range(n_approved):
        pid = memory.save_post(acct_id, "hot_take", f"approved draft {i} with a number: 7.2%",
                               persona_score=85, article_id=art_id, db_path=db)
        memory.set_post_status(pid, "approved", db_path=db)
    for i in range(n_rejected):
        pid = memory.save_post(acct_id, "thread", f"rejected vague draft {i}",
                               persona_score=72, article_id=art_id, db_path=db)
        memory.set_post_status(pid, "rejected", db_path=db)
    return acct_id


# ----------------------------------------------------------------- correlate
def test_correlate_counts_and_rates():
    reviewed = [_post("approved"), _post("edited"), _post("posted"),
                _post("rejected", fmt="thread")]
    stats = learning.correlate(reviewed)
    assert stats["total_reviewed"] == 4
    assert stats["approved"] == 3 and stats["rejected"] == 1
    assert stats["approval_rate"] == 0.75
    assert stats["by_format"]["hot_take"]["rate"] == 1.0
    assert stats["by_format"]["thread"]["rate"] == 0.0


def test_correlate_empty_is_safe():
    stats = learning.correlate([])
    assert stats["approval_rate"] is None
    assert stats["persona_score_approved"] is None


def test_correlate_measures_piles_separately():
    reviewed = [_post("approved", content="short?", score=90),
                _post("rejected", content="a much longer rejected draft body", score=60)]
    stats = learning.correlate(reviewed)
    assert stats["persona_score_approved"] == 90.0
    assert stats["persona_score_rejected"] == 60.0
    assert stats["avg_len_approved"] < stats["avg_len_rejected"]
    assert stats["question_rate_approved"] == 1.0


# ----------------------------------------------------- historical_performance
def test_historical_perf_neutral_with_no_reviews(temp_db):
    acct_id = memory.upsert_account(handle="me", db_path=temp_db)
    hp = learning.historical_performance(acct_id, db_path=temp_db)
    assert hp["overall"] == 5.0 and hp["by_vertical"] == {}


def test_historical_perf_shrinks_toward_neutral(temp_db):
    # 1 approval, 0 rejections: rate=10/10 but prior=10 keeps it near 5.
    acct_id = _seed_reviewed(temp_db, n_approved=1, n_rejected=0)
    hp = learning.historical_performance(acct_id, db_path=temp_db)
    assert 5.0 < hp["overall"] < 6.0   # (1*10 + 10*5)/11 ≈ 5.45
    assert hp["by_vertical"]["politics"] == hp["overall"]


def test_historical_perf_moves_with_evidence(temp_db):
    acct_id = _seed_reviewed(temp_db, n_approved=20, n_rejected=0)
    hp = learning.historical_performance(acct_id, db_path=temp_db)
    assert hp["overall"] > 8.0          # (20*10 + 50)/30 ≈ 8.33


def test_decision_agent_uses_hist_perf():
    from pipeline.decision import DecisionAgent

    agent = DecisionAgent(client=StubClient(json.dumps(
        {"relevance": 5, "reaction_potential": 5, "angle": "", "reasoning": ""})))
    art = {"id": 1, "title": "t", "vertical": "politics"}
    base = agent.score_article(art, {"id": 1}, hist_perf=None)
    assert base["historical_perf"] == 5.0
    boosted = agent.score_article(
        art, {"id": 1}, hist_perf={"overall": 6.0, "by_vertical": {"politics": 8.0}})
    assert boosted["historical_perf"] == 8.0      # vertical match preferred
    fallback = agent.score_article(
        art, {"id": 1}, hist_perf={"overall": 6.0, "by_vertical": {"finance": 8.0}})
    assert fallback["historical_perf"] == 6.0     # falls back to overall


# ------------------------------------------------- engagement -> historical_perf
def test_engagement_scores_relative_to_own_median(temp_db):
    acct_id = _seed_reviewed(temp_db, n_approved=3, n_rejected=0)
    posts = memory.get_posts(account_id=acct_id, db_path=temp_db)
    # median engagement value -> 5.0; double the median -> 10 (capped)
    memory.record_engagement(posts[0]["id"], likes=100, db_path=temp_db)
    memory.record_engagement(posts[1]["id"], likes=200, db_path=temp_db)
    memory.record_engagement(posts[2]["id"], likes=400, db_path=temp_db)
    scores = learning.engagement_scores(acct_id, db_path=temp_db)
    assert sorted(scores["overall"]) == [2.5, 5.0, 10.0]
    assert set(scores["by_vertical"]) == {"politics"}


def test_engagement_latest_snapshot_wins(temp_db):
    acct_id = _seed_reviewed(temp_db, n_approved=1, n_rejected=0)
    pid = memory.get_posts(account_id=acct_id, db_path=temp_db)[0]["id"]
    memory.record_engagement(pid, likes=5, db_path=temp_db)
    memory.record_engagement(pid, likes=500, db_path=temp_db)  # updated later
    rows = memory.get_post_engagement(acct_id, db_path=temp_db)
    assert len(rows) == 1 and rows[0]["likes"] == 500


def test_historical_perf_blends_engagement(temp_db):
    acct_id = _seed_reviewed(temp_db, n_approved=5, n_rejected=0)
    # reviews only: (5*10 + 10*5) / (5+10) = 6.67
    before = learning.historical_performance(acct_id, db_path=temp_db)["overall"]
    assert before == 6.67
    posts = memory.get_posts(account_id=acct_id, db_path=temp_db)[:2]
    memory.record_engagement(posts[0]["id"], likes=100, db_path=temp_db)
    memory.record_engagement(posts[1]["id"], likes=300, db_path=temp_db)
    # engagement scores vs median 200: 5*100/200=2.5 and 5*300/200=7.5;
    # blended: (5*10 + (2.5+7.5) + 10*5) / (5+2+10) = 110/17 = 6.47
    after = learning.historical_performance(acct_id, db_path=temp_db)["overall"]
    assert after == 6.47
    assert after < before  # mediocre engagement tempers the approve-only optimism


def test_retweets_and_replies_weighted_heavier():
    assert learning._engagement_value({"likes": 10, "retweets": 10, "replies": 10}) == 45.0


# -------------------------------------------------------------- apply_learning
JUDGED = {"avoid": ["vague outrage with no specific number"],
          "emphasize": ["lead with the surprising stat"],
          "summary": "specific numbers win"}


def test_apply_learning_skips_below_minimum(temp_db):
    acct_id = _seed_reviewed(temp_db, n_approved=2, n_rejected=1)
    memory.save_style_dna(acct_id, genome_a={"things_to_avoid": []}, db_path=temp_db)
    report = learning.ReviewLearner(client=StubClient("{}")).apply_learning(
        acct_id, db_path=temp_db)
    assert report["updated"] is False
    assert "need" in report["reason"]


def test_apply_learning_skips_without_dna(temp_db):
    acct_id = _seed_reviewed(temp_db, n_approved=6, n_rejected=6)
    report = learning.ReviewLearner(client=StubClient("{}")).apply_learning(
        acct_id, db_path=temp_db)
    assert report["updated"] is False and report["reason"] == "no style DNA yet"


def test_apply_learning_updates_genome_and_is_idempotent(temp_db):
    acct_id = _seed_reviewed(temp_db, n_approved=6, n_rejected=6)
    memory.save_style_dna(acct_id, genome_a={"things_to_avoid": ["formal language"]},
                          genome_b={"hook_patterns": ["x"]}, blend=0.3, db_path=temp_db)
    learner = learning.ReviewLearner(client=StubClient(json.dumps(JUDGED)))

    report = learner.apply_learning(acct_id, db_path=temp_db)
    assert report["updated"] is True
    assert report["avoid_added"] == JUDGED["avoid"]

    saved = memory.get_style_dna(acct_id, db_path=temp_db)
    assert saved["version"] == 2
    assert saved["genome_a"]["things_to_avoid"] == ["formal language"] + JUDGED["avoid"]
    lp = saved["genome_a"]["learned_preferences"]
    assert lp["emphasize"] == JUDGED["emphasize"]
    assert lp["format_approval_rates"]["hot_take"] == 1.0
    assert lp["format_approval_rates"]["thread"] == 0.0
    assert lp["preferred_formats"][0] == "hot_take"
    assert saved["genome_b"] == {"hook_patterns": ["x"]}   # carried forward
    assert saved["blend"] == 0.3

    # second pass with no new reviews: no-op, no version churn
    report2 = learner.apply_learning(acct_id, db_path=temp_db)
    assert report2["updated"] is False
    assert "no new reviews" in report2["reason"]
    assert memory.get_style_dna(acct_id, db_path=temp_db)["version"] == 2


def test_apply_learning_stats_only_when_one_sided(temp_db):
    # 12 approvals, 0 rejections: enough volume, but no contrast — Claude must
    # NOT be called; format stats still recorded.
    acct_id = _seed_reviewed(temp_db, n_approved=12, n_rejected=0)
    memory.save_style_dna(acct_id, genome_a={"things_to_avoid": []}, db_path=temp_db)
    stub = StubClient(json.dumps(JUDGED))
    report = learning.ReviewLearner(client=stub).apply_learning(acct_id, db_path=temp_db)
    assert report["updated"] is True
    assert stub.messages.calls == []                       # no model call
    saved = memory.get_style_dna(acct_id, db_path=temp_db)
    assert saved["genome_a"]["things_to_avoid"] == []
    assert saved["genome_a"]["learned_preferences"]["format_approval_rates"]["hot_take"] == 1.0


def test_merge_avoids_dedupes_and_caps():
    merged, kept = learning.ReviewLearner._merge_avoids(
        ["Formal Language"], ["formal language", "hedging", ""])
    assert merged == ["Formal Language", "hedging"]
    assert kept == ["hedging"]
    many = [f"rule {i}" for i in range(20)]
    merged, kept = learning.ReviewLearner._merge_avoids([], many)
    assert len(kept) == learning.MAX_LEARNED_AVOIDS
