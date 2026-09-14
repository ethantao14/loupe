import subprocess
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock

import pytest

from app import confine, sandbox


@pytest.fixture
def confined_host() -> None:
    reason = confine.unavailable_reason()
    if reason is not None:
        pytest.skip(reason)


def test_confined_python_starts(confined_host: None) -> None:
    assert sandbox.run_python("print(2 + 2)").output == "4\n"


@pytest.mark.parametrize("via_symlink", [False, True])
def test_outside_file_cannot_be_read(
    confined_host: None,
    tmp_path: Path,
    via_symlink: bool,
) -> None:
    secret = "outside-file-content-must-never-be-returned"
    outside = tmp_path / "secret.txt"
    outside.write_text(secret)
    assert outside.read_text() == secret
    code = (
        "import errno, os\n"
        f"outside = {str(outside)!r}\n"
        "assert os.path.commonpath([os.getcwd(), outside]) != os.getcwd()\n"
    )
    if via_symlink:
        code += "os.symlink(outside, 'link'); outside = 'link'\n"
    code += (
        "try:\n"
        "    print('LEAK:', open(outside).read())\n"
        "except OSError as error:\n"
        "    assert error.errno in (errno.EACCES, errno.EPERM, errno.ENOENT)\n"
        "    print('outside read blocked')\n"
    )

    result = sandbox.run_python(code)

    assert secret not in result.output
    assert result.output == "outside read blocked\n"


def test_tcp_connection_fails(confined_host: None) -> None:
    result = sandbox.run_python(
        "import errno, socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 80), timeout=0.5).close()\n"
        "except OSError as error:\n"
        "    assert error.errno in (errno.EPERM, errno.EACCES, errno.ENETUNREACH, "
        "errno.EHOSTUNREACH)\n"
        "    print('network blocked')\n"
        "else:\n"
        "    print('NETWORK ESCAPE')\n"
    )
    assert result.output == "network blocked\n"


def test_working_directory_is_readable_and_writable(confined_host: None) -> None:
    result = sandbox.run_python(
        "from pathlib import Path\n"
        "directory = Path.cwd() / 'nested'\n"
        "directory.mkdir()\n"
        "path = directory / 'data.txt'\n"
        "path.write_text('local content')\n"
        "print(path.read_text())\n"
        "path.unlink(); directory.rmdir()\n"
    )
    assert result.output == "local content\n"


@pytest.fixture
def fresh_probe() -> Iterator[None]:
    confine._availability.cache_clear()
    yield
    confine._availability.cache_clear()


def test_missing_docker_is_reported_and_cached(
    monkeypatch: pytest.MonkeyPatch, fresh_probe: None,
) -> None:
    which = Mock(return_value=None)
    probe = Mock()
    monkeypatch.setattr(confine.shutil, "which", which)
    monkeypatch.setattr(confine.subprocess, "run", probe)

    assert confine.unavailable_reason() is not None
    assert confine.describe() == (
        "Docker unavailable: Docker binary not found on PATH; code execution is not offered"
    )
    assert confine.unavailable_reason() is not None
    which.assert_called_once_with("docker")
    probe.assert_not_called()


@pytest.mark.parametrize("failure", [
    subprocess.CompletedProcess([], 1, stdout="", stderr="permission denied"),
    subprocess.TimeoutExpired("docker info", confine.DOCKER_TIMEOUT_SECONDS),
    OSError("cannot connect"),
])
def test_unreachable_daemon_is_reported_and_cached(
    monkeypatch: pytest.MonkeyPatch, fresh_probe: None,
    failure: subprocess.CompletedProcess[str] | Exception,
) -> None:
    monkeypatch.setattr(confine.shutil, "which", Mock(return_value="/usr/bin/docker"))
    probe = Mock()
    if isinstance(failure, Exception):
        probe.side_effect = failure
    else:
        probe.return_value = failure
    monkeypatch.setattr(confine.subprocess, "run", probe)

    assert confine.unavailable_reason() is not None
    assert "Docker daemon unavailable" in confine.describe()
    assert confine.unavailable_reason() is not None
    probe.assert_called_once()
    assert probe.call_args.kwargs["timeout"] == confine.DOCKER_TIMEOUT_SECONDS


def test_docker_prefix_and_successful_probe_are_cached(
    monkeypatch: pytest.MonkeyPatch, fresh_probe: None, tmp_path: Path,
) -> None:
    which = Mock(return_value="/usr/bin/docker")
    probe = Mock(return_value=subprocess.CompletedProcess([], 0, stdout="28.0", stderr=""))
    monkeypatch.setattr(confine.shutil, "which", which)
    monkeypatch.setattr(confine.subprocess, "run", probe)
    directory = tmp_path / "work with spaces"

    prefix = confine.command_prefix(str(directory))

    # Asserted as properties rather than an exact argument list, which broke on
    # every correct change to the flags without ever catching a real defect.
    assert prefix[:4] == ["/usr/bin/docker", "run", "--rm", "--init"]
    assert prefix[-3:] == ["sh", "-c", 'exec python -I -u -c "$0" 2>&1']
    assert confine.DOCKER_IMAGE in prefix
    for flag, value in [
        ("--network", "none"),
        ("--log-driver", "none"),
        ("--memory", confine.DOCKER_MEMORY),
        ("--memory-swap", confine.DOCKER_MEMORY),
        ("--cpus", confine.DOCKER_CPUS),
        ("--pids-limit", str(confine.DOCKER_PIDS_LIMIT)),
        ("--name", directory.name),
        ("-w", "/work"),
    ]:
        assert prefix[prefix.index(flag) + 1] == value
    assert "--read-only" in prefix
    assert f"/work:size={confine.DOCKER_TMPFS_SIZE},exec" in prefix
    assert f"/tmp:size={confine.DOCKER_TMPFS_SIZE}" in prefix
    # No host path is mounted into the container.
    assert "-v" not in prefix
    for name in confine.PROXY_VARIABLES:
        assert f"{name}=" in prefix
    assert confine.unavailable_reason() is None
    assert "no network" in confine.describe()
    which.assert_called_once_with("docker")
    # The daemon probe and the image check both run once, then stay cached.
    assert probe.call_count == 2
    assert probe.call_args_list[0].args[0] == [
        "/usr/bin/docker", "info", "--format", "{{.ServerVersion}}"
    ]
    assert probe.call_args_list[1].args[0] == [
        "/usr/bin/docker", "image", "inspect", confine.DOCKER_IMAGE
    ]


def test_command_prefix_requires_docker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        confine, "_availability", lambda: confine.Probe(None, "Docker unavailable")
    )

    with pytest.raises(RuntimeError, match="^Docker is unavailable$"):
        confine.command_prefix(str(tmp_path))


@pytest.mark.parametrize("failure", [
    subprocess.CompletedProcess([], 1, stdout="", stderr="pull refused"),
    subprocess.TimeoutExpired("docker pull", confine.DOCKER_PULL_TIMEOUT_SECONDS),
    OSError("cannot connect"),
])
def test_unpreparable_image_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, fresh_probe: None,
    failure: subprocess.CompletedProcess[str] | Exception,
) -> None:
    monkeypatch.setattr(confine.shutil, "which", Mock(return_value="/usr/bin/docker"))
    probe = Mock(side_effect=[
        subprocess.CompletedProcess([], 0, stdout="28.0", stderr=""),
        subprocess.CompletedProcess([], 1, stdout="", stderr="image missing"),
        failure,
    ])
    monkeypatch.setattr(confine.subprocess, "run", probe)

    reason = confine.unavailable_reason()

    assert reason is not None
    assert reason.startswith(f"Could not prepare {confine.DOCKER_IMAGE}:")
    assert confine._availability() == confine.Probe(None, reason)
    assert confine.describe() == f"Docker unavailable: {reason}; code execution is not offered"
    assert probe.call_count == 3
    assert probe.call_args.args[0] == ["/usr/bin/docker", "pull", "--quiet", confine.DOCKER_IMAGE]
    assert probe.call_args.kwargs["timeout"] == confine.DOCKER_PULL_TIMEOUT_SECONDS


def test_remove_container_succeeds_quietly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        confine, "_availability", lambda: confine.Probe("/usr/bin/docker", None)
    )
    remove = Mock(return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""))
    monkeypatch.setattr(confine.subprocess, "run", remove)

    assert confine.remove_container(str(tmp_path)) is None
    assert remove.call_count == 1
    assert remove.call_args.args[0] == ["/usr/bin/docker", "rm", "--force", tmp_path.name]


def test_already_removed_container_is_not_a_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        confine, "_availability", lambda: confine.Probe("/usr/bin/docker", None)
    )
    gone = subprocess.CompletedProcess([], 1, stdout="", stderr="Error: No such container: x")
    monkeypatch.setattr(confine.subprocess, "run", Mock(return_value=gone))

    assert confine.remove_container(str(tmp_path)) is None


def test_failed_removal_is_retried_then_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A container that outlives its client keeps consuming resources, so a
    failure to remove it must be reported rather than swallowed."""
    monkeypatch.setattr(
        confine, "_availability", lambda: confine.Probe("/usr/bin/docker", None)
    )
    refused = subprocess.CompletedProcess([], 1, stdout="", stderr="daemon refused")
    remove = Mock(return_value=refused)
    monkeypatch.setattr(confine.subprocess, "run", remove)

    failure = confine.remove_container(str(tmp_path))

    assert failure is not None
    assert "daemon refused" in failure
    assert remove.call_count == confine.REMOVE_ATTEMPTS


def test_every_proxy_variant_is_blanked() -> None:
    """Docker injects these from client config, and they can carry credentials."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "NO_PROXY", "ALL_PROXY"):
        assert name in confine.PROXY_VARIABLES
        assert name.lower() in confine.PROXY_VARIABLES
