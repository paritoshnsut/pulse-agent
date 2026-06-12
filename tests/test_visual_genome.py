"""Tests for the choose-the-right-visual layer: size variants (square/story),
the zero-cost visual A/B alternates engine, and Visual Genome v1 (preference
ranking + generic-card override)."""

import shutil
from pathlib import Path

import pytest

from conftest import patch_settings
from pipeline import memory, visual_prefs, visuals

PNG_MAGIC = b"\x89PNG"


def _seed_post(db, content="GDP grew 7.2% — look closer.", fmt="hot_take",
               meta=None):
    acct = memory.upsert_account(handle="me", db_path=db)
    pid = memory.save_post(acct, fmt, content, meta=meta, db_path=db)
    return acct, pid


def _reviewed(db, acct, template, status, n):
    for i in range(n):
        pid = memory.save_post(acct, "hot_take", f"{template}{status}{i}",
                               meta={"visual_template": template}, db_path=db)
        memory.set_post_status(pid, status, db_path=db)


# -------------------------------------------------------------- size variants
def test_size_variant_threads_size_and_keeps_primary(temp_db, tmp_path,
                                                     monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    _, pid = _seed_post(temp_db)
    seen = []

    class FakeRenderer:
        def render(self, template, data, brand):
            seen.append(data)
            return PNG_MAGIC + b"x"

    # primary first, then a square variant
    visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer())
    sq = visuals.generate_for_post(pid, db_path=temp_db,
                                   renderer=FakeRenderer(), size="square")
    assert "_size" not in seen[0]
    assert seen[1]["_size"] == "square"
    assert sq.endswith("-square.png")
    meta = memory.get_post(pid, db_path=temp_db)["meta_json"]
    # the square file lives beside the primary, never replacing it
    assert meta["visual"] != meta["visual_square"]
    assert meta["visual_square"].endswith("-square.png")


def test_invalid_size_ignored(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    _, pid = _seed_post(temp_db)

    class FakeRenderer:
        def render(self, template, data, brand):
            assert "_size" not in data
            return PNG_MAGIC + b"x"

    path = visuals.generate_for_post(pid, db_path=temp_db,
                                     renderer=FakeRenderer(), size="billboard")
    assert path and not path.endswith("-billboard.png")


# ------------------------------------------------------------- A/B alternates
def test_alternates_use_cached_structures_no_claude(temp_db, tmp_path,
                                                    monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    spec = {"kind": "bar", "title": "GDP", "labels": ["a", "b", "c"],
            "values": [1.0, 2.0, 3.0], "unit": "%", "source": ""}
    _, pid = _seed_post(temp_db, meta={"chart": spec,
                                       "visual_template": "stat_highlight"})
    rendered = []

    class FakeRenderer:
        def render(self, template, data, brand):
            rendered.append(template)
            return PNG_MAGIC + b"x"

    alts = visuals.generate_alternates(pid, k=2, db_path=temp_db,
                                       renderer=FakeRenderer())
    # the cached chart is a candidate; the primary (stat) is excluded
    assert [a["template"] for a in alts] == rendered
    assert "chart_card" in rendered
    assert "stat_highlight" not in rendered
    meta = memory.get_post(pid, db_path=temp_db)["meta_json"]
    assert len(meta["visual_alternates"]) == 2
    assert all((tmp_path / a["file"]).exists()
               for a in meta["visual_alternates"])


def test_alternates_ordered_by_genome(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    acct, pid = _seed_post(temp_db, content="No numbers here at all, plain.",
                           meta={"visual_template": "insight_card"})
    # history: this account loves quote cards (5/5), is lukewarm on hero (1/4)
    _reviewed(temp_db, acct, "quote_card", "approved", 5)
    _reviewed(temp_db, acct, "hero_card", "rejected", 3)
    _reviewed(temp_db, acct, "hero_card", "approved", 1)
    rendered = []

    class FakeRenderer:
        def render(self, template, data, brand):
            rendered.append(template)
            return PNG_MAGIC + b"x"

    visuals.generate_alternates(pid, k=2, db_path=temp_db,
                                renderer=FakeRenderer())
    # quote_card (rate 1.0) must come before hero_card (rate .25)
    assert rendered.index("quote_card") < rendered.index("hero_card")


def test_alternates_skip_failed_renders(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    _, pid = _seed_post(temp_db, meta={"visual_template": "stat_highlight"})

    class FlakyRenderer:
        def render(self, template, data, brand):
            return None if template == "hero_card" else PNG_MAGIC + b"x"

    alts = visuals.generate_alternates(pid, k=3, db_path=temp_db,
                                       renderer=FlakyRenderer())
    assert all(a["template"] != "hero_card" for a in alts)
    assert alts                                  # others still produced


# ------------------------------------------------------------- Genome v1
def test_preferred_templates_ranking(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    _reviewed(temp_db, acct, "chart_card", "approved", 4)
    _reviewed(temp_db, acct, "list_card", "approved", 2)
    _reviewed(temp_db, acct, "list_card", "rejected", 2)
    _reviewed(temp_db, acct, "framework_card", "rejected", 4)
    _reviewed(temp_db, acct, "quote_card", "approved", 2)   # below floor
    ranking = visual_prefs.preferred_templates(acct, db_path=temp_db)
    assert ranking == ["chart_card", "list_card", "framework_card"]


def test_better_generic_card_gates(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    # not enough evidence -> None
    _reviewed(temp_db, acct, "hero_card", "approved", 2)
    assert visual_prefs.better_generic_card(acct, db_path=temp_db) is None
    # enough evidence + clear margin -> hero wins
    _reviewed(temp_db, acct, "hero_card", "approved", 3)
    assert visual_prefs.better_generic_card(acct, db_path=temp_db) == "hero_card"
    # but if insight_card itself performs just as well, no override
    _reviewed(temp_db, acct, "insight_card", "approved", 5)
    assert visual_prefs.better_generic_card(acct, db_path=temp_db) is None


def test_generic_override_applied_on_auto_pick(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    acct, pid = _seed_post(temp_db, content="A plain statement, no numbers.",
                           fmt="evergreen", meta={"blueprint": None})
    _reviewed(temp_db, acct, "hero_card", "approved", 5)
    calls = []

    class FakeRenderer:
        def render(self, template, data, brand):
            calls.append(template)
            return PNG_MAGIC + b"x"

    visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer())
    assert calls == ["hero_card"]        # genome upgraded the generic card
    meta = memory.get_post(pid, db_path=temp_db)["meta_json"]
    assert meta["visual_template"] == "hero_card"


# ------------------------------------------------------- real render smoke
node_ready = (shutil.which("node") is not None
              and (Path(__file__).parent.parent / "render" / "node_modules"
                   / "satori").exists())


@pytest.mark.skipif(not node_ready, reason="node or render deps not installed")
def test_real_render_square_and_story(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    _, pid = _seed_post(temp_db)
    assert visuals.ensure_service() is True
    sq = visuals.generate_for_post(pid, db_path=temp_db, size="square")
    st = visuals.generate_for_post(pid, db_path=temp_db, size="story")
    from PIL import Image
    assert Image.open(sq).size == (1080, 1080)
    assert Image.open(st).size == (1080, 1920)
