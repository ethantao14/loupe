from dataclasses import dataclass, field

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
MAX_DETAIL_CHARS = 2000


@dataclass
class Step:
    """One thing the agent did, in the order it happened."""

    kind: str
    detail: str
    tool_name: str | None = None


@dataclass
class TurnResult:
    reply: str
    steps: list[Step] = field(default_factory=list)


def _shorten(text: str) -> str:
    if len(text) <= MAX_DETAIL_CHARS:
        return text
    return f"{text[:MAX_DETAIL_CHARS]}... [truncated]"


def run_turn(client: anthropic.Anthropic, history: list[dict]) -> TurnResult:
    """Run one assistant turn, recording each step the model and tools take."""
    messages: list[MessageParam] = [
        {"role": m["role"], "content": m["content"]} for m in history
    ]
    steps: list[Step] = []

    for _ in range(MAX_ITERATIONS):
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=tools.TOOLS,
            messages=messages,
        )

        is_final = response.stop_reason != "tool_use"
        reply: str | None = None
        results: list[ToolResultBlockParam] = []
        for block in response.content:
            if block.type == "thinking" and block.thinking:
                steps.append(Step(kind="thinking", detail=_shorten(block.thinking)))
            elif block.type == "text":
                if reply is None:
                    reply = block.text
                if block.text:
                    kind = "answer" if is_final else "thinking"
                    steps.append(Step(kind=kind, detail=_shorten(block.text)))
            elif block.type == "tool_use":
                steps.append(
                    Step(
                        kind="tool_call",
                        tool_name=block.name,
                        detail=_shorten(str(block.input)),
                    )
                )
                output = tools.run_tool(block.name, block.input)
                steps.append(
                    Step(kind="tool_result", tool_name=block.name, detail=_shorten(output))
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    }
                )

        if is_final:
            return TurnResult(reply=reply or "", steps=steps)

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": results})

    steps.append(Step(kind="answer", detail=OUT_OF_STEPS_REPLY))
    return TurnResult(reply=OUT_OF_STEPS_REPLY, steps=steps)
