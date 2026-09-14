"""Required Docker confinement for Python execution.

No host filesystem is mounted. The container has no network, a read-only root
filesystem, and memory, CPU and process caps.
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
# A cold daemon's first call routinely takes several seconds, and a timeout is
# cached, so too tight a bound silently withholds the tool for the whole process.
DOCKER_TIMEOUT_SECONDS = 10
DOCKER_PULL_TIMEOUT_SECONDS = 300
REMOVE_ATTEMPTS = 3  # A first pull is slow, and happens once.


class Probe(NamedTuple):
    """Whether confinement is usable, with a reason when it is unavailable."""

    launcher: str | None
    reason: str | None


@cache
def _daemon() -> Probe:
    launcher = shutil.which("docker")
    if launcher is None:
        return Probe(None, "Docker binary not found on PATH")
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
        return Probe(None, f"Docker daemon unavailable: {error}")
    if result.returncode:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        return Probe(None, f"Docker daemon unavailable: {detail}")
    return Probe(launcher, None)


@cache
def _availability() -> Probe:
    """The daemon check plus the image, which a first pull can make slow."""
    probe = _daemon()
    if probe.launcher is None:
        return probe
    missing = _ensure_image(probe.launcher)
    if missing:
        return Probe(None, missing)
    return probe


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


def daemon_unavailable_reason() -> str | None:
    """Whether Docker itself is usable, without preparing the image.

    Tool discovery runs on every turn, so it must not wait on an image pull.
    """
    return _daemon().reason


def unavailable_reason() -> str | None:
    """Whether code can actually run, so also that the image is prepared."""
    return _availability().reason


def command_prefix(directory: str) -> list[str]:
    """Return Docker and container Python arguments, requiring confinement."""
    launcher = _availability().launcher
    if launcher is None:
        raise RuntimeError("Docker is unavailable")
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
        # Without an explicit swap total Docker grants an equal amount of swap,
        # so the cap would really be twice DOCKER_MEMORY.
        "--memory-swap",
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
    if probe.reason is not None:
        return f"Docker unavailable: {probe.reason}; code execution is not offered"
    return (
        f"Docker ({DOCKER_IMAGE}): no host filesystem, no network, read-only root; "
        f"writes bounded to {DOCKER_TMPFS_SIZE}; memory {DOCKER_MEMORY}, CPUs {DOCKER_CPUS}, "
        f"processes {DOCKER_PIDS_LIMIT}"
    )
