from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from supabase import Client

from app import db


@pytest.mark.parametrize("table", ["messages", "steps"])
@pytest.mark.parametrize("row_count", [0, 1000, 2003])
def test_fetch_paginates_in_order(table: str, row_count: int) -> None:
    rows = [{"id": str(index), "seq": index} for index in range(row_count)]
    offsets = list(range(0, row_count + 1, 1000))
    client = Mock(spec=Client)
    query = client.table.return_value
    query.select.return_value = query
    query.in_.return_value = query
    query.order.return_value = query
    query.range.return_value = query
    query.execute.side_effect = [
        SimpleNamespace(data=rows[offset : offset + 1000]) for offset in offsets
    ]

    if table == "messages":
        result = db.fetch_messages(client)
        query.in_.assert_not_called()
    else:
        result = db.fetch_steps(client, ["assistant-id"])
        assert query.in_.call_args_list == [
            call("message_id", ["assistant-id"]) for _ in offsets
        ]

    assert result == rows
    assert client.table.call_args_list == [call(table) for _ in offsets]
    assert query.select.call_args_list == [call("*") for _ in offsets]
    assert query.order.call_args_list == [call("seq") for _ in offsets]
    assert query.range.call_args_list == [call(offset, offset + 999) for offset in offsets]
    assert query.execute.call_count == len(offsets)


def test_fetch_steps_without_messages_skips_query() -> None:
    client = Mock(spec=Client)

    assert db.fetch_steps(client, []) == []
    client.table.assert_not_called()


@pytest.mark.parametrize(
    "steps",
    [
        [],
        [
            {"kind": "tool_call", "tool_name": "fetch_url", "detail": "Input"},
            {"kind": "tool_result", "tool_name": "fetch_url", "detail": "Output"},
            {"kind": "answer", "tool_name": None, "detail": "Hello!"},
        ],
    ],
)
def test_insert_exchange_with_steps_uses_one_rpc(steps: list[dict]) -> None:
    client = Mock(spec=Client)
    user = {"id": "user-id", "role": "user", "content": "Hi"}
    reply = {"id": "assistant-id", "role": "assistant", "content": "Hello!"}
    stored_steps = [
        {"id": str(index), "message_id": reply["id"], **step}
        for index, step in enumerate(steps)
    ]
    client.rpc.return_value.execute.return_value = SimpleNamespace(
        data={"user": user, "reply": reply, "steps": stored_steps}
    )

    result = db.insert_exchange_with_steps(client, "Hi", "Hello!", steps)

    assert result == (user, reply, stored_steps)
    client.rpc.assert_called_once_with(
        "insert_exchange_with_steps",
        {"user_content": "Hi", "reply_content": "Hello!", "steps": steps},
    )
    client.rpc.return_value.execute.assert_called_once_with()
    client.table.assert_not_called()


def test_insert_exchange_with_steps_propagates_rpc_failure() -> None:
    client = Mock(spec=Client)
    client.rpc.return_value.execute.side_effect = RuntimeError("Step insert failed")

    with pytest.raises(RuntimeError, match="Step insert failed"):
        db.insert_exchange_with_steps(client, "Hi", "Hello!", [])

    client.rpc.return_value.execute.assert_called_once_with()
    client.table.assert_not_called()
