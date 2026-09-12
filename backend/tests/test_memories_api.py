from types import SimpleNamespace
from unittest.mock import Mock, call
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from supabase import Client

from app import db
from app.main import app, get_db_client
from app.memory import MemoryStore


@pytest.fixture
def memory_client(monkeypatch):
    database = Mock(spec=Client)
    query = database.table.return_value
    query.select.return_value = query
    query.order.return_value = query
    query.range.return_value = query
    query.delete.return_value = query
    query.eq.return_value = query
    monkeypatch.setitem(app.dependency_overrides, get_db_client, lambda: database)
    with TestClient(app) as client:
        yield client, database, query


@pytest.mark.parametrize("row_count", [0, 1000, 2003, 5001])
def test_list_memories_newest_first_across_all_pages(memory_client, row_count):
    client, database, query = memory_client
    rows = [
        {
            "id": str(UUID(int=index)),
            "fact": f"Fact {index}",
            "created_at": "2026-01-01T00:00:00Z",
            "seq": index,
        }
        for index in range(1, row_count + 1)
    ]

    def execute():
        assert query.order.call_args == call("seq", desc=True)
        start, end = query.range.call_args.args
        return SimpleNamespace(data=rows[::-1][start : end + 1])

    query.execute.side_effect = execute

    response = client.get("/api/memories")

    assert response.status_code == 200
    assert response.json() == [
        {key: row[key] for key in ("id", "fact", "created_at")} for row in reversed(rows)
    ]
    offsets = list(range(0, row_count + 1, db.PAGE_SIZE))
    assert database.table.call_args_list == [call("memories")] * len(offsets)
    assert query.range.call_args_list == [
        call(offset, offset + db.PAGE_SIZE - 1) for offset in offsets
    ]


def test_delete_memory_removes_only_selected_fact_and_excludes_it_from_recall(memory_client):
    client, database, query = memory_client
    rows = [
        {
            "id": str(UUID(int=index)),
            "fact": f"Fact {index}",
            "created_at": "2026-01-01T00:00:00Z",
        }
        for index in (1, 2)
    ]
    removed, remaining = rows

    def execute_delete():
        column, memory_id = query.eq.call_args.args
        deleted = [row for row in rows if row[column] == memory_id]
        rows[:] = [row for row in rows if row[column] != memory_id]
        return SimpleNamespace(data=deleted)

    query.execute.side_effect = execute_delete

    response = client.delete(f"/api/memories/{removed['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert rows == [remaining]
    database.table.assert_called_once_with("memories")
    query.delete.assert_called_once_with()
    query.eq.assert_called_once_with("id", removed["id"])
    query.execute.assert_called_once_with()
    query.select.assert_not_called()
    database.rpc.assert_not_called()

    query.execute.side_effect = None
    query.execute.return_value = SimpleNamespace(data=rows)
    assert client.get("/api/memories").json() == [remaining]
    assert MemoryStore(database).recall(10) == [remaining["fact"]]


def test_delete_unknown_memory_returns_not_found(memory_client):
    client, _, query = memory_client
    query.execute.return_value = SimpleNamespace(data=[])

    response = client.delete(f"/api/memories/{UUID(int=99)}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Remembered fact not found."}
    query.eq.assert_called_once_with("id", str(UUID(int=99)))


@pytest.mark.parametrize("memory_id", ["not-a-uuid", "123", "null"])
def test_malformed_memory_id_never_queries_database(memory_client, memory_id):
    client, database, _ = memory_client

    response = client.delete(f"/api/memories/{memory_id}")

    assert response.status_code == 422
    database.table.assert_not_called()
    database.rpc.assert_not_called()


def test_delete_database_error_is_not_reported_as_success(memory_client):
    client, _, query = memory_client
    query.execute.side_effect = RuntimeError("Database unavailable")

    with pytest.raises(RuntimeError, match="Database unavailable"):
        client.delete(f"/api/memories/{UUID(int=1)}")


def test_memory_delete_cors_preflight(memory_client):
    client, _, _ = memory_client
    cors = next(middleware for middleware in app.user_middleware)
    origin = cors.kwargs["allow_origins"][0]

    response = client.options(
        f"/api/memories/{UUID(int=1)}",
        headers={"Origin": origin, "Access-Control-Request-Method": "DELETE"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "DELETE" in response.headers["access-control-allow-methods"]
