import os

from dotenv import load_dotenv

load_dotenv()


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


ANTHROPIC_API_KEY = require_env("ANTHROPIC_API_KEY")
SUPABASE_URL = require_env("SUPABASE_URL")
SUPABASE_SERVICE_KEY = require_env("SUPABASE_SERVICE_KEY")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5")

# Code execution runs only inside a container and is not offered when Docker
# is unavailable. Set ENABLE_CODE_EXECUTION=false to turn it off.
ENABLE_CODE_EXECUTION = (os.environ.get("ENABLE_CODE_EXECUTION") or "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
