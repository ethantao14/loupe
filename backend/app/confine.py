"""Optional Docker confinement, falling back only when Docker is unavailable.

Only the disposable working directory is mounted from the host. The container
has no network, a read-only root filesystem, and memory, CPU and process caps.
A failed container launch never triggers an unconfined retry.
"""

import shutil
import subprocess
from functools import cache
from pathlib import Path

DOCKER_IMAGE = "python:3.13-slim"
DOCKER_MEMORY = "512m"
DOCKER_CPUS = "1"
DOCKER_PIDS_LIMIT = 64
DOCKER_TIMEOUT_SECONDS = 2


@cache
def _availability() -> tuple[str | None, str | None]:
    launcher = shutil.which("docker")
    if launcher is None:
        return None, "Docker binary not found on PATH"
    try:
        result = subprocess.run(
            [launcher, "info", "--format", "{{.ServerVersion}}"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=DOCKER_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, f"Docker daemon unavailable: {error}"
    if result.returncode:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        return None, f"Docker daemon unavailable: {detail}"
    return launcher, None


def unavailable_reason() -> str | None:
    """Return the cached binary/daemon check, including a bounded probe timeout."""
    return _availability()[1]


def command_prefix(directory: str) -> list[str]:
    """Return Docker and container Python arguments, or [] for the host fallback."""
    launcher, _ = _availability()
    if launcher is None:
        return []
    return [
        launcher,
        "run",
        "--rm",
        # Without an init process the code runs as PID 1, where signals with
        # default actions are ignored, so a kill would look like a clean exit.
        "--init",
        "--name",
        Path(directory).name,
        "--network",
        "none",
        "--memory",
        DOCKER_MEMORY,
        "--cpus",
        DOCKER_CPUS,
        "--pids-limit",
        str(DOCKER_PIDS_LIMIT),
        "--read-only",
        "--tmpfs",
        "/tmp:size=64m",
        "-v",
        f"{Path(directory).resolve()}:/work",
        "-w",
        "/work",
        DOCKER_IMAGE,
        # Merging the streams inside the container keeps their order stable.
        # The client writes them separately, so ordering is otherwise undefined.
        "sh",
        "-c",
        'exec python -I -u -c "$0" 2>&1',
    ]


def remove_container(directory: str) -> None:
    """Remove any container left running after its client exits or is killed."""
    launcher, _ = _availability()
    if launcher is None:
        return
    subprocess.run(
        [launcher, "rm", "--force", Path(directory).name],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=DOCKER_TIMEOUT_SECONDS,
        check=False,
    )


def describe() -> str:
    reason = unavailable_reason()
    if reason is not None:
        return f"Docker unavailable: {reason}; using weaker POSIX resource limits"
    return (
        f"Docker ({DOCKER_IMAGE}): host filesystem limited to working directory, "
        f"no network, read-only root; memory {DOCKER_MEMORY}, CPUs {DOCKER_CPUS}, "
        f"processes {DOCKER_PIDS_LIMIT}"
    )
