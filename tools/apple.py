import json
import shutil
import subprocess
import tempfile
from pathlib import Path

"""
This file will contain functions that communicate with Apple apps (Messages, Notes, etc)
"""


def _load_config() -> dict:
    with open("config.json") as f:
        return json.load(f)


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
