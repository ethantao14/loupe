from typing import cast

from supabase import Client, create_client

from app.config import SUPABASE_SERVICE_KEY, SUPABASE_URL

MESSAGES_TABLE = "messages"
STEPS_TABLE = "steps"


def get_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def fetch_messages(client: Client) -> list[dict]:
    response = client.table(MESSAGES_TABLE).select("*").order("seq").execute()
    return cast(list[dict], response.data)


def fetch_steps(client: Client, message_ids: list[str]) -> list[dict]:
    if not message_ids:
        return []
    response = (
        client.table(STEPS_TABLE)
        .select("*")
        .in_("message_id", message_ids)
        .order("seq")
        .execute()
    )
    return cast(list[dict], response.data)


def insert_steps(client: Client, message_id: str, steps: list[dict]) -> list[dict]:
    if not steps:
        return []
    rows = [{"message_id": message_id, **step} for step in steps]
    response = client.table(STEPS_TABLE).insert(rows).execute()
    return cast(list[dict], response.data)


def insert_exchange(client: Client, user_content: str, reply_content: str) -> list[dict]:
    # One statement, so a turn is never half stored.
    response = (
        client.table(MESSAGES_TABLE)
        .insert(
            [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": reply_content},
            ]
        )
        .execute()
    )
    return cast(list[dict], response.data)
