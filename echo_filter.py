"""
SelfEchoFilter — register outgoing texts before sending, drop incoming
messages that match.

Basically, this avoids the agent responding to its own reply which creates 
an infinite loop.

Usage:
    filter = SelfEchoFilter(ttl=30)
    filter.register(text)       # call before send_imessage()
    filter.is_echo(text)        # call on every incoming message
"""

import threading
import time


class SelfEchoFilter:
    def __init__(self, ttl: float = 30.0):
        self._ttl = ttl
        self._sent: dict[str, float] = {}  # text -> sent_at
        self._lock = threading.Lock()

    def register(self, text: str) -> None:
        """Register a text we're about to send so its loopback can be dropped."""
        with self._lock:
            self._sent[text] = time.monotonic()

    def is_echo(self, text: str) -> bool:
        """Return True if this text is a loopback of something we sent. Consumes the entry."""
        now = time.monotonic()
        with self._lock:
            self._evict(now)
            if text in self._sent:
                del self._sent[text]
                return True
        return False

    def _evict(self, now: float) -> None:
        expired = [t for t, ts in self._sent.items() if now - ts > self._ttl]
        for t in expired:
            del self._sent[t]
