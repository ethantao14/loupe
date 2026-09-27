import os
import re
from typing import overload

from dotenv import load_dotenv

load_dotenv()


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@overload
def optional_limit(name: str) -> int | None: ...


@overload
def optional_limit(name: str, default: int) -> int: ...


def optional_limit(name: str, default: int | None = None) -> int | None:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    if re.fullmatch(r"[0-9]+", value) is None:
        raise RuntimeError(f"{name} must be a non-negative integer.")
    return int(value)


ANTHROPIC_API_KEY = require_env("ANTHROPIC_API_KEY")
SUPABASE_URL = require_env("SUPABASE_URL")
SUPABASE_SERVICE_KEY = require_env("SUPABASE_SERVICE_KEY")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5")
DAILY_MESSAGES_PER_VISITOR = optional_limit("DAILY_MESSAGES_PER_VISITOR")
DAILY_MESSAGES_PER_IP = optional_limit("DAILY_MESSAGES_PER_IP")
DAILY_MESSAGES_TOTAL = optional_limit("DAILY_MESSAGES_TOTAL")
MAX_MESSAGE_CHARS = optional_limit("MAX_MESSAGE_CHARS", 2000)
TRUST_PROXY = (os.environ.get("TRUST_PROXY") or "false").strip().lower() in (
    "1",
    "true",
    "yes",
)

# Code execution runs only inside a container and is not offered when Docker
# is unavailable. Set ENABLE_CODE_EXECUTION=false to turn it off.
ENABLE_CODE_EXECUTION = (os.environ.get("ENABLE_CODE_EXECUTION") or "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
