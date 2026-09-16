"""Optional local embeddings, available only after an explicit model download."""

from __future__ import annotations

import importlib
from functools import cache
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, NamedTuple, cast

if TYPE_CHECKING:
    # Typed as the torch base class, which is what declares __call__; the
    # transformers class does not, so mypy rejects calling the model.
    from torch.nn import Module
    from transformers import PreTrainedTokenizerBase

MODEL_ID = "voyageai/voyage-4-nano"
QUERY_PROMPT = "Represent the query for retrieving supporting documents: "
DOCUMENT_PROMPT = "Represent the document for retrieval: "
DIMENSIONS = 256
MAX_TOKENS = 512


class Probe(NamedTuple):
    """The cached snapshot directory, or a reason embeddings cannot run."""

    directory: str | None
    reason: str | None


_tokenizer: PreTrainedTokenizerBase | None = None
_model: Module | None = None
_load_error: str | None = None
_load_lock = Lock()


@cache
def _availability() -> Probe:
    try:
        importlib.import_module("torch")
        transformers = importlib.import_module("transformers")
        if transformers.__version__.split(".")[0] != "4":
            return Probe(None, "Embeddings require transformers 4.x; install transformers<5")
        from huggingface_hub import try_to_load_from_cache

        for filename in ("model.safetensors", "pytorch_model.bin"):
            path = try_to_load_from_cache(MODEL_ID, filename)
            if isinstance(path, str) and Path(path).is_file():
                return Probe(str(Path(path).parent), None)
    except Exception as error:
        return Probe(None, f"Embedding libraries unavailable: {error}")
    return Probe(
        None,
        f"{MODEL_ID} weights not cached; fetch with "
        f"huggingface-cli download {MODEL_ID}",
    )


def unavailable_reason() -> str | None:
    return _load_error or _availability().reason


def describe() -> str:
    reason = unavailable_reason()
    if reason is not None:
        return f"Embeddings unavailable: {reason}"
    return f"{MODEL_ID}: {DIMENSIONS} dimensions, mean pooling including prompt, L2 normalised"


def load() -> None:
    global _model, _tokenizer, _load_error
    with _load_lock:
        reason = unavailable_reason()
        if reason is not None:
            raise RuntimeError(reason)
        if _model is not None:
            return
        directory = _availability().directory
        assert directory is not None
        try:
            from transformers import AutoModel, AutoTokenizer

            # A local snapshot and local_files_only also keep custom code and
            # tokenizer resolution offline when the cache is incomplete.
            tokenizer = AutoTokenizer.from_pretrained(
                directory, trust_remote_code=True, local_files_only=True
            )
            model = AutoModel.from_pretrained(
                directory, trust_remote_code=True, local_files_only=True
            )
            model.eval()
        except Exception as error:
            _load_error = f"Could not load {MODEL_ID}: {error}"
            raise RuntimeError(_load_error) from error
        _tokenizer = tokenizer
        _model = model


def _encode(texts: list[str], prompt: str) -> list[list[float]]:
    load()
    if not texts:
        return []
    import torch
    from torch.nn.functional import normalize

    assert _tokenizer is not None and _model is not None
    inputs = _tokenizer(
        [prompt + text for text in texts],
        padding=True,
        truncation=True,
        max_length=MAX_TOKENS,
        return_tensors="pt",
    )
    with torch.inference_mode():
        hidden = _model(**inputs).last_hidden_state
        mask = inputs["attention_mask"].unsqueeze(-1).to(hidden.dtype)
        pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
        vectors = normalize(pooled[:, :DIMENSIONS], p=2, dim=1)
    return cast(list[list[float]], vectors.tolist())


def encode_documents(texts: list[str]) -> list[list[float]]:
    return _encode(texts, DOCUMENT_PROMPT)


def encode_query(text: str) -> list[float]:
    return _encode([text], QUERY_PROMPT)[0]
