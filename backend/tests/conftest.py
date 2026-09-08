import os
from unittest.mock import Mock

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")


@pytest.fixture
def memory_store() -> Mock:
    from app.memory import MemoryStore

    store = Mock(spec=MemoryStore)
    store.recall.return_value = []
    return store
