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
WINS_CHANNEL_ID = "1473901847009034383"
WINS_AUTHOR_ID = "1288282611034226709"
EXPECTED_USER = "TheBakerr_"
TAG = "@OddsJam"
PLATFORM_EMOJI = {"prizepicks": "🟣", "sleeper": "💤", "dabble": "🟣", "underdog": "🐶", "chalkboard": "⚪"}
# Catch bare domains too: leaving a bare domain can still create a paid URL post.
URL = re.compile(r"https?://[^\s<>]+|www\.[^\s<>]+|(?<![\w@])(?:[a-z0-9-]+\.)+[a-z]{2,63}(?::\d+)?(?:/[^\s<>]*)?", re.I)
CUSTOM_EMOJI = re.compile(r"<a?:([^:>]+):\d+>")
MENTION = re.compile(r"<[@#][!&]?\d+>|@everyone|@here", re.I)


class RelayError(Exception):
    pass


class AmbiguousPost(RelayError):
    """X might have accepted a post; never automatically retry it."""


def safe_error(exc: Exception) -> str:
    if isinstance(exc, requests.RequestException):
        return f"Network failure ({type(exc).__name__})"
    text = str(exc)
    for key, value in os.environ.items():
        if value and len(value) > 6 and any(word in key.upper() for word in ("SECRET", "TOKEN", "API_KEY")):
            text = text.replace(value, "[redacted]")
    text = re.sub(r"https?://\S+", "[URL]", text)
    return " ".join(text.split())[:600]


def api_failure(response, operation: str) -> RelayError:
    details = []
    try:
        body = response.json()
        if isinstance(body, dict):
            for key in ("title", "detail"):
                if isinstance(body.get(key), str):
                    details.append(body[key])
            for item in body.get("errors", []):
                if isinstance(item, dict) and isinstance(item.get("message"), str):
                    details.append(item["message"])
    except (ValueError, TypeError):
        pass
    error = RelayError(f"{operation} HTTP {response.status_code}" + (": " + "; ".join(details) if details else ""))
    return RelayError(safe_error(error))


def format_text(content: str) -> str:
    def emoji(match):
        name = match[1].lower()
        if "prize" in name or name in {"pp", "prizepicks"}:
            return "🟣"
        for platform, symbol in PLATFORM_EMOJI.items():
            if platform in name:
                return symbol
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
        header = re.fullmatch(r"[^A-Za-z0-9]*((prizepicks|sleeper|dabble|underdog|chalkboard)\s+free\s+play)[^A-Za-z0-9]*", line, re.I)
        if header:
            symbol = PLATFORM_EMOJI[header[2].lower()]
            line = f"{symbol} {header[1]} {symbol}"
        # These were directions to the removed link, not part of the play itself.
        if re.fullmatch(r"(?:tail(?:\s+the\s+play)?(?:\s+(?:it|here|below))*(?:\s+here)?|(?:click|tap|link)\s+(?:here|below)|get\s+your\s+entry\s+in|lock\s+in\s+your\s+picks|link|go\s+get\s+it\s+for\s+free)\s*[👇⬇⏬️:! .]*", line, re.I):
            continue
        if not line or re.fullmatch(r"[👇⬇️<>\s]+", line):
            if lines and lines[-1] != "":
                lines.append("")
            continue
        lines.append(line)
    text = "\n".join(lines).strip()
    # Add the approved tag exactly once, at the end.
    text = re.sub(r"(?<!\w)@OddsJam\b", "", text, flags=re.I)
    text = "\n\n".join(line.strip() for line in text.splitlines() if line.strip())
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


def format_win(message: dict) -> str:
    content = message.get("content", "")
    first_line = content.splitlines()[0] if content else ""
    names = [match[1].lower() for match in CUSTOM_EMOJI.finditer(first_line)]
    platforms = [name for name in PLATFORM_EMOJI if any(name in custom for custom in names) or re.search(rf"\b{name}\b", first_line, re.I)]
    if len(platforms) != 1:
        raise RelayError("Win platform is ambiguous; review manually")
    payouts = re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)\s*[xX]\s+PAYOUT\b", content, re.I)
    if len(payouts) != 1:
        raise RelayError("Win requires exactly one listed payout; review manually")
    if not message.get("attachments"):
        raise RelayError("Win requires a cashed-slip attachment")
    platform = platforms[0]
    lead = "CASH ANOTHER" if re.search(r"CASH\s+ANOTHER", first_line, re.I) else "CASH THE"
    lines = format_text(content).splitlines()
    lines[0] = f"{lead} {platform.upper()} PLAY POSTED IN VIP{PLATFORM_EMOJI[platform]}📈"
    for index, line in enumerate(lines):
        if "BAKER25" in line and "25%" in line:
            lines[index] = line.replace("🔗", "").rstrip(" 👇") + "👇"
    text = "\n\n".join(line.strip() for line in lines if line.strip())
    if re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)\s*[xX]\s+PAYOUT\b", text, re.I) != payouts:
        raise RelayError("Listed payout changed during formatting")
    validate_text(text)
    return text


def format_message(message: dict) -> str:
    return format_win(message) if message.get("channel_id") == WINS_CHANNEL_ID else format_text(message.get("content", ""))


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


def candidate(message: dict, channel_id: str | None = None) -> bool:
    # Skip system events and chatter, but allow plays from people, bots or webhooks.
    channel_id = channel_id or message.get("channel_id", CHANNEL_ID)
    if channel_id == WINS_CHANNEL_ID:
        content = message.get("content", "")
        first_line = content.splitlines()[0] if content else ""
        return (message.get("type", 0) in (0, 19)
                and message.get("author", {}).get("id") == WINS_AUTHOR_ID
                and bool(re.search(r"\bCASH\b.*\bPLAY\s+POSTED\s+IN\s+VIP\b", first_line, re.I))
                and f"<#{CHANNEL_ID}>" not in content)
    if channel_id != CHANNEL_ID:
        return False
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

    def validate_channel(self, channel_id=CHANNEL_ID):
        channel = self.get(f"/channels/{channel_id}")
        if channel.get("guild_id") != GUILD_ID:
            raise RelayError("Discord channel belongs to an unexpected server")

    def newest(self, channel_id=CHANNEL_ID):
        return self.get(f"/channels/{channel_id}/messages", limit=1)

    def since(self, cursor: str, channel_id=CHANNEL_ID) -> list[dict]:
        # Walk backwards from newest. This also catches >100 messages after downtime.
        messages, before = [], None
        while True:
            params = {"limit": 100}
            if before:
                params["before"] = before
            page = self.get(f"/channels/{channel_id}/messages", **params)
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
            raise api_failure(response, "X account verification")
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
            raise api_failure(response, "X media upload")
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
            raise api_failure(response, "X create post")
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
        if "channel_id" not in {row[1] for row in self.db.execute("PRAGMA table_info(jobs)")}:
            with self.db:
                self.db.execute(f"ALTER TABLE jobs ADD COLUMN channel_id TEXT NOT NULL DEFAULT '{CHANNEL_ID}'")

    def cursor(self, channel_id=CHANNEL_ID):
        key = "cursor" if channel_id == CHANNEL_ID else "cursor:" + channel_id
        row = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def ingest(self, messages: list[dict], cursor: str, channel_id=CHANNEL_ID):
        key = "cursor" if channel_id == CHANNEL_ID else "cursor:" + channel_id
        with self.db:
            for message in messages:
                if candidate(message, channel_id):
                    payload = {**message, "channel_id": channel_id}
                    self.db.execute("INSERT OR IGNORE INTO jobs(id,payload,channel_id) VALUES (?,?,?)", (message["id"], json.dumps(payload), channel_id))
            self.db.execute("INSERT INTO metadata(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, cursor))

    def claim(self, channel_id=CHANNEL_ID):
        # Atomic claim prevents concurrent workers posting the same job.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT * FROM jobs WHERE status='pending' AND channel_id=? ORDER BY length(id),id LIMIT 1", (channel_id,)).fetchone()
            if row:
                self.db.execute("UPDATE jobs SET status='sending' WHERE id=?", (row["id"],))
        return row

    def finish(self, message_id, status, *, post_id=None, error=None):
        with self.db:
            self.db.execute("UPDATE jobs SET status=?,post_id=?,error=? WHERE id=?", (status, post_id, error, message_id))

    def problems(self, channel_id=None):
        sql = "SELECT id,status,error FROM jobs WHERE status IN ('blocked','uncertain','sending')"
        return self.db.execute(sql + (" AND channel_id=?" if channel_id else ""), (channel_id,) if channel_id else ()).fetchall()


def poll(discord: Discord, store: Store, channel_id=CHANNEL_ID):
    cursor = store.cursor(channel_id)
    if cursor is None:
        page = discord.newest(channel_id)
        # Snowflake based on current time also handles an empty channel safely.
        cursor = page[0]["id"] if page else str((int(time.time() * 1000) - 1420070400000) << 22)
        store.ingest([], cursor, channel_id)
        LOG.info("Initialized channel %s at newest message; historical plays will not be posted", channel_id)
        return
    messages = discord.since(cursor, channel_id)
    if messages:
        store.ingest(messages, messages[-1]["id"], channel_id)


def deliver(store: Store, x: X, channel_id=CHANNEL_ID):
    problems = store.problems(channel_id)
    if problems:
        first = problems[0]
        raise RelayError(f"Delivery paused at {first['id']} ({first['status']}): {first['error'] or 'outcome requires review'}")
    while row := store.claim(channel_id):
        stage = "formatting"
        try:
            message = json.loads(row["payload"])
            text = format_message(message)
            if not text:
                store.finish(row["id"], "skipped", error="No play text after cleaning")
                continue
            attachments = image_attachments(message)
            # Refresh expiring attachment URLs without changing the captured play text.
            if attachments and hasattr(x, "discord"):
                stage = "refreshing attachments"
                fresh = x.discord.get(f"/channels/{channel_id}/messages/{row['id']}")
                by_id = {a["id"]: a for a in fresh.get("attachments", [])}
                attachments = [by_id[a["id"]] for a in attachments]
                image_attachments({"attachments": attachments})
            stage = "uploading images"
            media_ids = [x.upload(a) for a in attachments]
            stage = "publishing tweet"
            post_id = x.post(text, media_ids)
            store.finish(row["id"], "sent", post_id=post_id)
            LOG.info("Posted Discord message %s as X post %s", row["id"], post_id)
        except AmbiguousPost as exc:
            store.finish(row["id"], "uncertain", error=f"{stage}: {safe_error(exc)}")
            raise
        except (RelayError, requests.RequestException, ValueError, KeyError) as exc:
            detail = f"{stage}: {safe_error(exc) if isinstance(exc, (RelayError, requests.RequestException)) else type(exc).__name__}"
            store.finish(row["id"], "blocked", error=detail)
            LOG.error("Discord message %s failed during %s", row["id"], detail)
            raise RelayError(detail) from None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["preview", "check", "run", "status"])
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.local")
    parser.add_argument("--channel", choices=["free-plays", "icon-wins"], default="free-plays")
    args = parser.parse_args()
    load_dotenv(args.env_file)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", filename=os.getenv("RELAY_LOG_PATH") or None, encoding="utf-8")
    state_path = Path(os.getenv("RELAY_STATE_PATH", str(ROOT / ".local-free-play-relay.sqlite3")))
    if args.command == "status":
        store = Store(state_path)
        for row in store.db.execute("SELECT id,status,post_id,error FROM jobs ORDER BY length(id),id"):
            print(dict(row))
        return
    if not os.getenv("FREE_PLAY_DISCORD_BOT_TOKEN"):
        raise RelayError("Missing FREE_PLAY_DISCORD_BOT_TOKEN")
    discord = Discord(os.environ["FREE_PLAY_DISCORD_BOT_TOKEN"])
    channel_id = WINS_CHANNEL_ID if args.channel == "icon-wins" else CHANNEL_ID
    channels = [CHANNEL_ID] + ([WINS_CHANNEL_ID] if os.getenv("RELAY_ICON_WINS_ENABLED", "false").lower() == "true" else [])
    for configured_channel in set(channels + [channel_id]):
        discord.validate_channel(configured_channel)
    if args.command == "preview":
        for message in discord.get(f"/channels/{channel_id}/messages", limit=50):
            if candidate(message, channel_id):
                print(format_message({**message, "channel_id": channel_id}))
                print(f"\nImages: {len(image_attachments(message))}; no post sent")
                return
        raise RelayError("No qualifying message found; check channel, author and Message Content Intent")
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
        for configured_channel in channels:
            try:
                poll(discord, store, configured_channel)
                deliver(store, x, configured_channel)
            except (RelayError, requests.RequestException) as exc:
                LOG.error("Channel %s check failed: %s. No automatic retry of failed posts.", configured_channel, safe_error(exc))
        time.sleep(interval)


if __name__ == "__main__":
    try:
        main()
    except RelayError as exc:
        LOG.error("%s", exc)
        raise SystemExit(1) from None
