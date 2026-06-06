# Voice Agent — Personal Voice-to-Action Bot

A personal Discord agent: send a voice note or text, and it transcribes it
(Whisper via Groq's free API), classifies intent with **Claude — powered by your
own Claude Pro/Max subscription** (not a billed API key), and writes a **note**,
**task**, or **draft** to Notion — or searches your existing Notion content. It
replies in Discord confirming what it did with a link to the Notion page.

## How it works

```
Discord DM (voice/text)
   └─ bot.py        receives the message, gates on your Discord user ID
        ├─ voice → transcriber.py (Whisper via Groq) → transcript
        └─ text  → used as-is
            └─ agent.py    Claude (via the Claude Agent SDK, authed by your
                 │          subscription) classifies intent + calls a tool
                 └─ notion_client_wrapper.py   writes to the right Notion DB
            └─ reply with confirmation + Notion link
```

The reasoning runs through the **Claude Agent SDK**, which drives the Claude Code
engine authenticated by your subscription via `CLAUDE_CODE_OAUTH_TOKEN`. The four
Notion operations are registered as in-process tools, so no Anthropic API key and
no per-message charge — usage counts against your subscription's limits.

Files: `config.py` (env), `notion_client_wrapper.py` (Notion SDK calls),
`agent.py` (Claude Agent SDK + in-process Notion tools), `transcriber.py`
(Whisper via Groq), `bot.py` / `main.py` (Discord gateway client),
`prompts/system.md` (the agent's brain).

> Note: the Notion wrapper module is `notion_client_wrapper.py`, not
> `notion_client.py`, so it doesn't shadow the installed `notion-client` package.

## One-time setup

1. **Discord bot** — at the [Discord Developer Portal](https://discord.com/developers/applications):
   create an application → **Bot** tab → copy the **token** (`DISCORD_BOT_TOKEN`).
   Under **Privileged Gateway Intents**, enable **Message Content Intent**. Invite
   the bot to a server you're in (OAuth2 → URL Generator → `bot` scope), then DM it.
   Get your own user ID: Discord Settings → Advanced → enable **Developer Mode**,
   then right-click your name → **Copy User ID** (`DISCORD_ALLOWED_USER_ID`).
2. **Claude subscription token** — with a Claude Pro or Max plan, install Claude
   Code and run `claude setup-token`. It opens a browser login and prints a
   long-lived token (`sk-ant-oat01-…`) — paste it into `.env` as
   `CLAUDE_CODE_OAUTH_TOKEN`. **This token is your subscription — keep it secret**
   (env only, never committed; on a server, lock the box down to just you).
3. **Notion** — create three full-page databases (**Notes**, **Tasks**, **Drafts**)
   with the schemas below. Create an internal integration
   (https://www.notion.so/my-integrations), copy its token (`ntn_…`), and **share
   each database with the integration** (database → ••• → Connections). Copy each
   database ID (the 32-char string in the database URL).
4. **Groq key** — get a free [Groq API key](https://console.groq.com/keys) for
   Whisper transcription (`GROQ_API_KEY`).

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

The Claude Agent SDK needs **Node.js** (it runs the Claude Code engine) and the
Claude Code CLI:

```bash
npm install -g @anthropic-ai/claude-code   # if not already installed
claude setup-token                          # one-time, paste token into .env

pip install -r requirements.txt
cp .env.example .env                        # fill in all values
python main.py
```

Test pieces independently before the full bot:

```bash
python notion_client_wrapper.py   # writes one page to each DB
python agent.py                   # runs sample transcripts end-to-end to Notion
```

## Hosting (free, always-on)

The bot uses an **outbound gateway connection** — no public URL or open port — so
any always-on process works. The host needs **Node.js + the Claude Code CLI** and
the `CLAUDE_CODE_OAUTH_TOKEN` in its environment (the bundled `Dockerfile` installs
Node and the CLI for you).

> **Single-user only.** Running on your subscription is fine for personal use, but
> the bot must stay gated to your own Discord user ID — don't open it up to others.

1. **Oracle Cloud Free Tier (recommended).** A genuinely *always-free* small VM.
   Install Node + the CLI, run `claude setup-token`, put your secrets in `.env`,
   and run under `systemd` so it restarts on reboot:

   ```ini
   # /etc/systemd/system/voice-agent.service
   [Unit]
   Description=Voice Agent Discord bot
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

2. **Fly.io.** Deploy the `Dockerfile` as a worker (no `[http_service]` in
   `fly.toml`, one always-on machine). Set secrets — never commit `.env`:
   ```bash
   fly secrets set DISCORD_BOT_TOKEN=… DISCORD_ALLOWED_USER_ID=… GROQ_API_KEY=… \
     CLAUDE_CODE_OAUTH_TOKEN=… NOTION_API_KEY=… NOTION_NOTES_DB_ID=… \
     NOTION_TASKS_DB_ID=… NOTION_DRAFTS_DB_ID=…
   ```

Avoid scale-to-zero / sleep-on-inactivity free tiers (Cloud Run, Render/Railway
free web tiers, PythonAnywhere free) — a gateway bot needs a persistent process.

## Notes on cost & limits

- **Transcription** is free on Groq's Whisper tier (rate-limited, fine for personal use).
- **Reasoning** runs on your Claude subscription via `CLAUDE_CODE_OAUTH_TOKEN` — no
  API key, no per-message charge. It counts against your plan's usage limits; as of
  June 15 2026, headless Agent-SDK usage on a subscription draws from a monthly
  credit pool, which is plenty for personal voice-note volume but not unlimited.

## Out of scope (v1)

Web search, reminders, email/calendar, hardware webhook trigger, cross-session
memory, multi-user — see `voice-agent-spec.md` §11 for the future roadmap.
