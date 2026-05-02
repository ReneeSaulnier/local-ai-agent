# Jarvis — Local iMessage AI Agent

Jarvis is a local AI agent that runs on your Mac and responds to iMessages. Text it a question, ask it to find a file, create a note, or send a message to a contact — it handles it without anything leaving your machine.

---

## How It Works

```
Your iPhone  →  iMessage  →  Mac Messages.app  →  chat.db  →  listener/listener.py  →  Ollama (local LLM)  →  reply
```

Your Mac watches its local iMessage database (`~/Library/Messages/chat.db`) for new incoming messages. When one arrives from an authorized number, it runs the message through a local Ollama model and sends the reply back via Messages.app.

**Nothing is sent to the cloud. The model runs entirely on your Mac.**

---

## Requirements

- macOS (iMessage must be set up)
- [Ollama](https://ollama.com) installed and running
- Python 3.11+
- The model pulled in Ollama (default: `gemma4:26b`)

Install Python dependencies:

```bash
pip install ollama pypdf
```

Pull the model:

```bash
ollama pull gemma4:26b
```

---

## Critical Setup: Mac Must Use a Different Apple ID than Your iPhone

This is the most important requirement. Jarvis works by texting **yourself** — your iPhone sends a message to your Mac's iMessage identity, and the Mac replies.

If your Mac and iPhone share the same Apple ID and phone number, iMessage will deduplicate the conversation and Jarvis will not see your messages reliably.

**The fix: sign your Mac into iMessage with an email address instead of your phone number.**

### Step-by-step

1. On your Mac, open **Messages** → **Settings** → **iMessage**
2. Under "You can be reached for messages at:", make sure only your **email address** (Apple ID) is checked — **uncheck your phone number**
3. Set "Start new conversations from" to your **email address**
4. On your iPhone, open **Settings** → **Messages** → **Send & Receive**
5. Make sure your **phone number** is checked there (it should be by default)

Now your Mac has identity: `your-email@example.com`
Your iPhone has identity: `+1XXXXXXXXXX`

When you text `your-email@example.com` from your iPhone, Jarvis sees it. When Jarvis replies, it comes from `your-email@example.com`.

Set `agent_reply_handle` in `config.json` to match the email address your Mac uses:

```json
"agent_reply_handle": "your-email@example.com"
```

---

## macOS Permissions

Jarvis needs several macOS permissions to function. The first time each action runs, macOS may prompt you — always click **Allow**. If you missed a prompt, grant them manually:

**System Settings → Privacy & Security**

| Permission | App | Why |
|---|---|---|
| Full Disk Access | Terminal / your terminal app | Read `~/Library/Messages/chat.db` |
| Accessibility | Terminal / your terminal app | Required for AppleScript automation |
| Automation → Messages | Terminal / your terminal app | Send iMessages via AppleScript |
| Automation → Notes | Terminal / your terminal app | Create Apple Notes via AppleScript |
| Files and Folders → Documents | Messages.app | Attach files from Documents when sending |

> **Terminal permission tip:** If you run Jarvis from Terminal.app, grant permissions to Terminal. If you use iTerm2 or another terminal, grant them to that app instead. The permissions follow whichever app launches the Python process.

### Grant Full Disk Access (required for reading chat.db)

1. Open **System Settings** → **Privacy & Security** → **Full Disk Access**
2. Click the **+** button
3. Navigate to your terminal app (`/Applications/Utilities/Terminal.app` or your preferred terminal)
4. Click **Open** and confirm

---

## Configuration

Config now lives beside the main entrypoints:

- [agent/config.json](agent/config.json) for the coding agent and shared file tools
- [listener/config.json](listener/config.json) for iMessage polling
- [app/config.json](app/config.json) for the Twilio webhook

The root [config.json](config.json) still works as a fallback during the transition.

### Agent Config (`agent/config.json`)

```json
{
  "model": "gemma4:26b",
  "coding_model": "qwen3.6:27b-coding-nvfp4",
  "allowed_folders": [
    "/Users/yourname/Documents",
    "/Users/yourname/Downloads"
  ],
  "max_file_chars": 8000,
  "max_iterations": 10,
  "imessage_handles": ["+15551234567"],
  "allowed_send_handles": {
    "You": "+15551234567",
    "Contact1": "+15551234568"
  },
  "agent_reply_handle": "your-email@example.com",
  "poll_interval": 3,
  "personality": "You are Jarvis — calm, dry-humored, and efficient."
}
```

| Key | Description |
|---|---|
| `model` | Ollama model name to use |
| `coding_model` | Ollama model to hand coding requests off to |
| `allowed_folders` | Folders Jarvis can read and write files in |
| `max_file_chars` | Max characters read from any single file |
| `max_iterations` | Max tool call loops per question before giving up |
| `imessage_handles` | Phone numbers allowed to send Jarvis commands (inbound) |
| `allowed_send_handles` | Contacts Jarvis is allowed to text outbound (name → number) |
| `agent_reply_handle` | Your Mac's iMessage identity (email address) |
| `poll_interval` | Seconds between database polls (default: 3) |
| `personality` | System prompt personality block injected into every session |

### Listener Config (`listener/config.json`)

```json
{
  "imessage_handles": ["+15551234567"],
  "agent_reply_handle": "your-email@example.com",
  "poll_interval": 3
}
```

### App Config (`app/config.json`)

```json
{
  "allowed_phone": "+15551234567"
}
```

Set `TWILIO_PHONE_NUMBER` in your environment for the sender number used by the webhook.

---

## Adding Contacts

Contacts live in `config.json` under two keys depending on direction:

### Who can command Jarvis (inbound)

Add their phone number to `imessage_handles`:

```json
"imessage_handles": ["+15551234567", "+15551234568"]
```

Anyone not on this list is silently ignored. Blocked attempts are logged to `blocked.log`.

### Who Jarvis can text (outbound)

Add a name and number to `allowed_send_handles`:

```json
"allowed_send_handles": {
  "You": "+15551234567",
  "Contact1": "+15551234568",
  "Contact2": "+15551234569"
}
```

Use the name exactly as you'd say it to Jarvis — "text Contact1 that I'll be late" will look up `"Contact1"` in this map. If the name isn't found, Jarvis refuses and tells you who it knows.

---

## Running Jarvis

```bash
./start.sh
```

This will:
1. Kill any previous Jarvis process
2. Start Ollama if it isn't already running
3. Launch the iMessage listener

You should see:

```
================================================
  Local Agent - iMessage Mode
  Text yourself to talk to the agent.
  Press Ctrl+C to stop.
================================================

[listener] Started at 2025-01-01T10:00:00
[listener] Watching handles: +15551234567
[listener] Watching self-chat: your-email@example.com
[listener] Starting rowid: 164800
[listener] Ready.
```

Now text your Mac's iMessage address from your iPhone. Jarvis will reply within a few seconds.

Stop Jarvis with **Ctrl+C**.

---

## Logs

All output is written to two log files in the project directory:

| File | Contents |
|---|---|
| `agent.log` | Full session log — every poll, tool call, AppleScript run, and reply |
| `blocked.log` | Unauthorized message attempts with timestamp and sender handle |

Tail the live log:

```bash
tail -f agent.log
```

---

## Testing Without iMessage

Run a one-off question directly from the terminal:

```bash
python -m main.main "What files do I have in my Downloads folder?"
```

This bypasses iMessage entirely and prints the answer to the terminal — useful for testing the agent and tools without needing to send a text.

---

## What Jarvis Can Do

| Command (example) | Tool used |
|---|---|
| "Find my lease agreement" | `search_files` |
| "What's in my Downloads folder?" | `list_directory` |
| "Read my budget spreadsheet" | `read_file` |
| "Create a shopping list note with milk and eggs" | `create_apple_note` |
| "Save this to a file called notes.txt" | `write_file` |
| "Text Contact1 that I'll be late" | `send_imessage` |
| "Send Contact2 my tax documents" | `send_imessage` + `search_files` |

## Coding Handoff

When a request looks like a code change or bug fix, Jarvis automatically routes it to the model named in `coding_model` and switches to a coding-focused system prompt. You can also force that path with prefixes like `code:`, `/code`, `fix:`, or `/fix`.

This mode is meant for requests like:

```text
code: add a retry button to the settings screen
fix: the listener is dropping duplicate iMessages
implement a dark mode toggle in the app
```

The coding model gets the same local file tools, so it can inspect, edit, and summarize changes without leaving your Mac.
