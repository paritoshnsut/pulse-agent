"""Tests for the visual-prowess build: chart extraction + chart_card path,
topic icon picking, decor/custom-font brand payload, the font upload API,
and a real-render smoke for the new templates (skipped without node deps)."""

import json
import shutil
from pathlib import Path

import pytest

from conftest import StubClient, patch_settings
from pipeline import charts, memory, visuals

PNG_MAGIC = b"\x89PNG"


# ---------------------------------------------------------- spec validation
def test_validate_spec_happy_path():
    spec = charts.validate_spec({"kind": "bar", "title": "GDP growth",
                                 "labels": ["FY22", "FY23", "FY24"],
                                 "values": [9.1, 7.2, 7.8], "unit": "%",
                                 "source": "MoSPI"})
    assert spec["kind"] == "bar" and spec["values"] == [9.1, 7.2, 7.8]
    assert spec["unit"] == "%"


def test_validate_spec_rejects_garbage():
    assert charts.validate_spec(None) is None
    assert charts.validate_spec("not a dict") is None
    # too few points
    assert charts.validate_spec({"labels": ["a", "b"], "values": [1, 2]}) is None
    # length mismatch
    assert charts.validate_spec({"labels": ["a", "b", "c"],
                                 "values": [1, 2]}) is None
    # non-numeric values
    assert charts.validate_spec({"labels": ["a", "b", "c"],
                                 "values": [1, "x", 3]}) is None


def test_validate_spec_negatives_force_line():
    spec = charts.validate_spec({"kind": "bar", "labels": ["a", "b", "c"],
                                 "values": [4.2, -5.8, 9.1]})
    assert spec["kind"] == "line"          # bars can't show negatives honestly


def test_numeric_gate():
    assert charts._numeric_gate("GDP was 4.2 then 9.1 then 7.8") is True
    assert charts._numeric_gate("RBI holds rates, nothing changes") is False
    assert charts._numeric_gate("") is False


# --------------------------------------------------------------- extraction
def _seed_post(db, content, fmt="data_story", meta=None):
    acct = memory.upsert_account(handle="me", db_path=db)
    pid = memory.save_post(acct, fmt, content, meta=meta, db_path=db)
    return acct, pid


def test_spec_for_extracts_and_caches(temp_db):
    payload = json.dumps({"kind": "line", "title": "Inflation trend",
                          "labels": ["Jan", "Feb", "Mar"],
                          "values": [6.5, 5.7, 4.8], "unit": "%"})
    _, pid = _seed_post(temp_db, "Inflation fell from 6.5 to 5.7 to 4.8.")
    ex = charts.ChartExtractor(client=StubClient(payload))
    spec = ex.spec_for(memory.get_post(pid, db_path=temp_db), db_path=temp_db)
    assert spec["kind"] == "line" and len(spec["values"]) == 3
    # cached on the post: a second extractor NEVER calls Claude
    class ExplodingClient:
        @property
        def messages(self):
            raise AssertionError("must not be called — spec is cached")
    cached = charts.ChartExtractor(client=ExplodingClient()).spec_for(
        memory.get_post(pid, db_path=temp_db), db_path=temp_db)
    assert cached == spec


def test_spec_for_numeric_gate_skips_claude(temp_db):
    _, pid = _seed_post(temp_db, "RBI holds rates. No numbers worth charting.")
    client = StubClient("should never be used")
    spec = charts.ChartExtractor(client=client).spec_for(
        memory.get_post(pid, db_path=temp_db), db_path=temp_db)
    assert spec is None
    assert client.messages.calls == []     # gate blocked the call
    # the miss is cached too
    meta = memory.get_post(pid, db_path=temp_db)["meta_json"]
    assert "chart" in meta and meta["chart"] is None


def test_spec_for_null_answer_cached(temp_db):
    _, pid = _seed_post(temp_db, "Numbers 1, 2, 3 but no real series here.")
    spec = charts.ChartExtractor(client=StubClient("null")).spec_for(
        memory.get_post(pid, db_path=temp_db), db_path=temp_db)
    assert spec is None
    assert memory.get_post(pid, db_path=temp_db)["meta_json"]["chart"] is None


def test_spec_for_garbage_not_cached(temp_db):
    """A transient parse failure must NOT cache a miss — retry next render."""
    _, pid = _seed_post(temp_db, "Series: 4.2 then 9.1 then 7.8 percent.")
    spec = charts.ChartExtractor(client=StubClient("totally not json")).spec_for(
        memory.get_post(pid, db_path=temp_db), db_path=temp_db)
    assert spec is None
    assert "chart" not in (memory.get_post(pid, db_path=temp_db)["meta_json"] or {})


# ------------------------------------------------------------- icon picking
def test_pick_icon_keywords_beat_format():
    assert visuals.pick_icon({"content": "Sensex rallies 800 points",
                              "format": "explainer"}) == "trending_up"
    assert visuals.pick_icon({"content": "Parliament passes the new bill",
                              "format": "hot_take"}) == "landmark"
    assert visuals.pick_icon({"content": "IPL final tonight",
                              "format": "hot_take"}) == "trophy"


def test_pick_icon_format_fallback_and_none():
    assert visuals.pick_icon({"content": "something neutral",
                              "format": "prediction"}) == "target"
    assert visuals.pick_icon({"content": "something neutral",
                              "format": "weird_format"}) is None


def test_choose_template_carries_icon_and_seed():
    post = {"id": 42, "format": "explainer", "meta_json": {},
            "content": "Why the court verdict matters"}
    t, d = visuals.choose_template(post)
    assert t == "insight_card"
    assert d["icon"] == "scale" and d["seed"] == 42


# ------------------------------------------------- brand payload additions
def test_brand_payload_decor_and_no_custom_font(temp_db, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_decor="bold")
    p = visuals.brand_payload({"id": 1, "handle": "me"}, {"font_family": "sans"})
    assert p["decor_style"] == "bold"
    assert p["custom_font_key"] is None


def test_brand_payload_custom_font_when_file_exists(tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, render_dir=str(tmp_path))
    d = tmp_path / "fonts" / "custom"
    d.mkdir(parents=True)
    (d / "acct7-400.ttf").write_bytes(b"\x00\x01\x00\x00fake")
    p = visuals.brand_payload({"id": 7, "handle": "me"},
                              {"font_family": "custom"})
    assert p["custom_font_key"] == "acct7"
    # kit says custom but no file -> fail-safe None
    p2 = visuals.brand_payload({"id": 8, "handle": "me"},
                               {"font_family": "custom"})
    assert p2["custom_font_key"] is None


# ------------------------------------------------------- chart render path
def test_data_story_with_series_renders_chart_card(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    spec = {"kind": "bar", "title": "GDP", "labels": ["a", "b", "c"],
            "values": [1.0, 2.0, 3.0], "unit": "%", "source": ""}
    _, pid = _seed_post(temp_db, "GDP went 1 then 2 then 3 percent.",
                        meta={"chart": spec})       # cached spec: no Claude
    seen = {}

    class FakeRenderer:
        def render(self, template, data, brand):
            seen.update(template=template, data=data)
            return PNG_MAGIC + b"chart"

    path = visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer())
    assert seen["template"] == "chart_card"
    assert seen["data"]["values"] == [1.0, 2.0, 3.0]
    assert Path(path).read_bytes().startswith(PNG_MAGIC)


def test_data_story_without_series_falls_back_to_stat(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    _, pid = _seed_post(temp_db, "GDP grew 7.2% — look closer.",
                        meta={"chart": None})       # cached miss: no Claude
    calls = []

    class FakeRenderer:
        def render(self, template, data, brand):
            calls.append(template)
            return PNG_MAGIC + b"x"

    visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer())
    assert calls == ["stat_highlight"]


def test_explicit_chart_template_without_series_autopicks(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    _, pid = _seed_post(temp_db, "No numbers here at all.", fmt="hot_take",
                        meta={"chart": None})
    calls = []

    class FakeRenderer:
        def render(self, template, data, brand):
            calls.append(template)
            return PNG_MAGIC + b"x"

    visuals.generate_for_post(pid, db_path=temp_db, renderer=FakeRenderer(),
                              template="chart_card")
    assert calls == ["insight_card"]       # graceful: no series -> normal card


# ------------------------------------------------------------ font API
def _client(temp_db, monkeypatch, tmp_render):
    from fastapi.testclient import TestClient
    from api import main as api_main
    patch_settings(monkeypatch, api_main, app_password="",
                   supabase_url="", supabase_jwt_secret="")
    patch_settings(monkeypatch, visuals, render_dir=str(tmp_render))
    monkeypatch.setattr(api_main, "DB", temp_db)
    return TestClient(api_main.app)


def test_font_upload_and_delete_roundtrip(temp_db, tmp_path, monkeypatch):
    client = _client(temp_db, monkeypatch, tmp_path)
    acct = client.post("/api/accounts", json={"handle": "brandy"}).json()
    aid = acct["id"]

    r = client.post(f"/api/accounts/{aid}/font", data={"weight": 400},
                    files={"file": ("Brand.ttf", b"\x00\x01\x00\x00" + b"x" * 64,
                                    "font/ttf")})
    assert r.status_code == 200
    assert r.json()["family"] == f"Custom-acct{aid}"
    assert (tmp_path / "fonts" / "custom" / f"acct{aid}-400.ttf").exists()
    assert memory.get_brand_kit(aid, db_path=temp_db)["font_family"] == "custom"

    r = client.delete(f"/api/accounts/{aid}/font")
    assert r.json()["removed"] == 1
    assert not (tmp_path / "fonts" / "custom" / f"acct{aid}-400.ttf").exists()
    assert memory.get_brand_kit(aid, db_path=temp_db)["font_family"] == "sans"


def test_font_upload_rejects_non_font(temp_db, tmp_path, monkeypatch):
    client = _client(temp_db, monkeypatch, tmp_path)
    aid = client.post("/api/accounts", json={"handle": "x"}).json()["id"]
    r = client.post(f"/api/accounts/{aid}/font", data={"weight": 400},
                    files={"file": ("evil.ttf", b"#!/bin/sh echo pwned",
                                    "font/ttf")})
    assert r.status_code == 422
    r = client.post(f"/api/accounts/{aid}/font", data={"weight": 500},
                    files={"file": ("f.ttf", b"\x00\x01\x00\x00" + b"x" * 64,
                                    "font/ttf")})
    assert r.status_code == 422            # only 400/700


# ------------------------------------------------------- real render smoke
node_ready = (shutil.which("node") is not None
              and (Path(__file__).parent.parent / "render" / "node_modules"
                   / "satori").exists())


@pytest.mark.skipif(not node_ready, reason="node or render deps not installed")
def test_real_chart_and_decor_render(temp_db, tmp_path, monkeypatch):
    patch_settings(monkeypatch, visuals, visuals_dir=str(tmp_path),
                   visuals_enabled=True)
    spec = {"kind": "line", "title": "Inflation, six months",
            "labels": ["Jan", "Feb", "Mar", "Apr", "May", "Jun"],
            "values": [6.5, 6.2, 5.7, 5.1, 4.8, 5.4], "unit": "%",
            "source": "CPI"}
    acct, pid = _seed_post(temp_db, "Inflation cooled.", meta={"chart": spec})
    memory.save_brand_kit(acct, {"accent_color": "#10b981"}, db_path=temp_db)
    assert visuals.ensure_service() is True
    path = visuals.generate_for_post(pid, db_path=temp_db)
    data = Path(path).read_bytes()
    assert data.startswith(PNG_MAGIC) and len(data) > 10_000

    # decorated insight card with an icon renders for real too
    pid2 = memory.save_post(acct, "explainer",
                            "Why the court verdict changes everything.",
                            db_path=temp_db)
    path2 = visuals.generate_for_post(pid2, db_path=temp_db)
    assert Path(path2).read_bytes().startswith(PNG_MAGIC)
