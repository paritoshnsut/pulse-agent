"""Marketing-ready v1: brand kit (rules + enforcement), Content Squeezer
(repurpose), de-politicized engine (account kind + presets)."""

import json

from conftest import StubClient, _Msg
from pipeline import memory
from style import brand as brand_mod
from style import voice


class SeqStub:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Msg(self.payloads.pop(0) if self.payloads else "{}")


# --------------------------------------------------------------- brand kit
def test_brand_enforce_swaps_and_flags():
    brand = {"word_swaps": {"cheap": "affordable", "client": "partner"},
             "banned_words": ["guys", "synergy"]}
    text, survivors = brand_mod.enforce("Cheap deal for you guys, real synergy", brand)
    assert "Affordable" in text and "cheap" not in text.lower()
    assert set(survivors) == {"guys", "synergy"}     # no swap -> flagged
    # case preserved
    t2, _ = brand_mod.enforce("CHEAP and cheap", brand)
    assert "AFFORDABLE" in t2 and "affordable" in t2


def test_brand_render_rules_and_apply_to_genome():
    kit = {"banned_words": ["cheap"], "word_swaps": {"client": "partner"},
           "disclaimers": ["Not financial advice."], "cta_text": "Try it free",
           "cta_url": "https://x.co", "notes": "always optimistic"}
    g = brand_mod.apply_to_genome({"tone": "warm"}, kit)
    assert g["tone"] == "warm" and g["brand"]["cta_text"] == "Try it free"
    rules = brand_mod.render_rules(g["brand"])
    assert "NEVER use" in rules and "Try it free" in rules and "Not financial advice" in rules
    # no kit -> genome untouched (every existing account behaves as before)
    assert brand_mod.apply_to_genome({"tone": "warm"}, None) == {"tone": "warm"}


def test_brand_kit_persists_and_loads(temp_db):
    acct = memory.upsert_account(handle="brand", db_path=temp_db)
    memory.save_brand_kit(acct, {"banned_words": ["cheap"],
                                 "word_swaps": {"client": "partner"},
                                 "cta_text": "Shop now"}, db_path=temp_db)
    kit = memory.get_brand_kit(acct, db_path=temp_db)
    assert kit["banned_words"] == ["cheap"]
    assert kit["word_swaps"] == {"client": "partner"}
    # upsert overwrites
    memory.save_brand_kit(acct, {"banned_words": ["guys"]}, db_path=temp_db)
    assert memory.get_brand_kit(acct, db_path=temp_db)["banned_words"] == ["guys"]


def test_voice_effective_for_merges_brand(temp_db):
    acct = memory.upsert_account(handle="brand", db_path=temp_db)
    memory.save_style_dna(acct, genome_a={"tone": "warm"}, db_path=temp_db)
    assert "brand" not in voice.effective_for(acct, db_path=temp_db)
    memory.save_brand_kit(acct, {"banned_words": ["cheap"]}, db_path=temp_db)
    g = voice.effective_for(acct, db_path=temp_db)
    assert g["brand"]["banned_words"] == ["cheap"]


def test_generator_brand_violation_flags_review(temp_db):
    from pipeline.generator import ContentGenerator
    # model returns a banned word with no swap -> flagged + needs_review
    draft = json.dumps({"text": "Our cheap plan is great", "hashtags": [],
                        "emotion": "pride", "note": ""})
    genome = {"emoji_usage": "none", "brand": {"banned_words": ["cheap"], "word_swaps": {}}}
    best = ContentGenerator(client=SeqStub(draft)).generate_checked(
        {"title": "Launch"}, genome, "hot_take", scorer=None)
    assert best["brand_violations"] == ["cheap"]
    assert best["needs_review"] is True


def test_generator_brand_swap_applied(temp_db):
    from pipeline.generator import ContentGenerator
    draft = json.dumps({"text": "A cheap option for our client", "hashtags": [],
                        "emotion": "neutral", "note": ""})
    genome = {"emoji_usage": "none",
              "brand": {"word_swaps": {"cheap": "affordable", "client": "customer"},
                        "banned_words": []}}
    best = ContentGenerator(client=SeqStub(draft)).generate_checked(
        {"title": "x"}, genome, "hot_take", scorer=None)
    assert "affordable" in best["content"] and "customer" in best["content"]
    assert "cheap" not in best["content"].lower()
    assert not best.get("brand_violations")


# ------------------------------------------------------------- repurpose
SQUEEZE_DRAFT = json.dumps({"text": "Repurposed insight.", "hashtags": [],
                           "emotion": "curiosity", "note": ""})


def test_content_squeezer_makes_a_pack(temp_db):
    from pipeline.repurpose import ContentSqueezer
    acct_id = memory.upsert_account(handle="brand", kind="brand", db_path=temp_db)
    memory.save_style_dna(acct_id, genome_a={"tone": "warm"}, db_path=temp_db)
    account = memory.get_account(acct_id, db_path=temp_db)
    # enough payloads for the plan (8 drafts) — SeqStub repeats {} after, but
    # plan-limited; give plenty
    stub = SeqStub(*([SQUEEZE_DRAFT] * 20))
    source = "Our new feature ships today. " * 20
    # shrink the plan so the test is fast and deterministic
    out = ContentSqueezer(client=stub, db_path=temp_db).squeeze(
        account, text=source, title="Launch day",
        plan=[("linkedin_post", 1), ("thread", 1), ("newsletter", 1)])
    assert out["ok"] is True and out["pack_id"]
    posts = memory.get_pack_posts(out["pack_id"], db_path=temp_db)
    assert len(posts) == 3
    assert {p["format"] for p in posts} == {"linkedin_post", "thread", "newsletter"}
    # the source was passed as grounding context, not invented
    gen_prompt = stub.calls[0]["messages"][0]["content"]
    assert "SOURCE CONTENT TO REPURPOSE" in gen_prompt


def test_squeezer_needs_voice_and_enough_text(temp_db):
    from pipeline.repurpose import ContentSqueezer
    acct_id = memory.upsert_account(handle="brand", db_path=temp_db)
    account = memory.get_account(acct_id, db_path=temp_db)
    # no voice
    assert ContentSqueezer(db_path=temp_db).squeeze(account, text="x" * 200)["ok"] is False
    memory.save_style_dna(acct_id, genome_a={"tone": "x"}, db_path=temp_db)
    # too little text
    assert ContentSqueezer(db_path=temp_db).squeeze(account, text="hi")["ok"] is False


def test_repurpose_formats_excluded_from_choosable():
    from pipeline.generator import CHOOSABLE_FORMATS, FORMATS, REPURPOSE_FORMATS
    for fmt in ("linkedin_post", "newsletter", "video_script"):
        assert fmt in FORMATS and fmt not in CHOOSABLE_FORMATS
    assert "linkedin_post" in REPURPOSE_FORMATS


# ------------------------------------------------------------ de-politicize
def test_account_kind_persists_and_reaches_decision_prompt(temp_db):
    from pipeline.decision import DecisionAgent
    acct = memory.upsert_account(handle="brand", kind="brand", db_path=temp_db)
    assert memory.get_account(acct, db_path=temp_db)["kind"] == "brand"
    stub = StubClient(json.dumps({"relevance": 5, "reaction_potential": 5,
                                  "angle": "", "topic": "t", "reasoning": ""}))
    DecisionAgent(client=stub).judge({"title": "x"}, {"kind": "brand", "niche": "saas"})
    prompt = stub.messages.calls[0]["messages"][0]["content"]
    assert "ACCOUNT TYPE: brand" in prompt


def test_presets_available():
    from presets import list_presets
    ps = list_presets()
    ids = {p["id"] for p in ps}
    assert {"saas_founder", "dtc_ecommerce", "creator", "political_commentator"} <= ids
    saas = next(p for p in ps if p["id"] == "saas_founder")
    assert saas["kind"] == "brand" and saas["topics"]
