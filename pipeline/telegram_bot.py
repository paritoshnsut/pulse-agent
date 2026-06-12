"""
telegram_bot.py — run the whole approve→post loop from your phone.

The scheduler polls Telegram getUpdates every minute. You text the bot:

    /list                          pending drafts
    /show 12                       full text of draft #12
    /approve 12                    approve → get final text + tap-to-compose link
    /reject 12                     reject (feeds the learning loop)
    /outbox                        approved drafts you haven't posted yet
    /posted 12 [url]               you posted it on X — close the loop
    /perf 12 <likes> <rts> <replies> [views]   engagement → historical_perf

So the full cycle is: draft lands as a push → /approve from the couch → tap the
intent link → X opens pre-filled → YOU press Post → /posted. The system never
touches X; you were just faster than everyone typing from scratch.

SECURITY: only messages from TELEGRAM_CHAT_ID (your own chat) are obeyed;
everything else is ignored. The getUpdates offset is persisted in kv_store so
restarts don't replay old commands.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from config import settings
from pipeline import memory, poster

logger = logging.getLogger("telegram_bot")

OFFSET_KEY = "telegram_update_offset"

HELP = (
    "Pulse copilot commands:\n"
    "/list — pending drafts\n"
    "/show ID — full draft text\n"
    "/approve ID — approve + get the post-it-yourself link\n"
    "/reject ID — reject (the agent learns from this)\n"
    "/outbox — approved, not yet posted\n"
    "/redo ID instruction — rewrite a draft ('/redo 12 make it more savage')\n"
    "/posted ID [url] — you posted it on X\n"
    "/perf ID likes retweets replies [views] — log engagement\n"
    "/evergreen [handle] [topic] — draft a no-news-peg opinion post"
)


class TelegramCommander:
    """Processes your commands from the private chat. Transport injectable."""

    def __init__(self, transport: Optional[Callable[[str, dict], dict]] = None,
                 db_path: Optional[str] = None) -> None:
        self._injected_transport = transport is not None  # True when caller provides test transport
        self._transport = transport or poster.default_transport
        self.db_path = db_path
        self.notifier = poster.TelegramNotifier(transport=self._transport)

    # ------------------------------------------------------------- polling
    def poll_once(self) -> int:
        """Fetch new updates, handle commands from YOUR chat, reply, advance
        the persisted offset. Returns how many commands were handled."""
        # When using the default (real) transport, credentials must be set.
        # Injected transports (tests, custom integrations) bypass this guard.
        if not self._injected_transport and not (
                settings.telegram_bot_token and settings.telegram_chat_id):
            return 0
        offset = int(memory.kv_get(OFFSET_KEY, "0", db_path=self.db_path) or 0)
        resp = self._transport("getUpdates", {"offset": offset + 1, "timeout": 0})
        handled = 0
        max_id = offset
        for upd in resp.get("result") or []:
            max_id = max(max_id, upd.get("update_id", 0))
            # Channel posts arrive as 'channel_post', not 'message'.
            channel_post = upd.get("channel_post")
            if channel_post:
                self._ingest_channel_post(channel_post)
                continue
            msg = upd.get("message") or {}
            chat_id = str((msg.get("chat") or {}).get("id", ""))
            text = (msg.get("text") or "").strip()
            if chat_id != str(settings.telegram_chat_id) or not text:
                continue  # not you, or not a text message — ignore silently
            reply = self.handle(text)
            if reply:
                self.notifier.send(reply)
                handled += 1
        if max_id != offset:
            memory.kv_set(OFFSET_KEY, str(max_id), db_path=self.db_path)
        return handled

    def _ingest_channel_post(self, msg: dict) -> None:
        """Persist a message from a watched Telegram channel as an article.

        SETUP: add the bot as an admin of the channel you want to watch, then add
        the channel to the watch list (Settings → Watch List, kind=telegram_channel,
        ref=@channelname or the numeric -100XXXX id). The bot receives all new
        posts from that channel via getUpdates automatically."""
        chat = msg.get("chat") or {}
        channel_id_str = str(chat.get("id", ""))
        channel_username = (chat.get("username") or "").lower().lstrip("@")

        # Only ingest channels the user has explicitly added to the watch list.
        watched = memory.get_watch(kind="telegram_channel", db_path=self.db_path)
        if not watched:
            return

        def _matches(ref: str) -> bool:
            r = ref.strip().lower().lstrip("@")
            return r == channel_id_str or r == channel_username or r == channel_id_str.lstrip("-")

        if not any(_matches(w["ref"]) for w in watched):
            return   # not a channel we're watching — ignore

        text = (msg.get("text") or msg.get("caption") or "").strip()
        if not text:
            return   # photo/sticker with no caption — nothing to ingest

        channel_name = chat.get("title") or chat.get("username") or channel_id_str
        msg_id = msg.get("message_id", "")
        url = (f"https://t.me/{channel_username}/{msg_id}" if channel_username
               else f"tg://channel?id={channel_id_str}&msgid={msg_id}")

        date = msg.get("date")
        pub_iso = (datetime.fromtimestamp(date, tz=timezone.utc).isoformat()
                   if date else datetime.now(timezone.utc).isoformat())

        art = {
            "source": "telegram_channel",
            "source_name": f"Telegram: {channel_name}",
            "vertical": None,
            "region": None,
            "url": url,
            "title": text[:200].replace("\n", " "),
            "description": text[:500] if len(text) > 200 else None,
            "content": text if len(text) > 500 else None,
            "author": channel_name,
            "published_at": pub_iso,
            "velocity_hint": None,  # no velocity signal from a channel post itself
            "raw_json": {"chat_id": channel_id_str, "message_id": msg_id},
        }
        try:
            _, is_new = memory.insert_article(art, db_path=self.db_path)
            if is_new:
                logger.info("Telegram channel [%s]: new post ingested", channel_name)
        except Exception as exc:  # noqa: BLE001
            logger.error("Telegram channel ingest failed: %s", exc)

    # ------------------------------------------------------------ commands
    @staticmethod
    def _summary(p: dict, width: int = 90) -> str:
        score = f"{p['persona_score']:.0f}" if p.get("persona_score") is not None else "—"
        body = p["content"].replace("\n", " ")
        body = body if len(body) <= width else body[: width - 1] + "…"
        return f"#{p['id']} [{p['format']}] persona={score} — {body}"

    def _get(self, post_id: int) -> Optional[dict]:
        return memory.get_post(post_id, db_path=self.db_path)

    def handle(self, text: str) -> str:
        """One command in, one reply out. Never raises — errors become replies."""
        parts = text.split()
        cmd = parts[0].lower().lstrip("/").split("@")[0]
        args = parts[1:]
        try:
            if cmd in ("start", "help"):
                return HELP

            if cmd == "list":
                drafts = memory.get_posts(status="draft", db_path=self.db_path)
                if not drafts:
                    return "No pending drafts."
                return "Pending drafts:\n" + "\n".join(self._summary(p) for p in drafts[:15])

            if cmd == "outbox":
                box = memory.get_outbox(db_path=self.db_path)
                if not box:
                    return "Outbox empty — nothing approved and unposted."
                return "To post:\n" + "\n".join(self._summary(p) for p in box[:15])

            if cmd == "show":
                p = self._get(int(args[0]))
                return poster.format_draft_alert(p) if p else f"No draft #{args[0]}."

            if cmd == "approve":
                pid = int(args[0])
                p = self._get(pid)
                if not p:
                    return f"No draft #{pid}."
                memory.set_post_status(pid, "approved", db_path=self.db_path)
                p = self._get(pid)
                self.notifier.publish_to_channel(p)
                card = poster.make_card(p, db_path=self.db_path)
                if card:
                    self.notifier.send_photo(
                        card, caption=f"card for #{pid} — attach it when composing")
                return poster.format_approved_package(p, db_path=self.db_path)

            if cmd == "reject":
                pid = int(args[0])
                if not self._get(pid):
                    return f"No draft #{pid}."
                memory.set_post_status(pid, "rejected", db_path=self.db_path)
                reason = " ".join(args[1:]).strip()
                if reason:
                    from pipeline.feedback import record_reject
                    record_reject(pid, reason, db_path=self.db_path)
                return (f"❌ #{pid} rejected"
                        + (" — reason noted, the voice will learn from it."
                           if reason else " — tip: add a reason ('/reject "
                           f"{pid} too preachy') to teach the voice."))

            if cmd == "redo":
                pid = int(args[0])
                if not self._get(pid):
                    return f"No draft #{pid}."
                instruction = " ".join(args[1:]).strip()
                if not instruction:
                    return f"How should I change it? e.g. /redo {pid} make it sharper"
                from pipeline.feedback import regenerate_with_steer
                r = regenerate_with_steer(pid, instruction, db_path=self.db_path)
                if not r.get("ok"):
                    return f"Couldn't redo #{pid}: {r.get('error')}"
                return ("🔁 redone:\n"
                        + poster.format_draft_alert(
                            memory.get_post(pid, db_path=self.db_path)))

            if cmd == "posted":
                pid = int(args[0])
                if not self._get(pid):
                    return f"No draft #{pid}."
                url = args[1] if len(args) > 1 else None
                memory.mark_posted(pid, url=url, db_path=self.db_path)
                # File into long-term memory (stance / timeline / predictions).
                from pipeline.updater import MemoryUpdater
                report = MemoryUpdater().on_posted(pid, db_path=self.db_path)
                memo = (f"\n🧠 filed under '{report['topic']}'"
                        + (f" — prediction tracked: \"{report['prediction']}\""
                           if report.get("prediction") else "")
                        if report.get("ok") else "")
                return (f"🎯 #{pid} marked posted.{memo}\n"
                        f"Log engagement later with:\n"
                        f"/perf {pid} <likes> <retweets> <replies>")

            if cmd == "perf":
                pid = int(args[0])
                if not self._get(pid):
                    return f"No draft #{pid}."
                nums = [int(a) for a in args[1:5]]
                likes, rts, reps = (nums + [0, 0, 0])[:3]
                views = nums[3] if len(nums) > 3 else 0
                memory.record_engagement(pid, likes=likes, retweets=rts,
                                         replies=reps, views=views,
                                         db_path=self.db_path)
                from style.corpus import file_posted_draft
                filed = file_posted_draft(pid, db_path=self.db_path)
                return (f"📈 #{pid}: {likes} likes, {rts} RTs, {reps} replies logged."
                        + (" Filed into your voice corpus 🧬" if filed else "")
                        + " historical_perf will pick it up.")

            if cmd == "evergreen":
                accounts = memory.list_active_accounts(db_path=self.db_path)
                if not accounts:
                    return "No active accounts."
                # optional first arg is a handle; the rest is the topic
                acct = next((a for a in accounts if args and a["handle"] == args[0]),
                            None)
                topic_args = args[1:] if acct else args
                acct = acct or accounts[0]
                topic = " ".join(topic_args) or None
                from pipeline.evergreen import EvergreenGenerator
                draft = EvergreenGenerator(db_path=self.db_path).generate_for(
                    acct, topic=topic)
                if not draft or draft.get("empty"):
                    return ("Couldn't draft an evergreen — no stances/topics in "
                            "memory yet, or no Style DNA for this account.")
                return ("🌲 evergreen drafted:\n"
                        + poster.format_draft_alert(
                            memory.get_post(draft["post_id"], db_path=self.db_path)))

            return f"Unknown command. {HELP}"
        except (ValueError, IndexError):
            return f"Couldn't parse that. {HELP}"
        except Exception as exc:  # noqa: BLE001
            logger.error("Command '%s' failed: %s", text, exc)
            return f"Something broke handling '{text}': {exc}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
    memory.init_db()
    n = TelegramCommander().poll_once()
    print(f"Processed {n} command(s).")
