"""Tests for the visual entity + strategy extractor (VISUALS.md V3 Step 1):
brief validation, deterministic strategy inference, the free pre-gate, and
the extract→cache lifecycle (hit / typographic verdict cached, transient miss
not cached)."""

import json

import pytest

from conftest import StubClient
from pipeline import entities, memory
from pipeline.entities import (looks_entity_rich, validate_visual_brief,
                               VisualEntityExtractor)


# --------------------------------------------------------------- validation
def test_validate_keeps_named_entities_and_strategy():
    brief = validate_visual_brief({
        "entities": [
            {"name": "Narendra Modi", "type": "person", "role": "subject"},
            {"name": "Donald Trump", "type": "person", "role": "subject"}],
        "visual_strategy": "image_vs"})
    assert brief["visual_strategy"] == "image_vs"
    assert [e["name"] for e in brief["entities"]] == ["Narendra Modi", "Donald Trump"]


def test_validate_drops_bad_types_and_defaults_role():
    brief = validate_visual_brief({
        "entities": [
            {"name": "Apple", "type": "org", "role": "subject"},
            {"name": "nameless", "type": "alien"},        # bad type -> dropped
            {"name": "", "type": "person"},               # empty name -> dropped
            {"name": "RBI", "type": "org"}],              # no role -> "mentioned"
        "visual_strategy": "product"})
    names = [(e["name"], e["role"]) for e in brief["entities"]]
    assert names == [("Apple", "subject"), ("RBI", "mentioned")]


def test_validate_caps_eight_and_clamps_name():
    raw = {"entities": [{"name": "P" * 200, "type": "person", "role": "subject"}]
           + [{"name": f"Org {i}", "type": "org", "role": "mentioned"}
              for i in range(12)],
           "visual_strategy": "typography"}
    brief = validate_visual_brief(raw)
    assert len(brief["entities"]) == 8
    assert len(brief["entities"][0]["name"]) == 80


def test_invalid_strategy_is_inferred_from_subjects():
    # two person/org subjects -> image_vs
    assert validate_visual_brief({
        "entities": [{"name": "A", "type": "person", "role": "subject"},
                     {"name": "B", "type": "org", "role": "subject"}],
        "visual_strategy": "nonsense"})["visual_strategy"] == "image_vs"
    # one subject -> image_portrait
    assert validate_visual_brief({
        "entities": [{"name": "A", "type": "person", "role": "subject"}],
        "visual_strategy": None})["visual_strategy"] == "image_portrait"
    # a product subject -> product
    assert validate_visual_brief({
        "entities": [{"name": "iPhone", "type": "product", "role": "subject"}],
        "visual_strategy": ""})["visual_strategy"] == "product"
    # nothing -> typography
    assert validate_visual_brief({"entities": [], "visual_strategy": "x"}
                                 )["visual_strategy"] == "typography"


def test_validate_rejects_non_dict():
    assert validate_visual_brief("garbage") is None
    assert validate_visual_brief(None) is None


# ------------------------------------------------------------------ pre-gate
def test_pre_gate_detects_names_and_ignores_opinions():
    assert looks_entity_rich("Modi and Trump discuss the killing of soldiers")
    assert looks_entity_rich("RBI holds the repo rate steady")          # acronym
    assert looks_entity_rich("Apple just shipped the Vision Pro")        # 2 caps
    assert not looks_entity_rich("Stop overthinking your launch and ship")
    assert not looks_entity_rich("the market is overreacting again")
    assert not looks_entity_rich("")


# --------------------------------------------------------------- extract+cache
def _seed_post(db, content, fmt="hot_take", meta=None):
    acct = memory.upsert_account(handle="me", db_path=db)
    pid = memory.save_post(acct, fmt, content, meta=meta, db_path=db)
    return acct, pid


def test_extract_caches_and_second_call_is_free(temp_db):
    payload = json.dumps({
        "entities": [{"name": "Narendra Modi", "type": "person", "role": "subject"},
                     {"name": "Donald Trump", "type": "person", "role": "subject"}],
        "visual_strategy": "image_vs"})
    _, pid = _seed_post(temp_db, "Modi and Trump just spoke about the border.")
    brief = VisualEntityExtractor(client=StubClient(payload)).brief_for(
        memory.get_post(pid, db_path=temp_db), db_path=temp_db)
    assert brief["visual_strategy"] == "image_vs" and len(brief["entities"]) == 2

    class ExplodingClient:
        @property
        def messages(self):
            raise AssertionError("must not be called — brief is cached")
    cached = VisualEntityExtractor(client=ExplodingClient()).brief_for(
        memory.get_post(pid, db_path=temp_db), db_path=temp_db)
    assert cached == brief


def test_typographic_verdict_is_cached(temp_db):
    """A 'no entities, typography' answer is a real verdict, cached so it never
    re-calls — distinct from a structurally-broken response."""
    _, pid = _seed_post(temp_db, "Just ship the thing. Stop overthinking.")
    payload = json.dumps({"entities": [], "visual_strategy": "typography"})
    brief = VisualEntityExtractor(client=StubClient(payload)).brief_for(
        memory.get_post(pid, db_path=temp_db), db_path=temp_db)
    expected = {"entities": [], "visual_strategy": "typography",
                "story_type": "", "headline": "", "highlight": "",
                "subheadline": "", "tag": ""}
    assert brief == expected
    stored = memory.get_post(pid, db_path=temp_db)["meta_json"]["visual_entities"]
    assert stored == expected


def test_transient_failure_not_cached(temp_db):
    _, pid = _seed_post(temp_db, "Some post.")
    brief = VisualEntityExtractor(client=StubClient("not json")).brief_for(
        memory.get_post(pid, db_path=temp_db), db_path=temp_db)
    assert brief is None
    # not cached -> retried next render
    assert "visual_entities" not in (
        memory.get_post(pid, db_path=temp_db)["meta_json"] or {})
