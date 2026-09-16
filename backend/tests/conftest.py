import os
from unittest.mock import Mock

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"


@pytest.fixture(autouse=True)
def optional_embeddings(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    from app import embedding

    if request.module.__name__ != "test_embedding":
        monkeypatch.setattr(
            embedding, "_availability", lambda: embedding.Probe(None, "disabled for test")
        )


@pytest.fixture
def memory_store() -> Mock:
    from app.memory import MemoryStore, RecallResult

    store = Mock(spec=MemoryStore)
    store.recall.return_value = []
    store.recall_relevant.return_value = RecallResult([], 0)
    return store
