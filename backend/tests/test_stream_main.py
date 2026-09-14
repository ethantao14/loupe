import json
from collections.abc import Iterator
from unittest.mock import Mock
from uuid import uuid4

import pytest
from test_main import FakeDb, make_client

from app import agent, db


def parse_events(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for frame in text.strip().split("\n\n"):
        name, data = frame.split("\n")
        assert name.startswith("event: ")
        assert data.startswith("data: ")
        events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


def test_stream_endpoint_events_and_done_match_saved_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = FakeDb()
    client = make_client(fake_db, monkeypatch)
    save = Mock(wraps=db.insert_exchange_with_steps)
    monkeypatch.setattr(db, "insert_exchange_with_steps", save)

    response = client.post("/api/messages/stream", json={"content": "Hello"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    events = parse_events(response.text)
    assert [name for name, _ in events] == ["delta", "delta", "step", "done"]
    assert events[:3] == [
        ("delta", {"text": "Hi"}),
        ("delta", {"text": " there!"}),
        ("step", {"kind": "answer", "tool_name": None, "detail": "Hi there!"}),
    ]
    saved = events[-1][1]
    save.assert_called_once()
    assert client.get("/api/messages").json() == [saved["user"], saved["reply"]]
    # Reuse the stored rows so the comparison includes identical ids and timestamps.
    save.return_value = (saved["conversation_id"], fake_db.rows[0], fake_db.rows[1], fake_db.steps)
    regular = client.post("/api/messages", json={"content": "Hello"})
    assert saved == regular.json()


def test_stream_unknown_conversation_rejected_before_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = FakeDb()
    client = make_client(fake_db, monkeypatch)
    stream_turn = Mock()
    monkeypatch.setattr(agent, "stream_turn", stream_turn)

    response = client.post("/api/messages/stream", json={
        "content": "Hello", "conversation_id": str(uuid4()),
    })

    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found."}
    stream_turn.assert_not_called()
    assert fake_db.rows == fake_db.steps == fake_db.conversations == []


def test_stream_failure_escapes_detail_and_persists_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = FakeDb()
    client = make_client(fake_db, monkeypatch)
    detail = 'First line\n"Quoted" second line'
    save = Mock()
    monkeypatch.setattr(db, "insert_exchange_with_steps", save)

    def fail(*args: object) -> Iterator[agent.TurnEvent]:
        yield agent.StepEvent(agent.Step("thinking", detail))
        yield agent.TextDelta("Partial answer")
        raise RuntimeError(detail)

    monkeypatch.setattr(agent, "stream_turn", fail)
    response = client.post("/api/messages/stream", json={"content": "Hello"})

    assert parse_events(response.text) == [
        ("step", {"kind": "thinking", "tool_name": None, "detail": detail}),
        ("delta", {"text": "Partial answer"}),
        ("error", {"detail": detail}),
    ]
    save.assert_not_called()
    assert fake_db.rows == fake_db.steps == fake_db.conversations == []


def test_stream_save_failure_emits_error_without_done(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = FakeDb()
    client = make_client(fake_db, monkeypatch)
    save = Mock(side_effect=RuntimeError("Save failed"))
    monkeypatch.setattr(db, "insert_exchange_with_steps", save)

    response = client.post("/api/messages/stream", json={"content": "Hello"})

    events = parse_events(response.text)
    assert [name for name, _ in events] == ["delta", "delta", "step", "error"]
    assert events[-1] == ("error", {"detail": "Save failed"})
    save.assert_called_once()
    assert fake_db.rows == fake_db.steps == fake_db.conversations == []


@pytest.mark.parametrize("existing", [False, True])
def test_stream_uses_selected_history(monkeypatch: pytest.MonkeyPatch, existing: bool) -> None:
    fake_db = FakeDb()
    selected_id, _, _, _ = fake_db.insert_exchange_with_steps(None, "Selected", "Reply", [])
    fake_db.insert_exchange_with_steps(None, "Unrelated", "Private reply", [])
    client = make_client(fake_db, monkeypatch)
    stream_turn = Mock(return_value=iter([agent.TurnComplete(agent.TurnResult("Done"))]))
    monkeypatch.setattr(agent, "stream_turn", stream_turn)
    history = fake_db.fetch_messages(selected_id) if existing else []
    body = {"content": "Follow up"}
    if existing:
        body["conversation_id"] = selected_id

    response = client.post("/api/messages/stream", json=body)

    stream_turn.assert_called_once()
    assert stream_turn.call_args.args[1] == [*history, {"role": "user", "content": "Follow up"}]
    saved = parse_events(response.text)[-1][1]
    assert (saved["conversation_id"] == selected_id) is existing
