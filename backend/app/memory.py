from supabase import Client

from app import db


class MemoryStore:
    def __init__(self, client: Client) -> None:
        self.client = client

    def remember(self, fact: str) -> None:
        db.insert_memory(self.client, fact)

    def recall(self, limit: int) -> list[str]:
        return [memory["fact"] for memory in db.fetch_memories(self.client, limit)]
