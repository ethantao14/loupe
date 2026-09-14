import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from app import config, confine, sandbox, tools


@pytest.fixture(autouse=True)
def enable_code_execution(monkeypatch):
    """Keep execution tests independent of the configured default."""
    monkeypatch.setattr(config, "ENABLE_CODE_EXECUTION", True)


@pytest.fixture
def execution_backend() -> None:
    reason = confine.unavailable_reason()
    if reason is not None:
        pytest.skip(reason)


@pytest.mark.usefixtures("execution_backend")
def test_run_python_in_a_container() -> None:
    result = sandbox.run_python("print(2 + 2)")

    assert result.output == "4\n"
    assert result.failed is False


@pytest.mark.parametrize("code", [None, 123])
def test_run_python_rejects_non_string_code(code: object) -> None:
    result = sandbox.run_python(code)  # type: ignore[arg-type]

    assert result.output == "Error: code must be a string."
    assert result.failed is True


def test_run_python_refuses_unavailable_confinement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        confine, "_availability", lambda: confine.Probe(None, "Docker daemon unavailable")
    )
    launch = Mock(side_effect=AssertionError("Code must not execute"))
    monkeypatch.setattr(sandbox.subprocess, "Popen", launch)

    result = sandbox.run_python("print('must not execute')")

    assert result.output == "Error: Python execution needs Docker: Docker daemon unavailable"
    assert result.failed is True
    launch.assert_not_called()


@pytest.mark.usefixtures("execution_backend")
def test_printed_error_prefix_is_not_a_failure() -> None:
    result = sandbox.run_python("print('Error: something')")

    assert result.output == "Error: something\n"
    assert result.failed is False


def test_failed_confinement_never_retries_unconfined(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(confine, "unavailable_reason", lambda: None)
    monkeypatch.setattr(confine, "command_prefix", lambda directory: ["/no-such-launcher"])
    monkeypatch.setattr(confine, "remove_container", lambda directory: None)

    result = sandbox.run_python("print('must not execute')")

    assert result.output.startswith("Error:")
    assert "must not execute" not in result.output
    assert result.failed is True


def test_docker_signal_status_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(confine, "unavailable_reason", lambda: None)
    monkeypatch.setattr(confine, "remove_container", lambda directory: None)
    monkeypatch.setattr(
        confine, "command_prefix",
        lambda directory: [sys.executable, "-I", "-c", "raise SystemExit(152)"],
    )

    result = sandbox.run_python("pass")

    assert result.output.startswith("Error: Python was killed by SIGXCPU")
    assert result.failed is True


@pytest.mark.usefixtures("execution_backend")
def test_prints_and_combines_stdout_and_stderr():
    result = sandbox.run_python("import sys; print('hello'); print('problem', file=sys.stderr)")

    assert result.output == "hello\nproblem\n"


@pytest.mark.parametrize("code", ["raise RuntimeError('boom')", "raise SystemExit(7)"])
@pytest.mark.usefixtures("execution_backend")
def test_nonzero_exit_is_text(code: str) -> None:
    result = sandbox.run_python(code)

    assert result.output.startswith("Error: Python exited with code")
    assert result.failed is True
    if "RuntimeError" in code:
        assert "RuntimeError: boom" in result.output


@pytest.mark.usefixtures("execution_backend")
def test_infinite_loop_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    timeout = 2
    monkeypatch.setattr(sandbox, "WALL_TIMEOUT_SECONDS", timeout)
    started = time.monotonic()

    result = sandbox.run_python("print('before loop')\nwhile True: pass")

    assert result.output.startswith("Error:")
    assert "timed out" in result.output
    assert "before loop" in result.output
    assert result.failed is True
    assert time.monotonic() - started < timeout + confine.DOCKER_TIMEOUT_SECONDS + 1


@pytest.mark.usefixtures("execution_backend")
def test_output_is_capped():
    result = sandbox.run_python(f"print('x' * {sandbox.MAX_OUTPUT_CHARS * 1000})")

    assert len(result.output) == sandbox.MAX_OUTPUT_CHARS
    assert result.output.endswith("[output truncated]")


@pytest.mark.usefixtures("execution_backend")
def test_error_note_survives_output_truncation():
    result = sandbox.run_python(
        f"print('x' * {sandbox.MAX_OUTPUT_CHARS * 10}); raise SystemExit(9)"
    )

    assert len(result.output) == sandbox.MAX_OUTPUT_CHARS
    assert result.output.startswith("Error: Python exited with code 9.")
    assert "[output truncated]" in result.output


@pytest.mark.parametrize("name", ["ANTHROPIC_API_KEY", "SUPABASE_SERVICE_KEY", "DATABASE_URL"])
@pytest.mark.usefixtures("execution_backend")
def test_credentials_are_not_inherited(monkeypatch, name):
    monkeypatch.setenv(name, "secret-must-not-leak")

    result = sandbox.run_python(f"import os; print(os.environ.get({name!r}))")

    assert result.output == "None\n"
    assert "secret-must-not-leak" not in result.output


@pytest.mark.usefixtures("execution_backend")
def test_working_directory_is_temporary_and_removed(monkeypatch):
    directories = []
    prefix = confine.command_prefix

    def record_directory(directory):
        directories.append(Path(directory))
        return prefix(directory)

    monkeypatch.setattr(confine, "command_prefix", record_directory)
    code = "import os; print(os.getcwd()); open('created.txt', 'w').write('temporary')"
    first = sandbox.run_python(code).output.strip()
    second = sandbox.run_python(code).output.strip()
    assert first == "/work"
    assert second == "/work"
    assert directories[0] != directories[1]
    assert all(path.name.startswith("loupe-python-") for path in directories)
    assert all(not path.exists() for path in directories)


@pytest.mark.usefixtures("execution_backend")
def test_uses_container_interpreter_and_isolated_mode(monkeypatch, tmp_path):
    (tmp_path / "injected_module.py").write_text("raise RuntimeError('injected')")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))

    result = sandbox.run_python(
        "import importlib.util, sys; print(sys.executable); "
        "print(sys.flags.isolated); print(sys.flags.no_user_site); "
        "print(importlib.util.find_spec('injected_module'))"
    )

    assert result.output.splitlines() == ["/usr/local/bin/python", "1", "1", "None"]


@pytest.mark.usefixtures("execution_backend")
def test_stdin_is_closed():
    assert sandbox.run_python("import sys; print(repr(sys.stdin.read()))").output == "''\n"


@pytest.mark.usefixtures("execution_backend")
def test_limit_signal_is_reported():
    result = sandbox.run_python("import os, signal; os.kill(os.getpid(), signal.SIGXCPU)")

    assert result.output.startswith("Error: Python was killed by SIGXCPU")
    assert "resource limit" in result.output


@pytest.mark.usefixtures("execution_backend")
def test_memory_limit_is_enforced() -> None:
    result = sandbox.run_python("data = bytearray(1024 * 1024 * 1024)")

    assert result.output.startswith("Error: Python was killed by SIGKILL")
    assert result.failed is True


@pytest.mark.parametrize("close_output", [False, True])
def test_container_client_timeout_kills_grandchild(monkeypatch, close_output):
    monkeypatch.setattr(confine, "unavailable_reason", lambda: None)
    monkeypatch.setattr(
        confine, "command_prefix", lambda directory: [sys.executable, "-I", "-u", "-c"]
    )
    monkeypatch.setattr(confine, "remove_container", lambda directory: None)
    monkeypatch.setattr(sandbox, "WALL_TIMEOUT_SECONDS", 0.4)
    # A grandchild holds a pipe writer open; EOF proves it was killed even when
    # it remains a zombie awaiting adoption and reaping by the operating system.
    reader, writer = os.pipe()
    popen = subprocess.Popen

    def inherit_test_pipe(*args, **kwargs):
        return popen(*args, **kwargs, pass_fds=(writer,))

    monkeypatch.setattr(sandbox.subprocess, "Popen", inherit_test_pipe)
    code = (
        "import os, time\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        + ("    os.close(1); os.close(2)\n" if close_output else "")
        + "    time.sleep(30)\n"
        "else:\n"
        "    print(pid)\n"
        "    time.sleep(30)\n"
    )
    grandchild = None
    try:
        result = sandbox.run_python(code)
        grandchild = int(result.output.splitlines()[-1])
        assert "timed out" in result.output
        os.close(writer)
        writer = -1
        os.set_blocking(reader, False)
        deadline = time.monotonic() + 1
        while True:
            try:
                assert os.read(reader, 1) == b""
                break
            except BlockingIOError:
                assert time.monotonic() < deadline
                time.sleep(0.01)
    finally:
        os.close(reader)
        if writer != -1:
            os.close(writer)
        if grandchild is not None:
            try:
                os.kill(grandchild, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.usefixtures("execution_backend")
def test_run_tool_dispatches(memory_store: Mock) -> None:
    assert tools.run_tool("run_python", {"code": "print(6 * 7)"}, memory_store) == (
        tools.ToolOutcome(output="42\n", failed=False)
    )
    assert tools.RUN_PYTHON_TOOL in tools.available_tools()
    assert tools.RUN_PYTHON_TOOL["input_schema"]["required"] == ["code"]


@pytest.mark.usefixtures("execution_backend")
def test_run_tool_dispatches_python_failure(memory_store: Mock) -> None:
    result = tools.run_tool("run_python", {"code": "import sys; sys.exit(3)"}, memory_store)

    assert result == tools.ToolOutcome(output="Error: Python exited with code 3.\n", failed=True)


@pytest.mark.usefixtures("execution_backend")
def test_run_tool_preserves_success_for_printed_error_prefix(memory_store: Mock) -> None:
    result = tools.run_tool("run_python", {"code": "print('Error: something')"}, memory_store)

    assert result == tools.ToolOutcome(output="Error: something\n", failed=False)


@pytest.mark.parametrize("tool_input", [{}, {"code": None}, {"code": 123}])
def test_run_tool_rejects_invalid_code(tool_input, memory_store):
    assert tools.run_tool("run_python", tool_input, memory_store) == tools.ToolOutcome(
        output="Error: code must be a string.", failed=True
    )


def test_tool_is_withheld_unless_enabled(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_CODE_EXECUTION", False)

    assert tools.RUN_PYTHON_TOOL not in tools.available_tools()
    assert tools.FETCH_URL_TOOL in tools.available_tools()


def test_disabled_tool_refuses_to_run(monkeypatch, memory_store):
    monkeypatch.setattr(config, "ENABLE_CODE_EXECUTION", False)

    assert tools.run_tool("run_python", {"code": "print(1)"}, memory_store) == tools.ToolOutcome(
        output="Error: The run_python tool is disabled.", failed=True
    )


@pytest.mark.parametrize("times_out", [False, True])
def test_container_client_has_no_posix_limits_and_is_cleaned_up(monkeypatch, times_out):
    monkeypatch.setattr(confine, "unavailable_reason", lambda: None)
    directories = []
    cleaned_up = []
    popen = subprocess.Popen

    def prefix(directory):
        directories.append(directory)
        return [sys.executable, "-I", "-u", "-c"]

    def launch(*args, **kwargs):
        assert "preexec_fn" not in kwargs
        assert kwargs["env"] is None
        assert kwargs["start_new_session"] is True
        return popen(*args, **kwargs)

    monkeypatch.setattr(confine, "command_prefix", prefix)
    monkeypatch.setattr(confine, "remove_container", cleaned_up.append)
    monkeypatch.setattr(sandbox.subprocess, "Popen", launch)
    monkeypatch.setattr(sandbox, "WALL_TIMEOUT_SECONDS", 0.3)
    code = "print('started')"
    if times_out:
        code += "; import time; time.sleep(30)"

    result = sandbox.run_python(code)

    assert "started" in result.output
    assert ("timed out" in result.output) == times_out
    assert cleaned_up == directories
    assert len(cleaned_up) == 1
    assert result.failed is times_out


def test_container_removal_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(confine, "unavailable_reason", lambda: None)
    monkeypatch.setattr(
        confine, "command_prefix", lambda directory: [sys.executable, "-I", "-u", "-c"]
    )
    monkeypatch.setattr(confine, "remove_container", lambda directory: "Container removal failed.")

    result = sandbox.run_python("print('finished')")

    assert result.output == "Error: Container removal failed.\nfinished\n"
    assert result.failed is True
