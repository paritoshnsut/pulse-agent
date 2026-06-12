"""Pulse Studio — the internal glass-wall API (api/studio.py). Read-only
windows over the pipeline's own tables: the funnel, the signal center, the
memory inspector, the voice studio, the learning dashboard, the generation
trace, and the content graph viewer."""

import pytest

from conftest import patch_settings
from pipeline import memory


@pytest.fixture()
def client(temp_db, monkeypatch):
    from fastapi.testclient import TestClient

    from api import main as api_main

    patch_settings(monkeypatch, api_main, app_password="",
                   supabase_url="", supabase_jwt_secret="")
    monkeypatch.setattr(api_main, "DB", temp_db)
    return TestClient(api_main.app)


def _account(client):
    return client.post("/api/accounts", json={"handle": "me"}).json()["id"]


def _article(temp_db, url="https://n.x/1", source="newsapi", **kw):
    art_id, _ = memory.insert_article(
        {"source": source, "url": url, "title": kw.get("title", "Big story"),
         "source_name": kw.get("source_name", "The Wire"),
         "vertical": kw.get("vertical", "finance")}, db_path=temp_db)
    return art_id


def _signal(temp_db, art_id, acct, tier="FIRE", score=9.0, **kw):
    return memory.insert_signal(
        {"article_id": art_id, "account_id": acct, "score": score, "tier": tier,
         "velocity": 8, "relevance": 9, "corroboration": 3,
         "reaction_potential": 7, "memory_leverage": 2, "window_urgency": 6,
         "historical_perf": 5, "brand_safety": 8, "sensitivity": "safe",
         "angle": kw.get("angle", "the contrarian read"),
         "topic": kw.get("topic", "rbi-policy"), "format": "hot_take",
         "reasoning": "fresh, relevant, hot"}, db_path=temp_db)


# ------------------------------------------------------------------- funnel
def test_funnel_counts_every_stage(client, temp_db):
    acct = _account(client)
    a1 = _article(temp_db, "https://n.x/1")
    a2 = _article(temp_db, "https://n.x/2", source="rss")
    _signal(temp_db, a1, acct, tier="FIRE")
    _signal(temp_db, a2, acct, tier="SKIP", score=2.0)
    p1 = memory.save_post(acct, "hot_take", "take one", db_path=temp_db)
    memory.save_post(acct, "hot_take", "take two", db_path=temp_db)
    memory.set_post_status(p1, "approved", db_path=temp_db)
    memory.log_claude_call("decision", "claude-sonnet-4-6", 500, 100, 0.01,
                           db_path=temp_db)
    memory.log_claude_call("generator", "claude-sonnet-4-6", 900, 300, 0.02,
                           db_path=temp_db)

    out = client.get("/api/studio/funnel?days=1").json()
    stages = {s["stage"]: s["n"] for s in out["stages"]}
    assert stages == {"ingested": 2, "scored": 2, "qualified": 1,
                      "drafted": 2, "approved": 1, "posted": 0}
    assert out["tiers"] == {"FIRE": 1, "SKIP": 1}
    assert out["rejected"] == 0
    assert {s["module"] for s in out["spend"]} == {"decision", "generator"}
    assert out["spend_total_usd"] == 0.03
    assert {s["source"] for s in out["sources"]} == {"newsapi", "rss"}


# ------------------------------------------------------------ signal center
def test_signals_listing_filters_and_subscores(client, temp_db):
    acct = _account(client)
    a1 = _article(temp_db, "https://n.x/1")
    a2 = _article(temp_db, "https://n.x/2")
    _signal(temp_db, a1, acct, tier="FIRE", score=9.0)
    _signal(temp_db, a2, acct, tier="COOL", score=5.0)

    rows = client.get("/api/studio/signals").json()
    assert len(rows) == 2 and rows[0]["score"] == 9.0   # ranked by score
    # the full anatomy is exposed: subscores + reasoning + joined article
    assert rows[0]["velocity"] == 8 and rows[0]["memory_leverage"] == 2
    assert rows[0]["reasoning"] == "fresh, relevant, hot"
    assert rows[0]["title"] == "Big story" and rows[0]["handle"] == "me"

    fire = client.get("/api/studio/signals?tier=fire").json()
    assert len(fire) == 1 and fire[0]["tier"] == "FIRE"
    assert client.get("/api/studio/signals?limit=1").json()[0]["score"] == 9.0
    assert client.get(
        f"/api/studio/signals?account_id={acct + 99}").json() == []


# ---------------------------------------------------------- memory inspector
def test_memory_center_totals_and_search(client, temp_db):
    acct = _account(client)
    memory.log_stance(acct, "rbi-policy", "rate cuts are premature",
                      db_path=temp_db)
    memory.log_stance(acct, "ai-regulation", "self-regulation won't work",
                      db_path=temp_db)
    memory.insert_prediction(acct, "repo rate cut by Q3", topic="rbi-policy",
                             db_path=temp_db)
    memory.seed_event("rbi-policy", "RBI held rates in June", db_path=temp_db)

    out = client.get(f"/api/studio/memory/{acct}").json()
    assert out["totals"] == {"stances": 2, "predictions": 1,
                             "open_predictions": 1, "events": 1}
    assert {t["topic"] for t in out["topics"]} == {"rbi-policy", "ai-regulation"}

    hit = client.get(f"/api/studio/memory/{acct}?q=rbi").json()
    assert len(hit["stances"]) == 1 and hit["stances"][0]["topic"] == "rbi-policy"
    assert len(hit["predictions"]) == 1 and len(hit["events"]) == 1
    miss = client.get(f"/api/studio/memory/{acct}?q=cricket").json()
    assert miss["stances"] == [] and miss["events"] == []

    assert client.get("/api/studio/memory/999").status_code == 404


# -------------------------------------------------------------- voice studio
def test_voice_studio_untrained_then_trained(client, temp_db):
    acct = _account(client)
    assert client.get(f"/api/studio/voice/{acct}").json()["trained"] is False

    memory.add_voice_samples(acct, [
        {"content": "Markets don't care about your feelings.", "kind": "own",
         "likes": 50, "retweets": 10},
        {"content": "Read the footnotes. Always.", "kind": "own", "likes": 5},
        {"content": "Someone else's banger", "kind": "inspiration",
         "origin": "import:blog"},
    ], db_path=temp_db)
    memory.save_style_dna(acct, genome_a={"tone": "dry",
                                          "signature_phrases": ["read the footnotes"]},
                          db_path=temp_db)

    out = client.get(f"/api/studio/voice/{acct}").json()
    assert out["trained"] is True and out["genome_a"]["tone"] == "dry"
    kinds = {k["kind"]: k["n"] for k in out["corpus"]["kinds"]}
    assert kinds == {"own": 2, "inspiration": 1}
    # top samples ranked by engagement, own posts only
    tops = out["corpus"]["top_samples"]
    assert tops[0]["content"].startswith("Markets don't care")
    assert all("banger" not in t["content"] for t in tops)


# --------------------------------------------------------- learning dashboard
def test_learning_center_statuses_stats_feedback(client, temp_db):
    acct = _account(client)
    p1 = memory.save_post(acct, "hot_take", "yes please", db_path=temp_db)
    p2 = memory.save_post(acct, "hot_take", "no thanks", db_path=temp_db)
    memory.save_post(acct, "data_story", "still waiting", db_path=temp_db)
    memory.set_post_status(p1, "approved", db_path=temp_db)
    memory.set_post_status(p2, "rejected", db_path=temp_db)
    memory.record_feedback(acct, p2, "reject_note", "too salesy",
                           db_path=temp_db)

    out = client.get(f"/api/studio/learning/{acct}").json()
    assert out["by_status"] == {"approved": 1, "rejected": 1, "draft": 1}
    assert out["stats"]["total_reviewed"] == 2
    assert out["stats"]["approval_rate"] == 0.5
    assert out["historical_perf"]["overall"] > 0
    fb = out["recent_feedback"]
    assert len(fb) == 1 and fb[0]["note"] == "too salesy"
    assert fb[0]["kind"] == "reject_note" and fb[0]["format"] == "hot_take"


# --------------------------------------------------------- generation trace
def test_trace_assembles_the_whole_chain(client, temp_db):
    acct = _account(client)
    art = _article(temp_db, "https://n.x/1")
    sig = _signal(temp_db, art, acct)
    post = memory.save_post(acct, "hot_take", "the take", signal_id=sig,
                            article_id=art, persona_score=84.0,
                            meta={"emotion": "surprise"}, db_path=temp_db)
    memory.record_engagement(post, likes=12, retweets=3, db_path=temp_db)

    out = client.get(f"/api/studio/trace/{post}").json()
    assert out["post"]["content"] == "the take"
    assert out["post"]["meta_json"]["emotion"] == "surprise"
    assert out["signal"]["score"] == 9.0 and out["signal"]["velocity"] == 8
    assert out["article"]["title"] == "Big story"
    assert "raw_json" not in out["article"]          # never ship the firehose
    assert out["engagement"]["likes"] == 12
    assert out["pack"] is None

    assert client.get("/api/studio/trace/9999").status_code == 404


def test_posts_pick_list_previews(client, temp_db):
    acct = _account(client)
    memory.save_post(acct, "hot_take", "x" * 500, db_path=temp_db)
    rows = client.get("/api/studio/posts").json()
    assert len(rows) == 1
    assert len(rows[0]["preview"]) == 120 and "content" not in rows[0]
    assert rows[0]["status"] == "draft"
    # scoped pick list
    assert client.get(f"/api/studio/posts?account_id={acct}").json()
    assert client.get("/api/studio/posts?account_id=999").status_code == 404


# ------------------------------------------------------- content graph view
def test_graph_returns_full_decomposition_tree(client, temp_db):
    acct = _account(client)
    asset = memory.save_content_asset(acct, "Distribution beats product. " * 40,
                                      title="The essay", source_type="paste",
                                      db_path=temp_db)
    memory.save_insights(asset, acct, {
        "ideas": [{"text": "Distribution beats product",
                   "angles": ["contrarian", "story"]}],
        "statistics": ["80% fail on distribution"],
        "quotes": ["Distribution beats perfection"],
    }, db_path=temp_db)
    pack = memory.create_content_pack(acct, "The essay", None, None,
                                      asset_id=asset,
                                      idea="Distribution beats product",
                                      db_path=temp_db)
    post = memory.save_post(acct, "linkedin_post", "draft text",
                            persona_score=91.0, db_path=temp_db)
    memory.set_post_pack(post, pack, db_path=temp_db)

    out = client.get(f"/api/studio/graph/{asset}").json()
    assert out["asset"]["title"] == "The essay"
    assert "raw_content" not in out["asset"] and out["asset"]["excerpt"]
    assert out["nodes"]["idea"][0]["angles"] == ["contrarian", "story"]
    assert out["nodes"]["statistic"][0]["text"].startswith("80%")
    assert len(out["packs"]) == 1
    assert out["packs"][0]["idea"] == "Distribution beats product"
    drafts = out["packs"][0]["drafts"]
    assert drafts == [{"id": post, "format": "linkedin_post",
                       "status": "draft", "persona_score": 91.0}]

    assert client.get("/api/studio/graph/9999").status_code == 404
