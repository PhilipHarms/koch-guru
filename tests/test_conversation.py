from koch_guru.services.conversation import ConversationStore


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_keeps_last_messages_per_chat():
    store = ConversationStore(max_messages=4, clock=Clock())
    for i in range(3):
        store.add_exchange(1, f"frage {i}", f"antwort {i}")
    store.add_exchange(2, "andere", "chat")
    assert [m["content"] for m in store.history(1)] == ["frage 1", "antwort 1", "frage 2", "antwort 2"]
    assert len(store.history(2)) == 2


def test_expires_after_inactivity_and_reset():
    clock = Clock()
    store = ConversationStore(ttl_seconds=60, clock=clock)
    store.add_exchange(1, "a", "b")
    clock.now = 59
    assert store.history(1)
    clock.now = 200
    assert store.history(1) == []
    store.add_exchange(1, "neu", "start")
    assert [m["content"] for m in store.history(1)] == ["neu", "start"]
    store.reset(1)
    assert store.history(1) == []
