"""
reddit_auth.py — Reddit OAuth (script-type app credentials).

Reddit blocks datacenter IPs (Railway, etc.) when using plain unauthenticated
requests against www.reddit.com.  A 'script'-type app credential authenticates
the app, switches the base URL to oauth.reddit.com, and lifts that block.

SETUP (5 minutes):
  1. reddit.com/prefs/apps → Create Another App → type: script
     Name: pulse-agent  |  redirect: http://localhost  (ignored for scripts)
  2. Copy the client_id (the string directly under the app name, not the secret)
     and the client_secret.
  3. Add to .env:
       REDDIT_CLIENT_ID=<client_id>
       REDDIT_CLIENT_SECRET=<client_secret>
       REDDIT_USERNAME=<your reddit username>

Without credentials the module silently falls back to keyless requests
(www.reddit.com) — this works fine on local dev but gets 403 on Railway.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger("watch.reddit_auth")

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
OAUTH_BASE = "https://oauth.reddit.com"
WWW_BASE = "https://www.reddit.com"
_EXPIRE_BUFFER_S = 60   # refresh this many seconds before actual expiry


class RedditAuth:
    """Bearer-token manager for a Reddit 'script' app credential.
    Tokens last 1 hour; the class re-fetches automatically on expiry."""

    def __init__(self, client_id: str, client_secret: str, username: str,
                 version: str = "0.1"):
        self._id = client_id
        self._secret = client_secret
        # Reddit API rules: UA must identify the platform, app id, version, and author.
        self._ua = f"python:pulse-agent:{version} (by /u/{username})" if username \
            else "python:pulse-agent:0.1 (single-user content agent)"
        self._token: Optional[str] = None
        self._expires_at: float = 0.0

    @property
    def configured(self) -> bool:
        return bool(self._id and self._secret)

    @property
    def base_url(self) -> str:
        """oauth.reddit.com when credentials are set; www.reddit.com otherwise."""
        return OAUTH_BASE if self.configured else WWW_BASE

    def headers(self) -> dict:
        """Request headers — OAuth bearer when configured, plain UA otherwise.
        Falls back to keyless on token failure so the watcher never hard-crashes."""
        if not self.configured:
            return {"User-Agent": self._ua}
        try:
            tok = self._fresh_token()
            return {"User-Agent": self._ua, "Authorization": f"Bearer {tok}"}
        except Exception as exc:  # noqa: BLE001
            logger.error("Reddit OAuth token failed; falling back to keyless: %s", exc)
            return {"User-Agent": self._ua}

    # ----------------------------------------------------------------- private

    def _fresh_token(self) -> str:
        if self._token and time.time() < self._expires_at - _EXPIRE_BUFFER_S:
            return self._token
        return self._fetch_token()

    def _fetch_token(self) -> str:
        resp = requests.post(
            TOKEN_URL,
            auth=(self._id, self._secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": self._ua},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._expires_at = time.time() + int(data.get("expires_in", 3600))
        logger.info("Reddit OAuth token fetched (expires in %ds)",
                    data.get("expires_in", 3600))
        return self._token


# ---------------------------------------------------------------- module-level singleton

_singleton: Optional[RedditAuth] = None


def default_auth() -> RedditAuth:
    """Lazily builds and caches the singleton from current settings.
    Both watch/reddit.py and watch/discover.py share this instance."""
    global _singleton
    if _singleton is None:
        from config import settings
        _singleton = RedditAuth(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            username=settings.reddit_username,
        )
    return _singleton
