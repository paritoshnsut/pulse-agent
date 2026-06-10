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
    """Connection context manager with dict-like rows and FK enforcement."""
    conn = sqlite3.connect(db_path or settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
                      ("owner_id", "TEXT")):  # supabase user id; NULL = shared
        if col not in acct_cols:
            conn.execute(f"ALTER TABLE accounts ADD COLUMN {col} {decl}")
    post_cols = {r["name"] for r in conn.execute("PRAGMA table_info(posts)")}
    for col in ("posted_at", "posted_url"):
        if col not in post_cols:
            conn.execute(f"ALTER TABLE posts ADD COLUMN {col} TEXT")
    sig_cols = {r["name"] for r in conn.execute("PRAGMA table_info(signals)")}
    for col in ("topic", "format"):
        if col not in sig_cols:
            conn.execute(f"ALTER TABLE signals ADD COLUMN {col} TEXT")
    pred_cols = {r["name"] for r in conn.execute("PRAGMA table_info(predictions_tracker)")}
    if pred_cols and "last_checked_at" not in pred_cols:
        conn.execute("ALTER TABLE predictions_tracker ADD COLUMN last_checked_at TEXT")


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
    db_path: Optional[str] = None,
) -> int:
    """Insert an account or return the existing id for (handle, platform).
    On an existing row, refresh niche/topics/verticals/regions/owner if given.
    owner_id is the Supabase user id; NULL means shared (family/dev mode)."""
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
                     owner_id = COALESCE(?, owner_id)
                   WHERE id = ?""",
                (
                    niche,
                    json.dumps(topics) if topics is not None else None,
                    json.dumps(verticals) if verticals is not None else None,
                    json.dumps(regions) if regions is not None else None,
                    owner_id,
                    row["id"],
                ),
            )
            return row["id"]
        cur = conn.execute(
            """INSERT INTO accounts
               (handle, platform, niche, topics, verticals, regions, owner_id,
                active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (
                handle, platform, niche,
                json.dumps(topics or []),
                json.dumps(verticals) if verticals is not None else None,
                json.dumps(regions) if regions is not None else None,
                owner_id,
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
            "reaction_potential", "window_urgency", "historical_perf", "angle",
            "topic", "format", "reasoning")
    params = {c: signal.get(c) for c in cols}
    params["created_at"] = signal.get("created_at") or _now()
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO signals
               (article_id, account_id, score, tier, velocity, relevance,
                reaction_potential, window_urgency, historical_perf, angle,
                topic, format, reasoning, created_at)
               VALUES (:article_id, :account_id, :score, :tier, :velocity,
                       :relevance, :reaction_potential, :window_urgency,
                       :historical_perf, :angle, :topic, :format, :reasoning,
                       :created_at)
               ON CONFLICT(article_id, account_id) DO UPDATE SET
                   score=excluded.score, tier=excluded.tier,
                   velocity=excluded.velocity, relevance=excluded.relevance,
                   reaction_potential=excluded.reaction_potential,
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
    article's vertical. This is the raw material for the approve/reject
    learning loop — the signal review.py captures, read back out."""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """SELECT p.*, a.vertical FROM posts p
               LEFT JOIN articles a ON a.id = p.article_id
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
            """SELECT e.*, p.format, p.posted_at, a.vertical FROM engagement e
               JOIN posts p ON p.id = e.post_id
               LEFT JOIN articles a ON a.id = p.article_id
               WHERE p.account_id = ?
                 AND e.id IN (SELECT MAX(id) FROM engagement GROUP BY post_id)
               ORDER BY e.recorded_at""",
            (account_id,),
        ).fetchall()
        return [dict(r) for r in rows]


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
