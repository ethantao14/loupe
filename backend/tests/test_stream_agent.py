from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_agent import Block, Response, ScriptedClient, text_response, tool_response

from app import agent, tools
from app.memory import RecallResult


def test_stream_emits_live_events_in_order_and_matches_run_turn(
    monkeypatch: pytest.MonkeyPatch, memory_store: Mock,
) -> None:
    memory_store.recall_relevant.return_value = RecallResult(
        [("Python preference", 1.5)], 3, rankers=("bm25",)
    )
    run_tool = Mock(return_value=tools.ToolOutcome("Tool failed", failed=True))
    monkeypatch.setattr(tools, "run_tool", run_tool)
    responses = [
        Response("tool_use", [
            SimpleNamespace(type="thinking", thinking="Consider the request"),
            Block("text", text="Checking"),
            Block("tool_use", name="fetch_url", block_id="tu_1", tool_input={"url": "https://a"}),
        ]),
        text_response("Done!"),
    ]
    client = ScriptedClient(responses)
    history = [{"role": "user", "content": "Python"}]
    stream = agent.stream_turn(client, history, memory_store)

    memory = next(stream)
    assert memory == agent.StepEvent(agent.Step(
        kind="memory",
        detail=("Selected 1 of 3 candidates\n"
                "Rankers: bm25; Embeddings unavailable: disabled for test\n"
                "- 1.500 | Python preference"),
    ))
    assert client.requests == []
    assert next(stream) == agent.TextDelta("Ch")
    assert next(stream) == agent.TextDelta("ecking")
    thinking = next(stream)
    preamble = next(stream)
    call = next(stream)
    assert thinking == agent.StepEvent(agent.Step("thinking", "Consider the request"))
    assert preamble == agent.StepEvent(agent.Step("thinking", "Checking"))
    assert call == agent.StepEvent(agent.Step("tool_call", "{'url': 'https://a'}", "fetch_url"))
    run_tool.assert_not_called()
    result = next(stream)
    assert result == agent.StepEvent(agent.Step("tool_error", "Tool failed", "fetch_url"))
    run_tool.assert_called_once()
    assert len(client.requests) == 1
    remaining = list(stream)
    expected_steps = [event.step for event in [memory, thinking, preamble, call, result]]
    expected_steps.append(agent.Step("answer", "Done!"))
    expected = agent.TurnResult("Done!", expected_steps)
    assert remaining == [
        agent.TextDelta("Do"), agent.TextDelta("ne!"),
        agent.StepEvent(expected_steps[-1]), agent.TurnComplete(expected),
    ]
    assert agent.run_turn(ScriptedClient(responses), history, memory_store) == expected


def test_stream_iteration_limit_emits_answer_and_one_completion(
    monkeypatch: pytest.MonkeyPatch, memory_store: Mock,
) -> None:
    monkeypatch.setattr(tools, "run_tool", Mock(return_value=tools.ToolOutcome("Again", False)))
    client = ScriptedClient([tool_response("https://a")] * agent.MAX_ITERATIONS)

    events = list(agent.stream_turn(client, [], memory_store))

    assert events[-2] == agent.StepEvent(agent.Step("answer", agent.OUT_OF_STEPS_REPLY))
    assert isinstance(events[-1], agent.TurnComplete)
    assert events[-1].result.reply == agent.OUT_OF_STEPS_REPLY
    assert events[-1].result.steps == [e.step for e in events if isinstance(e, agent.StepEvent)]
    assert sum(isinstance(e, agent.TurnComplete) for e in events) == 1
    assert not any(isinstance(e, agent.TextDelta) for e in events)
