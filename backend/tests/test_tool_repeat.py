from datetime import date
from unittest.mock import Mock, call

import pytest
from test_agent import Block, Response, ScriptedClient, text_response, tool_response

from app import agent, tools


@pytest.mark.parametrize("output", ["Network unavailable", "", "Error: " + "x" * 3000])
@pytest.mark.parametrize("same_response", [False, True])
def test_failed_repeat_emits_notice_without_execution(
    monkeypatch: pytest.MonkeyPatch, memory_store: Mock, output: str, same_response: bool,
) -> None:
    run_tool = Mock(return_value=tools.ToolOutcome(output, failed=True))
    monkeypatch.setattr(tools, "run_tool", run_tool)
    first = tool_response("https://example.com")
    repeat = Response("tool_use", [Block(
        "tool_use", name="fetch_url", block_id="tu_repeat",
        tool_input={"url": "https://example.com"},
    )])
    responses = (
        [Response("tool_use", first.content + repeat.content)]
        if same_response else [first, repeat]
    )
    client = ScriptedClient([*responses, text_response("Done")])

    events = list(agent.stream_turn(client, [], memory_store))

    run_tool.assert_called_once_with("fetch_url", {"url": "https://example.com"}, memory_store)
    steps = [event.step for event in events if isinstance(event, agent.StepEvent)]
    assert [step.kind for step in steps] == [
        "tool_call", "tool_error", "tool_call", "tool_repeat", "answer",
    ]
    assert steps[2].tool_name == steps[3].tool_name == "fetch_url"
    assert steps[2].detail == steps[0].detail
    notice = client.requests[-1]["messages"][-1]["content"][-1]
    assert notice["type"] == "tool_result"
    assert notice["tool_use_id"] == "tu_repeat"
    assert notice["is_error"] is True
    assert agent.REPEATED_CALL_NOTICE in notice["content"]
    assert f'Original error:\n"{output}"' in notice["content"]
    assert steps[3].detail.startswith(agent.REPEATED_CALL_NOTICE)
    assert len(steps[3].detail) <= agent.MAX_DETAIL_CHARS
    if len(notice["content"]) > agent.MAX_DETAIL_CHARS:
        assert steps[3].detail.endswith("... [truncated]")
    else:
        assert steps[3].detail == notice["content"]
    expected = agent.TurnResult(reply="Done", steps=steps)
    assert events[-1] == agent.TurnComplete(expected)
    assert sum(isinstance(event, agent.TurnComplete) for event in events) == 1
    assert agent.run_turn(
        ScriptedClient([*responses, text_response("Done")]), [], memory_store,
    ) == expected


@pytest.mark.parametrize(
    "first_failed, second_name, first_input, second_input, blocked",
    [
        (True, "fetch_url", {"url": "bad"}, {"url": "corrected"}, False),
        (False, "fetch_url", {"url": "same"}, {"url": "same"}, False),
        (True, "another_tool", {"url": "same"}, {"url": "same"}, False),
        (True, "fetch_url", {"a": 1, "b": {"c": 2, "d": 3}},
         {"b": {"d": 3, "c": 2}, "a": 1}, True),
        (True, "fetch_url", {"date": date(2026, 1, 1)}, {"date": date(2026, 1, 1)}, True),
    ],
    ids=["corrected-input", "success", "different-tool", "key-order", "odd-value"],
)
def test_repeat_matches_only_failed_tool_and_input(
    monkeypatch: pytest.MonkeyPatch, memory_store: Mock, first_failed: bool,
    second_name: str, first_input: dict[str, object], second_input: dict[str, object],
    blocked: bool,
) -> None:
    run_tool = Mock(side_effect=[
        tools.ToolOutcome("Original output", failed=first_failed),
        tools.ToolOutcome("Corrected output", failed=False),
    ])
    monkeypatch.setattr(tools, "run_tool", run_tool)
    client = ScriptedClient([
        Response("tool_use", [Block(
            "tool_use", name="fetch_url", block_id="tu_1", tool_input=first_input,
        )]),
        Response("tool_use", [Block(
            "tool_use", name=second_name, block_id="tu_2", tool_input=second_input,
        )]),
        text_response("Done"),
    ])

    result = agent.run_turn(client, [], memory_store)

    expected_calls = [call("fetch_url", first_input, memory_store)]
    if not blocked:
        expected_calls.append(call(second_name, second_input, memory_store))
    assert run_tool.call_args_list == expected_calls
    assert [step.kind for step in result.steps] == [
        "tool_call", "tool_error" if first_failed else "tool_result",
        "tool_call", "tool_repeat" if blocked else "tool_result", "answer",
    ]
    second_result = client.requests[2]["messages"][-1]["content"][0]
    assert second_result.get("is_error", False) is blocked
    if not blocked:
        assert second_result["content"] == "Corrected output"


def test_blocked_calls_still_exhaust_iterations(
    monkeypatch: pytest.MonkeyPatch, memory_store: Mock,
) -> None:
    run_tool = Mock(return_value=tools.ToolOutcome("Failed", failed=True))
    monkeypatch.setattr(tools, "run_tool", run_tool)
    client = ScriptedClient([tool_response("https://example.com")] * agent.MAX_ITERATIONS)

    events = list(agent.stream_turn(client, [], memory_store))

    run_tool.assert_called_once()
    assert len(client.requests) == agent.MAX_ITERATIONS
    steps = [event.step for event in events if isinstance(event, agent.StepEvent)]
    assert [step.kind for step in steps] == ["tool_call", "tool_error"] + [
        "tool_call", "tool_repeat",
    ] * (agent.MAX_ITERATIONS - 1) + ["answer"]
    assert events[-1] == agent.TurnComplete(agent.TurnResult(agent.OUT_OF_STEPS_REPLY, steps))
    assert sum(isinstance(event, agent.TurnComplete) for event in events) == 1


def test_failed_calls_are_forgotten_between_turns(
    monkeypatch: pytest.MonkeyPatch, memory_store: Mock,
) -> None:
    run_tool = Mock(return_value=tools.ToolOutcome("Failed", failed=True))
    monkeypatch.setattr(tools, "run_tool", run_tool)
    client = ScriptedClient([tool_response("https://example.com"), text_response("Done")] * 2)

    first = agent.run_turn(client, [], memory_store)
    second = agent.run_turn(client, [], memory_store)

    assert run_tool.call_count == 2
    assert first == second
    assert [step.kind for step in second.steps] == ["tool_call", "tool_error", "answer"]
