"""Squeezer v2 — the content graph. Decompose → idea-grouped packs with
angles, the asset library, YouTube ingestion, the novelty flag, and the
fail-safe back to the v1 whole-source squeeze."""

import json

import pytest

import pipeline.repurpose as rp
from conftest import _Msg, patch_settings
from pipeline import memory


class SeqStub:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Msg(self.payloads.pop(0) if self.payloads else "{}")


DRAFT = json.dumps({"text": "Repurposed insight.", "hashtags": [],
                    "emotion": "curiosity", "note": ""})

DECOMPOSED = json.dumps({
    "ideas": [
        {"idea": "Distribution matters more than product",
         "angles": ["contrarian: great products fail from bad distribution",
                    "story: I built for 18 months and got zero customers"]},
        {"idea": "Talk to customers before building anything",
         "angles": ["educational: three reasons to start with customers"]},
    ],
    "claims": ["80% of startups fail due to distribution"],
    "stories": ["Founder spent 2 years building before talking to customers"],
    "statistics": ["80% startup failure rate tied to distribution"],
    "quotes": ["Distribution beats perfection"],
    "opinions": ["Founders overvalue product quality"],
})

SOURCE = ("Distribution matters more than product. I built for 18 months and "
          "got zero customers. 80% of startups fail due to distribution. "
          "Distribution beats perfection. Talk to customers first. ") * 4


def _account(temp_db, handle="brand"):
    acct_id = memory.upsert_account(handle=handle, kind="brand", db_path=temp_db)
    memory.save_style_dna(acct_id, genome_a={"tone": "warm"}, db_path=temp_db)
    return memory.get_account(acct_id, db_path=temp_db)


def _all_prompts(stub):
    return [c["messages"][0]["content"] for c in stub.calls]


# ------------------------------------------------------------- graph squeeze
def test_graph_squeeze_idea_packs_and_insights(temp_db):
    account = _account(temp_db)
    stub = SeqStub(DECOMPOSED, *([DRAFT] * 30))
    out = rp.ContentSqueezer(client=stub, db_path=temp_db).squeeze(
        account, text=SOURCE, title="Distribution essay",
        plan=[("linkedin_post", 1), ("thread", 1), ("quote_context", 1)])

    assert out["ok"] and out["mode"] == "graph"
    assert out["ideas"] == ["Distribution matters more than product",
                            "Talk to customers before building anything"]
    # one pack per idea; 3 drafts round-robined 2/1 across the two ideas
    assert len(out["packs"]) == 2
    assert out["packs"][0]["drafts"] == 2 and out["packs"][1]["drafts"] == 1
    # the graph persisted: typed nodes, ideas carrying their angles
    ideas = memory.get_insights(out["asset_id"], kind="idea", db_path=temp_db)
    assert len(ideas) == 2 and len(ideas[0]["angles"]) == 2
    assert memory.get_insights(out["asset_id"], kind="statistic",
                               db_path=temp_db)[0]["text"].startswith("80%")
    # drafts carry idea + angle in meta and land in the right pack
    pack0 = memory.get_pack_posts(out["packs"][0]["pack_id"], db_path=temp_db)
    assert len(pack0) == 2
    for p in pack0:
        assert p["meta_json"]["idea"] == "Distribution matters more than product"
        assert p["meta_json"]["angle"]
    # the second draft for idea 0 cycled to the second angle
    assert {p["meta_json"]["angle"] for p in pack0} == {
        "contrarian: great products fail from bad distribution",
        "story: I built for 18 months and got zero customers"}
    # call 0 was decomposition, not generation
    assert "Do NOT write posts yet" in stub.calls[0]["messages"][0]["content"]
    # generation was idea-focused with supporting nodes attached
    gen = [p for p in _all_prompts(stub)
           if "BUILD THIS DRAFT AROUND ONE IDEA ONLY" in p]
    assert gen and any("(statistic) 80%" in p for p in gen)
    # and still grounded against the full source
    assert all("SOURCE CONTENT TO REPURPOSE" in p for p in gen)


def test_decompose_garbage_falls_back_to_direct(temp_db):
    account = _account(temp_db)
    stub = SeqStub("this is not json", *([DRAFT] * 10))
    out = rp.ContentSqueezer(client=stub, db_path=temp_db).squeeze(
        account, text=SOURCE, plan=[("linkedin_post", 1)])
    assert out["ok"] and out["mode"] == "direct"
    assert len(out["packs"]) == 1 and out["packs"][0]["idea"] is None
    # the asset is still filed even on the fallback path
    assert memory.get_content_asset(out["asset_id"], db_path=temp_db)


def test_decompose_can_be_disabled(temp_db, monkeypatch):
    patch_settings(monkeypatch, rp, squeeze_decompose=False)
    account = _account(temp_db)
    stub = SeqStub(*([DRAFT] * 10))
    out = rp.ContentSqueezer(client=stub, db_path=temp_db).squeeze(
        account, text=SOURCE, plan=[("linkedin_post", 1)])
    assert out["ok"] and out["mode"] == "direct"
    # no decompose call was spent: the first call is already generation
    assert "SOURCE CONTENT TO REPURPOSE" in stub.calls[0]["messages"][0]["content"]


# ----------------------------------------------------------------- ingestion
def test_youtube_url_uses_transcript(temp_db, monkeypatch):
    monkeypatch.setattr(rp, "fetch_youtube_text", lambda url: SOURCE)
    account = _account(temp_db)
    stub = SeqStub("{}", *([DRAFT] * 10))
    out = rp.ContentSqueezer(client=stub, db_path=temp_db).squeeze(
        account, url="https://www.youtube.com/watch?v=abc123",
        plan=[("linkedin_post", 1)])
    assert out["ok"]
    asset = memory.get_content_asset(out["asset_id"], db_path=temp_db)
    assert asset["source_type"] == "youtube"
    assert asset["source_url"] == "https://www.youtube.com/watch?v=abc123"


def test_youtube_without_captions_is_clear_error(temp_db, monkeypatch):
    monkeypatch.setattr(rp, "fetch_youtube_text", lambda url: None)
    account = _account(temp_db)
    out = rp.ContentSqueezer(client=SeqStub(), db_path=temp_db).squeeze(
        account, url="https://youtu.be/abc123")
    assert out["ok"] is False and "captions" in out["error"]


# ------------------------------------------------------------------- novelty
def test_novelty_flags_already_published_idea(temp_db):
    account = _account(temp_db)
    old = memory.save_post(account["id"], "hot_take",
                           "Distribution matters more than product. Always.",
                           db_path=temp_db)
    memory.set_post_status(old, "approved", db_path=temp_db)
    stub = SeqStub(DECOMPOSED, *([DRAFT] * 30))
    out = rp.ContentSqueezer(client=stub, db_path=temp_db).squeeze(
        account, text=SOURCE, plan=[("linkedin_post", 1)])
    assert out["packs"][0]["novelty"]            # idea 0 = the old post
    pack0 = memory.get_pack_posts(out["packs"][0]["pack_id"], db_path=temp_db)
    assert "similar idea" in pack0[0]["meta_json"]["novelty"]


# ----------------------------------------------------------- asset library
def test_resqueeze_reuses_stored_asset(temp_db):
    account = _account(temp_db)
    asset_id = memory.save_content_asset(
        account["id"], SOURCE, title="Old essay", source_type="paste",
        db_path=temp_db)
    stub = SeqStub(DECOMPOSED, *([DRAFT] * 30))
    out = rp.ContentSqueezer(client=stub, db_path=temp_db).squeeze(
        account, asset_id=asset_id, plan=[("linkedin_post", 1)])
    assert out["ok"] and out["asset_id"] == asset_id
    # no duplicate asset row
    assert len(memory.list_content_assets(account["id"], db_path=temp_db)) == 1


def test_resqueeze_rejects_foreign_asset(temp_db):
    mine = _account(temp_db, "mine")
    other_id = memory.upsert_account(handle="other", db_path=temp_db)
    foreign = memory.save_content_asset(other_id, SOURCE, db_path=temp_db)
    out = rp.ContentSqueezer(client=SeqStub(), db_path=temp_db).squeeze(
        mine, asset_id=foreign)
    assert out["ok"] is False and "library" in out["error"]


def test_url_asset_deduplicated(temp_db):
    account = _account(temp_db)
    a1 = memory.save_content_asset(account["id"], "text one",
                                   source_url="https://b.x/p", db_path=temp_db)
    a2 = memory.save_content_asset(account["id"], "text two",
                                   source_url="https://b.x/p", db_path=temp_db)
    assert a1 == a2


# ----------------------------------------------------------------------- api
@pytest.fixture()
def api_client(temp_db, monkeypatch):
    from fastapi.testclient import TestClient

    from api import main as api_main

    patch_settings(monkeypatch, api_main, app_password="",
                   supabase_url="", supabase_jwt_secret="")
    monkeypatch.setattr(api_main, "DB", temp_db)
    return TestClient(api_main.app)


def test_assets_api_list_and_resqueeze(api_client, temp_db, monkeypatch):
    acct = api_client.post("/api/accounts", json={"handle": "me"}).json()["id"]
    asset_id = memory.save_content_asset(acct, SOURCE, title="My essay",
                                         source_type="paste", db_path=temp_db)
    listed = api_client.get(f"/api/accounts/{acct}/assets").json()
    assert len(listed) == 1 and listed[0]["title"] == "My essay"
    assert "raw_content" not in listed[0]        # library list stays light

    seen = {}

    def fake_squeeze(self, account, **kw):
        seen.update(kw)
        return {"ok": True, "live": 4, "ideas": ["x"], "packs": []}
    monkeypatch.setattr(rp.ContentSqueezer, "squeeze", fake_squeeze)
    r = api_client.post(f"/api/accounts/{acct}/assets/{asset_id}/squeeze")
    assert r.status_code == 200 and r.json()["live"] == 4
    assert seen["asset_id"] == asset_id

    monkeypatch.setattr(rp.ContentSqueezer, "squeeze",
                        lambda self, account, **kw: {"ok": False, "error": "nope"})
    assert api_client.post(
        f"/api/accounts/{acct}/assets/{asset_id}/squeeze").status_code == 400
