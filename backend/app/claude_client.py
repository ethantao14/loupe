import anthropic

from app.config import ANTHROPIC_API_KEY


def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
