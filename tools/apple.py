import json
import shutil
import subprocess
import tempfile
import sqlite3
from pathlib import Path


DB_PATH = Path.home() / "Library/Messages/chat.db"

AGENT_CONFIG_PATHS = [
    Path(__file__).resolve().parents[1] / "agent" / "config.json",
    Path(__file__).resolve().parents[1] / "config.json",
]


def _load_config() -> dict:
    for path in AGENT_CONFIG_PATHS:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    raise FileNotFoundError("No agent config found")


def _load_contacts(config: dict) -> dict[str, str]:
    contacts = config.get("allow_list") or config.get("contacts") or config.get("allowed_send_handles") or {}
    if isinstance(contacts, list):
        return {str(name): str(name) for name in contacts}
    return {str(name): str(identifier) for name, identifier in contacts.items()}


def _is_allowed(path: str, allowed_folders: list[str]) -> bool:
    resolved = Path(path).resolve()
    for folder in allowed_folders:
        try:
            resolved.relative_to(Path(folder).resolve())
            return True
        except ValueError:
            continue
    return False


def _run_applescript(*lines: str) -> subprocess.CompletedProcess:
    args = ["osascript"]
    for line in lines:
        args += ["-e", line]
    script_preview = "\n    ".join(lines)
    print(f"[applescript] running:\n    {script_preview}")
    result = subprocess.run(args, capture_output=True, text=True)
    print(f"[applescript] exit={result.returncode}")
    if result.stdout.strip():
        print(f"[applescript] stdout: {result.stdout.strip()}")
    if result.stderr.strip():
        print(f"[applescript] stderr: {result.stderr.strip()}")
    return result


def send_imessage(to: str, message: str, attachment: str | None = None) -> str:
    config = _load_config()
    allowed = config.get("allowed_send_handles", {})
    number = allowed.get(to)
    if not number:
        known = ", ".join(allowed.keys())
        return f"Blocked: '{to}' is not in the allowed send list. Known contacts: {known}."

    if attachment:
        p = Path(attachment).resolve()
        if not p.exists():
            return f"Attachment not found: {attachment}"
        if not _is_allowed(str(p), config.get("allowed_folders", [])):
            return f"Access denied: '{attachment}' is not within an allowed folder."

    safe_number = number.replace("\\", "\\\\").replace('"', '\\"')
    safe_message = f"[Jarvis] {message}".replace("\\", "\\\\").replace('"', '\\"')

    script_lines = [
        'tell application "Messages"',
        '    set targetService to 1st service whose service type = iMessage',
        f'    set targetBuddy to buddy "{safe_number}" of targetService',
        f'    send "{safe_message}" to targetBuddy',
    ]

    tmp_path = None
    if attachment:
        # Copy to a system temp dir so Messages.app can always read it
        src = Path(attachment).resolve()
        tmp_dir = Path(tempfile.mkdtemp())
        tmp_path = tmp_dir / src.name
        shutil.copy2(src, tmp_path)
        print(f"[send_imessage] copied attachment to {tmp_path}")

        safe_path = str(tmp_path).replace("\\", "\\\\").replace('"', '\\"')
        script_lines += [
            '    delay 1',
            f'    send POSIX file "{safe_path}" to targetBuddy',
        ]

    script_lines.append('end tell')

    result = _run_applescript(*script_lines)

    if tmp_path and tmp_path.exists():
        shutil.rmtree(tmp_path.parent, ignore_errors=True)

    if result.returncode != 0:
        return f"Error sending message: {result.stderr.strip()}"

    if attachment:
        return f"Message and attachment sent to {to} ({number})."
    return f"Message sent to {to} ({number})."


def read_imessage(from_contact: str) -> str:
    config = _load_config()
    contacts = _load_contacts(config)
    identifier = contacts.get(from_contact)
    if not identifier:
        known = ", ".join(sorted(contacts.keys()))
        return f"Blocked: '{from_contact}' is not in the allowed contact list. Known contacts: {known}."

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        row = conn.execute(
            """
            SELECT m.text
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.rowid
            JOIN chat_message_join cmj ON m.rowid = cmj.message_id
            JOIN chat c ON cmj.chat_id = c.rowid
            WHERE m.text IS NOT NULL
              AND m.text != ''
              AND (
                h.id = ?
                OR c.chat_identifier = ?
                OR c.guid = ?
              )
            ORDER BY m.date DESC, m.rowid DESC
            LIMIT 1
            """,
            (identifier, identifier, identifier),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return f"No recent message found from {from_contact}."

    text = row[0]
    return f'Last message from {from_contact}: "{text}"'



def create_apple_note(title: str, body: str) -> str:
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    safe_body = body.replace("\\", "\\\\").replace('"', '\\"')
    result = subprocess.run(
        [
            "osascript",
            "-e", 'tell application "Notes"',
            "-e", f'make new note with properties {{name:"{safe_title}", body:"{safe_body}"}}',
            "-e", "end tell",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return f"Note created: {title}"
    return f"Error creating note: {result.stderr.strip()}"
