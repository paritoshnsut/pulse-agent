"""Visuals V2 design-agent tests: prompt construction, both image backends
(keyless library + capped paid), backend selection, the vision-critique
loop, the hero composite flow, and the refs API."""

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from conftest import StubClient, patch_settings
from pipeline import design, memory, visuals

PNG_MAGIC = b"\x89PNG"


def _png_bytes(color="#336699", size=(64, 36)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _seed(db, content="GDP grew 7.2% — look closer. #econ"):
    acct = memory.upsert_account(handle="me", db_path=db)
    pid = memory.save_post(acct, "hot_take", content, db_path=db)
    return acct, pid


class SeqClient:
    """Like StubClient but returns a different payload per call."""

    class _Messages:
        def __init__(self, payloads):
            self.payloads = list(payloads)
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            text = self.payloads.pop(0)
            block = type("B", (), {"text": text})()
            return type("M", (), {"content": [block]})()

    def __init__(self, payloads):
        self.messages = self._Messages(payloads)


# -------------------------------------------------------------------- prompt
def test_build_image_prompt_pulls_brand_and_subject():
    post = {"content": "Our spring drop lands Friday #sneakers #drop"}
    kit = {"accent_color": "#ff4400", "bg_style": "light", "notes": "playful"}
    p = design.build_image_prompt(post, kit, {"niche": "streetwear"})
    assert "Our spring drop lands Friday" in p
    assert "#sneakers" not in p                      # hashtags stripped
    assert "#ff4400" in p and "clean, airy" in p and "playful" in p
    assert "streetwear" in p
    assert "no text" in p and "no logos" in p        # typography is Satori's


def test_build_image_prompt_defaults_without_kit():
    p = design.build_image_prompt({"content": "hello"}, None, {})
    assert "moody, high-contrast" in p and "no text" in p


# ------------------------------------------------------------- library backend
def test_library_backend_unavailable_without_refs(temp_db):
    acct, _ = _seed(temp_db)
    lib = design.LibraryBackend(acct, db_path=temp_db)
    assert lib.available() is False
    assert design.pick_backend(acct, db_path=temp_db) is None


def test_library_backend_picks_best_tag_match(temp_db, tmp_path):
    acct, _ = _seed(temp_db)
    sea = tmp_path / "sea.png"; sea.write_bytes(_png_bytes("#003355"))
    fire = tmp_path / "fire.png"; fire.write_bytes(_png_bytes("#aa2200"))
    memory.add_visual_ref(acct, path=str(sea), tags=["ocean", "calm"],
                          db_path=temp_db)
    memory.add_visual_ref(acct, path=str(fire), notes="flames and energy",
                          tags=["fire"], db_path=temp_db)
    lib = design.LibraryBackend(acct, db_path=temp_db)
    assert lib.available() is True
    assert lib.generate("an image about calm ocean mornings") == sea.read_bytes()
    assert lib.generate("explosive fire energy launch") == fire.read_bytes()


def test_library_backend_unreadable_ref_returns_none(temp_db):
    acct, _ = _seed(temp_db)
    memory.add_visual_ref(acct, path="/nonexistent/bg.png", db_path=temp_db)
    assert design.LibraryBackend(acct, db_path=temp_db).generate("x") is None


# ---------------------------------------------------------------- paid backend
def test_openai_backend_gating(temp_db, monkeypatch):
    acct, _ = _seed(temp_db)
    # default backend is "library" -> paid never available
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert design.OpenAIImageBackend(acct, db_path=temp_db).available() is False
    # backend=openai but no key -> unavailable
    patch_settings(monkeypatch, design, imagegen_backend="openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert design.OpenAIImageBackend(acct, db_path=temp_db).available() is False
    # backend + key + under cap -> available
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert design.OpenAIImageBackend(acct, db_path=temp_db).available() is True


def test_openai_backend_persists_and_respects_daily_cap(temp_db, tmp_path,
                                                        monkeypatch):
    acct, _ = _seed(temp_db)
    patch_settings(monkeypatch, design, imagegen_backend="openai",
                   imagegen_daily_cap=1, visuals_dir=str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    png = _png_bytes()
    backend = design.OpenAIImageBackend(acct, db_path=temp_db,
                                        transport=lambda prompt: png)
    assert backend.available() is True
    assert backend.generate("a calm scene") == png
    # the generation was saved as a reusable ref and counts against the cap
    gen = memory.get_visual_refs(acct, kind="generated", db_path=temp_db)
    assert len(gen) == 1 and Path(gen[0]["path"]).read_bytes() == png
    assert memory.generated_images_today(db_path=temp_db) == 1
    assert backend.available() is False              # cap of 1 reached
    # but pick_backend now falls back to the library (the saved generation)
    picked = design.pick_backend(acct, db_path=temp_db)
    assert picked is not None and picked.name == "library"


def test_openai_backend_failure_returns_none(temp_db, monkeypatch):
    acct, _ = _seed(temp_db)
    patch_settings(monkeypatch, design, imagegen_backend="openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def boom(prompt):
        raise RuntimeError("api down")

    backend = design.OpenAIImageBackend(acct, db_path=temp_db, transport=boom)
    assert backend.generate("x") is None             # fail-safe, no raise


# -------------------------------------------------------------------- critique
def test_critique_parses_score_and_feedback():
    client = StubClient(json.dumps({"score": 4, "feedback": "darken the base"}))
    score, fb = design.critique_image(client, _png_bytes(), "the brief")
    assert score == 4.0 and fb == "darken the base"
    sent = client.messages.calls[0]
    types = [b["type"] for b in sent["messages"][0]["content"]]
    assert types == ["image", "text"]                # real vision call shape


def test_critique_fails_open_on_garbage():
    score, fb = design.critique_image(StubClient("not json at all"),
                                      _png_bytes(), "brief")
    assert score == design.settings.design_accept_score and fb == ""


# ------------------------------------------------------------------- hero flow
def test_generate_hero_with_library_ref(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, design, visuals_dir=str(tmp_path))
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    acct, pid = _seed(temp_db)
    memory.save_brand_kit(acct, {"accent_color": "#00ff00"}, db_path=temp_db)
    bg = tmp_path / "bg.png"; bg.write_bytes(_png_bytes(size=(120, 68)))
    memory.add_visual_ref(acct, path=str(bg), tags=["economy"], db_path=temp_db)
    seen = {}

    class FakeRenderer:
        def render(self, template, data, brand):
            seen.update(template=template, data=data, brand=brand)
            return PNG_MAGIC + b"hero"

    path = design.generate_hero(pid, db_path=temp_db, renderer=FakeRenderer())
    assert path and Path(path).read_bytes().startswith(PNG_MAGIC)
    assert seen["template"] == "hero_card"
    assert seen["data"]["text"].startswith("GDP grew 7.2%")
    assert seen["data"]["image"]["src"].startswith("data:image/png;base64,")
    assert seen["data"]["image"]["width"] == 120
    assert seen["brand"]["accent_color"] == "#00ff00"
    meta = memory.get_post(pid, db_path=temp_db)["meta_json"]
    assert meta["visual"] == Path(path).name
    assert meta["visual_template"] == "hero_card"


def test_generate_hero_without_backend_returns_none(temp_db, tmp_path,
                                                    monkeypatch):
    patch_settings(monkeypatch, design, visuals_dir=str(tmp_path))
    _, pid = _seed(temp_db)
    assert design.generate_hero(pid, db_path=temp_db) is None


def test_generate_hero_critique_loop_regenerates(temp_db, tmp_path, monkeypatch):
    """Paid backend: a low first score feeds the critique back into a second
    generation; the loop is bounded by design_max_iters."""
    patch_settings(monkeypatch, design, visuals_dir=str(tmp_path),
                   imagegen_backend="openai", design_max_iters=2,
                   design_accept_score=7.0)
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    acct, pid = _seed(temp_db)

    prompts = []
    def transport(prompt):
        prompts.append(prompt)
        return _png_bytes()
    real = design.OpenAIImageBackend
    monkeypatch.setattr(design, "OpenAIImageBackend",
                        lambda account_id, db_path=None:
                        real(account_id, db_path=db_path, transport=transport))
    client = SeqClient([json.dumps({"score": 3, "feedback": "way too bright"}),
                        json.dumps({"score": 9, "feedback": ""})])

    class FakeRenderer:
        def render(self, template, data, brand):
            return PNG_MAGIC + b"hero"

    path = design.generate_hero(pid, db_path=temp_db,
                                renderer=FakeRenderer(), client=client)
    assert path is not None
    assert len(prompts) == 2                         # regenerated once
    assert "Revision notes: way too bright" in prompts[1]
    assert len(client.messages.calls) == 2


def test_generate_hero_accepts_first_good_image(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, design, visuals_dir=str(tmp_path),
                   imagegen_backend="openai", design_max_iters=3)
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    acct, pid = _seed(temp_db)
    calls = []
    real = design.OpenAIImageBackend
    monkeypatch.setattr(design, "OpenAIImageBackend",
                        lambda account_id, db_path=None:
                        real(account_id, db_path=db_path,
                             transport=lambda p: calls.append(p) or _png_bytes()))
    client = StubClient(json.dumps({"score": 9, "feedback": ""}))

    class FakeRenderer:
        def render(self, template, data, brand):
            return PNG_MAGIC + b"x"

    assert design.generate_hero(pid, db_path=temp_db,
                                renderer=FakeRenderer(), client=client)
    assert len(calls) == 1                           # no wasted generations


def test_generate_for_post_hero_template_routes_to_design(temp_db, tmp_path,
                                                          monkeypatch):
    patch_settings(monkeypatch, design, visuals_dir=str(tmp_path))
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    acct, pid = _seed(temp_db)
    bg = tmp_path / "bg.png"; bg.write_bytes(_png_bytes())
    memory.add_visual_ref(acct, path=str(bg), db_path=temp_db)
    seen = []

    class FakeRenderer:
        def render(self, template, data, brand):
            seen.append(template)
            return PNG_MAGIC + b"x"

    path = visuals.generate_for_post(pid, db_path=temp_db,
                                     renderer=FakeRenderer(),
                                     template="hero_card")
    assert path is not None and seen == ["hero_card"]


def test_generate_for_post_hero_falls_back_to_flat_card(temp_db, tmp_path,
                                                        monkeypatch):
    """No refs, no paid backend -> hero request degrades to the auto-picked
    flat card instead of failing."""
    patch_settings(monkeypatch, design, visuals_dir=str(tmp_path))
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    _, pid = _seed(temp_db)
    seen = []

    class FakeRenderer:
        def render(self, template, data, brand):
            seen.append(template)
            return PNG_MAGIC + b"x"

    path = visuals.generate_for_post(pid, db_path=temp_db,
                                     renderer=FakeRenderer(),
                                     template="hero_card")
    assert path is not None
    assert seen == ["stat_highlight"]                # the auto-pick for this post


# ------------------------------------------------------------------- refs API
def test_refs_api_roundtrip(temp_db, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import main as api_main

    patch_settings(monkeypatch, api_main, app_password="",
                   supabase_url="", supabase_jwt_secret="")
    patch_settings(monkeypatch, design, visuals_dir=str(tmp_path))
    monkeypatch.setattr(api_main, "DB", temp_db)
    client = TestClient(api_main.app)
    acct = client.post("/api/accounts", json={"handle": "brandy"}).json()["id"]

    # upload a file ref with tags
    r = client.post(f"/api/accounts/{acct}/refs",
                    files={"file": ("bg.png", _png_bytes(), "image/png")},
                    data={"notes": "calm ocean", "tags": "ocean, calm"})
    assert r.status_code == 200
    ref_id = r.json()["id"]
    # and a url-only ref
    assert client.post(f"/api/accounts/{acct}/refs",
                       data={"url": "https://cdn.x/bg2.png"}).status_code == 200
    # neither file nor url -> 422
    assert client.post(f"/api/accounts/{acct}/refs",
                       data={"notes": "nothing"}).status_code == 422

    refs = client.get(f"/api/accounts/{acct}/refs").json()
    assert len(refs) == 2
    uploaded = next(x for x in refs if x["id"] == ref_id)
    assert uploaded["tags"] == ["ocean", "calm"]
    assert Path(uploaded["path"]).read_bytes() == _png_bytes()

    # delete one; deleting someone else's / unknown id is a 404
    assert client.delete(f"/api/accounts/{acct}/refs/{ref_id}").status_code == 200
    assert len(client.get(f"/api/accounts/{acct}/refs").json()) == 1
    assert client.delete(f"/api/accounts/{acct}/refs/9999").status_code == 404
