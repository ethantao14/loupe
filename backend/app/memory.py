from dataclasses import dataclass

from supabase import Client

from app import db
from app.ranking import rank, tokenize

RECALL_TOP_K = 10
MAX_MEMORY_CANDIDATES = 5000


@dataclass
class RecallResult:
    selected: list[tuple[str, float]]
    candidate_count: int
    fallback_reason: str | None = None


class MemoryStore:
    def __init__(self, client: Client) -> None:
        self.client = client

    def remember(self, fact: str) -> None:
        db.insert_memory(self.client, fact)

    def recall(self, limit: int) -> list[str]:
        return [memory["fact"] for memory in db.fetch_memories(self.client, limit)]

    def recall_relevant(self, query: str | None, limit: int = RECALL_TOP_K) -> RecallResult:
        """Rank the newest candidate facts, falling back to recency for zero matches."""
        if limit <= 0:
            return RecallResult([], 0)
        facts = self.recall(MAX_MEMORY_CANDIDATES)
        if not query or not tokenize(query):
            return RecallResult(
                [(fact, 0.0) for fact in facts[:limit]], len(facts), "no usable query text"
            )
        matches = [(fact, score) for fact, score in rank(query, facts) if score > 0]
        if matches:
            return RecallResult(matches[:limit], len(facts))
        return RecallResult(
            [(fact, 0.0) for fact in facts[:limit]], len(facts), "no matching terms"
        )
