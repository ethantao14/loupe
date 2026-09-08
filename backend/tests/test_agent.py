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
        self.requests.append(kwargs)
        return self.responses.pop(0)


def text_response(text):
    return Response("end_turn", [Block("text", text=text)])


def tool_response(url):
    return Response(
        "tool_use",
        [Block("tool_use", name="fetch_url", block_id="tu_1", tool_input={"url": url})],
    )


def test_answers_without_tools():
    client = ScriptedClient([text_response("No tool needed.")])

    result = agent.run_turn(client, [{"role": "user", "content": "Hi"}])

    assert result.reply == "No tool needed."
    assert result.steps == [agent.Step(kind="answer", detail="No tool needed.")]
    assert len(client.requests) == 1


def test_runs_tool_then_answers(monkeypatch):
    monkeypatch.setattr(tools, "run_tool", lambda name, tool_input: "Page said hello")
    client = ScriptedClient(
        [tool_response("https://example.com"), text_response("The page says hello.")]
    )

    result = agent.run_turn(client, [{"role": "user", "content": "Read example.com"}])

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


def test_tools_are_offered_to_the_model():
    client = ScriptedClient([text_response("Hi")])

    agent.run_turn(client, [{"role": "user", "content": "Hi"}])

    assert client.requests[0]["tools"] == tools.TOOLS


def test_stops_after_iteration_limit(monkeypatch):
    monkeypatch.setattr(tools, "run_tool", lambda name, tool_input: "still going")
    client = ScriptedClient(
        [tool_response("https://example.com") for _ in range(agent.MAX_ITERATIONS)]
    )

    result = agent.run_turn(client, [{"role": "user", "content": "Loop forever"}])

    assert result.reply == agent.OUT_OF_STEPS_REPLY
    assert result.steps[-1] == agent.Step(kind="answer", detail=agent.OUT_OF_STEPS_REPLY)
    assert len(client.requests) == agent.MAX_ITERATIONS
