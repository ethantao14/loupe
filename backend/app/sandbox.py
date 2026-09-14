"""Run Python only in Docker, bounding wall clock time and captured output.

The container has no network or host filesystem mounts, a read-only root, and
bounded writable /tmp and /work. Host credentials are not forwarded into it.
Container limits cap memory, CPU bandwidth and process count, not total CPU time.
After killing the client process group, container removal is attempted and any
removal failure is reported. Unavailable Docker or a failed container launch
never triggers execution on the host.
"""

import os
import selectors
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass

from app import confine

WALL_TIMEOUT_SECONDS = 5
MAX_OUTPUT_CHARS = 4000


# Container exit codes carry Linux signal numbers, which differ from this
# host's, so they are named from a Linux table rather than signal.Signals.
LINUX_SIGNALS = {
    1: "SIGHUP", 2: "SIGINT", 3: "SIGQUIT", 4: "SIGILL", 6: "SIGABRT",
    8: "SIGFPE", 9: "SIGKILL", 10: "SIGUSR1", 11: "SIGSEGV", 12: "SIGUSR2",
    13: "SIGPIPE", 14: "SIGALRM", 15: "SIGTERM", 24: "SIGXCPU", 25: "SIGXFSZ",
}
LINUX_SIGNAL_LIMIT = 65


@dataclass(frozen=True)
class SandboxResult:
    """What Python produced, and whether execution failed."""

    output: str
    failed: bool


def _linux_signal_name(number: int) -> str:
    return LINUX_SIGNALS.get(number, f"signal {number}")


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _format_output(output: bytearray, note: str) -> str:
    text = output.decode("utf-8", errors="replace")
    prefix = f"Error: {note}\n" if note else ""
    available = max(0, MAX_OUTPUT_CHARS - len(prefix))
    if len(text) > available:
        marker = "\n[output truncated]"
        text = text[: max(0, available - len(marker))] + marker
    return (prefix + text)[:MAX_OUTPUT_CHARS]


def run_python(code: str) -> SandboxResult:
    if not isinstance(code, str):
        return SandboxResult("Error: code must be a string.", failed=True)

    reason = confine.unavailable_reason()
    if reason is not None:
        return SandboxResult(f"Error: Python execution needs Docker: {reason}", failed=True)

    output = bytearray()
    note = ""
    try:
        with tempfile.TemporaryDirectory(prefix="loupe-python-") as directory:
            try:
                with subprocess.Popen(
                    confine.command_prefix(directory) + [code],
                    cwd=directory,
                    # Docker needs the host client configuration; no environment is
                    # forwarded into the container.
                    env=None,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                ) as process:
                    deadline = time.monotonic() + WALL_TIMEOUT_SECONDS
                    try:
                        assert process.stdout is not None
                        with selectors.DefaultSelector() as selector:
                            selector.register(process.stdout, selectors.EVENT_READ)
                            while selector.get_map():
                                remaining = deadline - time.monotonic()
                                if remaining <= 0:
                                    raise subprocess.TimeoutExpired(
                                        process.args, WALL_TIMEOUT_SECONDS
                                    )
                                if not selector.select(remaining):
                                    continue
                                chunk = os.read(process.stdout.fileno(), 65536)
                                if not chunk:
                                    selector.unregister(process.stdout)
                                    break
                                # Drain the pipe after the cap without growing parent memory.
                                # Four bytes per character cover UTF-8, plus an overflow sentinel.
                                budget = MAX_OUTPUT_CHARS * 4 + 1 - len(output)
                                output.extend(chunk[:budget])
                        process.wait(timeout=max(0, deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        note = f"Python timed out after {WALL_TIMEOUT_SECONDS} seconds."
                    finally:
                        # Also remove descendants when the direct child exits normally.
                        _kill_process_group(process)
                        process.wait()

                    returncode = process.returncode
                    # Docker reports container signals as shell-style exit statuses.
                    if 128 < returncode < 128 + LINUX_SIGNAL_LIMIT:
                        note = (
                            f"Python was killed by {_linux_signal_name(returncode - 128)} "
                            "(a resource limit may have been reached)."
                        )
                        returncode = 0
                    if not note and returncode < 0:
                        killed_by = signal.Signals(-returncode).name
                        note = (
                            f"Python was killed by {killed_by} "
                            "(a resource limit may have been reached)."
                        )
                    elif not note and process.returncode:
                        note = f"Python exited with code {process.returncode}."
            finally:
                failure = confine.remove_container(directory)
                if failure:
                    note = f"{note} ({failure})" if note else failure
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        note = f"Could not run Python in a container: {error}"

    return SandboxResult(_format_output(output, note), failed=bool(note))
