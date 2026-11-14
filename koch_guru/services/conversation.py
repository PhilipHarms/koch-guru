"""Short-term conversation memory per Telegram chat.

Kept in memory on purpose: it is only meant for follow-ups like "lieber ohne
Fleisch" and is lost on restart, which is fine.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

MAX_MESSAGES = 8  # four exchanges
TTL_SECONDS = 2 * 60 * 60  # forget after two hours without messages


@dataclass
class _Conversation:
    messages: deque[dict[str, str]] = field(default_factory=lambda: deque(maxlen=MAX_MESSAGES))
    last_activity: float = 0.0


class ConversationStore:
    def __init__(
        self,
        max_messages: int = MAX_MESSAGES,
        ttl_seconds: float = TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_messages
        self._ttl = ttl_seconds
        self._clock = clock
        self._chats: dict[int, _Conversation] = {}

    def history(self, chat_id: int) -> list[dict[str, str]]:
        conv = self._chats.get(chat_id)
        if conv is None:
            return []
        if self._clock() - conv.last_activity > self._ttl:
            del self._chats[chat_id]
            return []
        return list(conv.messages)

    def add_exchange(self, chat_id: int, user: str, assistant: str) -> None:
        self.history(chat_id)  # drops an expired conversation first
        conv = self._chats.setdefault(chat_id, _Conversation(deque(maxlen=self._max)))
        conv.messages.append({"role": "user", "content": user})
        conv.messages.append({"role": "assistant", "content": assistant})
        conv.last_activity = self._clock()

    def reset(self, chat_id: int) -> None:
        self._chats.pop(chat_id, None)
