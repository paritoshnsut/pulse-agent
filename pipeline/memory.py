"""
memory.py — the only module that touches the database.

Thin, dependency-free (stdlib sqlite3) read/write layer over schema.sql.
Everything else in the pipeline goes through these functions so the storage
choice (SQLite now, Postgres later) stays swappable behind one interface.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from config import settings


def _now() -> str:
    """Current UTC time as an ISO8601 string (the format stored everywhere)."""
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    """Connection context manager with dict-like rows and FK enforcement.

    Concurrency posture (single-container: web + API + watchers + telegram all
    share one SQLite file). WAL is already on (set persistently in schema.sql),
    so readers never block the writer. The piece that matters per-connection is
    busy_timeout: without it a write that collides with another write throws
    'database is locked' immediately; with it, the transaction waits and
    (because we never hold a write open across a Claude call — generation
    happens outside the connection) almost always wins. synchronous=NORMAL is
    the safe, fast pairing with WAL.
    """
    conn = sqlite3.connect(db_path or settings.db_path,
                           timeout=settings.db_busy_timeout_s)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {int(settings.db_busy_timeout_s * 1000)}")
    conn.execute("PRAGMA synchronous = NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Additive auto-migration for older DBs. Adding nullable columns is
    non-breaking (CLAUDE.md rule #7)."""
    art_cols = {r["name"] for r in conn.execute("PRAGMA table_info(articles)")}
    for col, decl in (("vertical", "TEXT"), ("region", "TEXT"), ("velocity_hint", "REAL")):
        if col not in art_cols:
            conn.execute(f"ALTER TABLE articles ADD COLUMN {col} {decl}")
    acct_cols = {r["name"] for r in conn.execute("PRAGMA table_info(accounts)")}
    for col, decl in (("verticals", "TEXT"), ("regions", "TEXT"),
                      ("active", "INTEGER NOT NULL DEFAULT 1"),
                      ("owner_id", "TEXT"),  # supabase user id; NULL = shared
                      ("kind", "TEXT NOT NULL DEFAULT 'commentator'")):
        if col not in acct_cols:
            conn.execute(f"ALTER TABLE accounts ADD COLUMN {col} {decl}")
    post_cols = {r["name"] for r in conn.execute("PRAGMA table_info(posts)")}
    for col in ("posted_at", "posted_url"):
        if col not in post_cols:
            conn.execute(f"ALTER TABLE posts ADD COLUMN {col} TEXT")
    if "pack_id" not in post_cols:
        conn.execute("ALTER TABLE posts ADD COLUMN pack_id INTEGER")
    sig_cols = {r["name"] for r in conn.execute("PRAGMA table_info(signals)")}
    for col in ("topic", "format"):
        if col not in sig_cols:
            conn.execute(f"ALTER TABLE signals ADD COLUMN {col} TEXT")
    for col in ("corroboration", "memory_leverage"):
        if col not in sig_cols:
            conn.execute(f"ALTER TABLE signals ADD COLUMN {col} REAL")
    pred_cols = {r["name"] for r in conn.execute("PRAGMA table_info(predictions_tracker)")}
    if pred_cols and "last_checked_at" not in pred_cols:
        conn.execute("ALTER TABLE predictions_tracker ADD COLUMN last_checked_at TEXT")
    vs_cols = {r["name"] for r in conn.execute("PRAGMA table_info(voice_samples)")}
    if vs_cols and "source" not in vs_cols:
        conn.execute("ALTER TABLE voice_samples ADD COLUMN source TEXT")
    bk_cols = {r["name"] for r in conn.execute("PRAGMA table_info(brand_kit)")}
    if bk_cols:
        for col in ("accent_color", "secondary_color", "bg_style", "font_family",
                    "watermark_text", "logo_url"):
            if col not in bk_cols:
                conn.execute(f"ALTER TABLE brand_kit ADD COLUMN {col} TEXT")


def init_db(db_path: Optional[str] = None, schema_path: Optional[str] = None) -> None:
    """Create all tables from schema.sql. Idempotent (schema uses IF NOT EXISTS)."""
    sql = Path(schema_path or settings.schema_path).read_text(encoding="utf-8")
    with get_conn(db_path) as conn:
        conn.executescript(sql)
        _ensure_columns(conn)


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #
def upsert_account(
    handle: str,
    platform: str = "twitter",
    niche: Optional[str] = None,
    topics: Optional[list[str]] = None,
    verticals: Optional[list[str]] = None,
    regions: Optional[list[str]] = None,
    owner_id: Optional[str] = None,
    kind: Optional[str] = None,
    db_path: Optional[str] = None,
) -> int:
    """Insert an account or return the existing id for (handle, platform).
    On an existing row, refresh fields if given. owner_id is the Supabase user
    id (NULL = shared). kind is commentator|brand|creator|... (flavors the
    decision agent's framing)."""
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "SELECT id FROM accounts WHERE handle = ? AND platform = ?",
            (handle, platform),
        )
        row = cur.fetchone()
        if row:
            conn.execute(
                """UPDATE accounts SET
                     niche = COALESCE(?, niche),
                     topics = COALESCE(?, topics),
                     verticals = COALESCE(?, verticals),
                     regions = COALESCE(?, regions),
                     owner_id = COALESCE(?, owner_id),
                     kind = COALESCE(?, kind)
                   WHERE id = ?""",
                (
                    niche,
                    json.dumps(topics) if topics is not None else None,
                    json.dumps(verticals) if verticals is not None else None,
                    json.dumps(regions) if regions is not None else None,
                    owner_id, kind,
                    row["id"],
                ),
            )
            return row["id"]
        cur = conn.execute(
            """INSERT INTO accounts
               (handle, platform, niche, topics, verticals, regions, owner_id,
                kind, active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (
                handle, platform, niche,
                json.dumps(topics or []),
                json.dumps(verticals) if verticals is not None else None,
                json.dumps(regions) if regions is not None else None,
                owner_id, kind or "commentator",
                _now(),
            ),
        )
        return cur.lastrowid


def _parse_account(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in ("topics", "verticals", "regions"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (json.JSONDecodeError, TypeError):
                d[k] = []
        else:
            d[k] = [] if k != "topics" else d.get(k)
    return d


def get_account(account_id: int, db_path: Optional[str] = None) -> Optional[dict]:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return _parse_account(row) if row else None


def list_active_accounts(owner_id: Optional[str] = None,
                         db_path: Optional[str] = None) -> list[dict]:
    """All active accounts; with owner_id, only that user's plus shared
    (NULL-owner) rows — the multi-user scoping used by the web API."""
    q = "SELECT * FROM accounts WHERE active = 1"
    params: list[Any] = []
    if owner_id is not None:
        q += " AND (owner_id = ? OR owner_id IS NULL)"
        params.append(owner_id)
    q += " ORDER BY id"
    with get_conn(db_path) as conn:
        return [_parse_account(r) for r in conn.execute(q, params).fetchall()]


# --------------------------------------------------------------------------- #
# Articles
# --------------------------------------------------------------------------- #
def insert_article(article: dict[str, Any], db_path: Optional[str] = None) -> tuple[int, bool]:
    """
    Insert a normalized article. Dedup is by URL: if the URL already exists the
    insert is skipped and the existing id is returned.

    Returns (article_id, is_new).
    """
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO articles
               (source, source_name, vertical, region, url, title, description,
                content, author, published_at, fetched_at, velocity_hint, raw_json, processed)
               VALUES (:source, :source_name, :vertical, :region, :url, :title,
                       :description, :content, :author, :published_at, :fetched_at,
                       :velocity_hint, :raw_json, 0)
               ON CONFLICT(url) DO NOTHING""",
            {
                "source": article["source"],
                "source_name": article.get("source_name"),
                "vertical": article.get("vertical"),
                "region": article.get("region"),
                "url": article["url"],
                "title": article["title"],
                "description": article.get("description"),
                "content": article.get("content"),
                "author": article.get("author"),
                "published_at": article.get("published_at"),
                "fetched_at": article.get("fetched_at") or _now(),
                "velocity_hint": article.get("velocity_hint"),
                "raw_json": json.dumps(article.get("raw_json", {})),
            },
        )
        if cur.rowcount and cur.lastrowid:
            return cur.lastrowid, True
        existing = conn.execute(
            "SELECT id FROM articles WHERE url = ?", (article["url"],)
        ).fetchone()
        return existing["id"], False


def get_article(article_id: int, db_path: Optional[str] = None) -> Optional[dict]:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        return dict(row) if row else None


def set_article_content(article_id: int, content: str,
                        db_path: Optional[str] = None) -> None:
    """Backfill an article's content (e.g. a fetched YouTube transcript)."""
    with get_conn(db_path) as conn:
        conn.execute("UPDATE articles SET content = ? WHERE id = ?",
                     (content, article_id))


def get_unprocessed_articles(limit: int = 50, db_path: Optional[str] = None) -> list[dict]:
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """SELECT * FROM articles WHERE processed = 0
               ORDER BY published_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_processed(article_id: int, db_path: Optional[str] = None) -> None:
    with get_conn(db_path) as conn:
        conn.execute("UPDATE articles SET processed = 1 WHERE id = ?", (article_id,))


def get_unscored_for_account(
    account: dict, limit: int = 40, db_path: Optional[str] = None
) -> list[dict]:
    """
    Articles this specific account hasn't scored yet, filtered to its verticals
    and regions. This is the multi-account queue: each persona drains only the
    lanes it covers, and never re-scores. An account with empty verticals/regions
    sees everything.
    """
    verticals = account.get("verticals") or []
    regions = account.get("regions") or []
    clauses = ["a.id NOT IN (SELECT article_id FROM scored_articles WHERE account_id = ?)"]
    params: list[Any] = [account["id"]]
    if verticals:
        clauses.append("a.vertical IN (%s)" % ",".join("?" * len(verticals)))
        params += verticals
    if regions:
        clauses.append("(a.region IN (%s) OR a.region IS NULL)" % ",".join("?" * len(regions)))
        params += regions
    sql = ("SELECT a.* FROM articles a WHERE " + " AND ".join(clauses)
           + " ORDER BY a.published_at DESC LIMIT ?")
    params.append(limit)
    with get_conn(db_path) as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def mark_scored(account_id: int, article_id: int, db_path: Optional[str] = None) -> None:
    """Record that an account has scored an article (idempotent)."""
    with get_conn(db_path) as conn:
        conn.execute(
            """INSERT INTO scored_articles (account_id, article_id, created_at)
               VALUES (?, ?, ?) ON CONFLICT DO NOTHING""",
            (account_id, article_id, _now()),
        )


# --------------------------------------------------------------------------- #
# Signals
# --------------------------------------------------------------------------- #
def insert_signal(signal: dict[str, Any], db_path: Optional[str] = None) -> int:
    """Upsert a signal for (article_id, account_id); re-scoring overwrites."""
    cols = ("article_id", "account_id", "score", "tier", "velocity", "relevance",
            "corroboration", "reaction_potential", "memory_leverage",
            "window_urgency", "historical_perf", "angle", "topic", "format",
            "reasoning")
    params = {c: signal.get(c) for c in cols}
    params["created_at"] = signal.get("created_at") or _now()
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO signals
               (article_id, account_id, score, tier, velocity, relevance,
                corroboration, reaction_potential, memory_leverage,
                window_urgency, historical_perf, angle, topic, format,
                reasoning, created_at)
               VALUES (:article_id, :account_id, :score, :tier, :velocity,
                       :relevance, :corroboration, :reaction_potential,
                       :memory_leverage, :window_urgency, :historical_perf,
                       :angle, :topic, :format, :reasoning, :created_at)
               ON CONFLICT(article_id, account_id) DO UPDATE SET
                   score=excluded.score, tier=excluded.tier,
                   velocity=excluded.velocity, relevance=excluded.relevance,
                   corroboration=excluded.corroboration,
                   reaction_potential=excluded.reaction_potential,
                   memory_leverage=excluded.memory_leverage,
                   window_urgency=excluded.window_urgency,
                   historical_perf=excluded.historical_perf,
                   angle=excluded.angle, topic=excluded.topic,
                   format=excluded.format, reasoning=excluded.reasoning,
                   created_at=excluded.created_at""",
            params,
        )
        return cur.lastrowid


def get_signal(signal_id: int, db_path: Optional[str] = None) -> Optional[dict]:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
        return dict(row) if row else None


def get_signals_by_tier(tier: str, db_path: Optional[str] = None) -> list[dict]:
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """SELECT s.*, a.title, a.url, a.source_name, a.source,
                      a.description, a.vertical, a.region
               FROM signals s JOIN articles a ON a.id = s.article_id
               WHERE s.tier = ? ORDER BY s.score DESC""",
            (tier,),
        ).fetchall()
        return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Brand kit (per-account content rules) + content packs (repurpose runs)
# --------------------------------------------------------------------------- #
_BRAND_JSON = ("banned_words", "word_swaps", "disclaimers")


def save_brand_kit(account_id: int, kit: dict, db_path: Optional[str] = None) -> None:
    """Upsert the brand kit for an account. JSON fields stored as text.
    Visual identity fields (accent/bg/font/watermark/logo) feed VISUALS.md."""
    now = _now()
    vals = {
        "banned_words": json.dumps(kit.get("banned_words") or []),
        "word_swaps": json.dumps(kit.get("word_swaps") or {}),
        "disclaimers": json.dumps(kit.get("disclaimers") or []),
        "cta_text": kit.get("cta_text"), "cta_url": kit.get("cta_url"),
        "website_url": kit.get("website_url"), "notes": kit.get("notes"),
        "accent_color": kit.get("accent_color"),
        "secondary_color": kit.get("secondary_color"),
        "bg_style": kit.get("bg_style"), "font_family": kit.get("font_family"),
        "watermark_text": kit.get("watermark_text"), "logo_url": kit.get("logo_url"),
    }
    with get_conn(db_path) as conn:
        conn.execute(
            """INSERT INTO brand_kit
               (account_id, banned_words, word_swaps, disclaimers, cta_text,
                cta_url, website_url, notes, accent_color, secondary_color,
                bg_style, font_family, watermark_text, logo_url,
                created_at, updated_at)
               VALUES (:aid, :banned_words, :word_swaps, :disclaimers, :cta_text,
                       :cta_url, :website_url, :notes, :accent_color,
                       :secondary_color, :bg_style, :font_family,
                       :watermark_text, :logo_url, :now, :now)
               ON CONFLICT(account_id) DO UPDATE SET
                   banned_words=excluded.banned_words, word_swaps=excluded.word_swaps,
                   disclaimers=excluded.disclaimers, cta_text=excluded.cta_text,
                   cta_url=excluded.cta_url, website_url=excluded.website_url,
                   notes=excluded.notes, accent_color=excluded.accent_color,
                   secondary_color=excluded.secondary_color,
                   bg_style=excluded.bg_style, font_family=excluded.font_family,
                   watermark_text=excluded.watermark_text,
                   logo_url=excluded.logo_url, updated_at=excluded.updated_at""",
            {"aid": account_id, "now": now, **vals},
        )


def get_brand_kit(account_id: int, db_path: Optional[str] = None) -> Optional[dict]:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM brand_kit WHERE account_id = ?",
                           (account_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        for k in _BRAND_JSON:
            try:
                d[k] = json.loads(d[k]) if d[k] else ([] if k != "word_swaps" else {})
            except (json.JSONDecodeError, TypeError):
                d[k] = [] if k != "word_swaps" else {}
        return d


def create_content_pack(account_id: int, source_title: Optional[str],
                        source_url: Optional[str], source_excerpt: Optional[str],
                        db_path: Optional[str] = None) -> int:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO content_packs
               (account_id, source_title, source_url, source_excerpt, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (account_id, source_title, source_url, source_excerpt, _now()),
        )
        return cur.lastrowid


def set_post_pack(post_id: int, pack_id: int, db_path: Optional[str] = None) -> None:
    with get_conn(db_path) as conn:
        conn.execute("UPDATE posts SET pack_id = ? WHERE id = ?", (pack_id, post_id))


def get_pack_posts(pack_id: int, db_path: Optional[str] = None) -> list[dict]:
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM posts WHERE pack_id = ? ORDER BY id", (pack_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["meta_json"] = json.loads(d["meta_json"]) if d["meta_json"] else {}
            out.append(d)
        return out


# --------------------------------------------------------------------------- #
# Voice corpus (persistent training data) + corpus suggestions
# --------------------------------------------------------------------------- #
def _content_hash(content: str) -> str:
    import hashlib
    return hashlib.sha256(content.strip().lower().encode("utf-8")).hexdigest()


def add_voice_samples(account_id: int, items: list[dict],
                      db_path: Optional[str] = None) -> dict:
    """Add samples to the corpus. Each item: {content, kind?, origin?, likes?,
    retweets?, replies?}. Deduplicated per account by content hash — re-pasting
    the same tweet is a no-op. Returns {"added": n, "duplicates": m}."""
    added = dup = 0
    with get_conn(db_path) as conn:
        for it in items:
            content = (it.get("content") or "").strip()
            if not content:
                continue
            cur = conn.execute(
                """INSERT INTO voice_samples
                   (account_id, kind, content, content_hash, origin, source,
                    likes, retweets, replies, active, added_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                   ON CONFLICT(account_id, content_hash) DO NOTHING""",
                (account_id, it.get("kind") or "own", content,
                 _content_hash(content), it.get("origin") or "manual",
                 it.get("source"), it.get("likes"), it.get("retweets"),
                 it.get("replies"), _now()),
            )
            added += int(bool(cur.rowcount))
            dup += int(not cur.rowcount)
    return {"added": added, "duplicates": dup}


def get_voice_samples(account_id: int, kind: Optional[str] = None,
                      db_path: Optional[str] = None) -> list[dict]:
    q = "SELECT * FROM voice_samples WHERE account_id = ? AND active = 1"
    params: list[Any] = [account_id]
    if kind:
        q += " AND kind = ?"; params.append(kind)
    q += " ORDER BY added_at"
    with get_conn(db_path) as conn:
        return [dict(r) for r in conn.execute(q, params).fetchall()]


def count_voice_samples(account_id: int, db_path: Optional[str] = None) -> dict:
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """SELECT kind, COUNT(*) AS n FROM voice_samples
               WHERE account_id = ? AND active = 1 GROUP BY kind""",
            (account_id,),
        ).fetchall()
    counts = {r["kind"]: r["n"] for r in rows}
    return {"own": counts.get("own", 0), "inspiration": counts.get("inspiration", 0)}


def insert_corpus_suggestion(account_id: int, article_id: int, reason: str,
                             db_path: Optional[str] = None) -> bool:
    """True if newly suggested; False if this article was already surfaced."""
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO corpus_suggestions
               (account_id, article_id, reason, status, created_at)
               VALUES (?, ?, ?, 'pending', ?)
               ON CONFLICT(account_id, article_id) DO NOTHING""",
            (account_id, article_id, reason, _now()),
        )
        return bool(cur.rowcount)


def get_corpus_suggestions(account_id: int, status: str = "pending",
                           db_path: Optional[str] = None) -> list[dict]:
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """SELECT cs.*, a.title, a.description, a.content, a.source_name, a.url
               FROM corpus_suggestions cs JOIN articles a ON a.id = cs.article_id
               WHERE cs.account_id = ? AND cs.status = ?
               ORDER BY cs.created_at DESC""",
            (account_id, status),
        ).fetchall()
        return [dict(r) for r in rows]


def set_suggestion_status(suggestion_id: int, status: str,
                          db_path: Optional[str] = None) -> None:
    with get_conn(db_path) as conn:
        conn.execute("UPDATE corpus_suggestions SET status = ? WHERE id = ?",
                     (status, suggestion_id))


# --------------------------------------------------------------------------- #
# Style DNA
# --------------------------------------------------------------------------- #
def save_style_dna(
    account_id: int,
    genome_a: dict,
    genome_b: Optional[dict] = None,
    blend: float = 0.4,
    sample_count: Optional[int] = None,
    db_path: Optional[str] = None,
) -> int:
    """Save a new style DNA version (auto-increments version per account)."""
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM style_dna WHERE account_id = ?",
            (account_id,),
        ).fetchone()
        next_version = row["v"] + 1
        now = _now()
        cur = conn.execute(
            """INSERT INTO style_dna
               (account_id, genome_a, genome_b, blend, sample_count, version,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                account_id,
                json.dumps(genome_a),
                json.dumps(genome_b) if genome_b else None,
                blend,
                sample_count,
                next_version,
                now,
                now,
            ),
        )
        return cur.lastrowid


def get_style_dna(account_id: int, db_path: Optional[str] = None) -> Optional[dict]:
    """Return the latest style DNA for an account, with JSON fields parsed."""
    with get_conn(db_path) as conn:
        row = conn.execute(
            """SELECT * FROM style_dna WHERE account_id = ?
               ORDER BY version DESC LIMIT 1""",
            (account_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["genome_a"] = json.loads(d["genome_a"])
        d["genome_b"] = json.loads(d["genome_b"]) if d["genome_b"] else None
        return d


# --------------------------------------------------------------------------- #
# Events timeline + stance memory + predictions — the agent's long-term memory.
# Written by decision.run (FIRE/WARM events) and pipeline/updater.py (stances,
# predictions, on actually-posted items); read by pipeline/context.py.
# --------------------------------------------------------------------------- #
def _like_clauses(fields: list[str], keywords: list[str]) -> tuple[str, list[str]]:
    """OR-joined LIKE filter over fields for each keyword (parameterized)."""
    clauses, params = [], []
    for kw in keywords:
        for f in fields:
            clauses.append(f"{f} LIKE ?")
            params.append(f"%{kw}%")
    return "(" + " OR ".join(clauses) + ")", params


def seed_event(
    topic: str,
    summary: str,
    source_url: Optional[str] = None,
    event_date: Optional[str] = None,
    db_path: Optional[str] = None,
) -> int:
    """Add an event to the timeline. Deduplicated by source_url when given, so
    the same story scored for two personas (or re-logged at posting time)
    lands exactly once. Returns the event id (existing one on dedup)."""
    with get_conn(db_path) as conn:
        if source_url:
            row = conn.execute(
                "SELECT id FROM events_timeline WHERE source_url = ?", (source_url,)
            ).fetchone()
            if row:
                return row["id"]
        cur = conn.execute(
            """INSERT INTO events_timeline (topic, summary, source_url, event_date, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (topic, summary, source_url, event_date, _now()),
        )
        return cur.lastrowid


def find_events(keywords: list[str], limit: int = 5,
                db_path: Optional[str] = None) -> list[dict]:
    """Timeline events whose topic or summary mentions any keyword, newest
    first. Pure SQL — the historical-context layer costs nothing."""
    if not keywords:
        return []
    where, params = _like_clauses(["topic", "summary"], keywords)
    with get_conn(db_path) as conn:
        rows = conn.execute(
            f"""SELECT * FROM events_timeline WHERE {where}
                ORDER BY COALESCE(event_date, created_at) DESC LIMIT ?""",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]


def log_stance(account_id: int, topic: str, stance: str,
               source_url: Optional[str] = None,
               db_path: Optional[str] = None) -> int:
    """Record the position this account just took publicly on a topic."""
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO stance_history (account_id, topic, stance, source_url, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (account_id, topic, stance, source_url, _now()),
        )
        return cur.lastrowid


def top_stance_topics(account_id: int, limit: int = 5,
                      db_path: Optional[str] = None) -> list[dict]:
    """The topics this account has taken positions on most often, with the
    latest stance for each — the evergreen generator's raw material."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """SELECT topic, COUNT(*) AS n, MAX(created_at) AS last_at,
                      (SELECT stance FROM stance_history s2
                       WHERE s2.account_id = s1.account_id AND s2.topic = s1.topic
                       ORDER BY created_at DESC LIMIT 1) AS latest_stance
               FROM stance_history s1 WHERE account_id = ?
               GROUP BY topic ORDER BY n DESC, last_at DESC LIMIT ?""",
            (account_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def find_stances(account_id: int, keywords: list[str], limit: int = 5,
                 db_path: Optional[str] = None) -> list[dict]:
    """What THIS account has said before on anything matching the keywords."""
    if not keywords:
        return []
    where, params = _like_clauses(["topic", "stance"], keywords)
    with get_conn(db_path) as conn:
        rows = conn.execute(
            f"""SELECT * FROM stance_history WHERE account_id = ? AND {where}
                ORDER BY created_at DESC LIMIT ?""",
            [account_id] + params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]


def find_related_articles(keywords: list[str], exclude_article_id: Optional[int] = None,
                          limit: int = 5, db_path: Optional[str] = None) -> list[dict]:
    """Already-ingested coverage matching the keywords (the data-enrichment
    layer, honestly named: it's related reporting, not a curated stats store)."""
    if not keywords:
        return []
    where, params = _like_clauses(["title", "description"], keywords)
    sql = f"SELECT id, title, source_name, url, published_at FROM articles WHERE {where}"
    if exclude_article_id is not None:
        sql += " AND id != ?"
        params.append(exclude_article_id)
    sql += " ORDER BY published_at DESC LIMIT ?"
    with get_conn(db_path) as conn:
        return [dict(r) for r in conn.execute(sql, params + [limit]).fetchall()]


def find_articles_fetched_after(keywords: list[str], fetched_after: str,
                                limit: int = 30, db_path: Optional[str] = None) -> list[dict]:
    """Articles ingested after a cursor timestamp that mention any keyword —
    the callback watcher's raw candidate pool (it ranks them in Python)."""
    if not keywords:
        return []
    where, params = _like_clauses(["title", "description"], keywords)
    with get_conn(db_path) as conn:
        rows = conn.execute(
            f"""SELECT id, title, description, source_name, url, published_at, fetched_at
                FROM articles WHERE {where} AND fetched_at > ?
                ORDER BY fetched_at DESC LIMIT ?""",
            params + [fetched_after, limit],
        ).fetchall()
        return [dict(r) for r in rows]


def touch_prediction_checked(prediction_id: int, checked_at: Optional[str] = None,
                             db_path: Optional[str] = None) -> None:
    """Advance the callback watcher's cursor so each article is judged at most
    once per prediction."""
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE predictions_tracker SET last_checked_at = ? WHERE id = ?",
            (checked_at or _now(), prediction_id),
        )


def insert_prediction(account_id: int, prediction: str, post_id: Optional[int] = None,
                      topic: Optional[str] = None, horizon: Optional[str] = None,
                      db_path: Optional[str] = None) -> int:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO predictions_tracker
               (account_id, post_id, topic, prediction, horizon, status, made_at)
               VALUES (?, ?, ?, ?, ?, 'open', ?)""",
            (account_id, post_id, topic, prediction, horizon, _now()),
        )
        return cur.lastrowid


def get_open_predictions(account_id: Optional[int] = None,
                         db_path: Optional[str] = None) -> list[dict]:
    q = "SELECT * FROM predictions_tracker WHERE status = 'open'"
    params: list[Any] = []
    if account_id is not None:
        q += " AND account_id = ?"
        params.append(account_id)
    q += " ORDER BY made_at"
    with get_conn(db_path) as conn:
        return [dict(r) for r in conn.execute(q, params).fetchall()]


def resolve_prediction(prediction_id: int, outcome: str, status: str = "resolved",
                       db_path: Optional[str] = None) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            """UPDATE predictions_tracker SET status = ?, outcome = ?, resolved_at = ?
               WHERE id = ?""",
            (status, outcome, _now(), prediction_id),
        )


# --------------------------------------------------------------------------- #
# Posts (generated drafts + human-in-the-loop lifecycle)
# --------------------------------------------------------------------------- #
def save_post(
    account_id: int,
    fmt: str,
    content: str,
    meta: Optional[dict] = None,
    signal_id: Optional[int] = None,
    article_id: Optional[int] = None,
    persona_score: Optional[float] = None,
    needs_review: bool = False,
    status: str = "draft",
    db_path: Optional[str] = None,
) -> int:
    """Persist a generated draft. Returns the new post id."""
    now = _now()
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO posts
               (account_id, signal_id, article_id, format, content, meta_json,
                persona_score, needs_review, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                account_id, signal_id, article_id, fmt, content,
                json.dumps(meta or {}), persona_score, int(needs_review),
                status, now, now,
            ),
        )
        return cur.lastrowid


def get_post(post_id: int, db_path: Optional[str] = None) -> Optional[dict]:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["meta_json"] = json.loads(d["meta_json"]) if d["meta_json"] else {}
        return d


def get_posts(
    account_id: Optional[int] = None,
    status: Optional[str] = None,
    db_path: Optional[str] = None,
) -> list[dict]:
    q = "SELECT * FROM posts"
    clauses, params = [], []
    if account_id is not None:
        clauses.append("account_id = ?"); params.append(account_id)
    if status is not None:
        clauses.append("status = ?"); params.append(status)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY created_at DESC"
    with get_conn(db_path) as conn:
        rows = conn.execute(q, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["meta_json"] = json.loads(d["meta_json"]) if d["meta_json"] else {}
            out.append(d)
        return out


def get_reviewed_posts(account_id: int, db_path: Optional[str] = None) -> list[dict]:
    """Posts a human has actioned (anything past 'draft'), joined with the
    article's vertical and the signal's topic slug. This is the raw material
    for the approve/reject learning loop and topic-level historical_perf."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """SELECT p.*, a.vertical, s.topic FROM posts p
               LEFT JOIN articles a ON a.id = p.article_id
               LEFT JOIN signals s ON s.id = p.signal_id
               WHERE p.account_id = ? AND p.status != 'draft'
               ORDER BY p.created_at""",
            (account_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["meta_json"] = json.loads(d["meta_json"]) if d["meta_json"] else {}
            out.append(d)
        return out


def record_feedback(account_id: int, post_id: Optional[int], kind: str, note: str,
                    db_path: Optional[str] = None) -> int:
    """Store a freeform steer/reason. The richer-than-binary learning signal."""
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO draft_feedback (account_id, post_id, kind, note, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (account_id, post_id, kind, note.strip(), _now()),
        )
        return cur.lastrowid


def get_recent_feedback_notes(account_id: int, limit: int = 15,
                              db_path: Optional[str] = None) -> list[str]:
    """Recent freeform steers/reasons — fed into the learning loop so a
    recurring 'more savage' becomes a standing preference."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """SELECT note FROM draft_feedback WHERE account_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (account_id, limit),
        ).fetchall()
        return [r["note"] for r in rows]


def update_post_meta(post_id: int, updates: dict, db_path: Optional[str] = None) -> None:
    """Merge keys into a post's meta_json (e.g. alt_hooks added after drafting)."""
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT meta_json FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not row:
            return
        meta = json.loads(row["meta_json"]) if row["meta_json"] else {}
        meta.update(updates)
        conn.execute("UPDATE posts SET meta_json = ?, updated_at = ? WHERE id = ?",
                     (json.dumps(meta), _now(), post_id))


def update_post_content(post_id: int, content: str, meta: dict,
                        needs_review: bool = True, db_path: Optional[str] = None) -> None:
    """Replace a draft's content + meta in place (the redo-with-steer path).
    Resets to 'draft' so a regenerated post re-enters the review lane."""
    with get_conn(db_path) as conn:
        conn.execute(
            """UPDATE posts SET content = ?, meta_json = ?, needs_review = ?,
               status = 'draft', updated_at = ? WHERE id = ?""",
            (content, json.dumps(meta or {}), int(needs_review), _now(), post_id),
        )


def set_post_status(post_id: int, status: str, db_path: Optional[str] = None) -> None:
    """Update a draft's lifecycle status (approved/edited/rejected/posted).
    This is the signal the approve/reject learning loop will read later."""
    if status not in {"draft", "approved", "edited", "rejected", "posted"}:
        raise ValueError(f"Invalid post status '{status}'")
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE posts SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), post_id),
        )


def count_recent_posts_on_topic(account_id: int, topic: str, since: str,
                                db_path: Optional[str] = None) -> int:
    """How many audience-facing posts (approved/edited/posted) this account
    has on a topic since the cutoff — the fatigue detector's raw count."""
    with get_conn(db_path) as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM posts p
               JOIN signals s ON s.id = p.signal_id
               WHERE p.account_id = ? AND s.topic = ?
                 AND p.status IN ('approved', 'edited', 'posted')
                 AND p.updated_at > ?""",
            (account_id, topic, since),
        ).fetchone()
        return row["n"]


def mark_posted(post_id: int, url: Optional[str] = None,
                db_path: Optional[str] = None) -> None:
    """You posted it yourself (manual flow): close the lifecycle, stamp when,
    and keep the live URL if given so engagement can be checked later."""
    with get_conn(db_path) as conn:
        conn.execute(
            """UPDATE posts SET status = 'posted', posted_at = ?,
               posted_url = COALESCE(?, posted_url), updated_at = ? WHERE id = ?""",
            (_now(), url, _now(), post_id),
        )


def get_outbox(account_id: Optional[int] = None, db_path: Optional[str] = None) -> list[dict]:
    """Approved/edited drafts you haven't posted yet — your manual posting queue."""
    posts = get_posts(account_id=account_id, db_path=db_path)
    return [p for p in posts if p["status"] in ("approved", "edited")]


# --------------------------------------------------------------------------- #
# Engagement (manual snapshots now, API rows later — same table)
# --------------------------------------------------------------------------- #
def record_engagement(post_id: int, likes: int = 0, retweets: int = 0,
                      replies: int = 0, views: int = 0,
                      db_path: Optional[str] = None) -> int:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO engagement (post_id, likes, retweets, replies, views, recorded_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (post_id, likes, retweets, replies, views, _now()),
        )
        return cur.lastrowid


def get_post_engagement(account_id: int, db_path: Optional[str] = None) -> list[dict]:
    """Latest engagement snapshot per post for an account, with the article's
    vertical — the raw material for the engagement half of historical_perf."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """SELECT e.*, p.format, p.posted_at, a.vertical, s.topic
               FROM engagement e
               JOIN posts p ON p.id = e.post_id
               LEFT JOIN articles a ON a.id = p.article_id
               LEFT JOIN signals s ON s.id = p.signal_id
               WHERE p.account_id = ?
                 AND e.id IN (SELECT MAX(id) FROM engagement GROUP BY post_id)
               ORDER BY e.recorded_at""",
            (account_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Claude cost ledger + backups
# --------------------------------------------------------------------------- #
def log_claude_call(module: str, model: Optional[str], input_tokens: int,
                    output_tokens: int, cost_usd: float,
                    db_path: Optional[str] = None) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            """INSERT INTO claude_logs
               (module, model, input_tokens, output_tokens, cost_usd, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (module, model, input_tokens, output_tokens, cost_usd, _now()),
        )


def cost_today(db_path: Optional[str] = None) -> float:
    """Total estimated Claude spend since UTC midnight."""
    midnight = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS c FROM claude_logs WHERE created_at >= ?",
            (midnight,),
        ).fetchone()
        return round(row["c"], 4)


def backup_db(db_path: Optional[str] = None, out_dir: Optional[str] = None,
              keep: Optional[int] = None) -> str:
    """Consistent snapshot via VACUUM INTO; prunes oldest past `keep`.
    The whole moat is one SQLite file — this is the insurance."""
    src = db_path or settings.db_path
    out = Path(out_dir or settings.backups_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    dest = out / f"agent-{stamp}.db"
    conn = sqlite3.connect(src)
    try:
        conn.execute(f"VACUUM INTO '{dest.as_posix()}'")
    finally:
        conn.close()
    backups = sorted(out.glob("agent-*.db"))
    for old in backups[: max(0, len(backups) - (keep or settings.backup_keep))]:
        old.unlink(missing_ok=True)
    return str(dest)


def touch_voice_sample_engagement(account_id: int, content: str, likes: int,
                                  retweets: int, replies: int,
                                  db_path: Optional[str] = None) -> None:
    """Update analytics on an existing corpus sample (re-/perf on a draft
    that's already been filed by the flywheel)."""
    with get_conn(db_path) as conn:
        conn.execute(
            """UPDATE voice_samples SET likes = ?, retweets = ?, replies = ?
               WHERE account_id = ? AND content_hash = ?""",
            (likes, retweets, replies, account_id, _content_hash(content)),
        )


def get_engagement_for_post(post_id: int, db_path: Optional[str] = None) -> Optional[dict]:
    """Latest engagement snapshot for one post."""
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM engagement WHERE post_id = ? ORDER BY id DESC LIMIT 1",
            (post_id,),
        ).fetchone()
        return dict(row) if row else None


# --------------------------------------------------------------------------- #
# KV store (process state that must survive restarts)
# --------------------------------------------------------------------------- #
def kv_get(key: str, default: Optional[str] = None,
           db_path: Optional[str] = None) -> Optional[str]:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def kv_set(key: str, value: str, db_path: Optional[str] = None) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            """INSERT INTO kv_store (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )


# --------------------------------------------------------------------------- #
# Watch list (deduplicated sources for the watch layer)
# --------------------------------------------------------------------------- #
def add_watch(
    kind: str,
    ref: str,
    label: Optional[str] = None,
    vertical: Optional[str] = None,
    region: Optional[str] = None,
    db_path: Optional[str] = None,
) -> int:
    """Add a source to watch. Deduplicated by (kind, ref) — adding the same
    channel twice is a no-op (CLAUDE.md rule #8)."""
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO watch_list (kind, ref, label, vertical, region, active, created_at)
               VALUES (?, ?, ?, ?, ?, 1, ?)
               ON CONFLICT(kind, ref) DO UPDATE SET
                   label=COALESCE(excluded.label, watch_list.label),
                   vertical=COALESCE(excluded.vertical, watch_list.vertical),
                   region=COALESCE(excluded.region, watch_list.region),
                   active=1""",
            (kind, ref, label, vertical, region, _now()),
        )
        if cur.lastrowid:
            return cur.lastrowid
        row = conn.execute(
            "SELECT id FROM watch_list WHERE kind = ? AND ref = ?", (kind, ref)
        ).fetchone()
        return row["id"]


def remove_watch(watch_id: int, db_path: Optional[str] = None) -> None:
    """Deactivate a watch source (kept for history; watchers skip inactive)."""
    with get_conn(db_path) as conn:
        conn.execute("UPDATE watch_list SET active = 0 WHERE id = ?", (watch_id,))


def get_watch(kind: Optional[str] = None, db_path: Optional[str] = None) -> list[dict]:
    q = "SELECT * FROM watch_list WHERE active = 1"
    params: list[Any] = []
    if kind:
        q += " AND kind = ?"; params.append(kind)
    q += " ORDER BY id"
    with get_conn(db_path) as conn:
        return [dict(r) for r in conn.execute(q, params).fetchall()]
