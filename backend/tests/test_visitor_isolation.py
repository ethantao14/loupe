from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from conftest import VISITOR_ID
from fastapi.testclient import TestClient
from supabase import Client

from app import agent, embedding
from app.main import app, get_claude_client, get_db_client
from app.memory import MemoryStore

OTHER_VISITOR = "22222222-2222-4222-8222-222222222222"
CONVERSATION_ID = str(uuid4())
MEMORY_ID = str(uuid4())
ENDPOINTS = [
    ("GET", "/api/conversations"),
    ("PATCH", f"/api/conversations/{CONVERSATION_ID}"),
    ("DELETE", f"/api/conversations/{CONVERSATION_ID}"),
    ("GET", "/api/messages"),
    ("POST", "/api/messages"),
    ("POST", "/api/messages/stream"),
    ("GET", "/api/memories"),
    ("DELETE", f"/api/memories/{MEMORY_ID}"),
]


@pytest.mark.parametrize("header", [None, "", "invalid", "00000000-0000-0000-0000-000000000000"])
@pytest.mark.parametrize("method, path", ENDPOINTS)
def test_every_endpoint_requires_non_nil_visitor_header(monkeypatch, header, method, path):
    database = Mock(spec=Client)
    model = Mock()
    monkeypatch.setitem(app.dependency_overrides, get_db_client, lambda: database)
    monkeypatch.setitem(app.dependency_overrides, get_claude_client, lambda: model)
    client = TestClient(app)

    response = client.request(
        method,
        path,
        json={"content": "Hello", "title": "New title"},
        headers={} if header is None else {"X-Visitor-Id": header},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "X-Visitor-Id must be a valid, non-nil UUID."}
    database.table.assert_not_called()
    database.rpc.assert_not_called()
    assert model.mock_calls == []


@pytest.fixture
def isolated_database(monkeypatch):
    rows = {
        "conversations": [
            {
                "id": str(uuid4()),
                "visitor_id": visitor,
                "seq": index,
                "title": f"Conversation {index}",
                "created_at": "2026-01-01T00:00:00Z",
            }
            for index, visitor in enumerate((VISITOR_ID, OTHER_VISITOR), 1)
        ],
        "memories": [
            {
                "id": str(uuid4()),
                "visitor_id": visitor,
                "seq": index,
                "fact": f"Python fact {index}",
                "embedding": [1.0, 0.0],
                "created_at": "2026-01-01T00:00:00Z",
            }
            for index, visitor in enumerate((VISITOR_ID, OTHER_VISITOR), 1)
        ],
        "messages": [],
        "steps": [],
    }
    for conversation in rows["conversations"]:
        rows["messages"].append(
            {
                "id": str(uuid4()),
                "conversation_id": conversation["id"],
                "seq": conversation["seq"],
                "role": "user",
                "content": conversation["title"],
                "created_at": "2026-01-01T00:00:00Z",
            }
        )
    database = Mock(spec=Client)

    def table(name):
        query = Mock()
        filters = []
        action = "select"
        changes = {}
        start, end = 0, None
        descending = False

        def eq(column, value):
            filters.append((column, value))
            return query

        def delete():
            nonlocal action
            action = "delete"
            return query

        def update(values):
            nonlocal changes
            changes = values
            return query

        def page(first, last):
            nonlocal start, end
            start, end = first, last + 1
            return query

        def order(column, desc=False):
            nonlocal descending
            descending = desc
            return query

        def execute():
            selected = [
                row for row in rows[name] if all(row[column] == value for column, value in filters)
            ]
            selected.sort(key=lambda row: row["seq"], reverse=descending)
            selected = selected[start:end]
            if action == "delete":
                rows[name][:] = [row for row in rows[name] if row not in selected]
            for row in selected:
                row.update(changes)
            return SimpleNamespace(data=deepcopy(selected))

        query.select.return_value = query
        query.eq.side_effect = eq
        query.delete.side_effect = delete
        query.update.side_effect = update
        query.range.side_effect = page
        query.limit.side_effect = lambda count: page(0, count - 1)
        query.order.side_effect = order
        query.execute.side_effect = execute
        return query

    database.table.side_effect = table
    monkeypatch.setitem(app.dependency_overrides, get_db_client, lambda: database)
    monkeypatch.setitem(app.dependency_overrides, get_claude_client, lambda: Mock())
    client = TestClient(app, headers={"X-Visitor-Id": VISITOR_ID})
    return client, database, rows


def test_lists_and_latest_history_only_include_owned_rows(isolated_database):
    client, _, rows = isolated_database
    for visitor, index in ((VISITOR_ID, 0), (OTHER_VISITOR, 1), (str(uuid4()), None)):
        headers = {"X-Visitor-Id": visitor}
        conversations = client.get("/api/conversations", headers=headers)
        memories = client.get("/api/memories", headers=headers)
        messages = client.get("/api/messages", headers=headers)
        for response in (conversations, memories, messages):
            assert response.status_code == 200
        for response, table in (
            (conversations, "conversations"),
            (memories, "memories"),
            (messages, "messages"),
        ):
            assert [row["id"] for row in response.json()] == (
                [] if index is None else [rows[table][index]["id"]]
            )


@pytest.mark.parametrize("operation", ["read", "rename", "delete", "post", "stream"])
def test_foreign_conversation_is_404_without_reading_or_writing_messages(
    isolated_database,
    monkeypatch,
    operation,
):
    client, database, rows = isolated_database
    before = deepcopy(rows)
    foreign_id = rows["conversations"][1]["id"]
    run = Mock()
    stream = Mock()
    monkeypatch.setattr(agent, "run_turn", run)
    monkeypatch.setattr(agent, "stream_turn", stream)
    if operation == "read":
        response = client.get("/api/messages", params={"conversation_id": foreign_id})
    elif operation == "rename":
        response = client.patch(f"/api/conversations/{foreign_id}", json={"title": "Changed"})
    elif operation == "delete":
        response = client.delete(f"/api/conversations/{foreign_id}")
    else:
        path = "/api/messages/stream" if operation == "stream" else "/api/messages"
        response = client.post(path, json={"content": "Hello", "conversation_id": foreign_id})

    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found."}
    assert rows == before
    assert all(call.args == ("conversations",) for call in database.table.call_args_list)
    database.rpc.assert_not_called()
    run.assert_not_called()
    stream.assert_not_called()


def test_cannot_delete_foreign_memory_but_can_delete_own(isolated_database):
    client, _, rows = isolated_database
    own, foreign = deepcopy(rows["memories"])
    response = client.delete(f"/api/memories/{foreign['id']}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Remembered fact not found."}
    assert rows["memories"] == [own, foreign]
    assert client.delete(f"/api/memories/{own['id']}").status_code == 204
    assert rows["memories"] == [foreign]


@pytest.mark.parametrize("query", [None, "Python", "unmatched"])
@pytest.mark.parametrize("dense", [False, True])
def test_recall_only_sees_owned_facts(isolated_database, monkeypatch, query, dense):
    _, database, rows = isolated_database
    if dense:
        monkeypatch.setattr(embedding, "unavailable_reason", lambda: None)
        monkeypatch.setattr(embedding, "encode_query", lambda text: [1.0, 0.0])
    for visitor, index in ((VISITOR_ID, 0), (OTHER_VISITOR, 1)):
        store = MemoryStore(database, visitor)
        expected = rows["memories"][index]["fact"]
        assert store.recall(10) == [expected]
        result = store.recall_relevant(query)
        assert result.candidate_count == 1
        assert [fact for fact, _ in result.selected] == [expected]


def test_uuid_header_is_canonicalized(isolated_database):
    client, _, rows = isolated_database
    visitor = "abcdef12-abcd-4abc-8abc-abcdef123456"
    rows["conversations"][0]["visitor_id"] = visitor
    response = client.get("/api/conversations", headers={"X-Visitor-Id": visitor.upper()})
    assert response.status_code == 200
    assert [row["id"] for row in response.json()] == [rows["conversations"][0]["id"]]
