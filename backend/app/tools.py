import html
import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx
from anthropic.types import ToolParam

MAX_CONTENT_CHARS = 4000
REQUEST_TIMEOUT_SECONDS = 10

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


def _reject_private_address(host: str) -> None:
    # The server fetches whatever the model asks for, so block anything that
    # points back at our own network or a cloud metadata endpoint.
    try:
        resolved = socket.getaddrinfo(host, None)
    except socket.gaierror as error:
        raise ToolError(f"Could not resolve host: {host}") from error

    for entry in resolved:
        address = ipaddress.ip_address(entry[4][0])
        if address.is_private or address.is_loopback or address.is_link_local:
            raise ToolError(f"Refusing to fetch a private address: {host}")


def _extract_text(document: str) -> str:
    without_code = re.sub(
        r"<(script|style)\b.*?</\1>", " ", document, flags=re.DOTALL | re.IGNORECASE
    )
    without_tags = re.sub(r"<[^>]+>", " ", without_code)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def fetch_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ToolError("Only http and https URLs are supported.")
    if not parsed.hostname:
        raise ToolError(f"Not a valid URL: {url}")

    _reject_private_address(parsed.hostname)

    try:
        response = httpx.get(
            url, timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True
        )
        response.raise_for_status()
    except httpx.HTTPError as error:
        raise ToolError(f"Could not fetch {url}: {error}") from error

    return _extract_text(response.text)[:MAX_CONTENT_CHARS]


def run_tool(name: str, tool_input: dict) -> str:
    # Failures come back as text so the model can react to them and retry,
    # rather than breaking the whole turn.
    try:
        if name == "fetch_url":
            return fetch_url(tool_input["url"])
        raise ToolError(f"Unknown tool: {name}")
    except ToolError as error:
        return f"Error: {error}"
