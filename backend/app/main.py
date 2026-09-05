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


def get_db_client():
    return db.get_client()


def get_claude_client():
    return claude_client.get_client()


@app.get("/api/messages", response_model=list[MessageOut])
def list_messages(client=Depends(get_db_client)) -> list[dict]:
    return db.fetch_messages(client)


@app.post("/api/messages", response_model=MessageOut)
def send_message(
    body: MessageIn,
    db_client=Depends(get_db_client),
    llm_client=Depends(get_claude_client),
) -> dict:
    db.insert_message(db_client, "user", body.content)
    history = db.fetch_messages(db_client)
    reply_text = claude_client.generate_reply(llm_client, history)
    return db.insert_message(db_client, "assistant", reply_text)
