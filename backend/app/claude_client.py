import anthropic

from app.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

SYSTEM_PROMPT = "You are Loupe, a helpful assistant. Keep answers concise."


def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def generate_reply(client: anthropic.Anthropic, history: list[dict]) -> str:
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": m["role"], "content": m["content"]} for m in history],
    )
    # Thinking blocks can precede the answer, so take the first text block.
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""
