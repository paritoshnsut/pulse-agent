"""Tests for the attention-design build: hook hierarchy, journey blueprints,
the narrative carousel engine, and visual analytics v1 (template logging +
auto-pick bias)."""

import json
import shutil
from pathlib import Path

import pytest

from conftest import StubClient, patch_settings
from pipeline import memory, narrative, visual_prefs, visuals
from pipeline.blueprint import validate_blueprint
from pipeline.narrative import validate_arc

PNG_MAGIC = b"\x89PNG"


def _seed_post(db, content, fmt="thread", meta=None, status=None):
    acct = memory.upsert_account(handle="me", db_path=db)
    pid = memory.save_post(acct, fmt, content, meta=meta, db_path=db)
    if status:
        memory.set_post_status(pid, status, db_path=db)
    return acct, pid


# ------------------------------------------------------------ hook + journey
def test_blueprint_carries_clamped_hook():
    bp = validate_blueprint({"type": "list", "title": "t", "hook": "H" * 100,
                             "items": ["a", "b", "c"]})
    assert bp["hook"] == "H" * 64
    bp2 = validate_blueprint({"type": "list", "title": "t",
                              "items": ["a", "b", "c"]})
    assert bp2["hook"] == ""          # absent hook -> empty, never invented


def test_journey_validates_moods():
    bp = validate_blueprint({"type": "journey", "title": "t", "hook": "h",
                             "milestones": [
                                 {"period": "M1", "text": "build", "mood": "fail"},
                                 {"period": "M12", "text": "build", "mood": "bogus"},
                                 {"period": "M18", "text": "users", "mood": "turn"}]})
    assert bp["type"] == "journey"
    assert [m["mood"] for m in bp["milestones"]] == ["fail", "neutral", "turn"]


def test_journey_without_beats_downgrades_to_timeline():
    bp = validate_blueprint({"type": "journey", "title": "t",
                             "milestones": [
                                 {"period": "2020", "text": "a"},
                                 {"period": "2022", "text": "b"},
                                 {"period": "2024", "text": "c"}]})
    assert bp["type"] == "timeline"   # no emotion = just a timeline


# --------------------------------------------------------------- arc engine
def _arc(n_points=3):
    return {"slides": [{"kind": "hook", "headline": "I wasted 2 years."}]
            + [{"kind": "point", "headline": f"Mistake #{i}", "body": "b"}
               for i in range(1, n_points + 1)]
            + [{"kind": "payoff", "headline": "Do this instead", "body": "talk"}]}


def test_validate_arc_happy_and_bounds():
    arc = validate_arc(_arc())
    assert len(arc) == 5 and arc[0]["kind"] == "hook"
    assert validate_arc(_arc(0)) is None        # 2 slides: too thin
    assert validate_arc({"slides": []}) is None
    assert validate_arc("nope") is None
    # first slide must be the hook
    bad = _arc()
    bad["slides"][0]["kind"] = "point"
    bad["slides"][1]["kind"] = "hook"
    assert validate_arc(bad) is None


def test_arc_extracts_and_caches(temp_db):
    _, pid = _seed_post(temp_db, "long story " * 50)
    ex = narrative.NarrativeArcExtractor(client=StubClient(json.dumps(_arc())))
    arc = ex.arc_for(memory.get_post(pid, db_path=temp_db), db_path=temp_db)
    assert arc[0]["headline"] == "I wasted 2 years."

    class ExplodingClient:
        @property
        def messages(self):
            raise AssertionError("cached — must not call")
    cached = narrative.NarrativeArcExtractor(client=ExplodingClient()).arc_for(
        memory.get_post(pid, db_path=temp_db), db_path=temp_db)
    assert cached == arc


def test_arc_null_cached_garbage_not(temp_db):
    _, pid = _seed_post(temp_db, "flat single idea")
    assert narrative.NarrativeArcExtractor(client=StubClient("null")).arc_for(
        memory.get_post(pid, db_path=temp_db), db_path=temp_db) is None
    assert memory.get_post(pid, db_path=temp_db)["meta_json"]["narrative"] is None

    _, pid2 = _seed_post(temp_db, "another")
    assert narrative.NarrativeArcExtractor(client=StubClient("garbage")).arc_for(
        memory.get_post(pid2, db_path=temp_db), db_path=temp_db) is None
    assert "narrative" not in (memory.get_post(pid2, db_path=temp_db)["meta_json"] or {})


# ------------------------------------------------- carousel uses the arc
def test_carousel_renders_narrative_arc(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True, narrative_carousel=True)
    arc = validate_arc(_arc())
    acct, pid = _seed_post(temp_db, "story",
                           meta={"narrative": arc,
                                 "tweets": ["hook", "one", "two"]})
    calls = []

    class FakeRenderer:
        def render(self, template, data, brand):
            calls.append((template, data))
            return PNG_MAGIC + b"s"

    visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer())
    # cover from the hook, content slides carry headlines, then CTA
    assert calls[0][0] == "carousel_cover"
    assert calls[0][1]["text"] == "I wasted 2 years."
    assert calls[1][1]["headline"] == "Mistake #1"
    assert calls[-1][0] == "carousel_cta"
    meta = memory.get_post(pid, db_path=temp_db)["meta_json"]
    assert meta["visual_template"] == "carousel_narrative"


def test_carousel_falls_back_to_split_on_arc_miss(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True, narrative_carousel=True)
    acct, pid = _seed_post(temp_db, "x",
                           meta={"narrative": None,        # cached miss
                                 "tweets": ["The hook", "one", "two"]})
    calls = []

    class FakeRenderer:
        def render(self, template, data, brand):
            calls.append((template, data))
            return PNG_MAGIC + b"s"

    visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer())
    assert calls[0][1]["text"] == "The hook"     # paragraph-split path
    meta = memory.get_post(pid, db_path=temp_db)["meta_json"]
    assert meta["visual_template"] == "carousel_split"


def test_narrative_disabled_uses_split(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True, narrative_carousel=False)
    acct, pid = _seed_post(temp_db, "x",
                           meta={"tweets": ["The hook", "one", "two"]})

    class FakeRenderer:
        def render(self, template, data, brand):
            return PNG_MAGIC + b"s"

    visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer())
    meta = memory.get_post(pid, db_path=temp_db)["meta_json"]
    assert meta["visual_template"] == "carousel_split"
    assert "narrative" not in meta               # extractor never ran


# --------------------------------------------------------- visual analytics
def test_single_card_logs_visual_template(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    _, pid = _seed_post(temp_db, "GDP grew 7.2% — look closer.",
                        fmt="hot_take")

    class FakeRenderer:
        def render(self, template, data, brand):
            return PNG_MAGIC + b"x"

    visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer())
    meta = memory.get_post(pid, db_path=temp_db)["meta_json"]
    assert meta["visual_template"] == "stat_highlight"


def test_template_stats_and_shunned(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    # 6 rejected stat cards, 2 approved chart cards
    for i in range(6):
        pid = memory.save_post(acct, "hot_take", f"r{i}",
                               meta={"visual_template": "stat_highlight"},
                               db_path=temp_db)
        memory.set_post_status(pid, "rejected", db_path=temp_db)
    for i in range(2):
        pid = memory.save_post(acct, "data_story", f"a{i}",
                               meta={"visual_template": "chart_card"},
                               db_path=temp_db)
        memory.set_post_status(pid, "approved", db_path=temp_db)

    stats = visual_prefs.template_stats(acct, db_path=temp_db)
    assert stats["stat_highlight"]["shown"] == 6
    assert stats["stat_highlight"]["rate"] == 0.0
    assert stats["chart_card"]["rate"] == 1.0
    shunned = visual_prefs.shunned_templates(acct, db_path=temp_db)
    assert shunned == {"stat_highlight"}         # chart below evidence floor


def test_shunned_blueprint_skipped_on_auto_but_honored_explicitly(
        temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    # history: this account rejects framework cards, 6 of 6
    for i in range(6):
        pid = memory.save_post(acct, "explainer", f"r{i}",
                               meta={"visual_template": "framework_card"},
                               db_path=temp_db)
        memory.set_post_status(pid, "rejected", db_path=temp_db)
    bp = {"type": "framework", "title": "t", "hook": "",
          "items": [{"label": "A", "desc": ""}, {"label": "B", "desc": ""},
                    {"label": "C", "desc": ""}]}
    pid = memory.save_post(acct, "explainer", "body",
                           meta={"blueprint": bp}, db_path=temp_db)
    calls = []

    class FakeRenderer:
        def render(self, template, data, brand):
            calls.append(template)
            return PNG_MAGIC + b"x"

    # auto-pick: framework is shunned -> falls through to the insight card
    visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer())
    assert calls == ["insight_card"]
    # explicit ask: always honored
    calls.clear()
    visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer(),
                              template="framework_card")
    assert calls == ["framework_card"]


# ------------------------------------------------------- real render smoke
node_ready = (shutil.which("node") is not None
              and (Path(__file__).parent.parent / "render" / "node_modules"
                   / "satori").exists())


@pytest.mark.skipif(not node_ready, reason="node or render deps not installed")
def test_real_render_journey_and_narrative_slide(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True, narrative_carousel=True)
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    bp = {"type": "journey", "title": "Founder timeline",
          "hook": "I wasted 18 months because of this.",
          "milestones": [
              {"period": "M1", "text": "build", "mood": "neutral"},
              {"period": "M12", "text": "build", "mood": "fail"},
              {"period": "M18", "text": "users", "mood": "turn"}]}
    pid = memory.save_post(acct, "explainer", "story",
                           meta={"blueprint": bp}, db_path=temp_db)
    assert visuals.ensure_service() is True
    path = visuals.generate_for_post(pid, db_path=temp_db)
    assert Path(path).read_bytes().startswith(PNG_MAGIC)

    arc = validate_arc(_arc())
    pid2 = memory.save_post(acct, "thread", "story",
                            meta={"narrative": arc,
                                  "tweets": ["h", "a", "b"]}, db_path=temp_db)
    path2 = visuals.generate_for_post(pid2, db_path=temp_db)
    data = Path(path2).read_bytes()
    assert data.startswith(PNG_MAGIC) and len(data) > 10_000
