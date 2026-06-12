"""Tests for the visual blueprint engine: per-type validation, extraction +
caching, the explicit-want path, generate_for_post wiring, and real-render
smokes for all five structured templates (skipped without node deps)."""

import json
import shutil
from pathlib import Path

import pytest

from conftest import StubClient, patch_settings
from pipeline import blueprint, memory, visuals
from pipeline.blueprint import validate_blueprint

PNG_MAGIC = b"\x89PNG"


# --------------------------------------------------------------- validation
def test_validate_comparison():
    bp = validate_blueprint({
        "type": "comparison", "title": "Old vs new",
        "left_title": "Old way", "right_title": "New way",
        "left_points": ["slow", "manual"], "right_points": ["fast", "auto"]})
    assert bp["type"] == "comparison" and len(bp["left_points"]) == 2
    # too few points on one side -> None
    assert validate_blueprint({
        "type": "comparison", "title": "x", "left_title": "a",
        "right_title": "b", "left_points": ["only one"],
        "right_points": ["1", "2"]}) is None


def test_validate_framework_and_process_bounds():
    items = [{"label": f"pillar {i}", "desc": "d"} for i in range(4)]
    assert validate_blueprint({"type": "framework", "title": "t",
                               "items": items})["type"] == "framework"
    # 2 items: below floor; 6: above cap
    assert validate_blueprint({"type": "framework", "title": "t",
                               "items": items[:2]}) is None
    steps = [{"label": f"s{i}", "desc": ""} for i in range(6)]
    assert validate_blueprint({"type": "process", "title": "t",
                               "steps": steps}) is None
    assert validate_blueprint({"type": "process", "title": "t",
                               "steps": steps[:4]})["type"] == "process"


def test_validate_timeline_and_list():
    ms = [{"period": "2020", "text": "a"}, {"period": "2022", "text": "b"},
          {"period": "2024", "text": "c"}]
    assert validate_blueprint({"type": "timeline", "title": "t",
                               "milestones": ms})["type"] == "timeline"
    assert validate_blueprint({"type": "list", "title": "t",
                               "items": ["a", "b", "c", "d"]})["type"] == "list"
    assert validate_blueprint({"type": "list", "title": "t",
                               "items": ["a", "b"]}) is None
    assert validate_blueprint({"type": "mind_map", "title": "t"}) is None
    assert validate_blueprint("garbage") is None


def test_validate_clamps_lengths():
    bp = validate_blueprint({"type": "list", "title": "T" * 200,
                             "items": ["x" * 300, "b", "c"]})
    assert len(bp["title"]) == 80 and len(bp["items"][0]) == 80


# --------------------------------------------------------------- extraction
def _seed_post(db, content, fmt="explainer", meta=None):
    acct = memory.upsert_account(handle="me", db_path=db)
    pid = memory.save_post(acct, fmt, content, meta=meta, db_path=db)
    return acct, pid


def test_blueprint_extracts_and_caches(temp_db):
    payload = json.dumps({"type": "process", "title": "How a draft ships",
                          "steps": [{"label": "Detect", "desc": ""},
                                    {"label": "Draft", "desc": ""},
                                    {"label": "Approve", "desc": ""}]})
    _, pid = _seed_post(temp_db, "First we detect, then draft, then approve.")
    ex = blueprint.BlueprintExtractor(client=StubClient(payload))
    bp = ex.blueprint_for(memory.get_post(pid, db_path=temp_db), db_path=temp_db)
    assert bp["type"] == "process" and len(bp["steps"]) == 3

    class ExplodingClient:
        @property
        def messages(self):
            raise AssertionError("must not be called — blueprint is cached")
    cached = blueprint.BlueprintExtractor(client=ExplodingClient()).blueprint_for(
        memory.get_post(pid, db_path=temp_db), db_path=temp_db)
    assert cached == bp


def test_blueprint_null_cached_garbage_not(temp_db):
    _, pid = _seed_post(temp_db, "Just a normal opinion, no structure.")
    bp = blueprint.BlueprintExtractor(client=StubClient("null")).blueprint_for(
        memory.get_post(pid, db_path=temp_db), db_path=temp_db)
    assert bp is None
    assert memory.get_post(pid, db_path=temp_db)["meta_json"]["blueprint"] is None

    _, pid2 = _seed_post(temp_db, "Another post.")
    bp2 = blueprint.BlueprintExtractor(client=StubClient("not json")).blueprint_for(
        memory.get_post(pid2, db_path=temp_db), db_path=temp_db)
    assert bp2 is None
    # transient failure NOT cached -> retried next render
    assert "blueprint" not in (memory.get_post(pid2, db_path=temp_db)["meta_json"] or {})


def test_blueprint_want_overrides_cached_other_type(temp_db):
    """A cached 'list' blueprint must not satisfy an explicit comparison ask."""
    cached = {"type": "list", "title": "t", "items": ["a", "b", "c"]}
    payload = json.dumps({"type": "comparison", "title": "X vs Y",
                          "left_title": "X", "right_title": "Y",
                          "left_points": ["1", "2"], "right_points": ["3", "4"]})
    _, pid = _seed_post(temp_db, "content", meta={"blueprint": cached})
    client = StubClient(payload)
    bp = blueprint.BlueprintExtractor(client=client).blueprint_for(
        memory.get_post(pid, db_path=temp_db), want="comparison",
        db_path=temp_db)
    assert bp["type"] == "comparison"
    assert len(client.messages.calls) == 1     # re-extracted for the ask
    # without want, the cached list comes back with no call
    bp2 = blueprint.BlueprintExtractor(client=StubClient("never")).blueprint_for(
        memory.get_post(pid, db_path=temp_db), db_path=temp_db)
    assert bp2["type"] == "comparison"         # cache now holds the comparison


# ------------------------------------------------------------ render wiring
def test_explainer_with_blueprint_renders_structured(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    bp = {"type": "framework", "title": "Three pillars",
          "items": [{"label": "A", "desc": ""}, {"label": "B", "desc": ""},
                    {"label": "C", "desc": ""}]}
    _, pid = _seed_post(temp_db, "Three pillars explained.",
                        meta={"blueprint": bp})     # cached: no Claude
    seen = {}

    class FakeRenderer:
        def render(self, template, data, brand):
            seen.update(template=template, data=data)
            return PNG_MAGIC + b"x"

    path = visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer())
    assert seen["template"] == "framework_card"
    assert seen["data"]["items"][0]["label"] == "A"
    assert Path(path).read_bytes().startswith(PNG_MAGIC)


def test_explainer_without_blueprint_falls_back(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    _, pid = _seed_post(temp_db, "Why it matters, explained.",
                        meta={"blueprint": None})   # cached miss: no Claude
    calls = []

    class FakeRenderer:
        def render(self, template, data, brand):
            calls.append(template)
            return PNG_MAGIC + b"x"

    visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer())
    assert calls == ["insight_card"]


def test_hot_take_never_auto_tries_blueprint(temp_db, tmp_path, monkeypatch):
    """Punchy formats stay punchy: no blueprint attempt, no Claude call."""
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    _, pid = _seed_post(temp_db, "Spicy take.", fmt="hot_take")

    class FakeRenderer:
        def render(self, template, data, brand):
            return PNG_MAGIC + b"x"

    visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer())
    meta = memory.get_post(pid, db_path=temp_db)["meta_json"] or {}
    assert "blueprint" not in meta              # never even attempted


def test_explicit_blueprint_template_no_structure_autopicks(temp_db, tmp_path,
                                                            monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    _, pid = _seed_post(temp_db, "No comparison lives here.", fmt="hot_take",
                        meta={"blueprint": None})
    calls = []

    class FakeRenderer:
        def render(self, template, data, brand):
            calls.append(template)
            return PNG_MAGIC + b"x"

    # the cached miss answers the explicit ask too (validate(None) -> None)
    visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer(),
                              template="comparison_card")
    assert calls == ["insight_card"]


# ------------------------------------------------------- real render smoke
node_ready = (shutil.which("node") is not None
              and (Path(__file__).parent.parent / "render" / "node_modules"
                   / "satori").exists())


@pytest.mark.skipif(not node_ready, reason="node or render deps not installed")
def test_real_render_all_five_blueprints(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    memory.save_brand_kit(acct, {"accent_color": "#4da3ff"}, db_path=temp_db)
    blueprints = [
        {"type": "comparison", "title": "Old vs new", "left_title": "Old",
         "right_title": "New", "left_points": ["slow", "manual"],
         "right_points": ["fast", "automatic"]},
        {"type": "framework", "title": "Three pillars",
         "items": [{"label": "Watch", "desc": "always on"},
                   {"label": "Draft", "desc": "your voice"},
                   {"label": "Learn", "desc": "every post"}]},
        {"type": "timeline", "title": "The road",
         "milestones": [{"period": "2024", "text": "start"},
                        {"period": "2025", "text": "scale"},
                        {"period": "2026", "text": "agents"}]},
        {"type": "process", "title": "The loop",
         "steps": [{"label": "Detect", "desc": ""},
                   {"label": "Draft", "desc": ""},
                   {"label": "Approve", "desc": ""}]},
        {"type": "list", "title": "3 rules",
         "items": ["be fast", "be specific", "bring receipts"]},
    ]
    assert visuals.ensure_service() is True
    for bp in blueprints:
        pid = memory.save_post(acct, "explainer", "body",
                               meta={"blueprint": bp}, db_path=temp_db)
        path = visuals.generate_for_post(pid, db_path=temp_db)
        data = Path(path).read_bytes()
        assert data.startswith(PNG_MAGIC) and len(data) > 10_000, bp["type"]
