from typing import cast

from supabase import Client, create_client

from app.config import SUPABASE_SERVICE_KEY, SUPABASE_URL

MESSAGES_TABLE = "messages"
STEPS_TABLE = "steps"
PAGE_SIZE = 1000


def get_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def fetch_messages(client: Client) -> list[dict]:
    messages: list[dict] = []
    while True:
        response = (
            client.table(MESSAGES_TABLE)
            .select("*")
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
    while True:
        response = (
            client.table(STEPS_TABLE)
            .select("*")
            .in_("message_id", message_ids)
            .order("seq")
            .range(len(steps), len(steps) + PAGE_SIZE - 1)
            .execute()
        )
        page = cast(list[dict], response.data)
        steps.extend(page)
        if len(page) < PAGE_SIZE:
            return steps


def insert_exchange_with_steps(
    client: Client, user_content: str, reply_content: str, steps: list[dict]
) -> tuple[dict, dict, list[dict]]:
    response = (
        client.rpc(
            "insert_exchange_with_steps",
            {"user_content": user_content, "reply_content": reply_content, "steps": steps},
        )
        .execute()
    )
    exchange = cast(dict, response.data)
    return exchange["user"], exchange["reply"], exchange["steps"]
