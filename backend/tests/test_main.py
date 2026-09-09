from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import agent, db
from app.main import app, get_claude_client, get_db_client


def raise_api_error(client, history, memory_store):
    raise RuntimeError("Claude API unavailable")


class FakeDb:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.steps: list[dict] = []
        self.memories: list[dict] = []

    def fetch_messages(self) -> list[dict]:
        return list(self.rows)

    def fetch_steps(self, message_ids: list[str]) -> list[dict]:
        return [step for step in self.steps if step["message_id"] in message_ids]

    def insert_exchange_with_steps(
        self, user_content: str, reply_content: str, steps: list[dict]
    ) -> tuple[dict, dict, list[dict]]:
        inserted = []
        for role, content in (("user", user_content), ("assistant", reply_content)):
            row = {
                "id": str(len(self.rows) + 1),
                "role": role,
                "content": content,
                "created_at": "2026-01-01T00:00:00Z",
            }
            self.rows.append(row)
            inserted.append(row)
        user_message, reply = inserted
        inserted_steps = []
        for step in steps:
            row = {"id": str(len(self.steps) + 1), "message_id": reply["id"], **step}
            self.steps.append(row)
            inserted_steps.append(row)
        return user_message, reply, inserted_steps


class FakeContentBlock:
    def __init__(self, block_type: str, text: str) -> None:
        self.type = block_type
        self.text = text
        self.thinking = text


class FakeClaudeResponse:
    def __init__(self, text: str) -> None:
        self.stop_reason = "end_turn"
        self.content = [
            FakeContentBlock("thinking", ""),
            FakeContentBlock("text", text),
        ]


class FakeClaudeClient:
    class messages:
        @staticmethod
        def create(**kwargs):
            return FakeClaudeResponse("Hi there!")


def make_client(fake_db: FakeDb, monkeypatch) -> TestClient:
    monkeypatch.setattr(db, "fetch_memories", lambda client, limit: client.memories[::-1][:limit])
    monkeypatch.setattr(
        db, "insert_memory", lambda client, fact: client.memories.append({"fact": fact})
    )
    monkeypatch.setattr(db, "fetch_messages", lambda client: client.fetch_messages())
    monkeypatch.setattr(
        db, "fetch_steps", lambda client, message_ids: client.fetch_steps(message_ids)
    )
    monkeypatch.setattr(
        db,
        "insert_exchange_with_steps",
        lambda client, user, reply, steps: client.insert_exchange_with_steps(user, reply, steps),
    )
    app.dependency_overrides[get_db_client] = lambda: fake_db
    app.dependency_overrides[get_claude_client] = lambda: FakeClaudeClient()
    return TestClient(app)


def test_remembers_fact_and_recalls_it_in_later_conversation(monkeypatch):
    fake_db = FakeDb()
    client = make_client(fake_db, monkeypatch)
    requests = []
    responses = [
        SimpleNamespace(
            stop_reason="tool_use",
            content=[
                SimpleNamespace(
                    type="tool_use",
                    name="remember",
                    id="remember_1",
                    input={"fact": "The user prefers Python."},
                )
            ],
        ),
        FakeClaudeResponse("I'll remember that."),
        FakeClaudeResponse("You prefer Python."),
    ]

    def create(**kwargs):
        requests.append(kwargs)
        return responses.pop(0)

    llm_client = SimpleNamespace(messages=SimpleNamespace(create=create))
    app.dependency_overrides[get_claude_client] = lambda: llm_client

    first = client.post("/api/messages", json={"content": "I prefer Python."})

    assert first.status_code == 200
    assert fake_db.memories == [{"fact": "The user prefers Python."}]
    assert requests[0]["system"] == agent.SYSTEM_PROMPT
    assert all(step["kind"] != "memory" for step in first.json()["reply"]["steps"])

    # A fresh conversation has no message history, but uses the same saved facts.
    fake_db.rows.clear()
    fake_db.steps.clear()
    second = client.post("/api/messages", json={"content": "What language do I prefer?"})

    assert second.status_code == 200
    assert "The user prefers Python." in requests[2]["system"]
    assert len(requests[2]["messages"]) == 1
    recalled = second.json()["reply"]["steps"][0]
    assert recalled["kind"] == "memory"
    assert recalled["detail"] == (
        "Selected 1 of 1 candidates\nRecency fallback: no matching terms\n"
        "- 0.000 | The user prefers Python."
    )
    assert client.get("/api/messages").json()[1]["steps"][0] == recalled


def test_list_messages_empty(monkeypatch) -> None:
    fake_db = FakeDb()
    client = make_client(fake_db, monkeypatch)

    response = client.get("/api/messages")

    assert response.status_code == 200
    assert response.json() == []


def test_send_message_persists_and_replies(monkeypatch) -> None:
    fake_db = FakeDb()
    client = make_client(fake_db, monkeypatch)

    response = client.post("/api/messages", json={"content": "Hello"})

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["content"] == "Hello"
    assert body["reply"]["role"] == "assistant"
    assert body["reply"]["content"] == "Hi there!"
    assert body["user"]["steps"] == []
    assert body["reply"]["steps"] == [
        {"id": "1", "kind": "answer", "tool_name": None, "detail": "Hi there!"}
    ]
    assert fake_db.steps == [
        {
            "id": "1",
            "message_id": body["reply"]["id"],
            "kind": "answer",
            "tool_name": None,
            "detail": "Hi there!",
        }
    ]
    assert [row["role"] for row in fake_db.rows] == ["user", "assistant"]


def test_send_message_persists_nothing_when_reply_fails(monkeypatch) -> None:
    fake_db = FakeDb()
    monkeypatch.setattr(agent, "run_turn", raise_api_error)
    client = make_client(fake_db, monkeypatch)

    with pytest.raises(RuntimeError):
        client.post("/api/messages", json={"content": "Hello"})

    assert fake_db.rows == []
    assert fake_db.steps == []


def test_send_message_returns_tool_steps_in_order(monkeypatch) -> None:
    fake_db = FakeDb()
    client = make_client(fake_db, monkeypatch)
    steps = [
        agent.Step(kind="tool_call", tool_name="fetch_url", detail="{'url': 'example.com'}"),
        agent.Step(kind="tool_result", tool_name="fetch_url", detail="Page content"),
        agent.Step(kind="answer", detail="Here is the summary."),
    ]
    monkeypatch.setattr(
        agent,
        "run_turn",
        lambda client, history, memory_store: agent.TurnResult("Here is the summary.", steps),
    )

    response = client.post("/api/messages", json={"content": "Read example.com"})

    assert response.status_code == 200
    reply = response.json()["reply"]
    assert reply["content"] == "Here is the summary."
    assert reply["steps"] == [
        {"id": str(index), "kind": step.kind, "tool_name": step.tool_name, "detail": step.detail}
        for index, step in enumerate(steps, start=1)
    ]
    assert all(step["message_id"] == reply["id"] for step in fake_db.steps)


def test_list_messages_attaches_stored_steps(monkeypatch) -> None:
    fake_db = FakeDb()
    _, _, first_steps = fake_db.insert_exchange_with_steps(
        "Hello",
        "First answer",
        [
            {"kind": "tool_call", "tool_name": "fetch_url", "detail": "Input"},
            {"kind": "tool_result", "tool_name": "fetch_url", "detail": "Output"},
            {"kind": "answer", "tool_name": None, "detail": "First answer"},
        ],
    )
    _, _, second_steps = fake_db.insert_exchange_with_steps(
        "Again",
        "Second answer",
        [{"kind": "answer", "tool_name": None, "detail": "Second answer"}],
    )
    client = make_client(fake_db, monkeypatch)

    response = client.get("/api/messages")

    assert response.status_code == 200
    messages = response.json()
    assert messages[0]["steps"] == []
    assert messages[2]["steps"] == []
    for message, stored_steps in ((messages[1], first_steps), (messages[3], second_steps)):
        assert message["steps"] == [
            {key: value for key, value in step.items() if key != "message_id"}
            for step in stored_steps
        ]
