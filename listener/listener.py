import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from agent.agent import run_agent
from tools.imessage import get_latest_rowid, get_new_messages, send_imessage

LISTENER_CONFIG_PATHS = [
    Path(__file__).resolve().parent / "listener" / "config.json",
    Path(__file__).resolve().parent / "config.json",
]

LOG_PATH = Path(__file__).parent / "agent.log"
BLOCKED_LOG_PATH = Path(__file__).parent / "blocked.log"

# Tee all print() output to both stdout and the log file
class _Tee:
    def __init__(self, *streams):
        self._streams = streams
    def write(self, data):
        for s in self._streams:
            s.write(data)
            s.flush()
    def flush(self):
        for s in self._streams:
            s.flush()

_log_file = open(LOG_PATH, "a", buffering=1)
sys.stdout = _Tee(sys.__stdout__, _log_file)
sys.stderr = _Tee(sys.__stderr__, _log_file)

# Track rowids currently being processed to avoid duplicates
in_flight = set()
in_flight_lock = threading.Lock()

# In-memory conversation context (last exchange only)
last_exchange: dict | None = None
last_exchange_time: float = 0.0
last_exchange_lock = threading.Lock()
CONVERSATION_TIMEOUT = 30 * 60  # seconds of silence before context resets


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def is_authorized(msg: dict, handles: list[str], self_chat: str | None) -> bool:
    """Python-level authorization check — defense in depth after SQL filtering.

    is_from_me=True  → must come from the exact self_chat identifier (your own messages).
    is_from_me=False → sender handle must be in the explicit allowlist.
    """
    handle = msg["handle"]
    if msg.get("is_from_me"):
        return self_chat is not None and handle == self_chat
    return handle in handles


def handle_message(reply_chat_id: str, rowid: int, text: str):
    global last_exchange, last_exchange_time
    t0 = time.time()
    try:
        print(f"[{ts()}] [in]    rowid={rowid} text={text!r}")

        with last_exchange_lock:
            timed_out = (time.time() - last_exchange_time) > CONVERSATION_TIMEOUT
            context = None if timed_out else last_exchange
            if timed_out and last_exchange:
                print(f"[{ts()}] [memory] conversation timed out, starting fresh")
                last_exchange = None

        answer = run_agent(text, last_exchange=context)
        elapsed = time.time() - t0
        print(f"[{ts()}] [out]   ({elapsed:.1f}s) {answer!r}")

        with last_exchange_lock:
            last_exchange = {"user": text, "assistant": answer}
            last_exchange_time = time.time()

        print(f"[{ts()}] [send]  replying to rowid={rowid}...")
        answer = f"[Jarvis] {answer}"
        send_imessage(reply_chat_id, answer)
        print(f"[{ts()}] [send]  done.")
    except Exception as e:
        print(f"[{ts()}] [error] rowid={rowid}: {e}")
    finally:
        with in_flight_lock:
            in_flight.discard(rowid)


def main():
    config = None
    for path in LISTENER_CONFIG_PATHS:
        if path.exists():
            with open(path) as f:
                config = json.load(f)
            break
    if config is None:
        raise FileNotFoundError("No listener config found")

    handles = config["imessage_handles"]
    self_chat = config.get("agent_reply_handle")
    poll_interval = config.get("poll_interval", 3)

    print(f"\n{'='*60}")
    print(f"[listener] Started at {datetime.now().isoformat()}")
    print(f"[listener] Log: {LOG_PATH}")
    last_rowid = get_latest_rowid()
    print(f"[listener] Watching handles: {', '.join(handles)}")
    if self_chat:
        print(f"[listener] Watching self-chat: {self_chat}")
    print(f"[listener] Starting rowid: {last_rowid}")
    print(f"[listener] Ready.\n")

    while True:
        try:
            messages = get_new_messages(last_rowid, handles, self_chat)
            for msg in messages:
                print(f"[{ts()}] [poll] new message — rowid={msg['rowid']} handle={msg['handle']} text={msg['text']!r}")
                last_rowid = msg["rowid"]
                rowid = msg["rowid"]
                text = msg["text"].strip()

                if not is_authorized(msg, handles, self_chat):
                    entry = f"[{datetime.now().isoformat()}] BLOCKED rowid={rowid} handle={msg['handle']!r} text={text!r}\n"
                    print(f"[{ts()}] [BLOCKED] unauthorized sender — rowid={rowid} handle={msg['handle']!r}")
                    with open(BLOCKED_LOG_PATH, "a") as bf:
                        bf.write(entry)
                    continue

                with in_flight_lock:
                    if rowid in in_flight:
                        print(f"[{ts()}] [poll] skipping rowid {rowid} (already in flight)")
                        continue
                    in_flight.add(rowid)

                reply_chat_id = msg["guid"]

                t = threading.Thread(
                    target=handle_message,
                    args=(reply_chat_id, rowid, text),
                    daemon=True,
                )
                t.start()

        except Exception as e:
            print(f"[{ts()}] [error] poll loop: {e}")

        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
