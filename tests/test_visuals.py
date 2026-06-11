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


# ----------------------------------------------------------------- carousel
def test_split_thread_into_slides():
    post = _post("ignored", "thread",
                 tweets=["The hook #tag", "point one", "point two", "point three"])
    pack = visuals.split_into_slides(post, {"cta_text": "Try it", "cta_url": "x.co"})
    assert pack["cover"] == "The hook"
    assert pack["slides"] == ["point one", "point two", "point three"]
    assert pack["cta"] == {"cta_text": "Try it", "cta_url": "x.co"}


def test_split_longform_packs_paragraphs(monkeypatch):
    patch_settings(monkeypatch, visuals, carousel_slide_chars=120,
                   carousel_max_slides=6)
    paras = ["A short hook line.",
             "First idea explained in some detail here, with enough words that "
             "the paragraph carries genuine substance for a slide.",
             "Second idea, also explained at length right here, again with "
             "enough body to make the slide worth swiping to.",
             "Third idea rounds out the whole argument nicely and gives the "
             "closing slide something concrete and memorable to land on."]
    post = _post("\n\n".join(paras), "linkedin_post")
    pack = visuals.split_into_slides(post, None)
    assert pack["cover"] == "A short hook line."
    assert len(pack["slides"]) >= 2                     # packed under budget
    assert all(len(s) <= 120 + 60 for s in pack["slides"])
    # everything survived the split
    assert "Third idea" in " ".join(pack["slides"])


def test_split_huge_opener_uses_first_sentence():
    long_first = ("This is the very first sentence of a long opener. " +
                  "And here is a great deal of follow-on detail " * 8).strip()
    post = _post(long_first + "\n\nSecond paragraph here with plenty of words "
                 "so the total clears the carousel-worthiness bar easily.",
                 "linkedin_post")
    pack = visuals.split_into_slides(post, None)
    assert pack["cover"] == "This is the very first sentence of a long opener."
    assert any("follow-on detail" in s for s in pack["slides"])


def test_split_thin_content_returns_none():
    assert visuals.split_into_slides(_post("too short", "linkedin_post"), None) is None
    assert visuals.split_into_slides(
        _post("x", "thread", tweets=["only one tweet"]), None) is None


def test_carousel_renders_all_slides_and_records_meta(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path), visuals_enabled=True)
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    memory.save_brand_kit(acct, {"cta_text": "Try it free"}, db_path=temp_db)
    pid = memory.save_post(acct, "thread", "one\n\n———\n\ntwo\n\n———\n\nthree",
                           meta={"tweets": ["The hook", "point one", "point two"]},
                           db_path=temp_db)
    calls = []

    class FakeRenderer:
        def render(self, template, data, brand):
            calls.append((template, data))
            return PNG_MAGIC + b"slide"

    cover = visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer())
    # cover + 2 content + cta = 4 renders, in order
    assert [c[0] for c in calls] == ["carousel_cover", "carousel_slide",
                                     "carousel_slide", "carousel_cta"]
    assert calls[0][1]["total"] == 4
    assert calls[1][1]["index"] == 2
    assert calls[3][1]["cta_text"] == "Try it free"
    meta = memory.get_post(pid, db_path=temp_db)["meta_json"]
    assert len(meta["visual_slides"]) == 4
    assert meta["visual"] == meta["visual_slides"][0]
    assert Path(cover).name == meta["visual_slides"][0]
    assert all((tmp_path / n).exists() for n in meta["visual_slides"])


def test_carousel_abandons_on_slide_failure_falls_back_to_card(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path), visuals_enabled=True)
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    pid = memory.save_post(acct, "thread", "x",
                           meta={"tweets": ["hook", "one", "two"]}, db_path=temp_db)

    class FlakyRenderer:  # cover ok, slide 2 dies -> single-card path kicks in
        n = 0
        def render(self, template, data, brand):
            FlakyRenderer.n += 1
            if FlakyRenderer.n == 2:
                return None
            return PNG_MAGIC + b"x"

    path = visuals.generate_for_post(pid, db_path=temp_db, renderer=FlakyRenderer())
    assert path is not None                       # the single card still produced
    meta = memory.get_post(pid, db_path=temp_db)["meta_json"]
    assert "visual_slides" not in meta            # no half-carousel recorded


# --------------------------------------------------------------- V1.5 bits
def test_template_override_rebuilds_data(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path), visuals_enabled=True)
    acct, pid = _seed_post(temp_db)  # "GDP grew 7.2% — look closer." -> stat by default
    seen = {}

    class FakeRenderer:
        def render(self, template, data, brand):
            seen.update(template=template, data=data)
            return PNG_MAGIC + b"x"

    # force the quote template instead of the auto-picked stat card
    visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer(),
                              template="quote_card")
    assert seen["template"] == "quote_card"
    assert "7.2%" in seen["data"]["text"]          # full text, not stat split


def test_template_override_skips_carousel(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path), visuals_enabled=True)
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    pid = memory.save_post(acct, "thread", "x",
                           meta={"tweets": ["hook", "one", "two"]}, db_path=temp_db)
    calls = []

    class FakeRenderer:
        def render(self, template, data, brand):
            calls.append(template)
            return PNG_MAGIC + b"x"

    visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer(),
                              template="insight_card")
    assert calls == ["insight_card"]               # single card, no carousel


def test_logo_asset_builds_data_url(monkeypatch):
    import io
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (200, 100), "#ff0000").save(buf, "PNG")
    png_bytes = buf.getvalue()

    class FakeResp:
        content = png_bytes
        headers = {"Content-Type": "image/png"}
        def raise_for_status(self): pass

    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResp())
    visuals._LOGO_CACHE.clear()
    asset = visuals.logo_asset("https://x/logo.png", height=40)
    assert asset["src"].startswith("data:image/png;base64,")
    assert asset["height"] == 40 and asset["width"] == 80   # aspect preserved
    # cached: second call doesn't re-fetch
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError))
    assert visuals.logo_asset("https://x/logo.png") == asset
    assert visuals.logo_asset(None) is None


def test_brand_payload_includes_logo(temp_db, monkeypatch):
    monkeypatch.setattr(visuals, "logo_asset",
                        lambda url, height=40: {"src": "data:x", "width": 1, "height": 1}
                        if url else None)
    p = visuals.brand_payload({"handle": "me"}, {"logo_url": "https://x/l.png"})
    assert p["logo"]["src"] == "data:x"


def test_preset_seeds_brand_kit_visuals(temp_db, monkeypatch):
    from fastapi.testclient import TestClient
    from api import main as api_main

    # dev-mode auth + temp db (a local .env may set APP_PASSWORD)
    patch_settings(monkeypatch, api_main, app_password="",
                   supabase_url="", supabase_jwt_secret="")
    monkeypatch.setattr(api_main, "DB", temp_db)
    client = TestClient(api_main.app)
    acct = client.post("/api/accounts",
                       json={"handle": "brandy", "preset": "saas_founder"}).json()
    kit = memory.get_brand_kit(acct["id"], db_path=temp_db)
    assert kit["accent_color"] == "#6366f1" and kit["bg_style"] == "dark"
    # presets list exposes the visual for swatches
    ps_list = client.get("/api/presets").json()
    saas = next(p for p in ps_list if p["id"] == "saas_founder")
    assert saas["visual"]["accent_color"] == "#6366f1"


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


@pytest.mark.skipif(not node_ready, reason="node or render deps not installed")
def test_real_carousel_render_end_to_end(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path), visuals_enabled=True)
    acct = memory.upsert_account(handle="me", db_path=temp_db)
    memory.save_brand_kit(acct, {"cta_text": "Try it", "bg_style": "gradient"},
                          db_path=temp_db)
    pid = memory.save_post(acct, "thread", "x",
                           meta={"tweets": ["The hook", "point one", "point two"]},
                           db_path=temp_db)
    assert visuals.ensure_service() is True
    visuals.generate_for_post(pid, db_path=temp_db)
    meta = memory.get_post(pid, db_path=temp_db)["meta_json"]
    assert len(meta["visual_slides"]) == 4
    for name in meta["visual_slides"]:            # every slide a real square PNG
        data = (tmp_path / name).read_bytes()
        assert data.startswith(PNG_MAGIC) and len(data) > 10_000
