import json
import logging
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from uuid import UUID

from anthropic import Anthropic
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from supabase import Client

from app import agent, claude_client, db, embedding, limits
from app.memory import MemoryStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        if embedding.unavailable_reason() is None:
            embedding.load()
    except Exception:
        logging.getLogger(__name__).exception("Could not warm up embeddings; continuing startup")
    yield


app = FastAPI(title="Loupe API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


class MessageIn(BaseModel):
    content: str
    conversation_id: UUID | None = None


class ConversationOut(BaseModel):
    id: str
    title: str | None
    created_at: str


class ConversationUpdate(BaseModel):
    title: str

    @field_validator("title")
    @classmethod
    def validate_title(cls, title: str) -> str:
        title = " ".join(title.split())
        if not title or len(title) > 200:
            raise ValueError("Title must contain between 1 and 200 characters.")
        return title


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
    conversation_id: str
    user: MessageOut
    reply: MessageOut


class MemoryOut(BaseModel):
    id: str
    fact: str
    created_at: str


def _with_steps(messages: list[dict], steps: list[dict]) -> list[dict]:
    by_message: dict[str, list[dict]] = {}
    for step in steps:
        by_message.setdefault(step["message_id"], []).append(step)
    return [{**message, "steps": by_message.get(message["id"], [])} for message in messages]


def get_visitor_id(x_visitor_id: str | None = Header(default=None)) -> str:
    try:
        visitor_id = UUID(x_visitor_id) if x_visitor_id is not None else None
    except ValueError:
        visitor_id = None
    if visitor_id is None or visitor_id.int == 0:
        raise HTTPException(status_code=400, detail="X-Visitor-Id must be a valid, non-nil UUID.")
    return str(visitor_id)


def get_db_client() -> Client:
    return db.get_client()


def get_claude_client() -> Anthropic:
    return claude_client.get_client()


def accept_message(
    body: MessageIn,
    request: Request,
    client: Client = Depends(get_db_client),
    visitor_id: str = Depends(get_visitor_id),
) -> MessageIn:
    body.content = limits.validate_content(body.content)
    if body.conversation_id is not None and not db.conversation_exists(
        client, visitor_id, str(body.conversation_id)
    ):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    limits.consume_quota(request, client, visitor_id)
    return body


@app.get("/api/health")
def health() -> dict[str, str]:
    try:
        db.check_health(get_db_client())
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable.") from None
    return {"status": "ok"}


@app.get("/api/memories", response_model=list[MemoryOut])
def list_memories(
    client: Client = Depends(get_db_client),
    visitor_id: str = Depends(get_visitor_id),
) -> list[dict]:
    return db.fetch_memories(client, visitor_id)


@app.delete("/api/memories/{memory_id}", status_code=204)
def forget_memory(
    memory_id: UUID,
    client: Client = Depends(get_db_client),
    visitor_id: str = Depends(get_visitor_id),
) -> Response:
    if not db.delete_memory(client, visitor_id, str(memory_id)):
        raise HTTPException(status_code=404, detail="Remembered fact not found.")
    return Response(status_code=204)


@app.get("/api/conversations", response_model=list[ConversationOut])
def list_conversations(
    client: Client = Depends(get_db_client),
    visitor_id: str = Depends(get_visitor_id),
) -> list[dict]:
    return db.fetch_conversations(client, visitor_id)


@app.patch("/api/conversations/{conversation_id}", response_model=ConversationOut)
def rename_conversation(
    conversation_id: UUID,
    body: ConversationUpdate,
    client: Client = Depends(get_db_client),
    visitor_id: str = Depends(get_visitor_id),
) -> dict:
    conversation = db.rename_conversation(client, visitor_id, str(conversation_id), body.title)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation


@app.delete("/api/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: UUID,
    client: Client = Depends(get_db_client),
    visitor_id: str = Depends(get_visitor_id),
) -> Response:
    if not db.delete_conversation(client, visitor_id, str(conversation_id)):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return Response(status_code=204)


@app.get("/api/messages", response_model=list[MessageOut])
def list_messages(
    conversation_id: UUID | None = None,
    client: Client = Depends(get_db_client),
    visitor_id: str = Depends(get_visitor_id),
) -> list[dict]:
    selected_id: str | None
    if conversation_id is not None:
        selected_id = str(conversation_id)
        if not db.conversation_exists(client, visitor_id, selected_id):
            raise HTTPException(status_code=404, detail="Conversation not found.")
    else:
        selected_id = db.fetch_latest_conversation_id(client, visitor_id)
    if selected_id is None:
        return []
    messages = db.fetch_messages(client, selected_id)
    steps = db.fetch_steps(client, [m["id"] for m in messages if m["role"] == "assistant"])
    return _with_steps(messages, steps)


@app.post("/api/messages", response_model=SendMessageOut)
def send_message(
    body: MessageIn = Depends(accept_message),
    db_client: Client = Depends(get_db_client),
    llm_client: Anthropic = Depends(get_claude_client),
    visitor_id: str = Depends(get_visitor_id),
) -> dict:
    conversation_id = str(body.conversation_id) if body.conversation_id is not None else None
    # Messages and steps are persisted together after the reply succeeds.
    # Facts saved by remember persist independently of the exchange.
    history = db.fetch_messages(db_client, conversation_id) if conversation_id is not None else []
    pending = [*history, {"role": "user", "content": body.content}]
    result = agent.run_turn(llm_client, pending, MemoryStore(db_client, visitor_id))

    conversation_id, user_message, reply, steps = db.insert_exchange_with_steps(
        db_client,
        visitor_id,
        conversation_id,
        body.content,
        result.reply,
        [
            {"kind": step.kind, "tool_name": step.tool_name, "detail": step.detail}
            for step in result.steps
        ],
    )
    return {
        "conversation_id": conversation_id,
        "user": user_message,
        "reply": _with_steps([reply], steps)[0],
    }


def _sse_event(name: str, payload: dict) -> str:
    data = json.dumps(payload, separators=(",", ":"))
    return f"event: {name}\ndata: {data}\n\n"


@app.post("/api/messages/stream")
def stream_message(
    body: MessageIn = Depends(accept_message),
    db_client: Client = Depends(get_db_client),
    llm_client: Anthropic = Depends(get_claude_client),
    visitor_id: str = Depends(get_visitor_id),
) -> StreamingResponse:
    conversation_id = str(body.conversation_id) if body.conversation_id is not None else None
    history = db.fetch_messages(db_client, conversation_id) if conversation_id is not None else []
    pending = [*history, {"role": "user", "content": body.content}]

    def events() -> Iterator[str]:
        try:
            for event in agent.stream_turn(llm_client, pending, MemoryStore(db_client, visitor_id)):
                if isinstance(event, agent.TextDelta):
                    yield _sse_event("delta", {"text": event.text})
                elif isinstance(event, agent.StepEvent):
                    yield _sse_event("step", asdict(event.step))
                elif isinstance(event, agent.TurnComplete):
                    saved_id, user, reply, steps = db.insert_exchange_with_steps(
                        db_client,
                        visitor_id,
                        conversation_id,
                        body.content,
                        event.result.reply,
                        [asdict(step) for step in event.result.steps],
                    )
                    result = SendMessageOut(
                        conversation_id=saved_id,
                        user=MessageOut.model_validate(user),
                        reply=MessageOut.model_validate(_with_steps([reply], steps)[0]),
                    )
                    yield _sse_event("done", result.model_dump(mode="json"))
                    return
        except Exception:
            logging.getLogger(__name__).exception("Streaming turn failed")
            yield _sse_event("error", {"detail": "The turn failed. Please try again."})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
