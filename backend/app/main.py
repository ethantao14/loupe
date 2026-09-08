import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import agent, claude_client, db
from app.memory import MemoryStore

app = FastAPI(title="Loupe API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class MessageIn(BaseModel):
    content: str


class StepOut(BaseModel):
    id: str
    kind: str
    tool_name: str | None = None
    detail: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: str
    steps: list[StepOut] = []


class SendMessageOut(BaseModel):
    user: MessageOut
    reply: MessageOut


def _with_steps(messages: list[dict], steps: list[dict]) -> list[dict]:
    by_message: dict[str, list[dict]] = {}
    for step in steps:
        by_message.setdefault(step["message_id"], []).append(step)
    return [{**message, "steps": by_message.get(message["id"], [])} for message in messages]


def get_db_client():
    return db.get_client()


def get_claude_client():
    return claude_client.get_client()


@app.get("/api/messages", response_model=list[MessageOut])
def list_messages(client=Depends(get_db_client)) -> list[dict]:
    messages = db.fetch_messages(client)
    steps = db.fetch_steps(client, [m["id"] for m in messages if m["role"] == "assistant"])
    return _with_steps(messages, steps)


@app.post("/api/messages", response_model=SendMessageOut)
def send_message(
    body: MessageIn,
    db_client=Depends(get_db_client),
    llm_client=Depends(get_claude_client),
) -> dict:
    # Messages and steps are persisted together after the reply succeeds.
    # Facts saved by remember persist independently of the exchange.
    history = db.fetch_messages(db_client)
    pending = [*history, {"role": "user", "content": body.content}]
    result = agent.run_turn(llm_client, pending, MemoryStore(db_client))

    user_message, reply, steps = db.insert_exchange_with_steps(
        db_client,
        body.content,
        result.reply,
        [
            {"kind": step.kind, "tool_name": step.tool_name, "detail": step.detail}
            for step in result.steps
        ],
    )
    return {"user": user_message, "reply": _with_steps([reply], steps)[0]}
