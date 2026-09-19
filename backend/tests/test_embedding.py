import importlib
import math
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest

from app import embedding


@pytest.fixture(autouse=True)
def reset_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    embedding._availability.cache_clear()
    monkeypatch.setattr(embedding, "_model", None)
    monkeypatch.setattr(embedding, "_tokenizer", None)
    monkeypatch.setattr(embedding, "_load_error", None)
    yield
    embedding._availability.cache_clear()


def fake_libraries(monkeypatch: pytest.MonkeyPatch, version: str = "4.51.3") -> Mock:
    transformers = ModuleType("transformers")
    monkeypatch.setattr(transformers, "__version__", version, raising=False)
    hub = ModuleType("huggingface_hub")
    cached = Mock(return_value=None)
    monkeypatch.setattr(hub, "try_to_load_from_cache", cached, raising=False)
    monkeypatch.setitem(sys.modules, "torch", ModuleType("torch"))
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    return cached


@pytest.mark.parametrize("library", ["torch", "transformers"])
def test_missing_library_has_reason(monkeypatch: pytest.MonkeyPatch, library: str) -> None:
    fake_libraries(monkeypatch)
    monkeypatch.setitem(sys.modules, library, None)
    assert library in (embedding.unavailable_reason() or "")


@pytest.mark.parametrize("version", ["3.5.0", "5.0.0"])
def test_wrong_transformers_major(monkeypatch: pytest.MonkeyPatch, version: str) -> None:
    cached = fake_libraries(monkeypatch, version)
    assert "transformers 4.x" in (embedding.unavailable_reason() or "")
    cached.assert_not_called()


@pytest.mark.parametrize("cache_result", [None, object(), "/missing/model.safetensors"])
def test_weights_not_cached(monkeypatch: pytest.MonkeyPatch, cache_result: object) -> None:
    cached = fake_libraries(monkeypatch)
    cached.return_value = cache_result
    reason = embedding.unavailable_reason()
    assert reason is not None
    assert embedding.MODEL_ID in reason
    assert "not cached" in reason and "huggingface-cli download" in reason
    assert embedding.describe() == f"Embeddings unavailable: {reason}"
    embedding.unavailable_reason()
    assert cached.call_count == 2


def test_cached_weights_describe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cached = fake_libraries(monkeypatch)
    weights = tmp_path / "model.safetensors"
    weights.touch()
    cached.return_value = str(weights)
    assert embedding.unavailable_reason() is None
    assert embedding._availability().directory == str(tmp_path)
    description = embedding.describe()
    assert embedding.MODEL_ID in description
    assert "256 dimensions" in description
    assert "mean pooling including prompt" in description
    assert "L2 normalised" in description


@pytest.mark.parametrize("operation", ["query", "documents", "empty", "load"])
def test_unavailable_encoding_raises(monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    fake_libraries(monkeypatch)
    with pytest.raises(RuntimeError, match="not cached"):
        if operation == "query":
            embedding.encode_query("dog breed")
        elif operation == "load":
            embedding.load()
        else:
            embedding.encode_documents([] if operation == "empty" else ["A corgi"])


def test_load_is_local_and_only_runs_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cached = fake_libraries(monkeypatch)
    weights = tmp_path / "model.safetensors"
    weights.touch()
    cached.return_value = str(weights)
    transformers = importlib.import_module("transformers")
    model = Mock()
    tokenizer = Mock()
    monkeypatch.setattr(transformers, "AutoModel", model, raising=False)
    monkeypatch.setattr(transformers, "AutoTokenizer", tokenizer, raising=False)
    embedding.load()
    embedding.load()
    for factory in (model, tokenizer):
        factory.from_pretrained.assert_called_once_with(
            str(tmp_path), trust_remote_code=True, local_files_only=True
        )
    model.from_pretrained.return_value.eval.assert_called_once_with()


def test_incomplete_cache_failure_stays_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    cached = fake_libraries(monkeypatch)
    weights = tmp_path / "model.safetensors"
    weights.touch()
    cached.return_value = str(weights)
    transformers = importlib.import_module("transformers")
    tokenizer = Mock()
    tokenizer.from_pretrained.side_effect = OSError("missing tokenizer")
    monkeypatch.setattr(transformers, "AutoModel", Mock(), raising=False)
    monkeypatch.setattr(transformers, "AutoTokenizer", tokenizer, raising=False)
    with pytest.raises(RuntimeError, match="missing tokenizer"):
        embedding.load()
    assert "missing tokenizer" in (embedding.unavailable_reason() or "")
    with pytest.raises(RuntimeError, match="missing tokenizer"):
        embedding.encode_query("dog")
    assert tokenizer.from_pretrained.call_count == 1


def test_real_encoding_uses_cached_model_only() -> None:
    reason = embedding.unavailable_reason()
    if reason is not None:
        pytest.skip(reason)
    documents = embedding.encode_documents(["The user has a corgi named Biscuit", "Uses Python"])
    query = embedding.encode_query("what breed is my dog")
    assert len(documents) == 2
    for vector in [*documents, query]:
        assert len(vector) == embedding.DIMENSIONS
        assert all(math.isfinite(value) for value in vector)
        assert math.sqrt(sum(value * value for value in vector)) == pytest.approx(1.0, abs=1e-5)
    assert sum(a * b for a, b in zip(query, documents[0], strict=True)) > sum(
        a * b for a, b in zip(query, documents[1], strict=True)
    )
