"""
poster.py — Session 6, reimagined for the copilot (manual posting) flow.

DELIBERATE DESIGN DECISION — no auto-posting to X:
API/browser-automated posting from a personal account is the fastest way to get
flagged as a bot, and X's official write API is paid anyway. So this module
never touches the X API. Instead it makes YOU the fastest manual poster alive:

  * X WEB INTENT LINKS — https://x.com/intent/post?text=... opens X's own
    compose window pre-filled with the final text. You tap Post yourself.
    Fully ToS-compliant, works on phone and desktop, zero bot signals: as far
    as X can tell, a human typed it.
  * TELEGRAM DELIVERY — every new draft is pushed to your private chat with the
    bot the moment it's generated; on approval you get the final, labeled,
    ready-to-post text + the intent link. Telegram bots messaging you are
    completely normal — this is a notification channel, not a posting bot.
  * TELEGRAM CHANNEL (optional) — if TELEGRAM_CHANNEL_ID is set, approved posts
    ARE auto-published there. That's safe: Telegram explicitly supports bot
    posting to your own channel; there is no bot-flagging concept to violate.

When X API write access is ever worth paying for, a post_to_x() lands here and
nothing upstream changes — the lifecycle (draft → approved → posted) is already
platform-agnostic.

Rule #10: the AI label (settings.ai_label) is appended to the postable text at
dispatch time. For a thread it goes on the last tweet. Since a human reviews
and posts each one, AI_LABEL= (empty) in .env disables it — your call.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Callable, Optional
from urllib.parse import quote

from config import settings
from pipeline import memory

logger = logging.getLogger("poster")

X_CHAR_LIMIT = 280
THREAD_SEP = "\n\n———\n\n"  # matches generator.py's thread rendering

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


# --------------------------------------------------------------------------- #
# Postable text (pure functions)
# --------------------------------------------------------------------------- #
def postable_texts(post: dict) -> list[str]:
    """The exact text(s) to publish: the post content split into tweets if it's
    a thread, with the AI label (rule #10) appended to the last one."""
    meta = post.get("meta_json") or {}
    tweets = meta.get("tweets")
    parts = [t for t in tweets if t and t.strip()] if tweets else \
        [p for p in post["content"].split(THREAD_SEP) if p.strip()]
    if not parts:
        return []
    if settings.ai_label:
        parts = parts[:-1] + [f"{parts[-1]}\n\n{settings.ai_label}"]
    return parts


def x_intent_url(text: str) -> str:
    """X's official pre-filled compose link. Opening it and pressing Post is a
    human action — this is the ToS-clean alternative to API posting."""
    return "https://x.com/intent/post?text=" + quote(text, safe="")


def copy_to_clipboard(text: str) -> bool:
    """Best-effort clipboard copy (pbcopy on macOS, xclip on Linux)."""
    cmd = ["pbcopy"] if sys.platform == "darwin" else ["xclip", "-selection", "clipboard"]
    try:
        subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=5)
        return True
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Message formatting (pure functions — also used by the Telegram commander)
# --------------------------------------------------------------------------- #
def _age_hours(post: dict) -> Optional[float]:
    from datetime import datetime, timezone
    try:
        created = datetime.fromisoformat(post["created_at"].replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - created).total_seconds() / 3600
    except (KeyError, ValueError, AttributeError, TypeError):
        return None


def _warning_lines(post: dict) -> list[str]:
    """Grounding + staleness warnings, shared by the alert and the package."""
    lines = []
    claims = (post.get("meta_json") or {}).get("ungrounded_claims") or []
    if claims:
        lines.append("🚨 VERIFY BEFORE POSTING — claims not found in the source:")
        lines += [f"  • {c}" for c in claims[:5]]
    age = _age_hours(post)
    if age is not None and age >= settings.draft_stale_hours:
        lines.append(f"⏳ this draft is {age:.0f}h old — check the moment "
                     "hasn't passed before posting")
    return lines


def format_draft_alert(post: dict, article_title: Optional[str] = None) -> str:
    """The push you get the moment a draft exists. Act from your phone."""
    score = f"{post['persona_score']:.0f}" if post.get("persona_score") is not None else "—"
    flag = " ⚠️ needs review" if post.get("needs_review") else ""
    lines = [f"📝 New draft #{post['id']} [{post['format']}] persona={score}{flag}"]
    if article_title:
        lines.append(f"re: {article_title}")
    lines += ["─" * 24, post["content"], "─" * 24]
    lines += _warning_lines(post)
    hooks = (post.get("meta_json") or {}).get("alt_hooks") or []
    if hooks:
        lines.append("alt hooks (swap in when you post, if stronger):")
        lines += [f"  {i}. {h}" for i, h in enumerate(hooks, 1)]
    lines.append(f"/approve {post['id']} · /reject {post['id']} · /list")
    return "\n".join(lines)


def format_approved_package(post: dict, db_path: Optional[str] = None) -> str:
    """Everything needed to post in one tap: final labeled text, char counts,
    intent link(s), timing advice, and what to do after."""
    parts = postable_texts(post)
    lines = [f"✅ Draft #{post['id']} approved — post it yourself:"]
    lines += _warning_lines(post)
    if len(parts) == 1:
        n = len(parts[0])
        over = f"  ⚠️ {n - X_CHAR_LIMIT} over the limit, trim in the compose box" if n > X_CHAR_LIMIT else ""
        lines += ["─" * 24, parts[0], "─" * 24,
                  f"{n}/{X_CHAR_LIMIT} chars{over}",
                  f"👉 tap to compose: {x_intent_url(parts[0])}"]
    else:
        lines.append(f"(thread of {len(parts)} — post 1, then post each next one as a reply)")
        for i, t in enumerate(parts, 1):
            lines += ["─" * 24, f"[{i}/{len(parts)}] {t}",
                      f"👉 {x_intent_url(t)}"]
        lines.append("─" * 24)
    if post.get("account_id"):
        try:  # timing advice is a bonus line, never a blocker
            from pipeline.timing import describe_windows
            lines.append(f"⏰ {describe_windows(post['account_id'], db_path=db_path)}")
        except Exception:  # noqa: BLE001
            pass
    lines.append(f"then:  /posted {post['id']}  (add the live URL if handy)")
    lines.append(f"later: /perf {post['id']} <likes> <retweets> <replies>  — feeds the learning loop")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Telegram transport
# --------------------------------------------------------------------------- #
def default_transport(method: str, payload: dict) -> dict:
    """POST to the Telegram Bot API. Swapped out in tests."""
    import requests

    resp = requests.post(
        TELEGRAM_API.format(token=settings.telegram_bot_token, method=method),
        json=payload, timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def default_photo_transport(method: str, payload: dict, file_path: str) -> dict:
    """Multipart upload to the Telegram Bot API (sendPhoto). Swapped in tests."""
    import requests

    with open(file_path, "rb") as fh:
        resp = requests.post(
            TELEGRAM_API.format(token=settings.telegram_bot_token, method=method),
            data=payload, files={"photo": fh}, timeout=30,
        )
    resp.raise_for_status()
    return resp.json()


def make_card(post: dict, db_path: Optional[str] = None) -> Optional[str]:
    """Render the branded image card for a post (first tweet for threads).
    Returns the PNG path, or None when cards are disabled / Pillow is missing /
    rendering fails — the card is a bonus, never a blocker."""
    if not settings.cards_enabled:
        return None
    try:
        from image.cards import render_card
    except ImportError:
        logger.info("Pillow not installed — skipping image card.")
        return None
    try:
        meta = post.get("meta_json") or {}
        text = (meta.get("tweets") or [None])[0] or \
            post["content"].split(THREAD_SEP)[0]
        acct = memory.get_account(post["account_id"], db_path=db_path) or {}
        return render_card(text, handle=acct.get("handle", ""))
    except Exception as exc:  # noqa: BLE001
        logger.error("Card rendering failed: %s", exc)
        return None


class TelegramNotifier:
    """Sends messages to your private chat (and optionally your channel).
    transport is injectable: callable(method, payload) -> response dict;
    photo_transport: callable(method, payload, file_path) -> response dict."""

    def __init__(self, transport: Optional[Callable[[str, dict], dict]] = None,
                 photo_transport: Optional[Callable[[str, dict, str], dict]] = None) -> None:
        self._transport = transport or default_transport
        self._photo_transport = photo_transport or default_photo_transport

    @property
    def configured(self) -> bool:
        return bool(settings.telegram_bot_token and settings.telegram_chat_id)

    def send(self, text: str, chat_id: Optional[str] = None) -> bool:
        chat_id = chat_id or settings.telegram_chat_id
        if not (settings.telegram_bot_token and chat_id):
            return False
        try:
            resp = self._transport("sendMessage", {
                "chat_id": chat_id, "text": text,
                "disable_web_page_preview": True,
            })
            return bool(resp.get("ok"))
        except Exception as exc:  # noqa: BLE001
            logger.error("Telegram send failed: %s", exc)
            return False

    def send_photo(self, file_path: str, caption: str = "",
                   chat_id: Optional[str] = None) -> bool:
        chat_id = chat_id or settings.telegram_chat_id
        if not (settings.telegram_bot_token and chat_id and file_path):
            return False
        try:
            resp = self._photo_transport(
                "sendPhoto", {"chat_id": chat_id, "caption": caption[:1000]},
                file_path)
            return bool(resp.get("ok"))
        except Exception as exc:  # noqa: BLE001
            logger.error("Telegram photo send failed: %s", exc)
            return False

    # ----------------------------------------------------------- high level
    def notify_draft(self, post: dict, article_title: Optional[str] = None) -> bool:
        """Push a fresh draft to your phone. No-op (False) if not configured."""
        if not self.configured:
            return False
        return self.send(format_draft_alert(post, article_title))

    def publish_to_channel(self, post: dict) -> bool:
        """Auto-publish the labeled text to YOUR Telegram channel, if one is
        configured. This is the one place auto-posting is safe — Telegram
        treats bot publishing as a first-class feature."""
        if not (settings.telegram_bot_token and settings.telegram_channel_id):
            return False
        text = "\n\n".join(postable_texts(post))
        return self.send(text, chat_id=settings.telegram_channel_id)


def dispatch_approved(post: dict, notifier: Optional[TelegramNotifier] = None,
                      db_path: Optional[str] = None) -> dict:
    """Everything that happens when a draft is approved: package to your chat,
    branded image card rendered + attached, optional channel publish. Returns
    what was delivered where, plus the intent URLs so CLI callers can print
    them and the card path so you can attach it in the compose window."""
    notifier = notifier or TelegramNotifier()
    parts = postable_texts(post)
    card = make_card(post, db_path=db_path)
    card_sent = False
    if card and notifier.configured:
        card_sent = notifier.send_photo(
            card, caption=f"card for draft #{post['id']} — attach it when composing")
    return {
        "texts": parts,
        "intent_urls": [x_intent_url(t) for t in parts],
        "card": card,
        "card_sent": card_sent,
        "telegram": notifier.configured and notifier.send(
            format_approved_package(post, db_path=db_path)),
        "channel": notifier.publish_to_channel(post),
    }


if __name__ == "__main__":
    # Smoke test: send yourself the latest draft (needs TELEGRAM_* in .env).
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    memory.init_db()
    drafts = memory.get_posts(status="draft")
    if not drafts:
        print("No drafts to send.")
    else:
        ok = TelegramNotifier().notify_draft(drafts[0])
        print(f"Sent draft #{drafts[0]['id']} to Telegram: {ok}")
