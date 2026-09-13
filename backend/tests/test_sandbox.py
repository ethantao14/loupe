import os
import resource
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
    """The tool ships disabled, so these tests turn it on explicitly."""
    monkeypatch.setattr(config, "ENABLE_CODE_EXECUTION", True)


@pytest.fixture(autouse=True)
def execution_backend(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    backend = getattr(request, "param", "host")
    if backend == "docker":
        reason = confine.unavailable_reason()
        if reason is not None:
            pytest.skip(reason)
    else:
        # Also bypass the fatal probe, so these stay tests of the host path
        # rather than tests of whether an image happens to be pullable.
        monkeypatch.setattr(confine, "command_prefix", lambda directory: [])
        monkeypatch.setattr(confine, "fatal_error", lambda: None)
    return backend


@pytest.mark.parametrize("execution_backend", ["host", "docker"], indirect=True)
def test_run_python_with_real_resource_limits() -> None:
    result = sandbox.run_python("print(2 + 2)")

    assert result.output == "4\n"
    assert result.failed is False


@pytest.mark.parametrize("code", [None, 123])
def test_run_python_rejects_non_string_code(code: object) -> None:
    result = sandbox.run_python(code)  # type: ignore[arg-type]

    assert result.output == "Error: code must be a string."
    assert result.failed is True


def test_run_python_reports_fatal_confinement_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(confine, "fatal_error", lambda: "Confinement unavailable.")

    result = sandbox.run_python("print('must not execute')")

    assert result.output == "Error: Confinement unavailable."
    assert result.failed is True


@pytest.mark.parametrize("execution_backend", ["host", "docker"], indirect=True)
def test_printed_error_prefix_is_not_a_failure() -> None:
    result = sandbox.run_python("print('Error: something')")

    assert result.output == "Error: something\n"
    assert result.failed is False


def test_missing_confinement_preserves_existing_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        confine, "_availability", lambda: confine.Probe(None, "Docker unavailable", False)
    )

    assert sandbox.run_python("print(2 + 2)").output == "4\n"


def test_failed_confinement_never_retries_unconfined(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(confine, "command_prefix", lambda directory: ["/no-such-launcher"])
    monkeypatch.setattr(confine, "remove_container", lambda directory: None)

    result = sandbox.run_python("print('must not execute')")

    assert result.output.startswith("Error:")
    assert "must not execute" not in result.output
    assert result.failed is True


def test_docker_signal_status_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(confine, "remove_container", lambda directory: None)
    monkeypatch.setattr(
        confine, "command_prefix",
        lambda directory: [sys.executable, "-I", "-c", f"raise SystemExit({128 + signal.SIGXCPU})"],
    )

    result = sandbox.run_python("pass")

    assert result.output.startswith("Error: Python was killed by SIGXCPU")
    assert result.failed is True


@pytest.mark.parametrize("execution_backend", ["host", "docker"], indirect=True)
def test_prints_and_combines_stdout_and_stderr():
    result = sandbox.run_python("import sys; print('hello'); print('problem', file=sys.stderr)")

    assert result.output == "hello\nproblem\n"


@pytest.mark.parametrize("code", ["raise RuntimeError('boom')", "raise SystemExit(7)"])
@pytest.mark.parametrize("execution_backend", ["host", "docker"], indirect=True)
def test_nonzero_exit_is_text(code: str) -> None:
    result = sandbox.run_python(code)

    assert result.output.startswith("Error: Python exited with code")
    assert result.failed is True
    if "RuntimeError" in code:
        assert "RuntimeError: boom" in result.output


@pytest.mark.parametrize("execution_backend", ["host", "docker"], indirect=True)
def test_infinite_loop_times_out(
    monkeypatch: pytest.MonkeyPatch, execution_backend: str,
) -> None:
    timeout = 2 if execution_backend == "docker" else 0.3
    monkeypatch.setattr(sandbox, "WALL_TIMEOUT_SECONDS", timeout)
    started = time.monotonic()

    result = sandbox.run_python("print('before loop')\nwhile True: pass")

    assert result.output.startswith("Error:")
    assert "timed out" in result.output
    assert "before loop" in result.output
    assert result.failed is True
    assert time.monotonic() - started < timeout + confine.DOCKER_TIMEOUT_SECONDS + 1


@pytest.mark.parametrize("execution_backend", ["host", "docker"], indirect=True)
def test_output_is_capped():
    result = sandbox.run_python(f"print('x' * {sandbox.MAX_OUTPUT_CHARS * 1000})")

    assert len(result.output) == sandbox.MAX_OUTPUT_CHARS
    assert result.output.endswith("[output truncated]")


@pytest.mark.parametrize("execution_backend", ["host", "docker"], indirect=True)
def test_error_note_survives_output_truncation():
    result = sandbox.run_python(
        f"print('x' * {sandbox.MAX_OUTPUT_CHARS * 10}); raise SystemExit(9)"
    )

    assert len(result.output) == sandbox.MAX_OUTPUT_CHARS
    assert result.output.startswith("Error: Python exited with code 9.")
    assert "[output truncated]" in result.output


@pytest.mark.parametrize("name", ["ANTHROPIC_API_KEY", "SUPABASE_SERVICE_KEY", "DATABASE_URL"])
@pytest.mark.parametrize("execution_backend", ["host", "docker"], indirect=True)
def test_credentials_are_not_inherited(monkeypatch, name):
    monkeypatch.setenv(name, "secret-must-not-leak")

    result = sandbox.run_python(f"import os; print(os.environ.get({name!r}))")

    assert result.output == "None\n"
    assert "secret-must-not-leak" not in result.output


@pytest.mark.parametrize("execution_backend", ["host", "docker"], indirect=True)
def test_working_directory_is_temporary_and_removed(monkeypatch, execution_backend):
    directories = []
    prefix = confine.command_prefix

    def record_directory(directory):
        directories.append(Path(directory))
        return prefix(directory)

    monkeypatch.setattr(confine, "command_prefix", record_directory)
    code = "import os; print(os.getcwd()); open('created.txt', 'w').write('temporary')"
    first = sandbox.run_python(code).output.strip()
    second = sandbox.run_python(code).output.strip()
    assert first == ("/work" if execution_backend == "docker" else str(directories[0].resolve()))
    assert second == ("/work" if execution_backend == "docker" else str(directories[1].resolve()))
    assert directories[0] != directories[1]
    assert all(path.name.startswith("loupe-python-") for path in directories)
    assert all(not path.exists() for path in directories)


@pytest.mark.parametrize("execution_backend", ["host", "docker"], indirect=True)
def test_uses_current_interpreter_and_isolated_mode(monkeypatch, tmp_path, execution_backend):
    (tmp_path / "injected_module.py").write_text("raise RuntimeError('injected')")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))

    result = sandbox.run_python(
        "import importlib.util, sys; print(sys.executable); "
        "print(sys.flags.isolated); print(sys.flags.no_user_site); "
        "print(importlib.util.find_spec('injected_module'))"
    )

    executable = "/usr/local/bin/python" if execution_backend == "docker" else sys.executable
    assert result.output.splitlines() == [executable, "1", "1", "None"]


@pytest.mark.parametrize("execution_backend", ["host", "docker"], indirect=True)
def test_stdin_is_closed():
    assert sandbox.run_python("import sys; print(repr(sys.stdin.read()))").output == "''\n"


def test_file_size_is_limited():
    result = sandbox.run_python(
        "import os\n"
        "try:\n"
        f"    open('large', 'wb').write(b'x' * {sandbox.FILE_SIZE_LIMIT_BYTES * 2})\n"
        "except OSError as error:\n"
        "    print(type(error).__name__)\n"
        "print(os.stat('large').st_size)"
    )

    assert result.output == f"OSError\n{sandbox.FILE_SIZE_LIMIT_BYTES}\n"


@pytest.mark.parametrize("execution_backend", ["host", "docker"], indirect=True)
def test_limit_signal_is_reported():
    result = sandbox.run_python("import os, signal; os.kill(os.getpid(), signal.SIGXCPU)")

    assert result.output.startswith("Error: Python was killed by SIGXCPU")
    assert "resource limit" in result.output


def test_cpu_limit_is_enforced():
    result = sandbox.run_python("while True: pass")

    assert "killed by SIG" in result.output
    assert "resource limit" in result.output
    assert "timed out" not in result.output


def test_memory_limit_is_enforced() -> None:
    # Probe in a child because lowering a hard limit cannot be undone.
    probe = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import resource, sys\n"
            "try:\n"
            f"    resource.setrlimit(resource.RLIMIT_AS, "
            f"({sandbox.MEMORY_LIMIT_BYTES}, {sandbox.MEMORY_LIMIT_BYTES}))\n"
            "except (ValueError, OSError):\n"
            "    sys.exit(77)\n",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if probe.returncode == 77:
        pytest.skip("The host cannot apply the memory limit")
    assert probe.returncode == 0, probe.stderr

    result = sandbox.run_python(f"data = bytearray({sandbox.MEMORY_LIMIT_BYTES * 2})")

    assert result.output.startswith("Error:")
    assert "MemoryError" in result.output


@pytest.mark.parametrize("close_output", [False, True])
def test_timeout_kills_grandchild(monkeypatch, close_output):
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


def test_applies_all_resource_limits(monkeypatch):
    calls = {}
    monkeypatch.setattr(resource, "setrlimit", lambda kind, limits: calls.update({kind: limits}))

    sandbox._apply_limits()

    assert calls == {
        resource.RLIMIT_CPU: (sandbox.CPU_LIMIT_SECONDS, sandbox.CPU_LIMIT_SECONDS + 1),
        resource.RLIMIT_AS: (sandbox.MEMORY_LIMIT_BYTES, sandbox.MEMORY_LIMIT_BYTES),
        resource.RLIMIT_FSIZE: (sandbox.FILE_SIZE_LIMIT_BYTES, sandbox.FILE_SIZE_LIMIT_BYTES),
        resource.RLIMIT_CORE: (0, 0),
    }


@pytest.mark.parametrize("error_type", [ValueError, OSError])
def test_unsupported_memory_limit_is_optional(
    monkeypatch: pytest.MonkeyPatch, error_type: type[ValueError] | type[OSError]
) -> None:
    calls: dict[int, tuple[int, int]] = {}

    def setrlimit(kind: int, limits: tuple[int, int]) -> None:
        calls[kind] = limits
        if kind == resource.RLIMIT_AS:
            raise error_type("unsupported memory limit")

    monkeypatch.setattr(resource, "setrlimit", setrlimit)

    sandbox._apply_limits()

    assert calls == {
        resource.RLIMIT_CPU: (sandbox.CPU_LIMIT_SECONDS, sandbox.CPU_LIMIT_SECONDS + 1),
        resource.RLIMIT_AS: (sandbox.MEMORY_LIMIT_BYTES, sandbox.MEMORY_LIMIT_BYTES),
        resource.RLIMIT_FSIZE: (sandbox.FILE_SIZE_LIMIT_BYTES, sandbox.FILE_SIZE_LIMIT_BYTES),
        resource.RLIMIT_CORE: (0, 0),
    }


@pytest.mark.parametrize("kind", [resource.RLIMIT_CPU, resource.RLIMIT_FSIZE, resource.RLIMIT_CORE])
@pytest.mark.parametrize("error_type", [ValueError, OSError])
def test_fails_closed_when_mandatory_limits_cannot_be_applied(
    monkeypatch: pytest.MonkeyPatch, kind: int, error_type: type[ValueError] | type[OSError]
) -> None:
    def setrlimit(resource_kind: int, limits: tuple[int, int]) -> None:
        if resource_kind == kind:
            raise error_type("unsupported required resource limit")

    monkeypatch.setattr(resource, "setrlimit", setrlimit)

    result = sandbox.run_python("print('must not execute')")

    assert result.output.startswith("Error: Could not run Python with required resource limits:")
    assert "must not execute" not in result.output
    assert result.failed is True


@pytest.mark.parametrize("execution_backend", ["host", "docker"], indirect=True)
def test_run_tool_dispatches(memory_store: Mock) -> None:
    assert tools.run_tool("run_python", {"code": "print(6 * 7)"}, memory_store) == (
        tools.ToolOutcome(output="42\n", failed=False)
    )
    assert tools.RUN_PYTHON_TOOL in tools.available_tools()
    assert tools.RUN_PYTHON_TOOL["input_schema"]["required"] == ["code"]


@pytest.mark.parametrize("execution_backend", ["host", "docker"], indirect=True)
def test_run_tool_dispatches_python_failure(memory_store: Mock) -> None:
    result = tools.run_tool("run_python", {"code": "import sys; sys.exit(3)"}, memory_store)

    assert result == tools.ToolOutcome(output="Error: Python exited with code 3.\n", failed=True)


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
    directories = []
    cleaned_up = []
    popen = subprocess.Popen

    def prefix(directory):
        directories.append(directory)
        return [sys.executable, "-I", "-u", "-c"]

    def launch(*args, **kwargs):
        assert kwargs["preexec_fn"] is None
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
    monkeypatch.setattr(
        confine, "command_prefix", lambda directory: [sys.executable, "-I", "-u", "-c"]
    )
    monkeypatch.setattr(confine, "remove_container", lambda directory: "Container removal failed.")

    result = sandbox.run_python("print('finished')")

    assert result.output == "Error: Container removal failed.\nfinished\n"
    assert result.failed is True
