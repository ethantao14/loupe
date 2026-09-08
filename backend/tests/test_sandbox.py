import os
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app import sandbox, tools


def test_run_python_with_real_resource_limits() -> None:
    assert sandbox.run_python("print(2 + 2)") == "4\n"


def test_prints_and_combines_stdout_and_stderr():
    result = sandbox.run_python("import sys; print('hello'); print('problem', file=sys.stderr)")

    assert result == "hello\nproblem\n"


@pytest.mark.parametrize("code", ["raise RuntimeError('boom')", "raise SystemExit(7)"])
def test_nonzero_exit_is_text(code):
    result = sandbox.run_python(code)

    assert result.startswith("Error: Python exited with code")
    if "RuntimeError" in code:
        assert "RuntimeError: boom" in result


def test_infinite_loop_times_out(monkeypatch):
    monkeypatch.setattr(sandbox, "WALL_TIMEOUT_SECONDS", 0.3)
    started = time.monotonic()

    result = sandbox.run_python("print('before loop')\nwhile True: pass")

    assert result.startswith("Error:")
    assert "timed out" in result
    assert "before loop" in result
    assert time.monotonic() - started < 3


def test_output_is_capped():
    result = sandbox.run_python(f"print('x' * {sandbox.MAX_OUTPUT_CHARS * 1000})")

    assert len(result) == sandbox.MAX_OUTPUT_CHARS
    assert result.endswith("[output truncated]")


def test_error_note_survives_output_truncation():
    result = sandbox.run_python(
        f"print('x' * {sandbox.MAX_OUTPUT_CHARS * 10}); raise SystemExit(9)"
    )

    assert len(result) == sandbox.MAX_OUTPUT_CHARS
    assert result.startswith("Error: Python exited with code 9.")
    assert "[output truncated]" in result


@pytest.mark.parametrize("name", ["ANTHROPIC_API_KEY", "SUPABASE_SERVICE_KEY", "DATABASE_URL"])
def test_credentials_are_not_inherited(monkeypatch, name):
    monkeypatch.setenv(name, "secret-must-not-leak")

    result = sandbox.run_python(f"import os; print(os.environ.get({name!r}))")

    assert result == "None\n"
    assert "secret-must-not-leak" not in result


def test_working_directory_is_temporary_and_removed():
    code = "import os; print(os.getcwd()); open('created.txt', 'w').write('temporary')"
    first = Path(sandbox.run_python(code).strip())
    second = Path(sandbox.run_python(code).strip())
    repo = Path(__file__).resolve().parents[2]

    assert first.name.startswith("loupe-python-")
    assert first != repo
    assert repo not in first.parents
    assert first != second
    assert not first.exists()
    assert not second.exists()


def test_uses_current_interpreter_and_isolated_mode(monkeypatch, tmp_path):
    (tmp_path / "injected_module.py").write_text("raise RuntimeError('injected')")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))

    result = sandbox.run_python(
        "import importlib.util, sys; print(sys.executable); "
        "print(sys.flags.isolated); print(sys.flags.no_user_site); "
        "print(importlib.util.find_spec('injected_module'))"
    )

    assert result.splitlines() == [sys.executable, "1", "1", "None"]


def test_stdin_is_closed():
    assert sandbox.run_python("import sys; print(repr(sys.stdin.read()))") == "''\n"


def test_file_size_is_limited():
    result = sandbox.run_python(
        "import os\n"
        "try:\n"
        f"    open('large', 'wb').write(b'x' * {sandbox.FILE_SIZE_LIMIT_BYTES * 2})\n"
        "except OSError as error:\n"
        "    print(type(error).__name__)\n"
        "print(os.stat('large').st_size)"
    )

    assert result == f"OSError\n{sandbox.FILE_SIZE_LIMIT_BYTES}\n"


def test_limit_signal_is_reported():
    result = sandbox.run_python("import os, signal; os.kill(os.getpid(), signal.SIGXCPU)")

    assert result.startswith("Error: Python was killed by SIGXCPU")
    assert "resource limit" in result


def test_cpu_limit_is_enforced():
    result = sandbox.run_python("while True: pass")

    assert "killed by SIG" in result
    assert "resource limit" in result
    assert "timed out" not in result


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

    assert result.startswith("Error:")
    assert "MemoryError" in result


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
        grandchild = int(result.splitlines()[-1])
        assert "timed out" in result
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

    assert result.startswith("Error: Could not run Python with required resource limits:")
    assert "must not execute" not in result


def test_run_tool_dispatches():
    assert tools.run_tool("run_python", {"code": "print(6 * 7)"}) == "42\n"
    assert tools.RUN_PYTHON_TOOL in tools.TOOLS
    assert tools.RUN_PYTHON_TOOL["input_schema"]["required"] == ["code"]


@pytest.mark.parametrize("tool_input", [{}, {"code": None}, {"code": 123}])
def test_run_tool_rejects_invalid_code(tool_input):
    assert tools.run_tool("run_python", tool_input) == "Error: code must be a string."
