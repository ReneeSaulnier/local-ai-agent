import json
import re
from pathlib import Path

import ollama

from tools import (
    create_apple_note,
    get_coding_model_name,
    get_model_name,
    list_directory,
    read_file,
    read_imessage,
    search_files,
    send_imessage,
    write_file,
)

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List the contents of a directory. Use this to explore folder structure and find relevant files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the directory.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Supports PDF and plain text files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the file.",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_imessage",
            "description": "Send an iMessage to a phone number or email address. Only succeeds if the recipient is on the allowed send list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "The recipient's name exactly as it appears in the allowed send list (e.g. 'Mom', 'John').",
                    },
                    "message": {
                        "type": "string",
                        "description": "The text message to send.",
                    },
                    "attachment": {
                        "type": "string",
                        "description": "Absolute path to a file to attach to the message. Optional.",
                    },
                },
                "required": ["to", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_imessage",
            "description": "Read the most recent iMessage from a contact on the allowed contact list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_contact": {
                        "type": "string",
                        "description": "The contact name exactly as it appears in the allow list, contacts map, or allowed send list.",
                    },
                },
                "required": ["from_contact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_apple_note",
            "description": "Create a new note in the Mac Notes app. Use this when the user asks to create a note, add a note, or save something to Notes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "The title of the note.",
                    },
                    "body": {
                        "type": "string",
                        "description": "The body content of the note.",
                    },
                },
                "required": ["title", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write text content to a file. Creates the file (and any parent directories) if it does not exist, or overwrites it if it does. Use this to create notes, lists, or any text file the user asks for.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path where the file should be written.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Text content to write into the file.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for files by name across all allowed folders. Returns matching file paths.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term to match against file names.",
                    }
                },
                "required": ["query"],
            },
        },
    },
]

TOOL_MAP = {
    "list_directory": list_directory,
    "read_file": read_file,
    "search_files": search_files,
    "write_file": write_file,
    "create_apple_note": create_apple_note,
    "send_imessage": send_imessage,
    "read_imessage": read_imessage,
}


def _load_config() -> dict:
    root = Path(__file__).resolve().parent
    for path in (root / "agent" / "config.json", root / "config.json"):
        if path.exists():
            with open(path) as f:
                return json.load(f)
    raise FileNotFoundError("No config.json found for agent")


def build_system_prompt(allowed_folders: list[str], personality: str = "", last_exchange: dict | None = None) -> str:
    folders = "\n".join(f"  - {f}" for f in allowed_folders)
    personality_block = f"\nPersonality:\n{personality}\n" if personality else ""
    if last_exchange:
        context_block = f"\nPrevious message: {last_exchange['user']}\nYour last reply: {last_exchange['assistant']}\n"
    else:
        context_block = ""
    return f"""You are an autonomous file agent. Answer the user's question by searching through their files.
{personality_block}{context_block}
You have access to these folders:
{folders}

Strategy:
1. Use search_files to find relevant files by name.
2. If nothing is found, use list_directory to explore folder structure.
3. Use read_file to read the contents of promising files.
4. Use write_file to create or update files when the user asks you to save, create, or write something.
5. Use read_imessage when the user asks for the latest message from a specific allowed contact.
6. Once you have the information or have completed the action, answer clearly and concisely.

Response rules:
- Be brief and direct. Answer in 1-3 sentences when possible.
- Plain text only — no asterisks, bold, bullet points, headers, HTML tags, or Slack-style formatting like <channel|> or <@mention>.
- No caveats, disclaimers, regional notes, or follow-up suggestions.
- State the answer plainly, as if texting a friend.

Do not ask follow-up questions. Find the answer yourself using your tools."""


def build_coding_system_prompt(allowed_folders: list[str], personality: str = "", last_exchange: dict | None = None) -> str:
    folders = "\n".join(f"  - {f}" for f in allowed_folders)
    personality_block = f"\nPersonality:\n{personality}\n" if personality else ""
    if last_exchange:
        context_block = f"\nPrevious request: {last_exchange['user']}\nYour last reply: {last_exchange['assistant']}\n"
    else:
        context_block = ""
    return f"""You are a coding agent working on the user's local codebase.
{personality_block}{context_block}
You have access to these folders:
{folders}

Task:
1. Inspect the relevant files before making changes.
2. Add features, fix bugs, or make small targeted refactors in the local codebase.
3. Use the file tools to read, search, and update code directly.
4. Prefer the smallest correct change that solves the request.
5. If you edit files, summarize exactly what changed.

Response rules:
- Be brief and direct.
- Plain text only.
- No caveats, disclaimers, regional notes, or follow-up suggestions.
- If you made changes, mention the files and the purpose of each change.

Do not ask follow-up questions unless you are blocked by missing information."""


DEFAULT_CODING_PREFIXES = ("/code", "code:", "/fix", "fix:", "/edit", "edit:")
DEFAULT_CODING_ACTION_WORDS = ("add", "build", "create", "implement", "fix", "debug", "patch", "update", "refactor", "change", "modify", "improve")
DEFAULT_CODING_CONTEXT_WORDS = ("code", "feature", "bug", "function", "class", "file", "repo", "project", "test", "tool", "endpoint", "api", "script")


def _is_coding_request(question: str, config: dict) -> bool:
    text = question.strip().lower()

    prefixes = tuple(config.get("coding_prefixes", DEFAULT_CODING_PREFIXES))
    if any(text.startswith(prefix) for prefix in prefixes):
        return True

    action_words = tuple(config.get("coding_action_words", DEFAULT_CODING_ACTION_WORDS))
    context_words = tuple(config.get("coding_context_words", DEFAULT_CODING_CONTEXT_WORDS))
    has_action = any(re.search(rf"\b{re.escape(word)}\b", text) for word in action_words)
    has_context = any(re.search(rf"\b{re.escape(word)}\b", text) for word in context_words)
    return has_action and has_context


def _clean(text: str) -> str:
    """Strip formatting artifacts the model sometimes prepends (e.g. <channel|>)."""
    text = re.sub(r"^(<[^>]*>\s*)+", "", text)
    return text.strip()


def run_agent(question: str, last_exchange: dict | None = None) -> str:
    config = _load_config()

    is_coding_request = _is_coding_request(question, config)
    model = get_coding_model_name() if is_coding_request else get_model_name()
    max_iterations = config.get("max_iterations", 10)
    personality = config.get("personality", "")
    system_prompt = (
        build_coding_system_prompt(config["allowed_folders"], personality, last_exchange)
        if is_coding_request
        else build_system_prompt(config["allowed_folders"], personality, last_exchange)
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    mode = "coding" if is_coding_request else "assistant"
    print(f"\n[agent] mode={mode} model={model} question: {question}\n")

    for iteration in range(max_iterations):
        response = ollama.chat(model=model, messages=messages, tools=TOOLS_SCHEMA)
        msg = response.message

        assistant_msg: dict = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_msg)

        if not msg.tool_calls:
            return _clean(msg.content)

        for tc in msg.tool_calls:
            name = tc.function.name
            args = tc.function.arguments

            print(f"[tool] {name}({args})")

            if name in TOOL_MAP:
                result = TOOL_MAP[name](**args)
            else:
                result = f"Unknown tool: {name}"

            preview = result[:200].replace("\n", " ")
            print(f"[result] {preview}...\n")

            messages.append({"role": "tool", "content": result})

    return "Reached maximum iterations without finding a definitive answer."
