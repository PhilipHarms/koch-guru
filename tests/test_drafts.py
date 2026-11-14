from koch_guru.services.drafts import DraftStore
from koch_guru.services.importer import RecipeDraft

DRAFT = RecipeDraft(name="X", url="https://x.de", ingredients=["a"])


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def test_pop_returns_a_draft_once():
    store = DraftStore()
    draft_id = store.add(DRAFT, "<b>X</b>")
    assert store.pop(draft_id).preview_html == "<b>X</b>"
    assert store.pop(draft_id) is None


def test_drafts_expire():
    clock = Clock()
    store = DraftStore(ttl_seconds=60, clock=clock)
    draft_id = store.add(DRAFT, "")
    clock.now = 61
    assert store.pop(draft_id) is None
