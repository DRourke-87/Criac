# Voice Agent System — Full Design Specification

**Project:** Personal Voice-to-Action Agent  
**Interface:** Telegram (voice + text)  
**Backend:** Python  
**AI:** Claude API (claude-sonnet-4-20250514)  
**Transcription:** OpenAI Whisper API  
**Storage:** Notion (via MCP)  
**Base repo to fork:** `linuz90/claude-telegram-bot`

---

## 1. Overview

A personal agent accessible via Telegram that accepts voice messages or text, transcribes speech, classifies intent, and routes to one of four action types: capture a note, create a task, produce a content draft, or execute a Claude agent action. All outputs are stored in Notion. The agent responds in Telegram confirming what it did.

---

## 2. Repository Structure

```
voice-agent/
├── main.py                  # Entry point — starts Telegram bot
├── bot.py                   # Telegram bot handler (messages, voice, commands)
├── transcriber.py           # Whisper API wrapper
├── agent.py                 # Claude agent — classification + routing + tool calls
├── notion_client.py         # Notion API wrapper (read/write to databases)
├── tools/
│   ├── __init__.py
│   ├── note.py              # create_note tool
│   ├── task.py              # create_task tool
│   ├── draft.py             # create_draft tool
│   └── search.py            # search_notion tool
├── config.py                # Env var loading and validation
├── prompts/
│   └── system.md            # Claude system prompt (the "brain" of the agent)
├── .env.example             # Template env file
├── requirements.txt
└── README.md
```

---

## 3. Environment Variables

```env
# Telegram
TELEGRAM_BOT_TOKEN=          # From @BotFather
TELEGRAM_ALLOWED_USER_ID=    # Your Telegram numeric user ID (security: only you can use it)

# OpenAI (Whisper)
OPENAI_API_KEY=              # For Whisper transcription

# Anthropic
ANTHROPIC_API_KEY=           # Claude API key

# Notion
NOTION_API_KEY=              # Notion integration token
NOTION_NOTES_DB_ID=          # Notion database ID for notes
NOTION_TASKS_DB_ID=          # Notion database ID for tasks
NOTION_DRAFTS_DB_ID=         # Notion database ID for drafts
```

---

## 4. Notion Database Schemas

### 4.1 Notes Database

| Property | Type | Notes |
|----------|------|-------|
| Title | Title | Auto-generated summary (first ~60 chars of content) |
| Content | Rich text | Full note body |
| Tags | Multi-select | Agent-inferred tags |
| Source | Select | "voice" or "text" |
| Created | Created time | Auto |

### 4.2 Tasks Database

| Property | Type | Notes |
|----------|------|-------|
| Task | Title | Task description |
| Due Date | Date | Extracted from voice if mentioned, else empty |
| Priority | Select | High / Medium / Low — agent-inferred |
| Status | Status | Not started (default) / In progress / Done |
| Context | Rich text | Any additional detail from the voice note |
| Source | Select | "voice" or "text" |
| Created | Created time | Auto |

### 4.3 Drafts Database

| Property | Type | Notes |
|----------|------|-------|
| Title | Title | Agent-generated title |
| Type | Select | LinkedIn / Email / Blog / Twitter / Other |
| Content | Rich text | Full drafted content |
| Status | Select | Draft / Ready / Published |
| Brief | Rich text | Original voice instruction |
| Source | Select | "voice" or "text" |
| Created | Created time | Auto |

---

## 5. Processing Pipeline

```
User sends voice message or text in Telegram
          │
          ▼
   [bot.py] Receives update
          │
          ├── Voice message → [transcriber.py] Whisper API → transcript string
          │
          └── Text message → use as-is
          │
          ▼
   [agent.py] Claude classifies intent and selects tool
          │
          ├── NOTE     → [tools/note.py]   → Notion Notes DB
          ├── TASK     → [tools/task.py]   → Notion Tasks DB
          ├── DRAFT    → [tools/draft.py]  → Notion Drafts DB
          └── ACTION   → Claude executes   → web_search / multi-step reasoning
          │
          ▼
   Telegram reply confirming action + Notion link
```

---

## 6. Agent Design

### 6.1 Claude Tool Definitions

The agent is given four tools. Claude decides which to call based on the transcript.

```python
tools = [
    {
        "name": "create_note",
        "description": "Store a note, thought, idea, or piece of information for later reference. Use when the user is capturing something they want to remember but not necessarily act on immediately.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short summary title (max 60 chars)"},
                "content": {"type": "string", "description": "Full note content, cleaned up from transcript"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Relevant topic tags"}
            },
            "required": ["title", "content"]
        }
    },
    {
        "name": "create_task",
        "description": "Create an actionable task with optional due date. Use when the user says they need to do something, follow up on something, or remember to take an action.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "Clear, actionable task description"},
                "due_date": {"type": "string", "description": "ISO 8601 date string if mentioned, else null"},
                "priority": {"type": "string", "enum": ["High", "Medium", "Low"]},
                "context": {"type": "string", "description": "Any additional context or detail"}
            },
            "required": ["task", "priority"]
        }
    },
    {
        "name": "create_draft",
        "description": "Write and store a content draft. Use when the user wants a piece of content created: LinkedIn post, email, blog post, tweet, or similar. Write the full draft, not just a plan.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Descriptive title for the draft"},
                "type": {"type": "string", "enum": ["LinkedIn", "Email", "Blog", "Twitter", "Other"]},
                "content": {"type": "string", "description": "The fully written draft content"},
                "brief": {"type": "string", "description": "Original instruction from the user"}
            },
            "required": ["title", "type", "content", "brief"]
        }
    },
    {
        "name": "search_notion",
        "description": "Search existing notes, tasks, or drafts in Notion. Use when the user asks what they have stored, wants to find something, or references previous notes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "database": {"type": "string", "enum": ["notes", "tasks", "drafts", "all"]}
            },
            "required": ["query", "database"]
        }
    }
]
```

### 6.2 System Prompt (`prompts/system.md`)

```
You are a personal assistant agent for Darren, a digital consultant specialising in defence and government sectors, based in Cumbria, UK. You receive voice notes or text messages and take action on them.

Your job is to:
1. Understand the intent of the message
2. Call the appropriate tool to action it
3. Be concise — your Telegram reply confirms the action, nothing more

## Intent Classification Rules

- If it is a thought, idea, reference, or something to remember → create_note
- If it mentions doing something, following up, or a deadline → create_task
- If it asks for content to be written (post, email, article, message) → create_draft
- If it asks what is stored or references past notes → search_notion
- If it is ambiguous between note and task, prefer create_task

## Writing Standards

For drafts:
- LinkedIn: professional but human tone, 150-300 words, no hashtag spam (max 3)
- Email: clear subject implied in title, direct and respectful
- Twitter/X: punchy, under 280 chars
- Blog: structured with a clear argument, 400-800 words unless instructed otherwise

For notes:
- Clean up filler words and false starts from transcripts
- Preserve the user's meaning precisely — do not editorialize

For tasks:
- Make them action-oriented (start with a verb)
- Infer priority from urgency language: "urgent", "ASAP", "today" = High; "soon", "this week" = Medium; everything else = Low
- Parse relative dates: "tomorrow", "next Tuesday", "end of week" → convert to ISO date using today's date

## Reply Format

After calling a tool, reply in Telegram with a single short confirmation:

✅ Note saved — "Your title here"
✅ Task created — "Task description" [due: date if set]
✅ Draft ready — "Title" (LinkedIn) — [Notion link]
🔍 Found 3 results — [brief summary]

Never explain your reasoning. Just confirm and include the Notion page link.
```

---

## 7. Module Specifications

### 7.1 `bot.py`

- Uses `python-telegram-bot` (v20+ async)
- Listens for two update types: `MessageHandler(filters.VOICE)` and `MessageHandler(filters.TEXT)`
- Security: Check `update.effective_user.id == TELEGRAM_ALLOWED_USER_ID` on every message — silently ignore all others
- Voice flow: download voice file → save as `.ogg` → pass to `transcriber.py` → get transcript string → pass to `agent.py`
- Text flow: pass message text directly to `agent.py`
- Send typing indicator (`bot.send_chat_action`) while processing
- Reply with agent response string + Notion page URL

### 7.2 `transcriber.py`

```python
def transcribe(audio_path: str) -> str:
    """Send audio file to OpenAI Whisper API, return transcript string."""
    # Use openai.Audio.transcriptions.create
    # model="whisper-1"
    # language="en"
    # Clean up temp file after transcription
```

### 7.3 `agent.py`

```python
def run(transcript: str, source: str = "voice") -> dict:
    """
    Send transcript to Claude with tools.
    Returns: {"reply": str, "notion_url": str | None}
    
    Flow:
    1. Call Claude with system prompt + transcript + tool definitions
    2. Extract tool_use block from response
    3. Call appropriate tool function
    4. Return confirmation reply
    """
```

- Use `anthropic` Python SDK
- Model: `claude-sonnet-4-20250514`
- Max tokens: 2048
- Handle tool_use stop reason — extract tool name and input
- Pass tool result back to Claude for final reply generation
- If Claude returns text without a tool call (rare edge case), store as a note automatically

### 7.4 `notion_client.py`

```python
def create_note(title: str, content: str, tags: list, source: str) -> str:
    """Creates page in Notes DB. Returns Notion page URL."""

def create_task(task: str, priority: str, due_date: str | None, context: str, source: str) -> str:
    """Creates page in Tasks DB. Returns Notion page URL."""

def create_draft(title: str, type: str, content: str, brief: str, source: str) -> str:
    """Creates page in Drafts DB. Returns Notion page URL."""

def search(query: str, database: str) -> list[dict]:
    """Full-text search across specified Notion DB(s). Returns list of matching pages."""
```

- Use `notion-client` Python library
- All create functions return the Notion page URL (`https://notion.so/...`)
- Rich text fields: pass content as plain text, let Notion handle formatting
- Tags: create as multi-select options (Notion auto-creates if they don't exist)

---

## 8. Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Whisper transcription fails | Reply: "⚠️ Couldn't transcribe that — try again or send as text" |
| Claude API error | Reply: "⚠️ Agent error — message saved, try again" + store raw transcript as note |
| Notion write fails | Reply: "⚠️ Stored locally but Notion sync failed" + log to stderr |
| Unauthorised user | Silent ignore — no reply |
| Empty transcript | Reply: "⚠️ Didn't catch anything — was that empty?" |
| Ambiguous audio (background noise) | Whisper still returns best effort; agent handles gracefully |

---

## 9. Dependencies (`requirements.txt`)

```
python-telegram-bot==20.7
openai==1.30.0
anthropic==0.28.0
notion-client==2.2.1
python-dotenv==1.0.1
aiohttp==3.9.5
```

---

## 10. Setup & Run

### One-time setup

```bash
# Clone base repo
git clone https://github.com/linuz90/claude-telegram-bot
cd claude-telegram-bot

# Replace with this architecture (or build fresh alongside)
pip install -r requirements.txt

# Configure
cp .env.example .env
# Fill in all keys

# Create Notion databases
# - Go to Notion, create three full-page databases: Notes, Tasks, Drafts
# - Add the schemas from Section 4
# - Share each with your integration (Settings → Connections)
# - Copy each database ID from the URL (32-char string after workspace name)

# Run
python main.py
```

### Getting your Telegram user ID
Message `@userinfobot` on Telegram — it replies with your numeric ID.

### Getting Notion database IDs
Open the database in Notion → copy URL → the ID is the 32-character string:
`https://notion.so/workspace/DATABASE_ID_HERE?v=...`

---

## 11. Future Iterations (not in v1)

These are out of scope for the initial build but designed for easy addition:

- **Reminders** — `create_reminder` tool using a cron job or Telegram scheduled message
- **Web search** — add `web_search` tool (Brave Search API or Tavily) for research actions
- **Email send** — Gmail API tool for "send an email to X saying..."
- **Calendar** — Google Calendar API tool for "block time on Tuesday for..."
- **Hardware trigger** — ESP32-S3 device POSTing audio to a `/webhook` endpoint instead of Telegram
- **Memory layer** — SQLite store of past actions for context ("what did I capture last week about...")
- **Multi-user** — extend `ALLOWED_USER_ID` to a list for family/team use

---

## 12. Build Order for Claude Code

Build in this sequence to keep things testable at each stage:

1. `config.py` — load and validate all env vars, fail fast with clear messages
2. `notion_client.py` — write and test all four Notion functions independently
3. `transcriber.py` — Whisper wrapper, test with a sample audio file
4. `agent.py` — Claude agent with tools, test with hardcoded transcript strings
5. `bot.py` — wire Telegram to the above, test voice → note end-to-end
6. `main.py` — entry point, start the bot
7. End-to-end test: send voice → confirm Notion page created

---

*Spec version 1.0 — June 2026*
