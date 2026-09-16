import logging
from dataclasses import dataclass

from supabase import Client

from app import db, embedding
from app.ranking import fuse, rank, tokenize

RECALL_TOP_K = 10
MAX_MEMORY_CANDIDATES = 5000


@dataclass
class RecallResult:
    selected: list[tuple[str, float]]
    candidate_count: int
    fallback_reason: str | None = None
    rankers: tuple[str, ...] = ()


class MemoryStore:
    def __init__(self, client: Client) -> None:
        self.client = client

    def remember(self, fact: str) -> None:
        vector: list[float] | None = None
        if embedding.unavailable_reason() is None:
            try:
                vector = embedding.encode_documents([fact])[0]
            except Exception:
                logging.getLogger(__name__).exception("Could not embed memory; storing fact alone")
        db.insert_memory(self.client, fact, vector)

    def recall(self, limit: int) -> list[str]:
        return [memory["fact"] for memory in db.fetch_memories(self.client, limit)]

    def recall_relevant(self, query: str | None, limit: int = RECALL_TOP_K) -> RecallResult:
        """Rank the newest candidate facts, falling back to recency for zero matches."""
        if limit <= 0:
            return RecallResult([], 0)
        memories = db.fetch_memories(self.client, MAX_MEMORY_CANDIDATES)
        facts = [memory["fact"] for memory in memories]
        if not query or not tokenize(query):
            return RecallResult(
                [(fact, 0.0) for fact in facts[:limit]], len(facts), "no usable query text"
            )
        bm25 = rank(query, facts)
        matches = [(fact, score) for fact, score in bm25 if score > 0]
        fallback_reason = None
        if embedding.unavailable_reason() is None:
            try:
                vector = embedding.encode_query(query)
                dense = [
                    (
                        memory["fact"],
                        sum(a * b for a, b in zip(vector, memory["embedding"], strict=True)),
                    )
                    for memory in memories
                    if memory.get("embedding") is not None
                ]
                if dense:
                    dense.sort(key=lambda item: item[1], reverse=True)
                    rankers = ("bm25", "dense") if matches else ("dense",)
                    return RecallResult(fuse(bm25, dense)[:limit], len(facts), rankers=rankers)
            except Exception as error:
                fallback_reason = f"Dense recall failed: {error}"
        if matches:
            return RecallResult(matches[:limit], len(facts), fallback_reason, ("bm25",))
        reason = "no matching terms"
        if fallback_reason:
            reason = f"{fallback_reason}; {reason}"
        return RecallResult(
            [(fact, 0.0) for fact in facts[:limit]], len(facts), reason, ("bm25",)
        )
