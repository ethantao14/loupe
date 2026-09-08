from copy import deepcopy

import pytest

from app import agent, tools


class Block:
    def __init__(self, block_type, text=None, name=None, block_id=None, tool_input=None):
        self.type = block_type
        self.text = text
        self.name = name
        self.id = block_id
        self.input = tool_input


class Response:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


class ScriptedClient:
    """Returns queued responses in order and records each request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(deepcopy(kwargs))
        return self.responses.pop(0)


def text_response(text):
    return Response("end_turn", [Block("text", text=text)])


def tool_response(url):
    return Response(
        "tool_use",
        [Block("tool_use", name="fetch_url", block_id="tu_1", tool_input={"url": url})],
    )


def test_answers_without_tools(memory_store):
    client = ScriptedClient([text_response("No tool needed.")])

    result = agent.run_turn(client, [{"role": "user", "content": "Hi"}], memory_store)

    assert result.reply == "No tool needed."
    assert result.steps == [agent.Step(kind="answer", detail="No tool needed.")]
    assert len(client.requests) == 1
    assert client.requests[0]["system"] == agent.SYSTEM_PROMPT
    memory_store.recall.assert_called_once_with(agent.MAX_RECALLED_MEMORIES)


def test_runs_tool_then_answers(monkeypatch, memory_store):
    monkeypatch.setattr(tools, "run_tool", lambda name, tool_input, memory_store: "Page said hello")
    client = ScriptedClient(
        [tool_response("https://example.com"), text_response("The page says hello.")]
    )

    result = agent.run_turn(client, [{"role": "user", "content": "Read example.com"}], memory_store)

    assert result.reply == "The page says hello."
    assert result.steps == [
        agent.Step(
            kind="tool_call",
            tool_name="fetch_url",
            detail="{'url': 'https://example.com'}",
        ),
        agent.Step(kind="tool_result", tool_name="fetch_url", detail="Page said hello"),
        agent.Step(kind="answer", detail="The page says hello."),
    ]
    # Second request carries the assistant tool_use turn and the tool result.
    sent = client.requests[1]["messages"]
    assert sent[-1]["content"][0]["type"] == "tool_result"
    assert sent[-1]["content"][0]["content"] == "Page said hello"
    assert sent[-1]["content"][0]["tool_use_id"] == "tu_1"


def test_tools_are_offered_to_the_model(memory_store):
    client = ScriptedClient([text_response("Hi")])

    agent.run_turn(client, [{"role": "user", "content": "Hi"}], memory_store)

    assert client.requests[0]["tools"] == tools.available_tools()


def test_interleaved_text_and_tools_preserve_order(
    monkeypatch: pytest.MonkeyPatch, memory_store
) -> None:
    monkeypatch.setattr(
        tools, "run_tool", lambda name, tool_input, memory_store: f"Result {tool_input['label']}"
    )
    response = Response(
        "tool_use",
        [
            Block("text", text="Text A"),
            Block("tool_use", name="tool_a", block_id="tu_a", tool_input={"label": "A"}),
            Block("text", text="Text B"),
            Block("tool_use", name="tool_b", block_id="tu_b", tool_input={"label": "B"}),
        ],
    )
    client = ScriptedClient([response, text_response("Final answer")])

    result = agent.run_turn(client, [{"role": "user", "content": "Run both tools"}], memory_store)

    assert result.reply == "Final answer"
    assert result.steps == [
        agent.Step(kind="thinking", detail="Text A"),
        agent.Step(kind="tool_call", tool_name="tool_a", detail="{'label': 'A'}"),
        agent.Step(kind="tool_result", tool_name="tool_a", detail="Result A"),
        agent.Step(kind="thinking", detail="Text B"),
        agent.Step(kind="tool_call", tool_name="tool_b", detail="{'label': 'B'}"),
        agent.Step(kind="tool_result", tool_name="tool_b", detail="Result B"),
        agent.Step(kind="answer", detail="Final answer"),
    ]
    assert len(client.requests) == 2
    sent = client.requests[1]["messages"]
    assert [message["role"] for message in sent] == ["user", "assistant", "user"]
    assert [vars(block) for block in sent[1]["content"]] == [
        vars(block) for block in response.content
    ]
    assert sent[2]["content"] == [
        {"type": "tool_result", "tool_use_id": "tu_a", "content": "Result A"},
        {"type": "tool_result", "tool_use_id": "tu_b", "content": "Result B"},
    ]


def test_stops_after_iteration_limit(monkeypatch, memory_store):
    monkeypatch.setattr(tools, "run_tool", lambda name, tool_input, memory_store: "still going")
    client = ScriptedClient(
        [tool_response("https://example.com") for _ in range(agent.MAX_ITERATIONS)]
    )

    result = agent.run_turn(client, [{"role": "user", "content": "Loop forever"}], memory_store)

    assert result.reply == agent.OUT_OF_STEPS_REPLY
    assert result.steps[-1] == agent.Step(kind="answer", detail=agent.OUT_OF_STEPS_REPLY)
    assert len(client.requests) == agent.MAX_ITERATIONS


def test_recall_injects_facts_and_records_first_step(memory_store, monkeypatch):
    facts = ["The user prefers Python.", "The project is called Loupe."]
    memory_store.recall.return_value = facts
    monkeypatch.setattr(tools, "run_tool", lambda name, tool_input, store: "Page content")
    client = ScriptedClient([tool_response("https://example.com"), text_response("Done")])

    result = agent.run_turn(client, [{"role": "user", "content": "Read the page"}], memory_store)

    assert result.steps[0] == agent.Step(kind="memory", detail="\n".join(f"- {f}" for f in facts))
    assert sum(step.kind == "memory" for step in result.steps) == 1
    memory_store.recall.assert_called_once_with(agent.MAX_RECALLED_MEMORIES)
    for request in client.requests:
        assert request["system"].startswith(agent.SYSTEM_PROMPT)
        assert "Known facts" in request["system"]
        assert all(fact in request["system"] for fact in facts)


def test_remember_tool_receives_store_and_reports_success(memory_store):
    client = ScriptedClient(
        [
            Response(
                "tool_use",
                [
                    Block(
                        "tool_use",
                        name="remember",
                        block_id="memory_1",
                        tool_input={"fact": "The user prefers Python."},
                    )
                ],
            ),
            text_response("Saved"),
        ]
    )

    result = agent.run_turn(client, [{"role": "user", "content": "I prefer Python"}], memory_store)

    memory_store.remember.assert_called_once_with("The user prefers Python.")
    assert [step.kind for step in result.steps] == ["tool_call", "tool_result", "answer"]
    assert client.requests[1]["messages"][-1]["content"][0]["content"] == (
        "Remembered: The user prefers Python."
    )
