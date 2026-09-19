"""Run from backend with: .venv/bin/python -m scripts.backfill_embeddings."""

from app import db, embedding

BATCH_SIZE = 32


def main() -> None:
    embedding.load()
    client = db.get_client()
    memories = [memory for memory in db.fetch_memories(client) if memory.get("embedding") is None]
    updated = 0
    for start in range(0, len(memories), BATCH_SIZE):
        batch = memories[start : start + BATCH_SIZE]
        vectors = embedding.encode_documents([memory["fact"] for memory in batch])
        for memory, vector in zip(batch, vectors, strict=True):
            response = (
                client.table(db.MEMORIES_TABLE)
                .update({"embedding": vector})
                .eq("id", memory["id"])
                .is_("embedding", "null")
                .execute()
            )
            updated += len(response.data)
    print(f"Updated {updated} memories.")


if __name__ == "__main__":
    main()
