"""Dedicated Discord -> X worker. No dashboard or existing bot changes required."""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

LOG = logging.getLogger("free_play_relay")
ROOT = Path(__file__).resolve().parent.parent
GUILD_ID = "1255342800258596898"
CHANNEL_ID = "1464472206334496829"
EXPECTED_USER = "TheBakerr_"
TAG = "@OddsJam"
# Catch bare domains too: leaving a bare domain can still create a paid URL post.
URL = re.compile(r"https?://[^\s<>]+|www\.[^\s<>]+|(?<![\w@])(?:[a-z0-9-]+\.)+[a-z]{2,63}(?::\d+)?(?:/[^\s<>]*)?", re.I)
CUSTOM_EMOJI = re.compile(r"<a?:([^:>]+):\d+>")
MENTION = re.compile(r"<[@#][!&]?\d+>|@everyone|@here", re.I)


class RelayError(Exception):
    pass


class AmbiguousPost(RelayError):
    """X might have accepted a post; never automatically retry it."""


def format_text(content: str) -> str:
    def emoji(match):
        name = match[1].lower()
        if "prize" in name or name in {"pp", "prizepicks"}:
            return "🟣"
        if "sleeper" in name:
            return "🪩"
        return ""  # Unknown Discord-only emojis have no portable representation.

    text = CUSTOM_EMOJI.sub(emoji, content)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = URL.sub("", text)
    text = MENTION.sub("", text)
    text = re.sub(r"\*\*|__|~~|`+|\|\|", "", text)
    lines = []
    for raw in text.splitlines():
        line = raw.strip().strip("<>").strip()
        line = re.sub(r"^#{1,3}\s+|^>\s?", "", line)
        # These were directions to the removed link, not part of the play itself.
        if re.fullmatch(r"(?:tail(?:\s+the\s+play)?(?:\s+(?:it|here|below))*(?:\s+here)?|(?:click|tap|link)\s+(?:here|below))\s*[👇⬇️:! .]*", line, re.I):
            continue
        if not line or re.fullmatch(r"[👇⬇️<>\s]+", line):
            if lines and lines[-1] != "":
                lines.append("")
            continue
        lines.append(line)
    text = "\n".join(lines).strip()
    # Add the approved tag exactly once, at the end.
    text = re.sub(r"(?<!\w)@OddsJam\b", "", text, flags=re.I)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return ""
    text += "\n\n" + TAG
    validate_text(text)
    return text


def validate_text(text: str) -> None:
    if URL.search(text):
        raise RelayError("URL detected: refusing to create a URL-priced post")
    # Conservative upper bound on X's weighted count (emoji clusters may overcount).
    weight = sum(1 if (ord(c) <= 0x10FF or 0x2000 <= ord(c) <= 0x200D or 0x2010 <= ord(c) <= 0x201F or 0x2032 <= ord(c) <= 0x2037) else 2 for c in text)
    if weight > 280:
        raise RelayError("Post exceeds the conservative 280-character limit; review manually")


def image_attachments(message: dict) -> list[dict]:
    images = []
    for item in message.get("attachments", []):
        media_type = item.get("content_type", "")
        if media_type in {"image/jpeg", "image/png", "image/webp"}:
            if int(item.get("size", 0)) > 5 * 1024 * 1024:
                raise RelayError("Attachment exceeds X's 5 MB image limit")
            images.append(item)
        else:
            raise RelayError("Unsupported attachment: manual review required")
    if len(images) > 4:
        raise RelayError("More than four images: manual review required")
    return images


def candidate(message: dict) -> bool:
    # Skip system events and chatter, but allow plays from people, bots or webhooks.
    return message.get("type", 0) in (0, 19) and bool(re.search(r"free\s*play", message.get("content", ""), re.I))


class Discord:
    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": "Bot " + token, "User-Agent": "IconLabsFreePlayRelay/1.0"})

    def get(self, path: str, **params):
        response = self.session.get("https://discord.com/api/v10" + path, params=params, timeout=30)
        if response.status_code == 429:
            raise RelayError("Discord rate limited; will retry next poll")
        if not response.ok:
            raise RelayError(f"Discord HTTP {response.status_code}")
        return response.json()

    def validate_channel(self):
        channel = self.get(f"/channels/{CHANNEL_ID}")
        if channel.get("guild_id") != GUILD_ID:
            raise RelayError("Discord channel belongs to an unexpected server")

    def newest(self):
        return self.get(f"/channels/{CHANNEL_ID}/messages", limit=1)

    def since(self, cursor: str) -> list[dict]:
        # Walk backwards from newest. This also catches >100 messages after downtime.
        messages, before = [], None
        while True:
            params = {"limit": 100}
            if before:
                params["before"] = before
            page = self.get(f"/channels/{CHANNEL_ID}/messages", **params)
            if not page:
                break
            messages.extend(m for m in page if int(m["id"]) > int(cursor))
            oldest = min(page, key=lambda m: int(m["id"]))["id"]
            if int(oldest) <= int(cursor) or len(page) < 100:
                break
            before = oldest
        return sorted(messages, key=lambda m: int(m["id"]))


class X:
    def __init__(self):
        from requests_oauthlib import OAuth1Session
        required = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]
        missing = [key for key in required if not os.getenv(key)]
        if missing:
            raise RelayError("Missing configuration: " + ", ".join(missing))
        self.session = OAuth1Session(os.environ[required[0]], client_secret=os.environ[required[1]], resource_owner_key=os.environ[required[2]], resource_owner_secret=os.environ[required[3]])

    def verify_account(self):
        response = self.session.get("https://api.x.com/2/users/me", timeout=30)
        if not response.ok:
            raise RelayError(f"X account verification HTTP {response.status_code}")
        if response.json().get("data", {}).get("username", "").lower() != EXPECTED_USER.lower():
            raise RelayError("X credentials are for the wrong account")

    def upload(self, attachment: dict) -> str:
        url = attachment["url"]
        if urlparse(url).scheme != "https" or urlparse(url).hostname not in {"cdn.discordapp.com", "media.discordapp.net"}:
            raise RelayError("Untrusted image host")
        # Never send the Discord bot token or X credentials to an image URL.
        with requests.get(url, timeout=30, stream=True, allow_redirects=False) as response:
            if not response.ok or response.is_redirect:
                raise RelayError(f"Image download HTTP {response.status_code}")
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > 5 * 1024 * 1024:
                    raise RelayError("Downloaded image exceeds 5 MB")
        response = self.session.post("https://api.x.com/2/media/upload", json={"media": base64.b64encode(data).decode("ascii"), "media_category": "tweet_image", "media_type": attachment["content_type"]}, timeout=60)
        if not response.ok:
            raise RelayError(f"X media upload HTTP {response.status_code}")
        media_id = response.json().get("data", {}).get("id")
        if not media_id:
            raise RelayError("X media upload returned no ID")
        return str(media_id)

    def post(self, text: str, media_ids: list[str]) -> str:
        validate_text(text)
        payload = {"text": text}
        if media_ids:
            payload["media"] = {"media_ids": media_ids}
        try:
            response = self.session.post("https://api.x.com/2/tweets", json=payload, timeout=45)
        except requests.RequestException:
            raise AmbiguousPost("X post outcome unknown; inspect the timeline before any retry") from None
        if response.status_code >= 500:
            raise AmbiguousPost("X server error: inspect the timeline before any retry")
        if not response.ok:
            raise RelayError(f"X create post HTTP {response.status_code}")
        try:
            post_id = response.json()["data"]["id"]
        except (ValueError, KeyError, TypeError):
            raise AmbiguousPost("X post response incomplete: inspect the timeline") from None
        return str(post_id)


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                post_id TEXT, error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        """)

    def cursor(self):
        row = self.db.execute("SELECT value FROM metadata WHERE key='cursor'").fetchone()
        return row[0] if row else None

    def ingest(self, messages: list[dict], cursor: str):
        with self.db:
            for message in messages:
                if candidate(message):
                    self.db.execute("INSERT OR IGNORE INTO jobs(id,payload) VALUES (?,?)", (message["id"], json.dumps(message)))
            self.db.execute("INSERT INTO metadata(key,value) VALUES ('cursor',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (cursor,))

    def claim(self):
        # Atomic claim prevents concurrent workers posting the same job.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY length(id),id LIMIT 1").fetchone()
            if row:
                self.db.execute("UPDATE jobs SET status='sending' WHERE id=?", (row["id"],))
        return row

    def finish(self, message_id, status, *, post_id=None, error=None):
        with self.db:
            self.db.execute("UPDATE jobs SET status=?,post_id=?,error=? WHERE id=?", (status, post_id, error, message_id))

    def problems(self):
        return self.db.execute("SELECT id,status,error FROM jobs WHERE status IN ('blocked','uncertain','sending')").fetchall()


def poll(discord: Discord, store: Store):
    cursor = store.cursor()
    if cursor is None:
        page = discord.newest()
        # Snowflake based on current time also handles an empty channel safely.
        cursor = page[0]["id"] if page else str((int(time.time() * 1000) - 1420070400000) << 22)
        store.ingest([], cursor)
        LOG.info("Initialized at newest message; historical plays will not be posted")
        return
    messages = discord.since(cursor)
    if messages:
        store.ingest(messages, messages[-1]["id"])


def deliver(store: Store, x: X):
    if store.problems():
        raise RelayError("Delivery paused: a blocked/uncertain/in-flight job needs manual review")
    while row := store.claim():
        try:
            message = json.loads(row["payload"])
            text = format_text(message.get("content", ""))
            if not text:
                store.finish(row["id"], "skipped", error="No play text after cleaning")
                continue
            attachments = image_attachments(message)
            # Refresh expiring attachment URLs without changing the captured play text.
            if attachments and hasattr(x, "discord"):
                fresh = x.discord.get(f"/channels/{CHANNEL_ID}/messages/{row['id']}")
                by_id = {a["id"]: a for a in fresh.get("attachments", [])}
                attachments = [by_id[a["id"]] for a in attachments]
                image_attachments({"attachments": attachments})
            media_ids = [x.upload(a) for a in attachments]
            post_id = x.post(text, media_ids)
            store.finish(row["id"], "sent", post_id=post_id)
            LOG.info("Posted Discord message %s as X post %s", row["id"], post_id)
        except AmbiguousPost as exc:
            store.finish(row["id"], "uncertain", error=str(exc))
            raise
        except (RelayError, requests.RequestException, ValueError, KeyError):
            store.finish(row["id"], "blocked", error="Delivery failed; check credentials, credits, attachments and text")
            raise RelayError("Delivery paused; inspect status before retrying") from None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["preview", "check", "run", "status"])
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.local")
    args = parser.parse_args()
    load_dotenv(args.env_file)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    state_path = Path(os.getenv("RELAY_STATE_PATH", str(ROOT / ".local-free-play-relay.sqlite3")))
    if args.command == "status":
        store = Store(state_path)
        for row in store.db.execute("SELECT id,status,post_id,error FROM jobs ORDER BY length(id),id"):
            print(dict(row))
        return
    if not os.getenv("FREE_PLAY_DISCORD_BOT_TOKEN"):
        raise RelayError("Missing FREE_PLAY_DISCORD_BOT_TOKEN")
    discord = Discord(os.environ["FREE_PLAY_DISCORD_BOT_TOKEN"])
    discord.validate_channel()
    if args.command == "preview":
        for message in discord.get(f"/channels/{CHANNEL_ID}/messages", limit=50):
            if candidate(message):
                print(format_text(message["content"]))
                print(f"\nImages: {len(image_attachments(message))}; no post sent")
                return
        raise RelayError("No free-play message found; check Message Content Intent")
    x = X()
    x.discord = discord
    x.verify_account()
    if args.command == "check":
        LOG.info("Discord channel and X account verified; no posts sent")
        return
    if os.getenv("RELAY_POSTING_ENABLED", "false").lower() != "true":
        raise RelayError("Set RELAY_POSTING_ENABLED=true only after preview/check and funding X credits")
    store = Store(state_path)
    interval = max(15, int(os.getenv("RELAY_POLL_SECONDS", "30")))
    while True:
        try:
            poll(discord, store)
            deliver(store, x)
        except (RelayError, requests.RequestException):
            LOG.error("Relay check failed; run status and check credentials/credits. No automatic retry of failed posts.")
        time.sleep(interval)


if __name__ == "__main__":
    try:
        main()
    except RelayError as exc:
        LOG.error("%s", exc)
        raise SystemExit(1) from None
