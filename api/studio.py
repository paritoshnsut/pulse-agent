"""
studio.py — the internal API behind Pulse Studio ("Mission Control").

Pulse has two faces. The customer app answers "what should I post?" and hides
the machinery. The Studio answers "what is the machine doing and why?" — for
us: every signal's subscores, every draft's full trace, the memory the agent
holds, the voice it measured, the rules it learned. The AI factory with a
glass wall around every machine.

Nothing here computes anything new — every endpoint is a read-only window
over data the pipeline already writes (signals, posts, claude_logs, stances,
predictions, events, style_dna, voice_samples, content graph). Zero Claude
cost; pure SQLite. All routes require the same auth as the app and respect
per-user account ownership.

Built as a router factory so api/main.py stays the only place that owns auth
and DB wiring (no circular imports).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException

from pipeline import memory
from pipeline.memory import get_conn

QUALIFIED = ("FIRE", "WARM", "COOL")
APPROVED = ("approved", "edited", "posted")


def _since(days: int) -> str:
    days = max(1, min(int(days or 1), 90))
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _rows(conn, q: str, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(q, params).fetchall()]


def _n(conn, q: str, params=()) -> int:
    return conn.execute(q, params).fetchone()[0]


def build_router(require_auth: Callable, own_account: Callable,
                 db: Callable) -> APIRouter:
    router = APIRouter(prefix="/api/studio", tags=["studio"])

    # ------------------------------------------------------ mission control
    @router.get("/funnel")
    def funnel(days: int = 1, user: dict = Depends(require_auth)):
        """The whole factory in one view: ingested → scored → qualified →
        drafted → approved → posted, plus spend and source health."""
        since = _since(days)
        with get_conn(db()) as conn:
            tiers = {r["tier"]: r["n"] for r in _rows(
                conn, """SELECT tier, COUNT(*) n FROM signals
                         WHERE created_at >= ? GROUP BY tier""", (since,))}
            stages = [
                {"stage": "ingested", "n": _n(conn,
                    "SELECT COUNT(*) FROM articles WHERE fetched_at >= ?", (since,)),
                 "desc": "articles pulled by the watchers"},
                {"stage": "scored", "n": _n(conn,
                    "SELECT COUNT(*) FROM signals WHERE created_at >= ?", (since,)),
                 "desc": "signals the decision agent judged"},
                {"stage": "qualified", "n": sum(tiers.get(t, 0) for t in QUALIFIED),
                 "desc": "scored above the SKIP line"},
                {"stage": "drafted", "n": _n(conn,
                    "SELECT COUNT(*) FROM posts WHERE created_at >= ?", (since,)),
                 "desc": "drafts generated (news + squeezer + evergreen)"},
                {"stage": "approved", "n": _n(conn,
                    f"""SELECT COUNT(*) FROM posts WHERE created_at >= ?
                        AND status IN {APPROVED}""", (since,)),
                 "desc": "you said yes (approved / edited / posted)"},
                {"stage": "posted", "n": _n(conn,
                    """SELECT COUNT(*) FROM posts WHERE created_at >= ?
                       AND status = 'posted'""", (since,)),
                 "desc": "actually published"},
            ]
            rejected = _n(conn, """SELECT COUNT(*) FROM posts WHERE
                created_at >= ? AND status = 'rejected'""", (since,))
            spend = _rows(conn, """SELECT module, COUNT(*) calls,
                ROUND(SUM(cost_usd), 4) usd FROM claude_logs
                WHERE created_at >= ? GROUP BY module ORDER BY usd DESC""", (since,))
            sources = _rows(conn, """SELECT source, COUNT(*) n,
                MAX(fetched_at) last_seen FROM articles
                WHERE fetched_at >= ? GROUP BY source ORDER BY n DESC""", (since,))
        return {"days": days, "stages": stages, "tiers": tiers,
                "rejected": rejected, "spend": spend,
                "spend_total_usd": round(sum(s["usd"] or 0 for s in spend), 4),
                "sources": sources}

    # ------------------------------------------------------- signal center
    @router.get("/signals")
    def signals(tier: Optional[str] = None, account_id: Optional[int] = None,
                days: int = 3, limit: int = 60,
                user: dict = Depends(require_auth)):
        """Every judged signal with all 7 subscores and the model's reasoning
        — why each story ranked where it did."""
        q = """SELECT s.*, a.title, a.source_name, a.url, a.vertical,
                      a.velocity_hint, ac.handle
               FROM signals s
               JOIN articles a ON a.id = s.article_id
               LEFT JOIN accounts ac ON ac.id = s.account_id
               WHERE s.created_at >= ?"""
        params: list = [_since(days)]
        if tier:
            q += " AND s.tier = ?"
            params.append(tier.upper())
        if account_id:
            q += " AND s.account_id = ?"
            params.append(account_id)
        q += " ORDER BY s.score DESC, s.id DESC LIMIT ?"
        params.append(max(1, min(limit, 200)))
        with get_conn(db()) as conn:
            return _rows(conn, q, params)

    # ------------------------------------------------------- memory center
    @router.get("/memory/{account_id}")
    def memory_center(account_id: int, q: Optional[str] = None,
                      user: dict = Depends(require_auth)):
        """What the agent knows: stances taken, predictions staked, the
        events timeline. Searchable — 'show me everything on AI regulation'."""
        own_account(account_id, user)
        like = f"%{(q or '').strip()}%"
        with get_conn(db()) as conn:
            stances = _rows(conn, """SELECT * FROM stance_history
                WHERE account_id = ? AND (? = '%%' OR topic LIKE ? OR stance LIKE ?)
                ORDER BY id DESC LIMIT 100""", (account_id, like, like, like))
            predictions = _rows(conn, """SELECT * FROM predictions_tracker
                WHERE account_id = ? AND (? = '%%' OR topic LIKE ? OR prediction LIKE ?)
                ORDER BY id DESC LIMIT 100""", (account_id, like, like, like))
            events = _rows(conn, """SELECT * FROM events_timeline
                WHERE (? = '%%' OR topic LIKE ? OR summary LIKE ?)
                ORDER BY id DESC LIMIT 100""", (like, like, like))
            totals = {
                "stances": _n(conn, "SELECT COUNT(*) FROM stance_history WHERE account_id = ?",
                              (account_id,)),
                "predictions": _n(conn, "SELECT COUNT(*) FROM predictions_tracker WHERE account_id = ?",
                                  (account_id,)),
                "open_predictions": _n(conn, """SELECT COUNT(*) FROM predictions_tracker
                    WHERE account_id = ? AND status = 'open'""", (account_id,)),
                "events": _n(conn, "SELECT COUNT(*) FROM events_timeline"),
            }
            topics = _rows(conn, """SELECT topic, COUNT(*) n FROM stance_history
                WHERE account_id = ? GROUP BY topic ORDER BY n DESC LIMIT 15""",
                (account_id,))
        return {"totals": totals, "topics": topics, "stances": stances,
                "predictions": predictions, "events": events}

    # -------------------------------------------------------- voice studio
    @router.get("/voice/{account_id}")
    def voice_studio(account_id: int, user: dict = Depends(require_auth)):
        """The voice, visible: measured fingerprint, judged traits, learned
        preferences, corpus composition. You need to SEE the voice."""
        own_account(account_id, user)
        dna = memory.get_style_dna(account_id, db_path=db())
        with get_conn(db()) as conn:
            kinds = _rows(conn, """SELECT kind, COUNT(*) n FROM voice_samples
                WHERE account_id = ? GROUP BY kind""", (account_id,))
            origins = _rows(conn, """SELECT COALESCE(origin, 'paste') origin,
                COUNT(*) n FROM voice_samples WHERE account_id = ?
                GROUP BY origin ORDER BY n DESC LIMIT 10""", (account_id,))
            best = _rows(conn, """SELECT content, likes, retweets, replies
                FROM voice_samples WHERE account_id = ? AND kind = 'own'
                ORDER BY (COALESCE(likes,0) + 2*COALESCE(retweets,0)
                          + COALESCE(replies,0)) DESC LIMIT 5""", (account_id,))
        if not dna:
            return {"trained": False, "corpus": {"kinds": kinds, "origins": origins}}
        return {"trained": True, "version": dna.get("version"),
                "sample_count": dna.get("sample_count"),
                "updated_at": dna.get("updated_at"),
                "genome_a": dna["genome_a"], "genome_b": dna.get("genome_b"),
                "blend": dna.get("blend"),
                "corpus": {"kinds": kinds, "origins": origins,
                           "top_samples": best}}

    # ----------------------------------------------------- learning center
    @router.get("/learning/{account_id}")
    def learning_center(account_id: int, user: dict = Depends(require_auth)):
        """Did it work, and what did the system change because of it?"""
        own_account(account_id, user)
        from style.learning import correlate, historical_performance
        reviewed = memory.get_reviewed_posts(account_id, db_path=db())
        dna = memory.get_style_dna(account_id, db_path=db())
        learned = (dna or {}).get("genome_a", {}).get("learned_preferences") or {}
        with get_conn(db()) as conn:
            by_status = {r["status"]: r["n"] for r in _rows(conn,
                """SELECT status, COUNT(*) n FROM posts WHERE account_id = ?
                   GROUP BY status""", (account_id,))}
            feedback = _rows(conn, """SELECT f.kind, f.note, f.created_at,
                p.format FROM draft_feedback f JOIN posts p ON p.id = f.post_id
                WHERE f.account_id = ? AND f.note != ''
                ORDER BY f.id DESC LIMIT 25""", (account_id,))
        return {"by_status": by_status, "reviewed": len(reviewed),
                "stats": correlate(reviewed),
                "historical_perf": historical_performance(account_id, db_path=db()),
                "learned_preferences": learned, "recent_feedback": feedback}

    # ------------------------------------------------- generation inspector
    @router.get("/trace/{post_id}")
    def trace(post_id: int, user: dict = Depends(require_auth)):
        """One draft, fully explained: the signal that triggered it (with all
        subscores + reasoning), the source article, the idea/angle it was
        built from, every guard's verdict, the persona score, engagement."""
        post = memory.get_post(post_id, db_path=db())
        if not post:
            raise HTTPException(status_code=404, detail="no such post")
        own_account(post["account_id"], user)
        out = {"post": post,
               "signal": memory.get_signal(post["signal_id"], db_path=db())
               if post.get("signal_id") else None,
               "article": memory.get_article(post["article_id"], db_path=db())
               if post.get("article_id") else None,
               "engagement": memory.get_engagement_for_post(post_id, db_path=db()),
               "pack": None}
        if post.get("pack_id"):
            with get_conn(db()) as conn:
                row = conn.execute("SELECT * FROM content_packs WHERE id = ?",
                                   (post["pack_id"],)).fetchone()
                out["pack"] = dict(row) if row else None
        if out["article"]:
            out["article"].pop("raw_json", None)
        return out

    @router.get("/posts")
    def recent_posts(account_id: Optional[int] = None, limit: int = 50,
                     user: dict = Depends(require_auth)):
        """Recent drafts across every status — the inspector's pick list."""
        if account_id:
            own_account(account_id, user)
        mine = {a["id"] for a in memory.list_active_accounts(
            owner_id=user["id"], db_path=db())}
        posts = memory.get_posts(account_id=account_id, db_path=db())
        return [{k: p.get(k) for k in
                 ("id", "account_id", "format", "status", "persona_score",
                  "created_at", "pack_id", "signal_id")}
                | {"preview": (p.get("content") or "")[:120]}
                for p in posts if p["account_id"] in mine][: max(1, min(limit, 200))]

    # ------------------------------------------------- ingested articles log
    @router.get("/articles")
    def articles_log(source: Optional[str] = None, days: int = 1,
                     limit: int = 100, offset: int = 0,
                     user: dict = Depends(require_auth)):
        """Flat log of every article the watchers pulled in, with source,
        title, URL, vertical, velocity hint, and raw JSON on demand."""
        since = _since(days)
        q = """SELECT id, source, source_name, title, url, vertical,
                      velocity_hint, published_at, fetched_at, raw_json
               FROM articles WHERE fetched_at >= ?"""
        params: list = [since]
        if source:
            q += " AND source = ?"
            params.append(source)
        q += " ORDER BY fetched_at DESC LIMIT ? OFFSET ?"
        params += [max(1, min(limit, 500)), max(0, offset)]
        with get_conn(db()) as conn:
            rows = _rows(conn, q, params)
            total = _n(conn,
                "SELECT COUNT(*) FROM articles WHERE fetched_at >= ?" +
                (" AND source = ?" if source else ""),
                [since] + ([source] if source else []))
            sources = _rows(conn, """SELECT source, COUNT(*) n
                FROM articles WHERE fetched_at >= ?
                GROUP BY source ORDER BY n DESC""", (since,))
        # parse raw_json strings → objects so the client gets real JSON
        for r in rows:
            if r.get("raw_json"):
                try:
                    r["raw_json"] = json.loads(r["raw_json"])
                except Exception:
                    pass
        return {"total": total, "offset": offset, "limit": limit,
                "sources": sources, "articles": rows}

    # ------------------------------------------------- content graph viewer
    @router.get("/graph/{asset_id}")
    def graph(asset_id: int, user: dict = Depends(require_auth)):
        """One asset's full decomposition tree: asset → ideas (with angles)
        → packs → drafts, plus every other node kind."""
        asset = memory.get_content_asset(asset_id, db_path=db())
        if not asset:
            raise HTTPException(status_code=404, detail="no such asset")
        own_account(asset["account_id"], user)
        nodes = memory.get_insights(asset_id, db_path=db())
        by_kind: dict = {}
        for n in nodes:
            by_kind.setdefault(n["kind"], []).append(
                {"text": n["text"], "angles": n["angles"]})
        with get_conn(db()) as conn:
            packs = _rows(conn, """SELECT id, idea, created_at FROM content_packs
                WHERE asset_id = ? ORDER BY id""", (asset_id,))
            for p in packs:
                p["drafts"] = _rows(conn, """SELECT id, format, status,
                    persona_score FROM posts WHERE pack_id = ? ORDER BY id""",
                    (p["id"],))
        asset["excerpt"] = (asset.pop("raw_content") or "")[:600]
        return {"asset": asset, "nodes": by_kind, "packs": packs}

    return router
