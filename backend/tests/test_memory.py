from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from supabase import Client

from app import db
from app.memory import MAX_MEMORY_CANDIDATES, RECALL_TOP_K, MemoryStore


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


def test_relevance_returns_best_matches_instead_of_newest(monkeypatch):
    client = Mock(spec=Client)
    facts = ["Newest weather fact", "Python and Rust", "Python Python"]
    fetch = Mock(return_value=[{"fact": fact} for fact in facts])
    monkeypatch.setattr(db, "fetch_memories", fetch)

    result = MemoryStore(client).recall_relevant("Python", limit=1)

    assert [fact for fact, _ in result.selected] == [facts[-1]]
    assert result.selected[0][1] > 0
    assert result.candidate_count == 3
    assert result.fallback_reason is None
    fetch.assert_called_once_with(client, MAX_MEMORY_CANDIDATES)


@pytest.mark.parametrize(
    "query, reason",
    [
        ("unmatched", "no matching terms"),
        (None, "no usable query text"),
        ("", "no usable query text"),
        ("  ", "no usable query text"),
        ("the and !", "no usable query text"),
    ],
)
def test_relevance_falls_back_to_recency(monkeypatch, query, reason):
    fetch = Mock(return_value=[{"fact": "Newest"}, {"fact": "Older"}, {"fact": "Oldest"}])
    monkeypatch.setattr(db, "fetch_memories", fetch)

    result = MemoryStore(Mock(spec=Client)).recall_relevant(query, limit=2)

    assert result.selected == [("Newest", 0.0), ("Older", 0.0)]
    assert result.candidate_count == 3
    assert result.fallback_reason == reason


def test_relevance_top_k_preserves_recency_for_ties(monkeypatch):
    facts = [f"Python {index}" for index in range(RECALL_TOP_K + 2)] + ["Unrelated"]
    monkeypatch.setattr(db, "fetch_memories", Mock(return_value=[{"fact": f} for f in facts]))

    result = MemoryStore(Mock(spec=Client)).recall_relevant("Python")

    assert [fact for fact, _ in result.selected] == facts[:RECALL_TOP_K]
    assert all(score > 0 for _, score in result.selected)
    assert result.candidate_count == len(facts)


def test_relevance_does_not_fill_matches_with_zero_scores(monkeypatch):
    monkeypatch.setattr(
        db, "fetch_memories", Mock(return_value=[{"fact": "Unrelated"}, {"fact": "Python"}])
    )

    result = MemoryStore(Mock(spec=Client)).recall_relevant("Python")

    assert [fact for fact, _ in result.selected] == ["Python"]


def test_relevance_empty_store(monkeypatch):
    monkeypatch.setattr(db, "fetch_memories", Mock(return_value=[]))

    result = MemoryStore(Mock(spec=Client)).recall_relevant("Python")

    assert result.selected == []
    assert result.candidate_count == 0


@pytest.mark.parametrize("limit", [0, -1])
def test_relevance_nonpositive_limit_skips_fetch(monkeypatch, limit):
    fetch = Mock()
    monkeypatch.setattr(db, "fetch_memories", fetch)

    assert MemoryStore(Mock(spec=Client)).recall_relevant("Python", limit).selected == []
    fetch.assert_not_called()


def test_relevance_paginates_candidates_up_to_cap():
    rows = [{"fact": "Weather"} for _ in range(MAX_MEMORY_CANDIDATES + 1)]
    rows[db.PAGE_SIZE] = {"fact": "Quasar"}
    rows[-1] = {"fact": "Quasar quasar"}
    client = Mock(spec=Client)
    query = client.table.return_value
    query.select.return_value = query
    query.order.return_value = query
    query.range.return_value = query

    def execute():
        start, end = query.range.call_args.args
        return SimpleNamespace(data=rows[start : end + 1])

    query.execute.side_effect = execute

    result = MemoryStore(client).recall_relevant("Quasar")

    assert [fact for fact, _ in result.selected] == ["Quasar"]
    assert result.candidate_count == MAX_MEMORY_CANDIDATES
    assert query.range.call_args_list == [
        call(start, min(start + db.PAGE_SIZE, MAX_MEMORY_CANDIDATES) - 1)
        for start in range(0, MAX_MEMORY_CANDIDATES, db.PAGE_SIZE)
    ]
