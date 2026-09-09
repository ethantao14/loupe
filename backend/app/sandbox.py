"""Bound wall clock and captured output, and omit credentials from executed code.

With Docker, host filesystem access is limited to the disposable working directory.
The container has no network, a read-only root and a bounded writable /tmp.
Container limits cap memory, CPU bandwidth and process count. Timed-out containers
are removed after killing the client process group.
Without Docker, use a scrubbed environment, isolated host interpreter, disposable
cwd and POSIX CPU-time/file-size limits. Memory is capped where supported (Linux
yes, macOS no). Arbitrary host file reads, network access and detached descendants
remain possible. A failed container launch never retries without confinement.
"""

import os
import resource
import selectors
import signal
import subprocess
import sys
import tempfile
import time

from app import confine

CPU_LIMIT_SECONDS = 2
MEMORY_LIMIT_BYTES = 512 * 1024 * 1024
FILE_SIZE_LIMIT_BYTES = 1024 * 1024
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


def _linux_signal_name(number: int) -> str:
    return LINUX_SIGNALS.get(number, f"signal {number}")


def _apply_limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_LIMIT_SECONDS, CPU_LIMIT_SECONDS + 1))
    try:
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT_BYTES, MEMORY_LIMIT_BYTES))
    except (ValueError, OSError):
        pass
    resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_SIZE_LIMIT_BYTES, FILE_SIZE_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


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


def run_python(code: str) -> str:
    if not isinstance(code, str):
        return "Error: code must be a string."

    blocking = confine.fatal_error()
    if blocking:
        return f"Error: {blocking}"

    output = bytearray()
    note = ""
    try:
        with tempfile.TemporaryDirectory(prefix="loupe-python-") as directory:
            prefix = confine.command_prefix(directory)
            try:
                with subprocess.Popen(
                    (prefix + [code]) if prefix else [sys.executable, "-I", "-u", "-c", code],
                    cwd=directory,
                    # Docker needs the host client configuration; no environment is
                    # forwarded into the container. The fallback stays scrubbed.
                    env=(
                        None if prefix
                        else {"LANG": "C.UTF-8", "HOME": directory, "TMPDIR": directory}
                    ),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    preexec_fn=None if prefix else _apply_limits,
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
                    if prefix and 128 < returncode < 128 + LINUX_SIGNAL_LIMIT:
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
                if prefix:
                    confine.remove_container(directory)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        note = f"Could not run Python with required resource limits: {error}"

    return _format_output(output, note)
