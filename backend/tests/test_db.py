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
        assert query.in_.call_args_list == [call("message_id", ["assistant-id"]) for _ in offsets]

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


def test_fetch_steps_batches_ids_and_paginates_in_order() -> None:
    message_ids = [f"assistant-{index}" for index in range(2003)]
    rows = [
        {"message_id": message_id, "seq": step_index * len(message_ids) + index}
        for step_index in range(6)
        for index, message_id in enumerate(message_ids)
    ]
    client = Mock(spec=Client)
    query = client.table.return_value
    query.select.return_value = query
    query.in_.return_value = query
    query.order.return_value = query
    query.range.return_value = query

    def execute() -> SimpleNamespace:
        batch = set(query.in_.call_args.args[1])
        start, end = query.range.call_args.args
        batch_rows = [row for row in rows if row["message_id"] in batch]
        return SimpleNamespace(data=batch_rows[start : end + 1])

    query.execute.side_effect = execute

    result = db.fetch_steps(client, message_ids)

    assert result == rows
    expected_filters = []
    expected_ranges = []
    for start in range(0, len(message_ids), 200):
        batch = message_ids[start : start + 200]
        for offset in range(0, len(batch) * 6 + 1, 1000):
            expected_filters.append(call("message_id", batch))
            expected_ranges.append(call(offset, offset + 999))
    assert query.in_.call_args_list == expected_filters
    assert query.range.call_args_list == expected_ranges
    assert query.order.call_args_list == [call("seq")] * len(expected_filters)
    assert query.execute.call_count == len(expected_filters)


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
        {"id": str(index), "message_id": reply["id"], **step} for index, step in enumerate(steps)
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


def test_insert_memory_uses_rpc():
    client = Mock(spec=Client)
    row = {"id": "memory-id", "seq": 1, "fact": "The user prefers Python."}
    client.rpc.return_value.execute.return_value = SimpleNamespace(data=row)

    assert db.insert_memory(client, row["fact"]) == row
    client.rpc.assert_called_once_with("insert_memory", {"fact": row["fact"]})
    client.rpc.return_value.execute.assert_called_once_with()
    client.table.assert_not_called()


def test_insert_memory_propagates_failure():
    client = Mock(spec=Client)
    client.rpc.return_value.execute.side_effect = RuntimeError("Insert failed")

    with pytest.raises(RuntimeError, match="Insert failed"):
        db.insert_memory(client, "A fact")


@pytest.mark.parametrize(
    "row_count, limit, ranges",
    [
        (0, 50, [(0, 49)]),
        (12, 50, [(0, 49)]),
        (100, 50, [(0, 49)]),
        (2003, 2000, [(0, 999), (1000, 1999)]),
        (2003, 2001, [(0, 999), (1000, 1999), (2000, 2000)]),
        (2003, 5000, [(0, 999), (1000, 1999), (2000, 2999)]),
        (1000, 5000, [(0, 999), (1000, 1999)]),
        (100, 0, []),
        (0, None, [(0, 999)]),
        (1000, None, [(0, 999), (1000, 1999)]),
        (2003, None, [(0, 999), (1000, 1999), (2000, 2999)]),
    ],
)
def test_fetch_memories_paginates_newest_first(row_count, limit, ranges):
    rows = [{"seq": index, "fact": f"Fact {index}"} for index in range(row_count, 0, -1)]
    client = Mock(spec=Client)
    query = client.table.return_value
    query.select.return_value = query
    query.order.return_value = query
    query.range.return_value = query

    def execute():
        start, end = query.range.call_args.args
        return SimpleNamespace(data=rows[start : end + 1])

    query.execute.side_effect = execute

    assert db.fetch_memories(client, limit) == rows[:limit]
    assert client.table.call_args_list == [call("memories")] * len(ranges)
    assert query.select.call_args_list == [call("*")] * len(ranges)
    assert query.order.call_args_list == [call("seq", desc=True)] * len(ranges)
    assert query.range.call_args_list == [call(start, end) for start, end in ranges]
    assert query.execute.call_count == len(ranges)
