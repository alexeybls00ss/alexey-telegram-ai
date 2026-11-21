# Alexey Telegram AI

Private Telegram Business archive and personal conversation assistant.

## Features
- Receives Telegram Business connection, new-message, edited-message and deleted-message updates for chats explicitly granted to the bot.
- Stores message text/captions, attachment markers, chat and sender metadata, timestamps and edit/delete state in SQLite.
- Labels messages from the connected account owner separately from interlocutors when Telegram supplies sender identity.
- Supports /start, /id, /help, /status, /search, /report and /analyze.
- Ranks keyword search results and can use saved daily chat summaries as additional context for natural-language questions sent to the bot.
- Automatically analyzes the previous calendar day at 00:05 Europe/Istanbul and sends a daily report to the configured owner.
- Saves daily reports and per-chat summaries in SQLite for later retrieval.
- Restricts archive access by numeric Telegram user ID.

## Daily reports
The report reviews all archived messages for each local calendar day and groups them by chat. It summarizes topics, chronology, facts, plans, dates, commitments, open questions and details worth remembering. It distinguishes messages from the account owner and other participants when sender IDs are available.

Commands:
- `/report` — show the latest saved report.
- `/report YYYY-MM-DD` — show a report for a specific date.
- `/analyze` — regenerate yesterday's report.
- `/analyze YYYY-MM-DD` — regenerate a report for the specified date.
- `/chats` — list chats currently present in the archive with their Telegram chat IDs and message counts.
- `/analyze_chat CHAT_ID` — analyze the full archived history of one private chat, including both participants.
- `/report_chat CHAT_ID` — retrieve the most recently saved analysis for that chat.
- `/import` — show instructions, then send a Telegram Desktop JSON export to the bot as a document to import it.

The daily task runs inside the single Uvicorn process. Keep one replica / one worker for this deployment to avoid duplicate scheduled runs. If the service is down around the scheduled time, it catches up the previous day's missing report after the service comes back online.

## Limitations
- Telegram does not provide a Bot API method to backfill old chat history. Telegram Desktop JSON exports can be imported by sending the `.json` document to the private bot chat; import is restricted to exports containing the configured `BOT_OWNER_ID` and personal chats.
- Only chats selected and permitted in the Telegram Business connection can be processed; this does not grant access to every Telegram chat, group or channel automatically.
- Attachment contents are not downloaded or transcribed yet; only markers for photos, audio, documents and other attachment types are stored.
- Search remains keyword-based with relevance ranking, not full semantic/vector search. Daily summaries improve context retrieval but do not replace original messages.
- Selected-chat analysis uses the Telegram private chat ID (the private chat ID normally matches the other person's user ID). It selects the exact chat ID, not all messages authored by that user in groups.
- The Telegram bot can answer questions using its own archive. This repository does not automatically connect this database to a separate ChatGPT conversation; reports can be retrieved from the bot and shared in ChatGPT.
- AI summaries are generated from message text sent to the configured OpenAI API project. API billing is separate from ChatGPT.

## Telegram setup
1. Keep Secretary Mode enabled in @BotFather.
2. Connect @aialexey11_bot via Telegram Business / Chat Automation and choose the chats.
3. Grant only the rights the archive actually needs. Message updates do not require permission to mark chats as read or delete messages.
4. After deployment, send /id to the bot; set BOT_OWNER_ID to that number.
5. Confirm /status and test /search using a low-sensitivity chat.

## Deploy
Deploy as a single-replica Docker service on Railway, Render or another HTTPS container host. Add these protected environment variables:
- TELEGRAM_BOT_TOKEN: newly rotated token; never commit or share it.
- OPENAI_API_KEY: API key for the OpenAI API project.
- BOT_OWNER_ID: numeric ID returned by /id.
- WEBHOOK_URL: public HTTPS base URL of this service.
- TELEGRAM_WEBHOOK_SECRET: random secret of 32+ characters, letters/numbers/_/- only.
- OPENAI_MODEL: model available to your API project (example: gpt-5.4-mini).
- DATABASE_PATH=/app/data/archive.sqlite3.
- APP_TIMEZONE=Europe/Istanbul (optional; this is the default).

Attach a persistent volume at /app/data. The app sets the Telegram webhook on startup and starts the daily scheduler. Verify /health, then send /status to the bot.

## Security
- Never send tokens or API keys in chat or Git commits.
- Keep the repository private.
- The database contains private messages; restrict access and backups.
- Revoke and rotate an exposed bot token immediately.
- Telegram Business access can be revoked in Telegram settings.
