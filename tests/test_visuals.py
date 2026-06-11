"""Visual generation tests: template mapping, brand payload, the renderer
interface with Pillow fallback, and a real Satori render smoke (skipped when
the node service deps aren't installed)."""

import shutil
from pathlib import Path

import pytest

from conftest import patch_settings
from pipeline import memory, visuals

PNG_MAGIC = b"\x89PNG"


def _post(content, fmt="hot_take", tweets=None):
    return {"id": 1, "format": fmt, "content": content,
            "meta_json": {"tweets": tweets} if tweets else {}}


# ------------------------------------------------------------ template pick
def test_extract_stat_variants():
    assert visuals.extract_stat("GDP grew 7.2% this quarter") == "7.2%"
    assert visuals.extract_stat("₹2,400 crore vanished") == "₹2,400 crore"
    assert visuals.extract_stat("$30m raised") == "$30m"
    assert visuals.extract_stat("a 75,000 strong march") == "75,000"
    assert visuals.extract_stat("no numbers here") is None


def test_choose_template_mapping():
    t, d = visuals.choose_template(_post("'Quote here' — minister", "quote_context"))
    assert t == "quote_card"
    t, d = visuals.choose_template(_post("7.2% growth but look closer", "data_story"))
    assert t == "stat_highlight" and d["stat"] == "7.2%"
    # hot take WITH a stat also gets the stat card
    t, d = visuals.choose_template(_post("₹500 crore gone. poof.", "hot_take"))
    assert t == "stat_highlight"
    # explainer without numbers -> insight card with its label
    t, d = visuals.choose_template(_post("Here is why it matters", "explainer"))
    assert t == "insight_card" and d["title"] == "Explained"
    # thread uses the first tweet, hashtags stripped
    t, d = visuals.choose_template(
        _post("ignored", "thread", tweets=["The hook line #tag1 #tag2", "second"]))
    assert d["text"] == "The hook line"


def test_brand_payload_defaults_and_kit():
    p = visuals.brand_payload({"handle": "me"}, None)
    assert p["handle"] == "me" and p["accent_color"] is None
    kit = {"accent_color": "#ff0000", "bg_style": "light", "font_family": "serif",
           "watermark_text": "acme.co"}
    p = visuals.brand_payload({"handle": "acme"}, kit)
    assert p["accent_color"] == "#ff0000" and p["watermark_text"] == "acme.co"


# ----------------------------------------------------------- generate flow
def _seed_post(db):
    acct = memory.upsert_account(handle="me", db_path=db)
    pid = memory.save_post(acct, "hot_take", "GDP grew 7.2% — look closer.",
                           db_path=db)
    return acct, pid


def test_generate_uses_renderer_and_saves(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path), visuals_enabled=True)
    acct, pid = _seed_post(temp_db)
    memory.save_brand_kit(acct, {"accent_color": "#00ff00"}, db_path=temp_db)
    seen = {}

    class FakeRenderer:
        def render(self, template, data, brand):
            seen.update(template=template, data=data, brand=brand)
            return PNG_MAGIC + b"fake"

    path = visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer())
    assert path and Path(path).read_bytes().startswith(PNG_MAGIC)
    assert seen["template"] == "stat_highlight"
    assert seen["brand"]["accent_color"] == "#00ff00"
    assert seen["brand"]["handle"] == "me"
    # post meta records the visual
    assert memory.get_post(pid, db_path=temp_db)["meta_json"]["visual"] == Path(path).name


def test_generate_falls_back_to_pillow(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path), visuals_enabled=True)
    _, pid = _seed_post(temp_db)

    class DeadRenderer:
        def render(self, template, data, brand):
            return None

    path = visuals.generate_for_post(pid, db_path=temp_db, renderer=DeadRenderer())
    assert path is not None                       # Pillow saved the day
    assert Path(path).read_bytes().startswith(PNG_MAGIC)


def test_generate_disabled_returns_none(temp_db, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_enabled=False)
    _, pid = _seed_post(temp_db)
    assert visuals.generate_for_post(pid, db_path=temp_db) is None


def test_brand_kit_visual_fields_roundtrip(temp_db):
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    memory.save_brand_kit(acct, {"accent_color": "#123456", "bg_style": "gradient",
                                 "font_family": "mono", "watermark_text": "wm",
                                 "logo_url": "https://x/logo.png"}, db_path=temp_db)
    kit = memory.get_brand_kit(acct, db_path=temp_db)
    assert kit["accent_color"] == "#123456" and kit["bg_style"] == "gradient"
    assert kit["font_family"] == "mono" and kit["logo_url"] == "https://x/logo.png"


# ------------------------------------------------------- real render smoke
node_ready = (shutil.which("node") is not None
              and (Path(__file__).parent.parent / "render" / "node_modules" / "satori").exists())


@pytest.mark.skipif(not node_ready, reason="node or render deps not installed")
def test_real_satori_render_end_to_end(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path), visuals_enabled=True)
    acct, pid = _seed_post(temp_db)
    memory.save_brand_kit(acct, {"accent_color": "#4da3ff", "bg_style": "dark"},
                          db_path=temp_db)
    assert visuals.ensure_service() is True       # spawns or reuses the service
    path = visuals.generate_for_post(pid, db_path=temp_db)
    data = Path(path).read_bytes()
    assert data.startswith(PNG_MAGIC) and len(data) > 10_000  # real raster, not stub
