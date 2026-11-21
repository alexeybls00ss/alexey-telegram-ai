"""Optional Telegram *user-account* media watcher.

This is not Bot API. It runs only with an explicitly provided StringSession
belonging to the configured owner. The user must authenticate locally first.
Only self-destructing PHOTO media in private chats is considered.

No photo is posted when received. The main app decides how long to retain it
and when to notify the owner.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
from pathlib import Path
from typing import Awaitable, Callable

from telethon import TelegramClient, events
from telethon.sessions import StringSession

log = logging.getLogger("alexey-telegram-ai.mtproto")


def is_ttl_photo(message) -> bool:
    media = getattr(message, "media", None)
    ttl = getattr(media, "ttl_seconds", None)
    photo = getattr(media, "photo", None)
    return photo is not None and type(ttl) is int and ttl > 0


async def watch_expiring_photos(
    *,
    api_id: int,
    api_hash: str,
    session: str,
    owner_id: int,
    media_root: Path,
    max_bytes: int,
    on_saved: Callable[[int, int, Path, int, str], Awaitable[None]],
) -> None:
    """Capture only media the authorized Telegram user account can retrieve.

    Both an arriving TTL photo and an outgoing reply to one are handled.
    Each is saved once to a dedicated directory; the callback writes metadata.
    """
    client = TelegramClient(StringSession(session), int(api_id), api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram user session is not authorized")
        own = await client.get_me()
        if not own or own.id != int(owner_id):
            raise RuntimeError("MTProto session owner does not match BOT_OWNER_ID")
        folder = media_root / "mtproto"
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(folder, 0o700)
        log.info("Optional MTProto watcher authorized for the configured account")

        async def capture(message, chat_id, source):
            if not is_ttl_photo(message):
                return
            if type(chat_id) is not int or type(message.id) is not int:
                return
            media = message.media
            ttl = media.ttl_seconds
            digest = hashlib.sha256(
                f"{chat_id}:{message.id}".encode("utf-8")).hexdigest()
            target = folder / f"{digest}.jpg"
            if target.is_file():
                await on_saved(chat_id, message.id, target, ttl, source)
                return
            temp = folder / f"{digest}-{secrets.token_hex(8)}.jpg"
            try:
                saved = await client.download_media(message, file=str(temp))
                if not saved:
                    log.info("TTL photo file unavailable via MTProto (chat/message recorded only in logs)")
                    return
                result = Path(saved)
                if not result.is_file():
                    return
                size = result.stat().st_size
                if size <= 0 or size > max_bytes:
                    log.warning("TTL photo omitted due to empty or over-limit file")
                    return
                os.replace(result, target)
                os.chmod(target, 0o600)
                await on_saved(chat_id, message.id, target, ttl, source)
            except Exception as exc:
                # Never leak access hashes, media bytes, session data or file refs.
                log.warning("TTL media could not be retrieved: %s", type(exc).__name__)
            finally:
                temp.unlink(missing_ok=True)

        @client.on(events.NewMessage)
        async def on_message(event):
            if not event.is_private:
                return
            try:
                message = event.message
                await capture(message, int(event.chat_id), "incoming")
                if message.out and message.reply_to_msg_id:
                    original = await event.get_reply_message()
                    if original is not None:
                        await capture(original, int(event.chat_id), "reply")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("MTProto message handler failed: %s", type(exc).__name__)

        await client.run_until_disconnected()
    finally:
        await client.disconnect()
