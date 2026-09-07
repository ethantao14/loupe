import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import claude_client, db

app = FastAPI(title="Loupe API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class MessageIn(BaseModel):
    content: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: str


class SendMessageOut(BaseModel):
    user: MessageOut
    reply: MessageOut


def get_db_client():
    return db.get_client()


def get_claude_client():
    return claude_client.get_client()


@app.get("/api/messages", response_model=list[MessageOut])
def list_messages(client=Depends(get_db_client)) -> list[dict]:
    return db.fetch_messages(client)


@app.post("/api/messages", response_model=SendMessageOut)
def send_message(
    body: MessageIn,
    db_client=Depends(get_db_client),
    llm_client=Depends(get_claude_client),
) -> dict:
    # Nothing is persisted until the reply succeeds, so a failed call
    # leaves no orphaned user turn behind for the retry to duplicate.
    history = db.fetch_messages(db_client)
    pending = [*history, {"role": "user", "content": body.content}]
    reply_text = claude_client.generate_reply(llm_client, pending)

    user_message, reply = db.insert_exchange(db_client, body.content, reply_text)
    return {"user": user_message, "reply": reply}
