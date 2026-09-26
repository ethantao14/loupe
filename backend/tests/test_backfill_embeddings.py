from unittest.mock import Mock

import pytest
from conftest import VISITOR_ID
from supabase import Client

from app import db, embedding
from scripts import backfill_embeddings


def test_backfill_updates_only_null_embeddings_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rows = [
        {"id": "old", "fact": "A corgi", "embedding": None},
        {"id": "ready", "fact": "Python", "embedding": [0.0, 1.0]},
        {"id": "older", "fact": "Boston", "embedding": None},
    ]
    client = Mock(spec=Client)
    query = client.table.return_value
    query.update.return_value = query
    query.eq.return_value = query
    query.is_.return_value = query

    def execute() -> Mock:
        assert query.eq.call_args_list[-2].args == ("visitor_id", VISITOR_ID)
        identifier = query.eq.call_args.args[1]
        updated = []
        for row in rows:
            if row["id"] == identifier and row["embedding"] is None:
                row["embedding"] = query.update.call_args.args[0]["embedding"]
                updated.append(row)
        return Mock(data=updated)

    query.execute.side_effect = execute
    monkeypatch.setattr(db, "get_client", lambda: client)
    fetch = Mock(return_value=rows)
    monkeypatch.setattr(db, "fetch_memories", fetch)
    monkeypatch.setattr(embedding, "load", Mock())
    encode = Mock(return_value=[[1.0, 0.0], [0.5, 0.5]])
    monkeypatch.setattr(embedding, "encode_documents", encode)

    backfill_embeddings.main(VISITOR_ID)
    assert capsys.readouterr().out == "Updated 2 memories.\n"
    fetch.assert_called_once_with(client, VISITOR_ID)
    encode.assert_called_once_with(["A corgi", "Boston"])
    assert rows[1]["embedding"] == [0.0, 1.0]
    query.is_.assert_called_with("embedding", "null")
    backfill_embeddings.main(VISITOR_ID)
    assert capsys.readouterr().out == "Updated 0 memories.\n"
    assert encode.call_count == 1
    assert query.execute.call_count == 2
