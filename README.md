# Voice Agent — Personal Voice-to-Action Bot

A personal Telegram agent: send a voice note or text, and it transcribes (Whisper via Groq's free API),
classifies intent with Claude (`claude-sonnet-4-6`), and writes a **note**, **task**, or
**draft** to Notion — or searches your existing Notion content. It replies in Telegram
confirming what it did with a link to the Notion page.

## How it works

```
Telegram (voice/text)
   └─ bot.py        receives the update, gates on your user ID
        ├─ voice → transcriber.py (Whisper) → transcript
        └─ text  → used as-is
            └─ agent.py    Claude classifies intent + calls a tool
                 └─ notion_client_wrapper.py   writes to the right Notion DB
            └─ reply with confirmation + Notion link
```

Files: `config.py` (env), `notion_client_wrapper.py` (Notion SDK calls),
`agent.py` (Claude tool-use loop), `transcriber.py` (Whisper), `bot.py` / `main.py`
(Telegram, long polling), `prompts/system.md` (the agent's brain).

> Note: the Notion wrapper module is `notion_client_wrapper.py`, not `notion_client.py`,
> so it doesn't shadow the installed `notion-client` package.

## One-time setup

1. **Telegram** — create a bot with [@BotFather](https://t.me/BotFather) for the token;
   message [@userinfobot](https://t.me/userinfobot) for your numeric user ID.
2. **Notion** — create three full-page databases (**Notes**, **Tasks**, **Drafts**) with
   the schemas below. Create an internal integration
   (https://www.notion.so/my-integrations), copy its token (`ntn_…`), and **share each
   database with the integration** (database → ••• → Connections). Copy each database ID
   (the 32-char string in the database URL).
3. **Keys** — get a free [Groq API key](https://console.groq.com/keys) (Whisper transcription)
   and an Anthropic API key from [console.anthropic.com](https://console.anthropic.com). Note: the
   Anthropic API is pay-as-you-go and separate from a Claude Pro subscription — Pro does not include
   API access.

### Notion database schemas

**Notes:** `Title` (title), `Content` (rich text), `Tags` (multi-select),
`Source` (select), `Created` (created time).

**Tasks:** `Task` (title), `Due Date` (date), `Priority` (select: High/Medium/Low),
`Status` (status: Not started/In progress/Done), `Context` (rich text),
`Source` (select), `Created` (created time).

**Drafts:** `Title` (title), `Type` (select: LinkedIn/Email/Blog/Twitter/Other),
`Content` (rich text), `Status` (select: Draft/Ready/Published), `Brief` (rich text),
`Source` (select), `Created` (created time).

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in all values
python main.py
```

Test pieces independently before the full bot:

```bash
python notion_client_wrapper.py   # writes one page to each DB
python agent.py                   # runs sample transcripts end-to-end to Notion
```

## Hosting (free, always-on)

The bot uses **long polling** — outbound network only, no public URL or open port —
so the simplest host is any always-on process.

1. **Oracle Cloud Free Tier (recommended).** A genuinely *always-free* small VM. Clone the
   repo, install deps, put your secrets in `.env`, and run under `systemd` so it restarts
   on reboot:

   ```ini
   # /etc/systemd/system/voice-agent.service
   [Unit]
   Description=Voice Agent Telegram bot
   After=network-online.target

   [Service]
   WorkingDirectory=/home/ubuntu/voice-agent
   EnvironmentFile=/home/ubuntu/voice-agent/.env
   ExecStart=/usr/bin/python3 main.py
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
   ```bash
   sudo systemctl enable --now voice-agent
   ```

2. **Fly.io.** Deploy the `Dockerfile` as a worker (no `[http_service]` in `fly.toml`, one
   always-on machine). Set secrets — never commit `.env`:
   ```bash
   fly secrets set TELEGRAM_BOT_TOKEN=… TELEGRAM_ALLOWED_USER_ID=… GROQ_API_KEY=… \
     ANTHROPIC_API_KEY=… NOTION_API_KEY=… NOTION_NOTES_DB_ID=… \
     NOTION_TASKS_DB_ID=… NOTION_DRAFTS_DB_ID=…
   ```

3. **Google Cloud Run (scale-to-zero).** Cloud Run is request-driven and scales to zero,
   so long polling won't stay alive. To use it, switch `bot.py` to **webhook mode**
   (`application.run_webhook(...)` + Telegram `setWebhook`) and expose the HTTPS URL. More
   moving parts — only worth it if you specifically want scale-to-zero.

Avoid Render/Railway free web tiers (they sleep on inactivity) and PythonAnywhere free
(no always-on task) for a polling bot.

## Out of scope (v1)

Web search, reminders, email/calendar, hardware webhook trigger, cross-session memory,
multi-user — see `voice-agent-spec.md` §11 for the future roadmap.
