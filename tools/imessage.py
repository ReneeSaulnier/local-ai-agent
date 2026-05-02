import sqlite3
import subprocess
from pathlib import Path

DB_PATH = Path.home() / "Library/Messages/chat.db"


def debug_recent_handles() -> list[str]:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT DISTINCT id FROM handle ORDER BY rowid DESC LIMIT 20").fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def get_latest_rowid() -> int:
    """Get the current max rowid so we only process new messages going forward."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT MAX(rowid) FROM message").fetchone()
        return row[0] or 0
    finally:
        conn.close()


def debug_new_rows(last_rowid: int) -> list:
    """Show all new message rows regardless of handle or direction."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = conn.execute("""
            SELECT m.rowid, m.is_from_me, m.text, h.id
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.rowid
            WHERE m.rowid > ?
            ORDER BY m.rowid ASC
            LIMIT 10
        """, (last_rowid,)).fetchall()
        return rows
    finally:
        conn.close()


def get_new_messages(last_rowid: int, handles: list[str], self_chat: str | None = None) -> list[dict]:
    """Return unprocessed incoming messages, including the chat_identifier to reply to.

    handles   — sender handles to watch for is_from_me=0 messages (other people texting you).
    self_chat — chat_identifier to watch for is_from_me=1 messages (your own messages
                synced from iPhone when you text your own email identity).
    """
    handle_placeholders = ",".join("?" * len(handles))
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        # Case 1: is_from_me=0 — someone else texting you. Filter by sender handle.
        # Case 2: is_from_me=1 — your own message synced from iPhone (phone→email
        #         self-chat). handle_id is NULL so we match on chat_identifier instead.
        # GROUP BY m.rowid prevents duplicates when a message belongs to multiple chats.
        self_chat_clause = "AND c.chat_identifier = ?" if self_chat else ""
        rows = conn.execute(f"""
            SELECT m.rowid, m.is_from_me, m.text,
                   COALESCE(h.id, c.chat_identifier) AS handle,
                   c.chat_identifier, c.guid
            FROM message m
            LEFT JOIN handle h ON m.handle_id = h.rowid
            JOIN chat_message_join cmj ON m.rowid = cmj.message_id
            JOIN chat c ON cmj.chat_id = c.rowid
            WHERE m.rowid > ?
              AND (
                (m.is_from_me = 0 AND h.id IN ({handle_placeholders}))
                OR
                (m.is_from_me = 1 {self_chat_clause})
              )
              AND m.text IS NOT NULL
              AND m.text != ''
            GROUP BY m.rowid
            ORDER BY m.rowid ASC
        """, (last_rowid, *handles, *([self_chat] if self_chat else []))).fetchall()
        msgs = [{"rowid": row[0], "is_from_me": bool(row[1]), "text": row[2], "handle": row[3], "chat_id": row[4], "guid": row[5]} for row in rows]
        for m in msgs:
            print(f"[db]   rowid={m['rowid']} handle={m['handle']} chat_id={m['chat_id']!r} guid={m['guid']!r}")
            # Show ALL chats this message belongs to so we can see if GROUP BY picked the wrong one
            all_chats = conn.execute("""
                SELECT c.rowid, c.chat_identifier, c.guid
                FROM chat_message_join cmj
                JOIN chat c ON cmj.chat_id = c.rowid
                WHERE cmj.message_id = ?
                ORDER BY c.rowid ASC
            """, (m["rowid"],)).fetchall()
            if len(all_chats) > 1:
                print(f"[db]   WARNING: message {m['rowid']} appears in {len(all_chats)} chats:")
                for ac in all_chats:
                    marker = " ← picked" if ac[2] == m["guid"] else ""
                    print(f"[db]     c.rowid={ac[0]}  chat_identifier={ac[1]!r}  guid={ac[2]!r}{marker}")
        return msgs
    finally:
        conn.close()


def send_imessage(chat_id: str, text: str):
    """Send a message to the given chat_id (e.g. 'iMessage;-;handle')."""
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(text)
        tmp_path = f.name

    print(f"[send]  chat_id={chat_id!r}")

    script = f'''
    set msgText to read POSIX file "{tmp_path}"
    tell application "Messages"
        set targetChat to first chat whose id is "{chat_id}"
        send msgText to targetChat
    end tell
    '''
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    os.unlink(tmp_path)

    if result.stderr.strip():
        print(f"[applescript error] {result.stderr.strip()}")
    if result.returncode != 0:
        print(f"[applescript] exit code {result.returncode}")
