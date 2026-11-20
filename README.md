# Alexey Telegram AI

Private Telegram Business archive and personal assistant.

## Features
- Receives Telegram Business connection, new-message, edited-message and deleted-message updates.
- Stores message text/captions and chat, sender and timestamp metadata in SQLite.
- Supports /start, /id, /help, /status and /search.
- Answers natural-language questions using OpenAI Responses API and archive snippets.
- Restricts archive access by numeric Telegram user ID.
- Does not send messages into personal chats, mark them read or delete them.

## Limitations
- Attachment content is not downloaded or transcribed; only markers for attachments are stored.
- Telegram Bot API cannot backfill old chat history. Only updates received after deployment and connection are archived.
- Search is keyword-based, not semantic/vector search.
- Test with a low-sensitivity chat before connecting additional conversations.

## Telegram setup
1. Keep Secretary Mode enabled in @BotFather.
2. Connect @aialexey11_bot via Telegram Business / Chat Automation and choose the chats.
3. Grant minimum rights. This release does not need reply, read-marking or delete rights.
4. After deployment, send /id to the bot; set BOT_OWNER_ID to that number.

## Deploy
Deploy as a Docker service on Railway, Render or another HTTPS container host. Add these protected environment variables:
- TELEGRAM_BOT_TOKEN: newly rotated token; never commit or share it.
- OPENAI_API_KEY: API key (API billing is separate from ChatGPT).
- BOT_OWNER_ID: numeric ID returned by /id.
- WEBHOOK_URL: public HTTPS base URL of this service.
- TELEGRAM_WEBHOOK_SECRET: random secret of 32+ characters, letters/numbers/_/- only.
- OPENAI_MODEL: model available to your API project (example: gpt-5.4-mini).
- DATABASE_PATH=/app/data/archive.sqlite3.

Attach a persistent volume at /app/data. The app sets Telegram webhook on startup. Verify /health and then send /status to the bot.

## Security
- Never send tokens or API keys in chat or Git commits.
- Keep the repository private.
- The database contains private messages; restrict access and backups.
- Revoke and rotate an exposed bot token immediately.
- Telegram Business access can be revoked in Telegram settings.
