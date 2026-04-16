import json
import re
import ollama
from tools import get_model_name, list_directory, read_file, search_files, write_file, create_apple_note, send_imessage

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
}


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
5. Once you have the information or have completed the action, answer clearly and concisely.

Response rules:
- Be brief and direct. Answer in 1-3 sentences when possible.
- Plain text only — no asterisks, bold, bullet points, headers, HTML tags, or Slack-style formatting like <channel|> or <@mention>.
- No caveats, disclaimers, regional notes, or follow-up suggestions.
- State the answer plainly, as if texting a friend.

Do not ask follow-up questions. Find the answer yourself using your tools."""



def _clean(text: str) -> str:
    """Strip formatting artifacts the model sometimes prepends (e.g. <channel|>)."""
    # Remove leading Slack-style tags like <channel|>, <@U123|name>, <#C123|name>
    text = re.sub(r"^(<[^>]*>\s*)+", "", text)
    return text.strip()


def run_agent(question: str, last_exchange: dict | None = None) -> str:
    with open("config.json") as f:
        config = json.load(f)

    model = get_model_name()
    max_iterations = config.get("max_iterations", 10)
    personality = config.get("personality", "")

    messages = [
        {"role": "system", "content": build_system_prompt(config["allowed_folders"], personality, last_exchange)},
        {"role": "user", "content": question},
    ]

    print(f"\n[agent] Question: {question}\n")

    for iteration in range(max_iterations):
        response = ollama.chat(model=model, messages=messages, tools=TOOLS_SCHEMA)
        msg = response.message

        # Build assistant message dict to append
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
            # No tool calls — model has its answer
            return _clean(msg.content)

        # Execute each tool call and feed results back
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
