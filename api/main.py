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

from fastapi import (Depends, FastAPI, File, Form, Header, HTTPException,
                     UploadFile)
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
    kind: Optional[str] = None
    preset: Optional[str] = None  # preset id — seeds the brand kit's visual defaults


class BrandBody(BaseModel):
    banned_words: list[str] = []
    word_swaps: dict[str, str] = {}
    disclaimers: list[str] = []
    cta_text: Optional[str] = None
    cta_url: Optional[str] = None
    website_url: Optional[str] = None
    notes: Optional[str] = None
    # visual identity (VISUALS.md)
    accent_color: Optional[str] = None
    secondary_color: Optional[str] = None
    bg_style: Optional[str] = None      # dark | light | gradient
    font_family: Optional[str] = None   # sans | serif | mono
    watermark_text: Optional[str] = None
    logo_url: Optional[str] = None


class RepurposeBody(BaseModel):
    account_id: int
    text: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None


class StyleBody(BaseModel):
    posts: list[str]
    blend: float = 0.4


class CorpusBody(BaseModel):
    text: str
    kind: str = "own"  # own | inspiration


class ImportVoiceBody(BaseModel):
    url: str
    kind: str = "own"  # own | inspiration


class PostedBody(BaseModel):
    url: Optional[str] = None


class RedoBody(BaseModel):
    instruction: str


class RejectBody(BaseModel):
    reason: Optional[str] = None


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


# Pulse Studio — the internal glass-wall API (api/studio.py). Read-only
# windows over the pipeline's own tables; same auth, same ownership rules.
from api.studio import build_router as _build_studio_router  # noqa: E402

app.include_router(_build_studio_router(require_auth, _own_account, _db))


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
        regions=body.regions or None, owner_id=user["id"], kind=body.kind,
        db_path=_db())
    # a preset seeds the brand kit's visual identity (only if none exists yet)
    if body.preset and not memory.get_brand_kit(acct_id, db_path=_db()):
        from presets import PRESETS
        visual = PRESETS.get(body.preset, {}).get("visual")
        if visual:
            memory.save_brand_kit(acct_id, visual, db_path=_db())
    return memory.get_account(acct_id, db_path=_db())


@app.get("/api/presets")
def get_presets(user: dict = Depends(require_auth)):
    """Starter packs for onboarding any kind of account (public-ish; authed)."""
    from presets import list_presets
    return list_presets()


# --------------------------------------------------------------------------- #
# Routes — brand kit
# --------------------------------------------------------------------------- #
@app.get("/api/accounts/{account_id}/brand")
def get_brand(account_id: int, user: dict = Depends(require_auth)):
    _own_account(account_id, user)
    return memory.get_brand_kit(account_id, db_path=_db()) or {}


@app.post("/api/accounts/{account_id}/brand")
def save_brand(account_id: int, body: BrandBody, user: dict = Depends(require_auth)):
    _own_account(account_id, user)
    memory.save_brand_kit(account_id, body.model_dump(), db_path=_db())
    return {"ok": True}


@app.post("/api/accounts/{account_id}/brand/preview")
def brand_preview(account_id: int, body: BrandBody, user: dict = Depends(require_auth)):
    """Live preview: render a sample card with the (possibly unsaved) brand
    values from the editor, so you see the look before you commit it."""
    account = _own_account(account_id, user)
    from fastapi import Response
    from pipeline import visuals
    brand = visuals.brand_payload(account, body.model_dump())
    png = visuals.SatoriRenderer().render(
        "quote_card",
        {"text": "This is how your branded graphics will look — colors, font, "
                 "and watermark come from your kit."},
        brand)
    if png is None:
        raise HTTPException(status_code=503,
                            detail="render service unavailable — try again shortly")
    return Response(content=png, media_type="image/png")


@app.post("/api/drafts/{post_id}/visual")
def regenerate_visual(post_id: int, template: Optional[str] = None,
                      size: Optional[str] = None,
                      user: dict = Depends(require_auth)):
    """Re-render a draft's visual, optionally as a different template (the
    swap control on the review card) and/or a different canvas: size=square
    (IG feed) or size=story (9:16 reels/stories). Size variants are saved
    alongside the primary visual, never replacing it."""
    _own_post(post_id, user)
    from pipeline.visuals import VALID_SIZES, generate_for_post
    if size and size not in VALID_SIZES:
        raise HTTPException(status_code=422,
                            detail=f"size must be one of {VALID_SIZES}")
    path = generate_for_post(post_id, db_path=_db(), template=template,
                             size=size)
    if not path:
        raise HTTPException(status_code=503, detail="visual generation failed")
    mount = "visuals" if Path(path).parent == Path(settings.visuals_dir) else "cards"
    return {"card_url": f"/{mount}/{Path(path).name}"}


@app.post("/api/drafts/{post_id}/visual/alternates")
def visual_alternates(post_id: int, k: int = 2,
                      user: dict = Depends(require_auth)):
    """The visual A/B control: render up to k alternate approaches (zero
    Claude calls — cached structures + free templates only), ordered by this
    account's Visual Genome. Picking one via the swap control records the
    preference signal."""
    _own_post(post_id, user)
    from pipeline.visuals import generate_alternates
    alts = generate_alternates(post_id, k=max(1, min(k, 4)), db_path=_db())
    return {"alternates": [{"template": a["template"],
                            "card_url": f"/visuals/{a['file']}"}
                           for a in alts]}


# --------------------------------------------------------------------------- #
# Routes — visual references (the V2 design agent's library)
# --------------------------------------------------------------------------- #
@app.get("/api/accounts/{account_id}/refs")
def list_refs(account_id: int, kind: Optional[str] = None,
              user: dict = Depends(require_auth)):
    _own_account(account_id, user)
    return memory.get_visual_refs(account_id, kind=kind, db_path=_db())


@app.post("/api/accounts/{account_id}/refs")
async def add_ref(account_id: int,
                  file: Optional[UploadFile] = File(None),
                  url: Optional[str] = Form(None),
                  notes: str = Form(""),
                  tags: str = Form(""),
                  user: dict = Depends(require_auth)):
    """Add an approved background: an uploaded image OR a URL. Tags/notes are
    what the library backend matches prompts against — describe the mood."""
    _own_account(account_id, user)
    if file is None and not (url or "").strip():
        raise HTTPException(status_code=422, detail="provide a file or a url")
    from pipeline import design
    path = None
    if file is not None:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=422, detail="empty file")
        ext = Path(file.filename or "bg.png").suffix.lower() or ".png"
        if ext not in (".png", ".jpg", ".jpeg", ".webp"):
            raise HTTPException(status_code=422, detail="png/jpg/webp only")
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S%f")
        p = design.refs_dir() / f"ref-{account_id}-{stamp}{ext}"
        p.write_bytes(data)
        path = str(p)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    ref_id = memory.add_visual_ref(account_id, kind="background", path=path,
                                   url=(url or "").strip() or None,
                                   notes=notes, tags=tag_list, db_path=_db())
    return {"ok": True, "id": ref_id}


@app.delete("/api/accounts/{account_id}/refs/{ref_id}")
def delete_ref(account_id: int, ref_id: int,
               user: dict = Depends(require_auth)):
    _own_account(account_id, user)
    mine = {r["id"] for r in memory.get_visual_refs(account_id, db_path=_db())}
    if ref_id not in mine:
        raise HTTPException(status_code=404, detail="no such reference")
    memory.remove_visual_ref(ref_id, db_path=_db())
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Routes — custom brand fonts (VISUALS.md: beyond the three bundled families)
# --------------------------------------------------------------------------- #
@app.post("/api/accounts/{account_id}/font")
async def upload_font(account_id: int,
                      file: UploadFile = File(...),
                      weight: int = Form(400),
                      user: dict = Depends(require_auth)):
    """Upload a brand TTF (regular=400 and/or bold=700). Saved by convention
    as render/fonts/custom/acct{id}-{weight}.ttf; the render service loads it
    per render, so it takes effect immediately. Sets font_family='custom'."""
    _own_account(account_id, user)
    if weight not in (400, 700):
        raise HTTPException(status_code=422, detail="weight must be 400 or 700")
    ext = Path(file.filename or "font.ttf").suffix.lower()
    if ext not in (".ttf", ".otf"):
        raise HTTPException(status_code=422, detail="ttf/otf only")
    data = await file.read()
    # every TrueType/OpenType file starts with one of these magics
    if len(data) < 12 or data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        raise HTTPException(status_code=422, detail="not a valid font file")
    from pipeline.visuals import custom_font_dir
    d = custom_font_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"acct{account_id}-{weight}.ttf").write_bytes(data)
    kit = memory.get_brand_kit(account_id, db_path=_db()) or {}
    kit["font_family"] = "custom"
    memory.save_brand_kit(account_id, kit, db_path=_db())
    return {"ok": True, "family": f"Custom-acct{account_id}", "weight": weight}


@app.delete("/api/accounts/{account_id}/font")
def delete_font(account_id: int, user: dict = Depends(require_auth)):
    """Remove uploaded brand fonts and fall back to the bundled stack."""
    _own_account(account_id, user)
    from pipeline.visuals import custom_font_dir
    removed = 0
    for w in (400, 700):
        p = custom_font_dir() / f"acct{account_id}-{w}.ttf"
        if p.exists():
            p.unlink()
            removed += 1
    kit = memory.get_brand_kit(account_id, db_path=_db())
    if kit and kit.get("font_family") == "custom":
        kit["font_family"] = "sans"
        memory.save_brand_kit(account_id, kit, db_path=_db())
    return {"ok": True, "removed": removed}


# --------------------------------------------------------------------------- #
# Routes — Content Squeezer (repurpose)
# --------------------------------------------------------------------------- #
@app.post("/api/repurpose")
def repurpose(body: RepurposeBody, user: dict = Depends(require_auth)):
    account = _own_account(body.account_id, user)
    from pipeline.repurpose import ContentSqueezer
    out = ContentSqueezer(db_path=_db()).squeeze(
        account, text=body.text, url=body.url, title=body.title)
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error"))
    return out


@app.get("/api/packs/{pack_id}")
def pack(pack_id: int, user: dict = Depends(require_auth)):
    posts = memory.get_pack_posts(pack_id, db_path=_db())
    if posts:
        _own_account(posts[0]["account_id"], user)
    return posts


@app.get("/api/accounts/{account_id}/assets")
def list_assets(account_id: int, user: dict = Depends(require_auth)):
    """The content library: everything this account ever squeezed."""
    _own_account(account_id, user)
    return memory.list_content_assets(account_id, db_path=_db())


@app.post("/api/accounts/{account_id}/assets/{asset_id}/squeeze")
def resqueeze_asset(account_id: int, asset_id: int,
                    user: dict = Depends(require_auth)):
    """Re-squeeze a library asset — fresh decomposition, fresh packs, with
    whatever the voice genome has learned since the asset was filed."""
    account = _own_account(account_id, user)
    from pipeline.repurpose import ContentSqueezer
    out = ContentSqueezer(db_path=_db()).squeeze(account, asset_id=asset_id)
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error"))
    return out


@app.get("/api/accounts/{account_id}/style")
def get_style(account_id: int, user: dict = Depends(require_auth)):
    _own_account(account_id, user)
    dna = memory.get_style_dna(account_id, db_path=_db())
    if not dna:
        raise HTTPException(status_code=404, detail="No voice trained yet")
    return dna


@app.post("/api/accounts/{account_id}/style")
def train_style(account_id: int, body: StyleBody, user: dict = Depends(require_auth)):
    """Legacy one-shot trainer; now also files the posts into the corpus so
    nothing pasted is ever lost. Prefer the /corpus + /retrain endpoints."""
    _own_account(account_id, user)
    posts = [p.strip() for p in body.posts if p and p.strip()]
    if len(posts) < 5:
        raise HTTPException(status_code=400,
                            detail="Paste at least 5 posts (50-200 is ideal).")
    memory.add_voice_samples(account_id,
                             [{"content": p, "kind": "own"} for p in posts],
                             db_path=_db())
    genome = StyleDNAExtractor().extract_and_save(
        account_id, posts, blend=body.blend, db_path=_db())
    return {"genome_a": genome, "sample_count": len(posts)}


# --------------------------------------------------------------------------- #
# Routes — voice corpus (the living training set)
# --------------------------------------------------------------------------- #
@app.get("/api/accounts/{account_id}/corpus")
def corpus_stats(account_id: int, user: dict = Depends(require_auth)):
    _own_account(account_id, user)
    from style.corpus import CorpusManager
    mgr = CorpusManager(db_path=_db())
    account = memory.get_account(account_id, db_path=_db())
    mgr.suggest(account)  # cheap, deterministic; keeps suggestions fresh
    dna = memory.get_style_dna(account_id, db_path=_db())
    return {
        "counts": memory.count_voice_samples(account_id, db_path=_db()),
        "voice_version": dna["version"] if dna else 0,
        "trained_on": dna["sample_count"] if dna else 0,
        "suggestions": [
            {"id": s["id"], "title": s["title"], "source": s.get("source_name"),
             "reason": s["reason"], "url": s.get("url")}
            for s in memory.get_corpus_suggestions(account_id, db_path=_db())
        ],
    }


@app.post("/api/accounts/{account_id}/corpus")
def corpus_add(account_id: int, body: CorpusBody, user: dict = Depends(require_auth)):
    _own_account(account_id, user)
    if body.kind not in ("own", "inspiration"):
        raise HTTPException(status_code=400, detail="kind must be own|inspiration")
    from style.corpus import CorpusManager
    return CorpusManager(db_path=_db()).add(account_id, body.text, kind=body.kind)


@app.post("/api/accounts/{account_id}/import-voice")
def import_voice(account_id: int, body: ImportVoiceBody,
                 user: dict = Depends(require_auth)):
    """One-paste onboarding: a blog/Substack/Medium/RSS URL → their writing
    becomes the corpus, the voice trains itself, the niche fills itself."""
    _own_account(account_id, user)
    from style.importer import import_voice as run_import
    out = run_import(account_id, body.url, kind=body.kind, db_path=_db())
    if not out.get("ok"):
        raise HTTPException(status_code=422, detail=out.get("error", "import failed"))
    return out


@app.post("/api/accounts/{account_id}/retrain")
def corpus_retrain(account_id: int, user: dict = Depends(require_auth)):
    _own_account(account_id, user)
    from style.corpus import CorpusManager
    try:
        out = CorpusManager(db_path=_db()).retrain(account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return out


@app.post("/api/suggestions/{suggestion_id}/{verdict}")
def corpus_suggestion_verdict(suggestion_id: int, verdict: str, account_id: int,
                              user: dict = Depends(require_auth)):
    _own_account(account_id, user)
    if verdict not in ("accept", "reject"):
        raise HTTPException(status_code=400, detail="verdict must be accept|reject")
    from style.corpus import CorpusManager
    mgr = CorpusManager(db_path=_db())
    if verdict == "accept":
        try:
            mgr.accept_suggestion(suggestion_id, account_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
    else:
        mgr.reject_suggestion(suggestion_id)
    return {"ok": True}


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
    posts = [p for p in posts if p["account_id"] in mine][:50]
    # "why this draft": the signal's verdict + the story behind it, so the
    # review card explains itself instead of presenting text from nowhere
    for p in posts:
        why = {}
        if p.get("signal_id"):
            s = memory.get_signal(p["signal_id"], db_path=_db()) or {}
            why = {k: s.get(k) for k in ("score", "tier", "angle", "topic")}
        if p.get("article_id"):
            a = memory.get_article(p["article_id"], db_path=_db()) or {}
            why["source_name"] = a.get("source_name")
            why["source_title"] = a.get("title")
            why["source_url"] = a.get("url")
        p["why"] = {k: v for k, v in why.items() if v}
    return posts


@app.post("/api/drafts/{post_id}/approve")
def approve(post_id: int, user: dict = Depends(require_auth)):
    post = _own_post(post_id, user)
    memory.set_post_status(post_id, "approved", db_path=_db())
    post = memory.get_post(post_id, db_path=_db())
    result = poster.dispatch_approved(post, db_path=_db())
    card = result.get("card")
    card_url = None
    visual_urls: list[str] = []
    if card:
        # visuals (Satori) and cards (Pillow fallback) live on different mounts
        mount = "visuals" if Path(card).parent == Path(settings.visuals_dir) else "cards"
        card_url = f"/{mount}/{Path(card).name}"
        fresh = memory.get_post(post_id, db_path=_db()) or {}
        slides = (fresh.get("meta_json") or {}).get("visual_slides") or []
        visual_urls = [f"/visuals/{n}" for n in slides] or [card_url]
    return {
        "texts": result["texts"],
        "intent_urls": result["intent_urls"],
        "card_url": card_url,
        "visual_urls": visual_urls,
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
def reject(post_id: int, body: RejectBody = RejectBody(),
           user: dict = Depends(require_auth)):
    _own_post(post_id, user)
    memory.set_post_status(post_id, "rejected", db_path=_db())
    if body.reason and body.reason.strip():
        from pipeline.feedback import record_reject
        record_reject(post_id, body.reason, db_path=_db())
    return {"ok": True}


@app.post("/api/drafts/{post_id}/redo")
def redo(post_id: int, body: RedoBody, user: dict = Depends(require_auth)):
    _own_post(post_id, user)
    from pipeline.feedback import regenerate_with_steer
    r = regenerate_with_steer(post_id, body.instruction, db_path=_db())
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r.get("error"))
    return memory.get_post(post_id, db_path=_db())


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
    from style.corpus import file_posted_draft
    filed = file_posted_draft(post_id, db_path=_db())
    return {"ok": True, "filed_to_corpus": filed}


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


@app.get("/api/dashboard")
def dashboard(user: dict = Depends(require_auth)):
    """Everything the home screen needs in one call: today's agent activity,
    setup progress, and recent drafts — the 'you can see it working' view."""
    accounts = _my_accounts(user)
    ids = [a["id"] for a in accounts]
    counts = memory.dashboard_counts(ids, db_path=_db())
    has_voice = any(memory.get_style_dna(i, db_path=_db()) for i in ids)
    has_brand = any(memory.get_brand_kit(i, db_path=_db()) for i in ids)
    recent = [p for p in memory.get_posts(db_path=_db()) if p["account_id"] in set(ids)][:6]
    return {
        **counts,
        "pending_drafts": len([p for p in memory.get_posts(status="draft", db_path=_db())
                               if p["account_id"] in set(ids)]),
        "outbox": len([p for p in memory.get_outbox(db_path=_db())
                       if p["account_id"] in set(ids)]),
        "watch_sources": len(memory.get_watch(db_path=_db())),
        "spend_today_usd": memory.cost_today(db_path=_db()),
        "daily_budget_usd": settings.daily_budget_usd,
        "scheduler_in_app": os.getenv("SCHEDULER_IN_APP", "0") in ("1", "true", "yes"),
        "telegram_configured": bool(settings.telegram_bot_token and settings.telegram_chat_id),
        "setup": {
            "account": len(accounts) > 0,
            "voice": has_voice,
            "brand": has_brand,
            "watching": len(memory.get_watch(db_path=_db())) > 0,
            "telegram": bool(settings.telegram_bot_token and settings.telegram_chat_id),
        },
        "recent": [{"id": p["id"], "format": p["format"], "status": p["status"],
                    "created_at": p["created_at"],
                    "content": p["content"][:140]} for p in recent],
    }


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
        "spend_today_usd": memory.cost_today(db_path=_db()),
        "daily_budget_usd": settings.daily_budget_usd,
    }


# --------------------------------------------------------------------------- #
# Static: dashboard + cards. The built React app (frontend/dist, from
# `npm run build`) is preferred; the build-free fallback in api/static still
# works when no build has been run.
# --------------------------------------------------------------------------- #
Path(settings.cards_dir).mkdir(parents=True, exist_ok=True)
app.mount("/cards", StaticFiles(directory=settings.cards_dir), name="cards")
Path(settings.visuals_dir).mkdir(parents=True, exist_ok=True)
app.mount("/visuals", StaticFiles(directory=settings.visuals_dir), name="visuals")

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/", include_in_schema=False)
def index():
    if (FRONTEND_DIST / "index.html").exists():
        return FileResponse(FRONTEND_DIST / "index.html")
    return FileResponse(STATIC_DIR / "index.html")
