# Optional MTProto capture of expiring photos

The main bot continues using Telegram Bot API and works without MTProto.

The optional owner-account watcher uses Telethon to capture self-destructing photos that are actually retrievable by your own Telegram account. It handles both an arriving TTL photo and an outgoing reply to an earlier TTL photo. Files go to the persistent media volume at /app/data/photos/mtproto. They are not automatically forwarded on arrival. Deleted-message alerts and daily reports keep their existing behavior.

**No 100% guarantee:** Telegram can omit media from API updates, invalidate references, or deny downloads. Even a user-account session cannot bypass a server refusal, expired file, inaccessible message, or account restrictions.

## Authorization (opt-in)

A Telegram StringSession is equivalent to account credentials. Do not share it in chats or commit it to GitHub.

1. On a trusted local computer install Python and dependencies: python -m pip install -r requirements.txt
2. Obtain a personal api_id and api_hash at https://my.telegram.org.
3. Set TELEGRAM_API_ID and TELEGRAM_API_HASH as local environment variables.
4. Run python generate_mtproto_session.py and authenticate with your phone, login code, and two-step password if prompted.
5. Privately add these Railway Variables: MT_PROTO_ENABLED=true, TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION (the generated StringSession).
6. Confirm the persistent Railway volume is mounted at /app/data (DATABASE_PATH=/app/data/archive.sqlite3). The watcher saves photos under /app/data/photos/mtproto.
7. Redeploy and use /expiring_status, /expiring_list and /photo_stats in your private bot chat.

The watcher checks the account ID against BOT_OWNER_ID and exits if they differ. It cannot silently authorize an account; the session must be authorized before Railway starts.

## Accessing stored photos

/expiring_list shows the 15 most recent saved chat/message IDs.
/expiring_send CHAT_ID MESSAGE_ID sends that stored photo to your private bot chat on request.
Deletion notifications also attach a matching archived MTProto photo when Telegram reports deletion to the Business bot.
The watcher does not call OpenAI.

## Security and limitations

- Protect your Railway project, its private variables, and persistent photo volume.
- If the session leaks, revoke it from Telegram Settings > Devices.
- To stop monitoring, set MT_PROTO_ENABLED=false and redeploy. Existing files remain until deliberately removed.
- Telegram Bot API documentation says reply_to_message can be omitted for a reply to an ephemeral message. MTProto is a different user-account connection with separate limitations.
- Only private-chat TTL photos are handled. Video, voice, stories, and Telegram secret chats are not supported.
