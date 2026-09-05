from fastapi.testclient import TestClient

from app import db
from app.main import app, get_claude_client, get_db_client


class FakeDb:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def fetch_messages(self) -> list[dict]:
        return list(self.rows)

    def insert_message(self, role: str, content: str) -> dict:
        row = {
            "id": str(len(self.rows) + 1),
            "role": role,
            "content": content,
            "created_at": "2026-01-01T00:00:00Z",
        }
        self.rows.append(row)
        return row


class FakeContentBlock:
    def __init__(self, block_type: str, text: str) -> None:
        self.type = block_type
        self.text = text


class FakeClaudeResponse:
    def __init__(self, text: str) -> None:
        self.content = [
            FakeContentBlock("thinking", ""),
            FakeContentBlock("text", text),
        ]


class FakeClaudeClient:
    class messages:
        @staticmethod
        def create(**kwargs):
            return FakeClaudeResponse("Hi there!")


def make_client(fake_db: FakeDb) -> TestClient:
    app.dependency_overrides[get_db_client] = lambda: fake_db
    app.dependency_overrides[get_claude_client] = lambda: FakeClaudeClient()
    return TestClient(app)


def test_list_messages_empty(monkeypatch) -> None:
    fake_db = FakeDb()
    monkeypatch.setattr(db, "fetch_messages", lambda client: client.fetch_messages())
    client = make_client(fake_db)

    response = client.get("/api/messages")

    assert response.status_code == 200
    assert response.json() == []


def test_send_message_persists_and_replies(monkeypatch) -> None:
    fake_db = FakeDb()
    monkeypatch.setattr(db, "fetch_messages", lambda client: client.fetch_messages())
    monkeypatch.setattr(
        db, "insert_message", lambda client, role, content: client.insert_message(role, content)
    )
    client = make_client(fake_db)

    response = client.post("/api/messages", json={"content": "Hello"})

    assert response.status_code == 200
    assert response.json()["role"] == "assistant"
    assert response.json()["content"] == "Hi there!"
    assert [row["role"] for row in fake_db.rows] == ["user", "assistant"]
