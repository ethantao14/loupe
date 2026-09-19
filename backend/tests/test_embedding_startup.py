from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app import embedding
from app.main import app


@pytest.mark.parametrize("available, fails", [(False, False), (True, False), (True, True)])
def test_startup_warms_available_model_and_survives_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    available: bool, fails: bool,
) -> None:
    monkeypatch.setattr(embedding, "unavailable_reason", lambda: None if available else "no torch")
    load = Mock(side_effect=RuntimeError("broken cache") if fails else None)
    monkeypatch.setattr(embedding, "load", load)
    with TestClient(app) as client:
        assert client.get("/openapi.json").status_code == 200
    assert load.call_count == int(available)
    if fails:
        assert "Could not warm up embeddings" in caplog.text
