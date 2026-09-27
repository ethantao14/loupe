import runpy

import pytest

from app import config

LIMIT_NAMES = [
    "DAILY_MESSAGES_PER_VISITOR", "DAILY_MESSAGES_PER_IP", "DAILY_MESSAGES_TOTAL",
    "MAX_MESSAGE_CHARS",
]


@pytest.fixture(autouse=True)
def clean_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dotenv.load_dotenv", lambda: None)
    for name in [*LIMIT_NAMES, "TRUST_PROXY"]:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_unset_limits(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is not None:
        for name in LIMIT_NAMES:
            monkeypatch.setenv(name, value)
    loaded = runpy.run_path(config.__file__)
    for name in LIMIT_NAMES[:3]:
        assert loaded[name] is None
    assert loaded["MAX_MESSAGE_CHARS"] == 2000
    assert loaded["TRUST_PROXY"] is False


@pytest.mark.parametrize("name", LIMIT_NAMES)
@pytest.mark.parametrize("value", ["0", "10", " 2000 "])
def test_valid_limit(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)
    assert runpy.run_path(config.__file__)[name] == int(value)


@pytest.mark.parametrize("name", LIMIT_NAMES)
@pytest.mark.parametrize("value", ["no", "1.5", "-1", "1_000", "true"])
def test_invalid_limit_fails_at_import(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str,
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match=f"{name} must be a non-negative integer"):
        runpy.run_path(config.__file__)


@pytest.mark.parametrize("value, expected", [("true", True), ("false", False), ("", False)])
def test_trust_proxy(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("TRUST_PROXY", value)
    assert runpy.run_path(config.__file__)["TRUST_PROXY"] is expected
