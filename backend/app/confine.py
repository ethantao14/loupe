"""Optional Docker confinement, falling back only when Docker is unavailable.

Only the disposable working directory is mounted from the host. The container
has no network, a read-only root filesystem, and memory, CPU and process caps.
A failed container launch never triggers an unconfined retry.
"""

import shutil
import subprocess
from functools import cache
from pathlib import Path
from typing import NamedTuple

DOCKER_TMPFS_SIZE = "64m"  # Bounds what executed code can write.
DOCKER_IMAGE = "python:3.13-slim"
DOCKER_MEMORY = "512m"
DOCKER_CPUS = "1"
DOCKER_PIDS_LIMIT = 64
DOCKER_TIMEOUT_SECONDS = 2
DOCKER_PULL_TIMEOUT_SECONDS = 300
REMOVE_ATTEMPTS = 3  # A first pull is slow, and happens once.


class Probe(NamedTuple):
    """Whether confinement is usable, and whether failing back is acceptable."""

    launcher: str | None
    reason: str | None
    fatal: bool


@cache
def _availability() -> Probe:
    launcher = shutil.which("docker")
    if launcher is None:
        return Probe(None, "Docker binary not found on PATH", False)
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
        return Probe(None, f"Docker daemon unavailable: {error}", False)
    if result.returncode:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        return Probe(None, f"Docker daemon unavailable: {detail}", False)

    missing = _ensure_image(launcher)
    if missing:
        # Docker is here but unusable. Falling back would quietly drop isolation,
        # so this is fatal, decided by where it failed rather than by its wording.
        return Probe(None, missing, True)
    return Probe(launcher, None, False)


def _ensure_image(launcher: str) -> str | None:
    """Pull the image once up front, so a cold start cannot eat the run deadline."""
    try:
        present = subprocess.run(
            [launcher, "image", "inspect", DOCKER_IMAGE],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=DOCKER_TIMEOUT_SECONDS,
            check=False,
        )
        if present.returncode == 0:
            return None
        pulled = subprocess.run(
            [launcher, "pull", "--quiet", DOCKER_IMAGE],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=DOCKER_PULL_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"Could not prepare {DOCKER_IMAGE}: {error}"
    if pulled.returncode:
        detail = pulled.stderr.strip() or f"exit code {pulled.returncode}"
        return f"Could not prepare {DOCKER_IMAGE}: {detail}"
    return None


def fatal_error() -> str | None:
    """A reason the tool must refuse rather than run with weaker confinement."""
    probe = _availability()
    return probe.reason if probe.fatal else None


def unavailable_reason() -> str | None:
    """Return the cached binary/daemon check, including a bounded probe timeout."""
    return _availability().reason


def command_prefix(directory: str) -> list[str]:
    """Return Docker and container Python arguments, or [] for the host fallback."""
    launcher = _availability().launcher
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
        # Container output is captured through the client, so host side logging
        # would only be an unbounded second copy.
        "--log-driver",
        "none",
        # Docker injects proxy settings from client config, which can carry
        # credentials. Blank them so executed code cannot read them.
        *_blank_proxy_arguments(),
        "--memory",
        DOCKER_MEMORY,
        "--cpus",
        DOCKER_CPUS,
        "--pids-limit",
        str(DOCKER_PIDS_LIMIT),
        "--read-only",
        "--tmpfs",
        f"/tmp:size={DOCKER_TMPFS_SIZE}",
        # A tmpfs rather than a host mount, so writes are bounded, nothing from
        # the host is reachable, and no files are left behind to clean up.
        "--tmpfs",
        f"/work:size={DOCKER_TMPFS_SIZE},exec",
        "-w",
        "/work",
        DOCKER_IMAGE,
        # Merging the streams inside the container keeps their order stable.
        # The client writes them separately, so ordering is otherwise undefined.
        "sh",
        "-c",
        'exec python -I -u -c "$0" 2>&1',
    ]


PROXY_VARIABLES = (
    "HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "NO_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "ftp_proxy", "no_proxy", "all_proxy",
)


def _blank_proxy_arguments() -> list[str]:
    arguments: list[str] = []
    for name in PROXY_VARIABLES:
        arguments.extend(["--env", f"{name}="])
    return arguments


def remove_container(directory: str) -> str | None:
    """Remove a container the client left behind, reporting a failure to remove it.

    Killing the client does not stop the container, so a timed out run keeps
    consuming resources until this succeeds.
    """
    launcher = _availability().launcher
    if launcher is None:
        return None

    name = Path(directory).name
    last_detail = ""
    for _ in range(REMOVE_ATTEMPTS):
        try:
            result = subprocess.run(
                [launcher, "rm", "--force", name],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=DOCKER_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            last_detail = str(error)
            continue
        stderr = result.stderr.strip()
        # A container that is already gone is the outcome we wanted.
        if result.returncode == 0 or "No such container" in stderr:
            return None
        last_detail = stderr or f"exit code {result.returncode}"
    return f"could not remove container {name}: {last_detail}"


def describe() -> str:
    probe = _availability()
    if probe.fatal:
        # Refusing, not falling back, so the trace must not imply code ran.
        return f"Docker unusable: {probe.reason}; code execution refused"
    if probe.reason is not None:
        return f"Docker unavailable: {probe.reason}; using weaker POSIX resource limits"
    return (
        f"Docker ({DOCKER_IMAGE}): no host filesystem, no network, read-only root; "
        f"writes bounded to {DOCKER_TMPFS_SIZE}; memory {DOCKER_MEMORY}, CPUs {DOCKER_CPUS}, "
        f"processes {DOCKER_PIDS_LIMIT}"
    )
