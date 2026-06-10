"""
api/main.py — the web app (Sessions 17-26, minus billing). One process serves:

  * the dashboard (api/static/index.html — no build step, see that file)
  * the JSON API under /api/* (everything the CLI + Telegram bot can do)
  * the image cards under /cards/*
  * the always-on scheduler (watchers, scorer, drafter, learning loops) —
    started in the app lifespan, so deploying THIS service deploys everything.

Run locally:   uvicorn api.main:app --reload          (scheduler off by default
                                                       under --reload; set
                                                       SCHEDULER_IN_APP=1)
Run deployed:  uvicorn api.main:app --host 0.0.0.0 --port 8080
               with SCHEDULER_IN_APP=1 (the Dockerfile does this).

AUTH — three modes, auto-selected from env (settings.auth_mode):

  supabase  SUPABASE_URL + SUPABASE_JWT_SECRET set. Real per-user accounts:
            the frontend signs in via Supabase (email+password), gets a JWT,
            and every /api/* call carries it. We verify the JWT locally
            (HS256, audience "authenticated") — no network round-trip.
            ALLOWED_EMAILS restricts who may use the deployment (set it!).
            Personas are owned: accounts created by a user carry their
            owner_id; everyone sees their own + shared (NULL-owner) personas.
  password  Only APP_PASSWORD set: one shared family password exchanged for
            an HMAC token at /api/login. No per-user separation.
  dev       Nothing set: open. Local development only.

The DB module-global below exists so tests can point the whole API at a temp
database; None means settings.db_path, same as everywhere else.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import settings
from pipeline import briefing, memory, poster, timing
from pipeline.evergreen import EvergreenGenerator
from style.dna import StyleDNAExtractor
from style.learning import correlate, historical_performance

logger = logging.getLogger("api")

DB: Optional[str] = None  # tests point this at a temp db
_TOKEN_SALT = b"pulse-agent-v1"

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _db() -> Optional[str]:
    return DB


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def _token() -> str:
    return hmac.new(_TOKEN_SALT, settings.app_password.encode(),
                    hashlib.sha256).hexdigest()


def _verify_supabase_jwt(token: str) -> dict:
    """Validate a Supabase access token locally; returns {id, email}."""
    import jwt as pyjwt

    try:
        claims = pyjwt.decode(token, settings.supabase_jwt_secret,
                              algorithms=["HS256"], audience="authenticated")
    except Exception:  # noqa: BLE001  (expired, bad signature, wrong aud, ...)
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    email = (claims.get("email") or "").lower()
    allowed = settings.allowed_email_set()
    if allowed and email not in allowed:
        raise HTTPException(status_code=403,
                            detail="This email isn't on the allowed list.")
    return {"id": claims.get("sub"), "email": email}


def require_auth(authorization: Optional[str] = Header(default=None)) -> dict:
    """Returns the caller: {id, email} in supabase mode, {id: None} otherwise.
    Endpoints use the id for persona ownership scoping."""
    mode = settings.auth_mode
    if mode == "dev":
        return {"id": None, "email": None}
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization[len("Bearer "):]
    if mode == "supabase":
        return _verify_supabase_jwt(token)
    if not hmac.compare_digest(token, _token()):
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    return {"id": None, "email": None}


# --------------------------------------------------------------------------- #
# App + lifespan (scheduler lives inside the web process)
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI):
    memory.init_db(db_path=_db())
    sched = None
    if os.getenv("SCHEDULER_IN_APP", "0").lower() in ("1", "true", "yes"):
        from scheduler import start_background
        sched = start_background()
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(title="Pulse", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class LoginBody(BaseModel):
    password: str


class AccountBody(BaseModel):
    handle: str
    niche: Optional[str] = None
    topics: list[str] = []
    verticals: list[str] = []
    regions: list[str] = []


class StyleBody(BaseModel):
    posts: list[str]
    blend: float = 0.4


class PostedBody(BaseModel):
    url: Optional[str] = None


class PerfBody(BaseModel):
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    views: int = 0


class WatchBody(BaseModel):
    kind: str
    ref: str
    label: Optional[str] = None
    vertical: Optional[str] = None
    region: Optional[str] = None


class EvergreenBody(BaseModel):
    account_id: int
    topic: Optional[str] = None


# --------------------------------------------------------------------------- #
# Routes — auth + config
# --------------------------------------------------------------------------- #
@app.get("/api/config")
def get_config():
    """Public: tells the frontend which login UI to show. The anon key is
    public by design (it's what every Supabase browser client ships with)."""
    return {
        "auth_mode": settings.auth_mode,
        "supabase_url": settings.supabase_url,
        "supabase_anon_key": settings.supabase_anon_key,
    }


@app.post("/api/login")
def login(body: LoginBody):
    if settings.auth_mode == "supabase":
        raise HTTPException(status_code=400, detail="Use Supabase sign-in")
    if settings.auth_mode == "dev":
        return {"token": "dev"}
    if not hmac.compare_digest(body.password, settings.app_password):
        raise HTTPException(status_code=401, detail="Wrong password")
    return {"token": _token()}


# --------------------------------------------------------------------------- #
# Routes — accounts + voice
# --------------------------------------------------------------------------- #
def _my_accounts(user: dict) -> list[dict]:
    return memory.list_active_accounts(owner_id=user["id"], db_path=_db())


def _own_account(account_id: int, user: dict) -> dict:
    """The account, if this user may touch it (theirs, or shared)."""
    account = memory.get_account(account_id, db_path=_db())
    if not account:
        raise HTTPException(status_code=404, detail="No such account")
    if user["id"] and account.get("owner_id") not in (None, user["id"]):
        raise HTTPException(status_code=403, detail="Not your persona")
    return account


@app.get("/api/accounts")
def list_accounts(user: dict = Depends(require_auth)):
    out = []
    for a in _my_accounts(user):
        dna = memory.get_style_dna(a["id"], db_path=_db())
        out.append({**a, "has_voice": dna is not None,
                    "voice_version": dna["version"] if dna else 0,
                    "has_crowd": bool(dna and dna["genome_b"])})
    return out


@app.post("/api/accounts")
def create_account(body: AccountBody, user: dict = Depends(require_auth)):
    acct_id = memory.upsert_account(
        handle=body.handle.strip().lstrip("@"), niche=body.niche,
        topics=body.topics, verticals=body.verticals or None,
        regions=body.regions or None, owner_id=user["id"], db_path=_db())
    return memory.get_account(acct_id, db_path=_db())


@app.get("/api/accounts/{account_id}/style")
def get_style(account_id: int, user: dict = Depends(require_auth)):
    _own_account(account_id, user)
    dna = memory.get_style_dna(account_id, db_path=_db())
    if not dna:
        raise HTTPException(status_code=404, detail="No voice trained yet")
    return dna


@app.post("/api/accounts/{account_id}/style")
def train_style(account_id: int, body: StyleBody, user: dict = Depends(require_auth)):
    _own_account(account_id, user)
    posts = [p.strip() for p in body.posts if p and p.strip()]
    if len(posts) < 5:
        raise HTTPException(status_code=400,
                            detail="Paste at least 5 posts (50-200 is ideal).")
    genome = StyleDNAExtractor().extract_and_save(
        account_id, posts, blend=body.blend, db_path=_db())
    return {"genome_a": genome, "sample_count": len(posts)}


# --------------------------------------------------------------------------- #
# Routes — the review lane
# --------------------------------------------------------------------------- #
def _own_post(post_id: int, user: dict) -> dict:
    post = memory.get_post(post_id, db_path=_db())
    if not post:
        raise HTTPException(status_code=404, detail="No such draft")
    _own_account(post["account_id"], user)
    return post


@app.get("/api/drafts")
def list_drafts(status: str = "draft", account_id: Optional[int] = None,
                user: dict = Depends(require_auth)):
    mine = {a["id"] for a in _my_accounts(user)}
    posts = memory.get_posts(account_id=account_id,
                             status=None if status == "all" else status,
                             db_path=_db())
    return [p for p in posts if p["account_id"] in mine][:50]


@app.post("/api/drafts/{post_id}/approve")
def approve(post_id: int, user: dict = Depends(require_auth)):
    post = _own_post(post_id, user)
    memory.set_post_status(post_id, "approved", db_path=_db())
    post = memory.get_post(post_id, db_path=_db())
    result = poster.dispatch_approved(post, db_path=_db())
    card = result.get("card")
    return {
        "texts": result["texts"],
        "intent_urls": result["intent_urls"],
        "card_url": f"/cards/{Path(card).name}" if card else None,
        "timing": _safe_timing(post.get("account_id")),
    }


def _safe_timing(account_id: Optional[int]) -> Optional[str]:
    if not account_id:
        return None
    try:
        return timing.describe_windows(account_id, db_path=_db())
    except Exception:  # noqa: BLE001
        return None


@app.post("/api/drafts/{post_id}/reject")
def reject(post_id: int, user: dict = Depends(require_auth)):
    _own_post(post_id, user)
    memory.set_post_status(post_id, "rejected", db_path=_db())
    return {"ok": True}


@app.post("/api/drafts/{post_id}/posted")
def mark_posted(post_id: int, body: PostedBody, user: dict = Depends(require_auth)):
    _own_post(post_id, user)
    memory.mark_posted(post_id, url=body.url, db_path=_db())
    from pipeline.updater import MemoryUpdater
    report = MemoryUpdater().on_posted(post_id, db_path=_db())
    return {"ok": True, "memory": report}


@app.post("/api/drafts/{post_id}/perf")
def log_perf(post_id: int, body: PerfBody, user: dict = Depends(require_auth)):
    _own_post(post_id, user)
    memory.record_engagement(post_id, likes=body.likes, retweets=body.retweets,
                             replies=body.replies, views=body.views, db_path=_db())
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Routes — ideas, briefing, predictions, evergreen
# --------------------------------------------------------------------------- #
@app.get("/api/ideas/{account_id}")
def ideas(account_id: int, user: dict = Depends(require_auth)):
    _own_account(account_id, user)
    return briefing._cool_ideas(account_id, db_path=_db())


@app.get("/api/briefing/{account_id}")
def get_briefing(account_id: int, user: dict = Depends(require_auth)):
    account = _own_account(account_id, user)
    return {"text": briefing.build(account, db_path=_db())}


@app.get("/api/predictions/{account_id}")
def predictions(account_id: int, user: dict = Depends(require_auth)):
    _own_account(account_id, user)
    return memory.get_open_predictions(account_id, db_path=_db())


@app.post("/api/evergreen")
def evergreen(body: EvergreenBody, user: dict = Depends(require_auth)):
    account = _own_account(body.account_id, user)
    draft = EvergreenGenerator(db_path=_db()).generate_for(account, topic=body.topic)
    if not draft or draft.get("empty"):
        raise HTTPException(status_code=400,
                            detail="Nothing to draft — train the voice and build "
                                   "some stance memory first (or give a topic).")
    return memory.get_post(draft["post_id"], db_path=_db())


# --------------------------------------------------------------------------- #
# Routes — analytics + watch list + status
# --------------------------------------------------------------------------- #
@app.get("/api/analytics/{account_id}")
def analytics(account_id: int, user: dict = Depends(require_auth)):
    _own_account(account_id, user)
    reviewed = memory.get_reviewed_posts(account_id, db_path=_db())
    stats = correlate(reviewed)
    windows = timing.best_windows(account_id, db_path=_db())
    return {
        "stats": stats,
        "historical_perf": historical_performance(account_id, db_path=_db()),
        "timing": {**windows, "label": settings.tz_label},
        "open_predictions": len(memory.get_open_predictions(account_id, db_path=_db())),
    }


@app.get("/api/watch", dependencies=[Depends(require_auth)])
def list_watch():
    return memory.get_watch(db_path=_db())


@app.post("/api/watch", dependencies=[Depends(require_auth)])
def add_watch(body: WatchBody):
    wid = memory.add_watch(kind=body.kind, ref=body.ref.strip(), label=body.label,
                           vertical=body.vertical, region=body.region, db_path=_db())
    return {"id": wid}


@app.delete("/api/watch/{watch_id}", dependencies=[Depends(require_auth)])
def delete_watch(watch_id: int):
    memory.remove_watch(watch_id, db_path=_db())
    return {"ok": True}


@app.get("/api/status")
def status(user: dict = Depends(require_auth)):
    mine = {a["id"] for a in _my_accounts(user)}
    drafts = [p for p in memory.get_posts(status="draft", db_path=_db())
              if p["account_id"] in mine]
    outbox = [p for p in memory.get_outbox(db_path=_db()) if p["account_id"] in mine]
    return {
        "accounts": len(mine),
        "pending_drafts": len(drafts),
        "outbox": len(outbox),
        "watch_sources": len(memory.get_watch(db_path=_db())),
        "scheduler_in_app": os.getenv("SCHEDULER_IN_APP", "0") in ("1", "true", "yes"),
        "telegram_configured": bool(settings.telegram_bot_token and settings.telegram_chat_id),
        "auth_enabled": settings.auth_mode != "dev",
        "auth_mode": settings.auth_mode,
        "user_email": user.get("email"),
    }


# --------------------------------------------------------------------------- #
# Static: dashboard + cards. The built React app (frontend/dist, from
# `npm run build`) is preferred; the build-free fallback in api/static still
# works when no build has been run.
# --------------------------------------------------------------------------- #
Path(settings.cards_dir).mkdir(parents=True, exist_ok=True)
app.mount("/cards", StaticFiles(directory=settings.cards_dir), name="cards")

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/", include_in_schema=False)
def index():
    if (FRONTEND_DIST / "index.html").exists():
        return FileResponse(FRONTEND_DIST / "index.html")
    return FileResponse(STATIC_DIR / "index.html")
