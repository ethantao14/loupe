import ipaddress
import re
import socket
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx
from anthropic.types import ToolParam

from app import config
from app.memory import MemoryStore
from app.sandbox import run_python

MAX_CONTENT_CHARS = 4000
MAX_RESPONSE_BYTES = 2_000_000
MAX_REDIRECTS = 3
REQUEST_TIMEOUT_SECONDS = 10
TOTAL_DEADLINE_SECONDS = 20

FETCH_URL_TOOL: ToolParam = {
    "name": "fetch_url",
    "description": (
        "Fetch a web page and return its visible text. Use this whenever the user "
        "asks about the contents of a specific URL."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Full URL including the http or https scheme.",
            }
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    "strict": True,
}

RUN_PYTHON_TOOL: ToolParam = {
    "name": "run_python",
    "description": (
        "Run Python code for calculations or data processing and return stdout and stderr. "
        "Execution has resource and time limits and uses a disposable working directory."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"code": {"type": "string", "description": "Python source code to execute."}},
        "required": ["code"],
        "additionalProperties": False,
    },
    "strict": True,
}

REMEMBER_TOOL: ToolParam = {
    "name": "remember",
    "description": (
        "Remember a durable fact about the user or the task for future conversations. "
        "Use this when learning lasting preferences, context, or requirements, "
        "not for transient chatter."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"fact": {"type": "string", "description": "The durable fact to remember."}},
        "required": ["fact"],
        "additionalProperties": False,
    },
    "strict": True,
}


def available_tools() -> list[ToolParam]:
    """Code execution is offered only when it has been deliberately enabled."""
    if config.ENABLE_CODE_EXECUTION:
        return [FETCH_URL_TOOL, RUN_PYTHON_TOOL, REMEMBER_TOOL]
    return [FETCH_URL_TOOL, REMEMBER_TOOL]


class ToolError(Exception):
    pass


@dataclass(frozen=True)
class ToolOutcome:
    """What a tool produced, and whether it failed. Failures come back as an
    outcome rather than an exception so the model can react and retry."""

    output: str
    failed: bool


class Target:
    """A URL that has been parsed and resolved to one vetted public address."""

    def __init__(self, url: str, host: str, port: int, address: str) -> None:
        self.url = url
        self.host = host
        self.port = port
        self.address = address

    @property
    def host_header(self) -> str:
        default_port = 443 if self.url.startswith("https") else 80
        host = self.ascii_host
        if ":" in host:
            host = f"[{host}]"
        return host if self.port == default_port else f"{host}:{self.port}"

    @property
    def ascii_host(self) -> str:
        # Headers and SNI must be ASCII, so an internationalized name is
        # converted rather than raising deep inside the HTTP client.
        if self.host.isascii():
            return self.host
        try:
            return self.host.encode("idna").decode("ascii")
        except UnicodeError as error:
            raise ToolError(f"Not a valid hostname: {self.host}") from error

    @property
    def pinned_url(self) -> str:
        parsed = urlparse(self.url)
        literal = f"[{self.address}]" if ":" in self.address else self.address
        return parsed._replace(netloc=f"{literal}:{self.port}").geturl()


def _resolve_public_address(host: str, port: int) -> str:
    try:
        resolved = socket.getaddrinfo(host, port)
    except (socket.gaierror, UnicodeError) as error:
        raise ToolError(f"Could not resolve host: {host}") from error

    addresses = [str(entry[4][0]) for entry in resolved]
    for candidate in addresses:
        address = ipaddress.ip_address(candidate)
        # is_global covers loopback, private, link-local, reserved and shared
        # address space in one check, so carrier-grade NAT ranges cannot slip past.
        if not address.is_global or address.is_multicast:
            raise ToolError(f"Refusing to fetch a private address: {host}")
    return addresses[0]


def _build_target(url: str) -> Target:
    try:
        parsed = urlparse(url)
    except ValueError as error:
        raise ToolError(f"Not a valid URL: {url}") from error

    if parsed.scheme not in ("http", "https"):
        raise ToolError("Only http and https URLs are supported.")
    try:
        host, port = parsed.hostname, parsed.port
    except ValueError as error:
        raise ToolError(f"Not a valid URL: {url}") from error
    if not host:
        raise ToolError(f"Not a valid URL: {url}")

    port = port or (443 if parsed.scheme == "https" else 80)
    return Target(url, host, port, _resolve_public_address(host, port))


def _make_client() -> httpx.Client:
    timeout = httpx.Timeout(
        connect=REQUEST_TIMEOUT_SECONDS,
        read=REQUEST_TIMEOUT_SECONDS,
        write=REQUEST_TIMEOUT_SECONDS,
        pool=REQUEST_TIMEOUT_SECONDS,
    )
    return httpx.Client(timeout=timeout, follow_redirects=False)


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise ToolError("Took too long to fetch that page.")


def _read_capped(response: httpx.Response, deadline: float) -> str:
    chunks: list[bytes] = []
    remaining = MAX_RESPONSE_BYTES
    for chunk in response.iter_bytes():
        _check_deadline(deadline)
        # Chunks arrive decompressed, so one chunk can exceed the whole budget.
        chunks.append(chunk[:remaining])
        remaining -= min(len(chunk), remaining)
        if remaining <= 0:
            break
    return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")


class _TextExtractor(HTMLParser):
    """Collects visible text. A parser rather than a regex, because regex tag
    stripping degrades badly on hostile markup."""

    SKIPPED_TAGS = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self.SKIPPED_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def _extract_text(document: str) -> str:
    parser = _TextExtractor()
    parser.feed(document)
    parser.close()
    # Joined with a space so text from separate elements does not run together.
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def fetch_url(url: str) -> str:
    deadline = time.monotonic() + TOTAL_DEADLINE_SECONDS

    try:
        with _make_client() as client:
            for _ in range(MAX_REDIRECTS + 1):
                # Every hop is re-resolved and re-vetted, and the connection is
                # pinned to the address we checked, so neither a redirect nor a
                # second DNS answer can reach a private host.
                _check_deadline(deadline)
                target = _build_target(url)
                request = client.build_request(
                    "GET",
                    target.pinned_url,
                    # Identity encoding, so a small compressed body cannot
                    # expand past the byte budget before we can trim it.
                    headers={
                        "Host": target.host_header,
                        "Accept-Encoding": "identity",
                    },
                    extensions={"sni_hostname": target.ascii_host},
                )
                response = client.send(request, stream=True)
                try:
                    _check_deadline(deadline)
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ToolError(f"Redirect without a location from {url}")
                        url = urljoin(url, location)
                        continue
                    response.raise_for_status()
                    document = _read_capped(response, deadline)
                finally:
                    response.close()
                return _extract_text(document)[:MAX_CONTENT_CHARS]
    except (httpx.HTTPError, httpx.InvalidURL) as error:
        raise ToolError(f"Could not fetch {url}: {error}") from error

    raise ToolError(f"Too many redirects starting from {url}")


def run_tool(name: str, tool_input: dict, memory_store: MemoryStore) -> ToolOutcome:
    try:
        if name == "remember":
            fact = tool_input.get("fact")
            if not isinstance(fact, str):
                raise ToolError("fact must be a string.")
            if not fact.strip():
                raise ToolError("fact must not be empty.")
            try:
                memory_store.remember(fact)
            except Exception as error:
                raise ToolError("Could not save memory. Please try again.") from error
            return ToolOutcome(output="Remembered: " + fact, failed=False)
        if name == "fetch_url":
            url = tool_input.get("url")
            if not isinstance(url, str):
                raise ToolError("url must be a string.")
            return ToolOutcome(output=fetch_url(url), failed=False)
        if name == "run_python":
            if not config.ENABLE_CODE_EXECUTION:
                raise ToolError("The run_python tool is disabled.")
            code = tool_input.get("code")
            if not isinstance(code, str):
                raise ToolError("code must be a string.")
            return ToolOutcome(output=run_python(code), failed=False)
        raise ToolError(f"Unknown tool: {name}")
    except ToolError as error:
        return ToolOutcome(output=f"Error: {error}", failed=True)
