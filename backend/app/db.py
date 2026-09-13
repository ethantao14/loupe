from typing import cast

from supabase import Client, create_client

from app.config import SUPABASE_SERVICE_KEY, SUPABASE_URL

MESSAGES_TABLE = "messages"
CONVERSATIONS_TABLE = "conversations"
STEPS_TABLE = "steps"
MEMORIES_TABLE = "memories"
PAGE_SIZE = 1000
MESSAGE_ID_BATCH_SIZE = 200


def get_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def insert_memory(client: Client, fact: str) -> dict:
    response = client.rpc("insert_memory", {"fact": fact}).execute()
    return cast(dict, response.data)


def delete_memory(client: Client, memory_id: str) -> bool:
    response = client.table(MEMORIES_TABLE).delete().eq("id", memory_id).execute()
    return bool(response.data)


def fetch_memories(client: Client, limit: int | None = None) -> list[dict]:
    """Read facts newest first, optionally stopping at the requested limit."""
    memories: list[dict] = []
    while limit is None or len(memories) < limit:
        page_size = PAGE_SIZE if limit is None else min(PAGE_SIZE, limit - len(memories))
        response = (
            client.table(MEMORIES_TABLE)
            .select("*")
            .order("seq", desc=True)
            .range(len(memories), len(memories) + page_size - 1)
            .execute()
        )
        page = cast(list[dict], response.data)
        memories.extend(page)
        if len(page) < page_size:
            break
    return memories


def fetch_conversations(client: Client) -> list[dict]:
    conversations: list[dict] = []
    while True:
        response = (
            client.table(CONVERSATIONS_TABLE)
            .select("*")
            .order("seq", desc=True)
            .range(len(conversations), len(conversations) + PAGE_SIZE - 1)
            .execute()
        )
        page = cast(list[dict], response.data)
        conversations.extend(page)
        if len(page) < PAGE_SIZE:
            return conversations


def rename_conversation(client: Client, conversation_id: str, title: str) -> dict | None:
    """Returns the updated conversation, or None when there was no such row."""
    response = (
        client.table(CONVERSATIONS_TABLE)
        .update({"title": title})
        .eq("id", conversation_id)
        .execute()
    )
    updated = cast(list[dict], response.data)
    return updated[0] if updated else None


def delete_conversation(client: Client, conversation_id: str) -> bool:
    response = client.table(CONVERSATIONS_TABLE).delete().eq("id", conversation_id).execute()
    return bool(response.data)


def fetch_latest_conversation_id(client: Client) -> str | None:
    response = (
        client.table(CONVERSATIONS_TABLE)
        .select("id")
        .order("seq", desc=True)
        .limit(1)
        .execute()
    )
    conversations = cast(list[dict], response.data)
    return conversations[0]["id"] if conversations else None


def conversation_exists(client: Client, conversation_id: str) -> bool:
    response = (
        client.table(CONVERSATIONS_TABLE)
        .select("id")
        .eq("id", conversation_id)
        .limit(1)
        .execute()
    )
    return bool(response.data)


def fetch_messages(client: Client, conversation_id: str) -> list[dict]:
    messages: list[dict] = []
    while True:
        response = (
            client.table(MESSAGES_TABLE)
            .select("*")
            .eq("conversation_id", conversation_id)
            .order("seq")
            .range(len(messages), len(messages) + PAGE_SIZE - 1)
            .execute()
        )
        page = cast(list[dict], response.data)
        messages.extend(page)
        if len(page) < PAGE_SIZE:
            return messages


def fetch_steps(client: Client, message_ids: list[str]) -> list[dict]:
    if not message_ids:
        return []
    steps: list[dict] = []
    for start in range(0, len(message_ids), MESSAGE_ID_BATCH_SIZE):
        batch = message_ids[start : start + MESSAGE_ID_BATCH_SIZE]
        offset = 0
        while True:
            response = (
                client.table(STEPS_TABLE)
                .select("*")
                .in_("message_id", batch)
                .order("seq")
                .range(offset, offset + PAGE_SIZE - 1)
                .execute()
            )
            page = cast(list[dict], response.data)
            steps.extend(page)
            if len(page) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    return sorted(steps, key=lambda step: step["seq"])


def insert_exchange_with_steps(
    client: Client,
    conversation_id: str | None,
    user_content: str,
    reply_content: str,
    steps: list[dict],
) -> tuple[str, dict, dict, list[dict]]:
    response = client.rpc(
        "insert_exchange_with_steps",
        {
            "conversation": conversation_id,
            "user_content": user_content,
            "reply_content": reply_content,
            "steps": steps,
        },
    ).execute()
    exchange = cast(dict, response.data)
    return exchange["conversation_id"], exchange["user"], exchange["reply"], exchange["steps"]
