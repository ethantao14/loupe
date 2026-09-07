import html
import ipaddress
import re
import socket
import time
from urllib.parse import urljoin, urlparse

import httpx
from anthropic.types import ToolParam

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

TOOLS: list[ToolParam] = [FETCH_URL_TOOL]


class ToolError(Exception):
    pass


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
        return self.host if self.port == default_port else f"{self.host}:{self.port}"

    @property
    def pinned_url(self) -> str:
        parsed = urlparse(self.url)
        literal = f"[{self.address}]" if ":" in self.address else self.address
        return parsed._replace(netloc=f"{literal}:{self.port}").geturl()


def _resolve_public_address(host: str, port: int) -> str:
    try:
        resolved = socket.getaddrinfo(host, port)
    except socket.gaierror as error:
        raise ToolError(f"Could not resolve host: {host}") from error

    addresses = [str(entry[4][0]) for entry in resolved]
    for candidate in addresses:
        address = ipaddress.ip_address(candidate)
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        ):
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
    return httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False)


def _read_capped(response: httpx.Response, deadline: float) -> str:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        if time.monotonic() > deadline:
            raise ToolError("Took too long to download that page.")
        chunks.append(chunk)
        total += len(chunk)
        if total >= MAX_RESPONSE_BYTES:
            break
    return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")


def _extract_text(document: str) -> str:
    without_code = re.sub(
        r"<(script|style)\b.*?</\1>", " ", document, flags=re.DOTALL | re.IGNORECASE
    )
    without_tags = re.sub(r"<[^>]+>", " ", without_code)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def fetch_url(url: str) -> str:
    deadline = time.monotonic() + TOTAL_DEADLINE_SECONDS

    try:
        with _make_client() as client:
            for _ in range(MAX_REDIRECTS + 1):
                # Every hop is re-resolved and re-vetted, and the connection is
                # pinned to the address we checked, so neither a redirect nor a
                # second DNS answer can reach a private host.
                target = _build_target(url)
                request = client.build_request(
                    "GET",
                    target.pinned_url,
                    headers={"Host": target.host_header},
                    extensions={"sni_hostname": target.host},
                )
                response = client.send(request, stream=True)
                try:
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


def run_tool(name: str, tool_input: dict) -> str:
    # Failures come back as text so the model can react to them and retry,
    # rather than breaking the whole turn.
    try:
        if name == "fetch_url":
            return fetch_url(tool_input["url"])
        raise ToolError(f"Unknown tool: {name}")
    except ToolError as error:
        return f"Error: {error}"
