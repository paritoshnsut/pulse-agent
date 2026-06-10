"""Supabase-mode auth tests: JWT verification, email allowlist, and per-user
persona ownership. Tokens are minted locally with the same secret the API
verifies against — no network, no real Supabase project needed."""

import time

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from conftest import patch_settings
from pipeline import memory

SECRET = "test-jwt-secret"


def make_token(sub="user-1", email="me@example.com", secret=SECRET, exp_in=3600):
    return pyjwt.encode(
        {"sub": sub, "email": email, "aud": "authenticated",
         "exp": int(time.time()) + exp_in},
        secret, algorithm="HS256")


@pytest.fixture()
def sb(temp_db, monkeypatch):
    """TestClient in supabase mode with two allowed users."""
    import config as config_mod
    from api import main as api_main

    monkeypatch.setattr(api_main, "DB", temp_db)
    for mod in (api_main, config_mod):
        patch_settings(monkeypatch, mod,
                       supabase_url="https://proj.supabase.co",
                       supabase_anon_key="anon-key",
                       supabase_jwt_secret=SECRET,
                       allowed_emails="me@example.com, bhai@example.com",
                       app_password="")
    return TestClient(api_main.app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_config_is_public_and_advertises_mode(sb):
    cfg = sb.get("/api/config").json()
    assert cfg["auth_mode"] == "supabase"
    assert cfg["supabase_url"] == "https://proj.supabase.co"
    assert cfg["supabase_anon_key"] == "anon-key"


def test_jwt_verification(sb):
    assert sb.get("/api/accounts").status_code == 401                      # no token
    assert sb.get("/api/accounts",
                  headers=_auth("garbage")).status_code == 401             # not a jwt
    assert sb.get("/api/accounts",
                  headers=_auth(make_token(secret="wrong"))).status_code == 401
    assert sb.get("/api/accounts",
                  headers=_auth(make_token(exp_in=-100))).status_code == 401  # expired
    assert sb.get("/api/accounts",
                  headers=_auth(make_token())).status_code == 200          # valid


def test_email_allowlist(sb):
    r = sb.get("/api/accounts",
               headers=_auth(make_token(sub="x", email="stranger@example.com")))
    assert r.status_code == 403
    assert "allowed list" in r.json()["detail"]
    assert sb.get("/api/accounts",
                  headers=_auth(make_token(sub="b", email="bhai@example.com"))).status_code == 200


def test_password_login_disabled_in_supabase_mode(sb):
    assert sb.post("/api/login", json={"password": "x"}).status_code == 400


def test_persona_ownership_scoping(sb, temp_db):
    me = _auth(make_token(sub="user-me", email="me@example.com"))
    bhai = _auth(make_token(sub="user-bhai", email="bhai@example.com"))

    mine = sb.post("/api/accounts", headers=me,
                   json={"handle": "econ_take", "niche": "economy"}).json()
    his = sb.post("/api/accounts", headers=bhai,
                  json={"handle": "cricket_take", "niche": "cricket"}).json()

    # each sees only their own personas
    assert [a["handle"] for a in sb.get("/api/accounts", headers=me).json()] == ["econ_take"]
    assert [a["handle"] for a in sb.get("/api/accounts", headers=bhai).json()] == ["cricket_take"]

    # cross-user access to account-scoped resources is blocked
    assert sb.get(f"/api/briefing/{his['id']}", headers=me).status_code == 403
    assert sb.get(f"/api/analytics/{mine['id']}", headers=bhai).status_code == 403

    # drafts are scoped too: a draft on his persona is invisible to me
    pid = memory.save_post(his["id"], "hot_take", "his draft", db_path=temp_db)
    assert sb.get("/api/drafts", headers=me).json() == []
    assert len(sb.get("/api/drafts", headers=bhai).json()) == 1
    assert sb.post(f"/api/drafts/{pid}/reject", headers=me).status_code == 403
    assert sb.post(f"/api/drafts/{pid}/reject", headers=bhai).status_code == 200


def test_shared_legacy_accounts_visible_to_all(sb, temp_db):
    # accounts created before supabase mode (owner_id NULL) stay usable by both
    memory.upsert_account(handle="family_shared", db_path=temp_db)
    me = _auth(make_token(sub="user-me", email="me@example.com"))
    bhai = _auth(make_token(sub="user-bhai", email="bhai@example.com"))
    assert [a["handle"] for a in sb.get("/api/accounts", headers=me).json()] == ["family_shared"]
    assert [a["handle"] for a in sb.get("/api/accounts", headers=bhai).json()] == ["family_shared"]


def test_status_reports_user(sb):
    st = sb.get("/api/status", headers=_auth(make_token())).json()
    assert st["auth_mode"] == "supabase" and st["user_email"] == "me@example.com"
