from typing import cast

from supabase import Client, create_client

from app.config import SUPABASE_SERVICE_KEY, SUPABASE_URL

MESSAGES_TABLE = "messages"


def get_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def fetch_messages(client: Client) -> list[dict]:
    response = client.table(MESSAGES_TABLE).select("*").order("created_at").execute()
    return cast(list[dict], response.data)


def insert_message(client: Client, role: str, content: str) -> dict:
    response = (
        client.table(MESSAGES_TABLE)
        .insert({"role": role, "content": content})
        .execute()
    )
    return cast(dict, response.data[0])
