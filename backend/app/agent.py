import anthropic
from anthropic.types import MessageParam, ToolResultBlockParam

from app import tools
from app.config import CLAUDE_MODEL

SYSTEM_PROMPT = (
    "You are Loupe, a helpful assistant with tools. Use a tool when it would "
    "give you a better answer than guessing. Keep answers concise."
)

MAX_ITERATIONS = 5
OUT_OF_STEPS_REPLY = (
    "I couldn't finish that within my tool-use limit. Try narrowing the question."
)


def _first_text(response) -> str:
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


def run_turn(client: anthropic.Anthropic, history: list[dict]) -> str:
    """Run one assistant turn, letting the model call tools until it answers."""
    messages: list[MessageParam] = [
        {"role": m["role"], "content": m["content"]} for m in history
    ]

    for _ in range(MAX_ITERATIONS):
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=tools.TOOLS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            return _first_text(response)

        messages.append({"role": "assistant", "content": response.content})
        results: list[ToolResultBlockParam] = [
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": tools.run_tool(block.name, block.input),
            }
            for block in response.content
            if block.type == "tool_use"
        ]
        messages.append({"role": "user", "content": results})

    return OUT_OF_STEPS_REPLY
