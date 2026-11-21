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


## Smart OpenAI API model routing (2026-11)

The bot uses an explicit, allowlisted three-tier router:

- **Simple lookups:** GPT-5.4 nano (gpt-5.4-nano), e.g. short questions asking who/where/when or to find a message.
- **Chat analysis, all daily reports and ambiguous/complex questions:** GPT-5.4 mini (gpt-5.4-mini).
- **Deep reasoning:** GPT-5.4 (gpt-5.4) ONLY after the owner sends /deep Твой вопрос and confirms the one-time code using /confirm CODE within 10 minutes. Unconfirmed text never activates this tier.

Routing is rule-based: no extra classification API calls are billed. All analysis batches and automatic reports default to Mini; Nano is used for short, simple interactive questions only. No implicit premium escalation, including requests quoting archived text. /cancel cancels an awaiting request.

Owner-only commands:

- /model - model routing details and prices per 1M text tokens.
- /usage - recorded successful API calls, token counts, estimated cost in USD for 24h, 30d and all time, by model.
- /deep ВОПРОС - request a one-time confirmed premium question; maximum question length 1,800 characters.
- /confirm CODE - confirm a pending premium question (or a supported analysis job).

Price table (USD per 1M standard text tokens, checked 2026-11-21; input / cached input / output): Nano 0.20/0.02/1.25; Mini 0.75/0.075/4.50; GPT-5.4 2.50/0.25/15.00. See [OpenAI pricing](https://developers.openai.com/api/docs/pricing). These prices are a snapshot, not live billing. The [nano model page](https://developers.openai.com/api/docs/models/gpt-5.4-nano) marks a dated snapshot as deprecated; monitor model availability.

The existing api_usage SQLite table is migrated without deleting legacy rows. New columns: tier, cached_input_tokens, estimated_cost_usd. Older rows have NULL cost and are excluded from USD totals; /usage labels the number of such rows. Costs are estimated from the Responses API usage for successful responses (including cached input) using the published token prices. It is not the authoritative OpenAI invoice: failed calls, tax, other API features or future pricing changes may differ.

Existing ANALYSIS_BUDGET_USD (default 0.10) applies to multi-call analysis jobs. PREMIUM_BUDGET_USD (default 0.30) controls the estimated pre-call guard for a premium one-off request. These are best-effort estimates, not guaranteed payment ceilings. Configure billing/spend limits at OpenAI Platform. The legacy Railway variable OPENAI_MODEL is deliberately ignored after this change to prevent accidental global premium selection.


## Direct read-only Telegram archive link (2026-11-21)

The owner can now issue an unguessable read-only URL with /sync_link in their private Telegram conversation with the bot. The link opens the /bridge portal, chat list, individual chat messages, search, status, and notes without a repeated one-time-code login or TinyFish cookie persistence. Access is **not public**: anyone with the secret link can view the archive, so keep it private and never paste it in public channels, tickets, code, or screenshots.

- Sending /sync_link again immediately rotates the secret, invalidating the previous URL.
- /sync_revoke immediately disables all direct read-link access.
- Only the Telegram owner (BOT_OWNER_ID) can request or revoke the link.
- The randomly generated token is stored in SQLite only as a SHA-256 hash.
- Direct links grant GET-only *read* access, not POST or modification of shared notes or archive data.
- Original browser cookie login remains supported for legacy sessions; anonymous /bridge/chats stays blocked.
- Site responses use no-store and no-referrer headers to reduce token/data leakage.
- Uvicorn access logging is disabled: its default URL logs would otherwise disclose the bearer query token. Railway and other proxy/network systems may still see request URLs.

**Security:** The URL is effectively a password to all currently accessible chat data. It has no automatic expiry until rotated or revoked. Do not expose it publicly or grant it to untrusted websites/apps. For extra assurance, run /sync_revoke to disable it.
