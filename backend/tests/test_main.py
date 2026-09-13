from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import agent, db
from app.main import app, get_claude_client, get_db_client


def raise_api_error(client, history, memory_store):
    raise RuntimeError("Claude API unavailable")


class FakeDb:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.conversations: list[dict] = []
        self.steps: list[dict] = []
        self.memories: list[dict] = []

    def fetch_conversations(self) -> list[dict]:
        return self.conversations[::-1]

    def fetch_latest_conversation_id(self) -> str | None:
        return self.conversations[-1]["id"] if self.conversations else None

    def conversation_exists(self, conversation_id: str) -> bool:
        return any(row["id"] == conversation_id for row in self.conversations)

    def fetch_conversation(self, conversation_id: str) -> dict | None:
        return next((row for row in self.conversations if row["id"] == conversation_id), None)

    def rename_conversation(self, conversation_id: str, title: str) -> dict | None:
        conversation = self.fetch_conversation(conversation_id)
        if conversation is None:
            return None
        conversation["title"] = title
        return conversation

    def delete_conversation(self, conversation_id: str) -> bool:
        conversation = self.fetch_conversation(conversation_id)
        if conversation is None:
            return False
        self.conversations.remove(conversation)
        return True

    def fetch_messages(self, conversation_id: str) -> list[dict]:
        return [row for row in self.rows if row["conversation_id"] == conversation_id]

    def fetch_steps(self, message_ids: list[str]) -> list[dict]:
        return [step for step in self.steps if step["message_id"] in message_ids]

    def insert_exchange_with_steps(
        self,
        conversation_id: str | None,
        user_content: str,
        reply_content: str,
        steps: list[dict],
    ) -> tuple[str, dict, dict, list[dict]]:
        if conversation_id is None:
            conversation_id = str(uuid4())
            self.conversations.append({
                "id": conversation_id,
                "title": None,
                "created_at": "2026-01-01T00:00:00Z",
            })
        conversation = next(row for row in self.conversations if row["id"] == conversation_id)
        if conversation["title"] is None:
            conversation["title"] = " ".join(user_content.split())[:60] or None
        inserted: list[dict] = []
        for role, content in (("user", user_content), ("assistant", reply_content)):
            row = {
                "id": str(len(self.rows) + 1),
                "conversation_id": conversation_id,
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
        return conversation_id, user_message, reply, inserted_steps


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


def make_client(fake_db: FakeDb, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        db, "fetch_memories", lambda client, limit=None: client.memories[::-1][:limit]
    )
    monkeypatch.setattr(
        db, "insert_memory", lambda client, fact: client.memories.append({"fact": fact})
    )
    monkeypatch.setattr(db, "fetch_conversations", lambda client: client.fetch_conversations())
    monkeypatch.setattr(
        db, "rename_conversation", lambda client, cid, title: client.rename_conversation(cid, title)
    )
    monkeypatch.setattr(
        db, "delete_conversation", lambda client, cid: client.delete_conversation(cid)
    )
    monkeypatch.setattr(
        db, "fetch_latest_conversation_id", lambda client: client.fetch_latest_conversation_id()
    )
    monkeypatch.setattr(
        db, "conversation_exists", lambda client, cid: client.conversation_exists(cid)
    )
    monkeypatch.setattr(db, "fetch_messages", lambda client, cid: client.fetch_messages(cid))
    monkeypatch.setattr(
        db, "fetch_steps", lambda client, message_ids: client.fetch_steps(message_ids)
    )
    monkeypatch.setattr(
        db,
        "insert_exchange_with_steps",
        lambda client, cid, user, reply, steps: client.insert_exchange_with_steps(
            cid, user, reply, steps
        ),
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
    second = client.post("/api/messages", json={"content": "What language do I prefer?"})

    assert second.status_code == 200
    assert first.json()["conversation_id"] != second.json()["conversation_id"]
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
    assert body["conversation_id"] == fake_db.conversations[0]["id"]
    assert all(row["conversation_id"] == body["conversation_id"] for row in fake_db.rows)
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
    assert fake_db.conversations == []
    assert fake_db.steps == []


@pytest.mark.parametrize("result_kind", ["tool_result", "tool_error"])
def test_send_message_returns_tool_steps_in_order(
    monkeypatch: pytest.MonkeyPatch, result_kind: str
) -> None:
    fake_db = FakeDb()
    client = make_client(fake_db, monkeypatch)
    steps = [
        agent.Step(kind="tool_call", tool_name="fetch_url", detail="{'url': 'example.com'}"),
        agent.Step(kind=result_kind, tool_name="fetch_url", detail="Tool output"),
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


@pytest.mark.parametrize("result_kind", ["tool_result", "tool_error"])
def test_list_messages_attaches_stored_steps(
    monkeypatch: pytest.MonkeyPatch, result_kind: str
) -> None:
    fake_db = FakeDb()
    conversation_id, _, _, first_steps = fake_db.insert_exchange_with_steps(
        None,
        "Hello",
        "First answer",
        [
            {"kind": "tool_call", "tool_name": "fetch_url", "detail": "Input"},
            {"kind": result_kind, "tool_name": "fetch_url", "detail": "Output"},
            {"kind": "answer", "tool_name": None, "detail": "First answer"},
        ],
    )
    _, _, _, second_steps = fake_db.insert_exchange_with_steps(
        conversation_id,
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


def test_list_conversations_newest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = FakeDb()
    client = make_client(fake_db, monkeypatch)
    assert client.get("/api/conversations").json() == []
    fake_db.insert_exchange_with_steps(None, "  First\n conversation  ", "Answer", [])
    fake_db.insert_exchange_with_steps(None, "", "Answer", [])

    response = client.get("/api/conversations")

    assert response.status_code == 200
    assert response.json() == fake_db.conversations[::-1]
    assert response.json()[0]["title"] is None
    assert response.json()[1]["title"] == "First conversation"


@pytest.mark.parametrize("explicit", [False, True])
def test_list_messages_scoped_to_conversation(
    monkeypatch: pytest.MonkeyPatch, explicit: bool
) -> None:
    fake_db = FakeDb()
    first_id, _, _, _ = fake_db.insert_exchange_with_steps(None, "First", "First reply", [])
    latest_id, _, _, _ = fake_db.insert_exchange_with_steps(None, "Second", "Second reply", [])
    client = make_client(fake_db, monkeypatch)

    response = client.get(
        "/api/messages", params={"conversation_id": first_id} if explicit else {}
    )

    assert response.status_code == 200
    selected_id = first_id if explicit else latest_id
    assert [row["id"] for row in response.json()] == [
        row["id"] for row in fake_db.fetch_messages(selected_id)
    ]


@pytest.mark.parametrize("method", ["get", "post"])
def test_unknown_conversation_returns_404_without_model_call(
    monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    fake_db = FakeDb()
    client = make_client(fake_db, monkeypatch)
    run_turn = Mock()
    monkeypatch.setattr(agent, "run_turn", run_turn)
    conversation_id = str(uuid4())

    if method == "get":
        response = client.get("/api/messages", params={"conversation_id": conversation_id})
    else:
        response = client.post(
            "/api/messages", json={"content": "Hello", "conversation_id": conversation_id}
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation not found."
    run_turn.assert_not_called()
    assert fake_db.rows == []
    assert fake_db.conversations == []


@pytest.mark.parametrize("existing", [False, True])
def test_send_message_uses_only_selected_history(
    monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    fake_db = FakeDb()
    selected_id, _, _, _ = fake_db.insert_exchange_with_steps(None, "Selected", "Reply", [])
    fake_db.insert_exchange_with_steps(None, "Unrelated", "Private reply", [])
    client = make_client(fake_db, monkeypatch)
    run_turn = Mock(return_value=agent.TurnResult("New reply", []))
    monkeypatch.setattr(agent, "run_turn", run_turn)
    history = fake_db.fetch_messages(selected_id) if existing else []
    body = {"content": "Follow up"}
    if existing:
        body["conversation_id"] = selected_id

    response = client.post("/api/messages", json=body)

    assert response.status_code == 200
    run_turn.assert_called_once()
    assert run_turn.call_args.args[1] == [*history, {"role": "user", "content": "Follow up"}]
    saved_id = response.json()["conversation_id"]
    assert (saved_id == selected_id) is existing
    assert len(fake_db.conversations) == (2 if existing else 3)
    assert fake_db.fetch_messages(saved_id)[-2]["content"] == "Follow up"
    assert fake_db.fetch_messages(saved_id)[-1]["content"] == "New reply"
    assert fake_db.conversations[0]["title"] == "Selected"


@pytest.mark.parametrize("title, expected", [
    ("Renamed", "Renamed"),
    ("  A pasted\n\t title   here  ", "A pasted title here"),
    ("x" * 200, "x" * 200),
    ("  " + "x" * 200 + "\n", "x" * 200),
])
def test_rename_conversation(
    monkeypatch: pytest.MonkeyPatch, title: str, expected: str
) -> None:
    fake_db = FakeDb()
    conversation_id, _, _, _ = fake_db.insert_exchange_with_steps(None, "Original", "Reply", [])
    client = make_client(fake_db, monkeypatch)

    response = client.patch(f"/api/conversations/{conversation_id}", json={"title": title})

    assert response.status_code == 200
    assert response.json() == {
        "id": conversation_id, "title": expected, "created_at": "2026-01-01T00:00:00Z",
    }
    assert client.get("/api/conversations").json()[0]["title"] == expected


@pytest.mark.parametrize("title", ["", "   ", "\n\t  ", "x" * 201])
def test_rename_conversation_rejects_invalid_title(
    monkeypatch: pytest.MonkeyPatch, title: str
) -> None:
    fake_db = FakeDb()
    conversation_id, _, _, _ = fake_db.insert_exchange_with_steps(None, "Original", "Reply", [])
    client = make_client(fake_db, monkeypatch)

    response = client.patch(f"/api/conversations/{conversation_id}", json={"title": title})

    assert response.status_code == 422
    assert fake_db.conversations[0]["title"] == "Original"


def test_delete_conversation(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = FakeDb()
    conversation_id, _, _, _ = fake_db.insert_exchange_with_steps(None, "Original", "Reply", [])
    fake_db.insert_exchange_with_steps(None, "Keep", "Reply", [])
    client = make_client(fake_db, monkeypatch)

    response = client.delete(f"/api/conversations/{conversation_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert [row["title"] for row in client.get("/api/conversations").json()] == ["Keep"]


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_conversation_mutation_unknown_id(monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    client = make_client(FakeDb(), monkeypatch)

    response = client.request(method, f"/api/conversations/{uuid4()}", json={"title": "New"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation not found."


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
def test_conversation_mutation_requires_uuid(monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    client = make_client(FakeDb(), monkeypatch)

    response = client.request(method, "/api/conversations/invalid", json={"title": "New"})

    assert response.status_code == 422


def test_cors_allows_patch() -> None:
    middleware = next(item for item in app.user_middleware if "allow_methods" in item.kwargs)
    assert "PATCH" in middleware.kwargs["allow_methods"]
    client = TestClient(app)

    response = client.options("/api/conversations", headers={
        "Origin": middleware.kwargs["allow_origins"][0],
        "Access-Control-Request-Method": "PATCH",
        "Access-Control-Request-Headers": "content-type",
    })

    assert response.status_code == 200
    assert "PATCH" in response.headers["access-control-allow-methods"]
