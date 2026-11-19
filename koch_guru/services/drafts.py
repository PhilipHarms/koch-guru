"""Recipe drafts waiting for "Speichern" or "Verwerfen". In memory, short-lived."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Callable

from koch_guru.services.importer import RecipeDraft

TTL_SECONDS = 60 * 60


@dataclass
class PendingDraft:
    draft: RecipeDraft
    preview_html: str
    created: float


class DraftStore:
    def __init__(self, ttl_seconds: float = TTL_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._drafts: dict[str, PendingDraft] = {}

    def add(self, draft: RecipeDraft, preview_html: str = "") -> str:
        self._expire()
        draft_id = secrets.token_hex(4)
        self._drafts[draft_id] = PendingDraft(draft, preview_html, self._clock())
        return draft_id

    def get(self, draft_id: str) -> PendingDraft | None:
        """Look at a draft without taking it out, e.g. to retry a failed save."""
        self._expire()
        return self._drafts.get(draft_id)

    def pop(self, draft_id: str) -> PendingDraft | None:
        """Take a draft out. A second button press then finds nothing."""
        self._expire()
        return self._drafts.pop(draft_id, None)

    def _expire(self) -> None:
        now = self._clock()
        for key in [k for k, d in self._drafts.items() if now - d.created > self._ttl]:
            del self._drafts[key]
