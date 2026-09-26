"""Run from backend with: .venv/bin/python -m scripts.backfill_embeddings --visitor-id UUID."""

import argparse
from uuid import UUID

from app import db, embedding

BATCH_SIZE = 32


def main(visitor_id: str) -> None:
    embedding.load()
    client = db.get_client()
    memories = [
        memory
        for memory in db.fetch_memories(client, visitor_id)
        if memory.get("embedding") is None
    ]
    updated = 0
    for start in range(0, len(memories), BATCH_SIZE):
        batch = memories[start : start + BATCH_SIZE]
        vectors = embedding.encode_documents([memory["fact"] for memory in batch])
        for memory, vector in zip(batch, vectors, strict=True):
            updated += db.update_memory_embedding(client, visitor_id, memory["id"], vector)
    print(f"Updated {updated} memories.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Embed one visitor's remembered facts.")
    parser.add_argument("--visitor-id", required=True, type=UUID)
    args = parser.parse_args()
    if args.visitor_id.int == 0:
        parser.error("--visitor-id must be a non-nil UUID")
    main(str(args.visitor_id))
