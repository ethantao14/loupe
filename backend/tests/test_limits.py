import hashlib
from datetime import UTC, date, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest
from conftest import VISITOR_ID
from fastapi import Request
from fastapi.testclient import TestClient
from test_main import FakeDb, make_client

from app import agent, config, db, limits
from app.main import app

ENDPOINTS = ["/api/messages", "/api/messages/stream"]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(app, "dependency_overrides", {})
    monkeypatch.setattr(config, "DAILY_MESSAGES_PER_VISITOR", 10)
    monkeypatch.setattr(config, "DAILY_MESSAGES_PER_IP", None)
    monkeypatch.setattr(config, "DAILY_MESSAGES_TOTAL", None)
    monkeypatch.setattr(config, "MAX_MESSAGE_CHARS", 2000)
    monkeypatch.setattr(config, "TRUST_PROXY", False)
    return make_client(FakeDb(), monkeypatch)


@pytest.fixture
def quota(monkeypatch: pytest.MonkeyPatch) -> Mock:
    consume = Mock(return_value=None)
    monkeypatch.setattr(db, "consume_message_quota", consume)
    return consume


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize(
    "content, detail",
    [
        ("x" * 2001, "Message content must be at most 2000 characters."),
        ("", "Message content must not be empty."),
        (" \t\n ", "Message content must not be empty."),
    ],
)
def test_invalid_content_spends_nothing(
    client: TestClient, quota: Mock, monkeypatch: pytest.MonkeyPatch,
    endpoint: str, content: str, detail: str,
) -> None:
    run = Mock()
    stream = Mock()
    monkeypatch.setattr(agent, "run_turn", run)
    monkeypatch.setattr(agent, "stream_turn", stream)

    response = client.post(endpoint, json={"content": content})

    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    quota.assert_not_called()
    run.assert_not_called()
    stream.assert_not_called()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("scope", ["total", "ip", "visitor"])
def test_exhausted_quota_rejects_before_model(
    client: TestClient, quota: Mock, monkeypatch: pytest.MonkeyPatch,
    endpoint: str, scope: str,
) -> None:
    class FixedTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 26, 23, 59, 58, 500000, tzinfo=UTC)

    monkeypatch.setattr(limits, "datetime", FixedTime)
    quota.return_value = scope
    run = Mock()
    stream = Mock()
    monkeypatch.setattr(agent, "run_turn", run)
    monkeypatch.setattr(agent, "stream_turn", stream)

    response = client.post(endpoint, json={"content": "Hello"})

    assert response.status_code == 429
    expected = limits.TOTAL_LIMIT_DETAIL if scope == "total" else limits.PERSONAL_LIMIT_DETAIL
    assert response.json() == {"detail": expected}
    assert response.headers["retry-after"] == "2"
    quota.assert_called_once()
    run.assert_not_called()
    stream.assert_not_called()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_unknown_conversation_spends_nothing(
    client: TestClient, quota: Mock, monkeypatch: pytest.MonkeyPatch, endpoint: str,
) -> None:
    run = Mock()
    stream = Mock()
    monkeypatch.setattr(agent, "run_turn", run)
    monkeypatch.setattr(agent, "stream_turn", stream)

    response = client.post(endpoint, json={"content": "Hi", "conversation_id": str(uuid4())})

    assert response.status_code == 404
    quota.assert_not_called()
    run.assert_not_called()
    stream.assert_not_called()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_disabled_limits_skip_quota(
    client: TestClient, quota: Mock, monkeypatch: pytest.MonkeyPatch, endpoint: str,
) -> None:
    monkeypatch.setattr(config, "DAILY_MESSAGES_PER_VISITOR", None)

    assert client.post(endpoint, json={"content": "Hello"}).status_code == 200
    quota.assert_not_called()


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize(
    "setting", ["DAILY_MESSAGES_PER_VISITOR", "DAILY_MESSAGES_PER_IP", "DAILY_MESSAGES_TOTAL"]
)
def test_accepted_message_consumes_once_and_hashes_ip(
    client: TestClient, quota: Mock, monkeypatch: pytest.MonkeyPatch, endpoint: str, setting: str,
) -> None:
    monkeypatch.setattr(config, "DAILY_MESSAGES_PER_VISITOR", None)
    monkeypatch.setattr(config, setting, 0)
    monkeypatch.setattr(config, "TRUST_PROXY", True)
    response = client.post(
        endpoint,
        json={"content": "  " + "x" * 2000 + "  "},
        headers={"X-Forwarded-For": "spoofed, 192.0.2.8"},
    )

    assert response.status_code == 200
    quota.assert_called_once()
    assert quota.call_args.args[1:] == (
        VISITOR_ID,
        limits.hash_ip("192.0.2.8"),
        0 if setting == "DAILY_MESSAGES_PER_VISITOR" else None,
        0 if setting == "DAILY_MESSAGES_PER_IP" else None,
        0 if setting == "DAILY_MESSAGES_TOTAL" else None,
    )
    saved = client.get("/api/messages").json()
    assert saved[0]["content"] == "x" * 2000


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_failed_turn_still_consumes_quota(
    client: TestClient, quota: Mock, monkeypatch: pytest.MonkeyPatch, endpoint: str,
) -> None:
    def fail(*args: object) -> None:
        quota.assert_called_once()
        raise RuntimeError("Turn failed")

    monkeypatch.setattr(agent, "run_turn", fail)
    monkeypatch.setattr(agent, "stream_turn", fail)
    if endpoint.endswith("/stream"):
        response = client.post(endpoint, json={"content": "Hello"})
        assert "event: error" in response.text
    else:
        with pytest.raises(RuntimeError, match="Turn failed"):
            client.post(endpoint, json={"content": "Hello"})
    quota.assert_called_once()


@pytest.mark.parametrize(
    "trust, forwarded, expected",
    [
        (False, None, "192.0.2.1"),
        (False, "spoofed, 198.51.100.2", "192.0.2.1"),
        (True, None, "192.0.2.1"),
        (True, "", "192.0.2.1"),
        (True, "198.51.100.2", "198.51.100.2"),
        (True, "spoofed, 203.0.113.3, 198.51.100.2 ", "198.51.100.2"),
    ],
)
def test_client_ip(
    monkeypatch: pytest.MonkeyPatch, trust: bool, forwarded: str | None, expected: str,
) -> None:
    monkeypatch.setattr(config, "TRUST_PROXY", trust)
    headers = [] if forwarded is None else [(b"x-forwarded-for", forwarded.encode())]
    request = Request({"type": "http", "client": ("192.0.2.1", 80), "headers": headers})
    assert limits.client_ip(request) == expected


def test_client_ip_uses_the_proxy_value_across_separate_header_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "TRUST_PROXY", True)
    # The client sent the first line; the proxy appended the second.
    headers = [(b"x-forwarded-for", b"198.51.100.1"), (b"x-forwarded-for", b"192.0.2.8")]
    request = Request({"type": "http", "client": ("127.0.0.1", 80), "headers": headers})

    assert limits.client_ip(request) == "192.0.2.8"


@pytest.mark.parametrize("failure", [None, "read", "connect"])
def test_health_without_visitor(monkeypatch: pytest.MonkeyPatch, failure: str | None) -> None:
    database = Mock()
    query = database.table.return_value.select.return_value.limit.return_value
    get_client = Mock(return_value=database)
    monkeypatch.setattr(db, "get_client", get_client)
    if failure == "read":
        query.execute.side_effect = RuntimeError("Unavailable")
    elif failure == "connect":
        get_client.side_effect = RuntimeError("Unavailable")

    response = TestClient(app).get("/api/health")

    assert response.status_code == (503 if failure else 200)
    assert response.json() == (
        {"detail": "Database unavailable."} if failure else {"status": "ok"}
    )
    if failure != "connect":
        database.table.assert_called_once_with("conversations")
        database.table.return_value.select.assert_called_once_with("id")
        database.table.return_value.select.return_value.limit.assert_called_once_with(1)
        query.execute.assert_called_once_with()


def test_ip_hash_is_keyed_and_changes_daily() -> None:
    first = limits.hash_ip("192.0.2.8", date(2026, 9, 26))

    assert first == limits.hash_ip("192.0.2.8", date(2026, 9, 26))
    assert first != limits.hash_ip("192.0.2.8", date(2026, 9, 27))
    assert first != limits.hash_ip("192.0.2.9", date(2026, 9, 26))
    assert first != hashlib.sha256(b"192.0.2.8").hexdigest()
    assert "192.0.2.8" not in first
