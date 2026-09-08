from unittest.mock import Mock

from supabase import Client

from app import db
from app.memory import MemoryStore


def test_remember_stores_fact(monkeypatch):
    client = Mock(spec=Client)
    insert = Mock()
    monkeypatch.setattr(db, "insert_memory", insert)

    MemoryStore(client).remember("The user prefers Python.")

    insert.assert_called_once_with(client, "The user prefers Python.")


def test_recall_returns_facts_with_requested_limit(monkeypatch):
    client = Mock(spec=Client)
    fetch = Mock(return_value=[{"fact": "Latest fact"}, {"fact": "Older fact"}])
    monkeypatch.setattr(db, "fetch_memories", fetch)

    assert MemoryStore(client).recall(2) == ["Latest fact", "Older fact"]
    fetch.assert_called_once_with(client, 2)
