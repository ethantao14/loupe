import hashlib
import hmac
import math
from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException, Request
from supabase import Client

from app import config, db

TOTAL_LIMIT_DETAIL = (
    "The live demo has used today's message budget. The replays still work, "
    "and the budget resets at midnight UTC."
)
PERSONAL_LIMIT_DETAIL = (
    "You have reached today's limit of live messages for this demo. The replays still work, "
    "and the limit resets at midnight UTC."
)


def client_ip(request: Request) -> str:
    if config.TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded.strip():
            return forwarded.rsplit(",", 1)[-1].strip()
    return request.client.host if request.client else "unknown"


def hash_ip(ip: str, day: date | None = None) -> str:
    # A plain hash of an IPv4 address is reversible by trying all of them, so
    # key it with a server secret. Including the day stops linking across days.
    day = day or datetime.now(UTC).date()
    message = f"{day.isoformat()}|{ip}".encode()
    return hmac.new(config.SUPABASE_SERVICE_KEY.encode(), message, hashlib.sha256).hexdigest()


def validate_content(content: str) -> str:
    content = content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Message content must not be empty.")
    if len(content) > config.MAX_MESSAGE_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Message content must be at most {config.MAX_MESSAGE_CHARS} characters.",
        )
    return content


def consume_quota(request: Request, client: Client, visitor_id: str) -> None:
    daily_limits = (
        config.DAILY_MESSAGES_PER_VISITOR,
        config.DAILY_MESSAGES_PER_IP,
        config.DAILY_MESSAGES_TOTAL,
    )
    if all(limit is None for limit in daily_limits):
        return
    scope = db.consume_message_quota(
        client, visitor_id, hash_ip(client_ip(request)), *daily_limits
    )
    if scope is not None:
        now = datetime.now(UTC)
        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        raise HTTPException(
            status_code=429,
            detail=TOTAL_LIMIT_DETAIL if scope == "total" else PERSONAL_LIMIT_DETAIL,
            headers={"Retry-After": str(math.ceil((midnight - now).total_seconds()))},
        )
