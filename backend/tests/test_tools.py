import time
from unittest.mock import Mock

import httpx
import pytest

from app import confine, tools


def use_fake_network(monkeypatch, handler, address="93.184.216.34"):
    """Resolve every host to one public address and serve responses from handler."""
    monkeypatch.setattr(tools, "_resolve_public_address", lambda host, port: address)
    monkeypatch.setattr(
        tools,
        "_make_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
    )


def test_extracts_visible_text_only():
    document = """
    <html><head><style>body { color: red; }</style>
    <script>console.log("hidden");</script></head>
    <body><h1>Title</h1><p>Hello &amp; welcome</p></body></html>
    """

    text = tools._extract_text(document)

    assert "Title" in text
    assert "Hello & welcome" in text
    assert "console.log" not in text
    assert "color: red" not in text


def test_rejects_non_http_scheme(memory_store):
    result = tools.run_tool("fetch_url", {"url": "file:///etc/passwd"}, memory_store)

    assert "Only http and https" in result.output


def test_rejects_malformed_url(memory_store):
    assert "Not a valid URL" in tools.run_tool(
        "fetch_url", {"url": "http://[bad"}, memory_store
    ).output
    assert "Not a valid URL" in tools.run_tool(
        "fetch_url", {"url": "http://host:abc"}, memory_store
    ).output


@pytest.mark.parametrize("tool_input", [{}, {"url": None}, {"url": 123}])
def test_rejects_missing_or_non_string_url(tool_input, memory_store):
    assert tools.run_tool("fetch_url", tool_input, memory_store) == tools.ToolOutcome(
        output="Error: url must be a string.", failed=True
    )


def test_rejects_unknown_tool(memory_store):
    assert "Unknown tool" in tools.run_tool("rm_rf", {}, memory_store).output


def test_rejects_private_address(monkeypatch, memory_store):
    monkeypatch.setattr(
        tools.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 80))]
    )

    result = tools.run_tool("fetch_url", {"url": "http://sneaky.example"}, memory_store)

    assert "Refusing to fetch a private address" in result.output


def test_rejects_when_any_resolved_address_is_private(monkeypatch, memory_store):
    monkeypatch.setattr(
        tools.socket,
        "getaddrinfo",
        lambda *a, **k: [
            (2, 1, 6, "", ("93.184.216.34", 80)),
            (2, 1, 6, "", ("169.254.169.254", 80)),
        ],
    )

    result = tools.run_tool("fetch_url", {"url": "http://sneaky.example"}, memory_store)

    assert "Refusing to fetch a private address" in result.output


def test_fetch_returns_text(monkeypatch, memory_store):
    use_fake_network(
        monkeypatch,
        lambda request: httpx.Response(200, text="<p>Loupe docs</p>"),
    )

    assert tools.run_tool("fetch_url", {"url": "https://example.com"}, memory_store) == (
        tools.ToolOutcome(output="Loupe docs", failed=False)
    )


@pytest.mark.parametrize(
    "url, output, failed",
    [
        ("file:///etc/passwd", "Error: Only http and https URLs are supported.", True),
        ("https://example.com", "Error: quoted page content", False),
    ],
)
def test_tool_outcome_reports_failure(
    monkeypatch: pytest.MonkeyPatch, memory_store: Mock, url: str, output: str, failed: bool
) -> None:
    use_fake_network(
        monkeypatch, lambda request: httpx.Response(200, text="<p>Error: quoted page content</p>")
    )

    outcome = tools.run_tool("fetch_url", {"url": url}, memory_store)

    assert outcome.output == output
    assert outcome.failed is failed


def test_sends_original_host_not_the_pinned_address(monkeypatch):
    seen = {}

    def handler(request):
        seen["host"] = request.headers["Host"]
        seen["url"] = str(request.url)
        return httpx.Response(200, text="<p>ok</p>")

    use_fake_network(monkeypatch, handler)
    tools.fetch_url("https://example.com/page")

    assert seen["host"] == "example.com"
    assert "93.184.216.34" in seen["url"]


def test_follows_redirect_to_a_public_host(monkeypatch):
    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "https://example.com/end"})
        return httpx.Response(200, text="<p>arrived</p>")

    use_fake_network(monkeypatch, handler)

    assert tools.fetch_url("https://example.com/start") == "arrived"


def test_redirect_to_private_address_is_refused(monkeypatch, memory_store):
    def handler(request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1:8000/admin"})

    monkeypatch.setattr(
        tools,
        "_make_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
    )
    real_resolve = tools._resolve_public_address

    def resolve(host, port):
        if host == "127.0.0.1":
            return real_resolve(host, port)
        return "93.184.216.34"

    monkeypatch.setattr(tools, "_resolve_public_address", resolve)

    result = tools.run_tool("fetch_url", {"url": "https://example.com/start"}, memory_store)

    assert "Refusing to fetch a private address" in result.output


def test_gives_up_after_too_many_redirects(monkeypatch, memory_store):
    use_fake_network(
        monkeypatch,
        lambda request: httpx.Response(302, headers={"location": "https://example.com/next"}),
    )

    assert "Too many redirects" in tools.run_tool(
        "fetch_url", {"url": "https://example.com/start"}, memory_store
    ).output


def test_reports_http_errors(monkeypatch, memory_store):
    use_fake_network(monkeypatch, lambda request: httpx.Response(404))

    assert "Could not fetch" in tools.run_tool(
        "fetch_url", {"url": "https://example.com"}, memory_store
    ).output


def test_caps_response_size(monkeypatch):
    oversized = "<p>" + ("word " * 1_000_000) + "</p>"
    use_fake_network(monkeypatch, lambda request: httpx.Response(200, text=oversized))

    assert len(tools.fetch_url("https://example.com")) == tools.MAX_CONTENT_CHARS


def test_raises_on_unresolvable_host():
    with pytest.raises(tools.ToolError, match="Could not resolve host"):
        tools._resolve_public_address("not-a-real-host.invalid", 80)


def test_rejects_shared_address_space(monkeypatch, memory_store):
    # 100.64.0.0/10 is neither private nor reserved, but it is not globally
    # routable and reaches internal services on some clouds.
    monkeypatch.setattr(
        tools.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("100.100.100.200", 80))]
    )

    result = tools.run_tool("fetch_url", {"url": "http://sneaky.example"}, memory_store)

    assert "Refusing to fetch a private address" in result.output


def test_extraction_is_linear_on_hostile_markup():
    # Unclosed tags used to force quadratic backtracking.
    hostile = "<" * 200_000

    start = time.monotonic()
    tools._extract_text(hostile)

    assert time.monotonic() - start < 2


def test_internationalized_host_is_converted_for_headers(monkeypatch):
    seen = {}

    def handler(request):
        seen["host"] = request.headers["Host"]
        return httpx.Response(200, text="<p>ok</p>")

    use_fake_network(monkeypatch, handler)
    tools.fetch_url("https://bücher.example/")

    assert seen["host"] == "xn--bcher-kva.example"


def test_oversized_single_chunk_is_truncated(monkeypatch):
    # One decompressed chunk larger than the whole budget.
    huge = b"<p>" + (b"x" * (tools.MAX_RESPONSE_BYTES * 2)) + b"</p>"
    use_fake_network(monkeypatch, lambda request: httpx.Response(200, content=huge))

    assert len(tools.fetch_url("https://example.com")) == tools.MAX_CONTENT_CHARS


def test_brackets_ipv6_literals_in_host_header(monkeypatch):
    seen = {}

    def handler(request):
        seen["host"] = request.headers["Host"]
        return httpx.Response(200, text="<p>ok</p>")

    use_fake_network(monkeypatch, handler, address="2606:4700:4700::1111")
    tools.fetch_url("http://[2606:4700:4700::1111]/")

    assert seen["host"] == "[2606:4700:4700::1111]"


def test_asks_for_identity_encoding(monkeypatch):
    seen = {}

    def handler(request):
        seen["encoding"] = request.headers["Accept-Encoding"]
        return httpx.Response(200, text="<p>ok</p>")

    use_fake_network(monkeypatch, handler)
    tools.fetch_url("https://example.com")

    assert seen["encoding"] == "identity"


def test_overlong_hostname_label_is_a_tool_error(memory_store):
    result = tools.run_tool("fetch_url", {"url": f"http://{'a' * 100}.example/"}, memory_store)

    assert "Could not resolve host" in result.output


def test_deadline_is_checked_before_requesting(monkeypatch, memory_store):
    use_fake_network(monkeypatch, lambda request: httpx.Response(200, text="<p>ok</p>"))
    monkeypatch.setattr(tools, "TOTAL_DEADLINE_SECONDS", -1)

    assert "Took too long" in tools.run_tool(
        "fetch_url", {"url": "https://example.com"}, memory_store
    ).output


def test_remember_dispatches(memory_store):
    fact = "The user prefers concise answers."

    assert tools.run_tool("remember", {"fact": fact}, memory_store) == tools.ToolOutcome(
        output=f"Remembered: {fact}", failed=False
    )
    memory_store.remember.assert_called_once_with(fact)


@pytest.mark.parametrize("tool_input", [{}, {"fact": None}, {"fact": 123}, {"fact": []}])
def test_remember_rejects_missing_or_non_string_fact(tool_input, memory_store):
    assert tools.run_tool("remember", tool_input, memory_store) == tools.ToolOutcome(
        output="Error: fact must be a string.", failed=True
    )
    memory_store.remember.assert_not_called()


@pytest.mark.parametrize("fact", ["", " \n\t"])
def test_remember_rejects_blank_fact(fact, memory_store):
    assert tools.run_tool("remember", {"fact": fact}, memory_store) == tools.ToolOutcome(
        output="Error: fact must not be empty.", failed=True
    )
    memory_store.remember.assert_not_called()


def test_remember_returns_helpful_storage_error(memory_store):
    memory_store.remember.side_effect = RuntimeError("Database unavailable")

    assert tools.run_tool("remember", {"fact": "A fact"}, memory_store) == tools.ToolOutcome(
        output="Error: Could not save memory. Please try again.", failed=True
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_remember_is_always_offered(monkeypatch, enabled):
    monkeypatch.setattr(confine, "unavailable_reason", lambda: None)
    monkeypatch.setattr(tools.config, "ENABLE_CODE_EXECUTION", enabled)

    assert tools.REMEMBER_TOOL in tools.available_tools()
    schema = tools.REMEMBER_TOOL["input_schema"]
    assert schema["required"] == ["fact"]
    assert schema["properties"]["fact"]["type"] == "string"


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("reason", [None, "Docker daemon unavailable"])
def test_python_requires_enabled_flag_and_docker(monkeypatch, enabled, reason):
    monkeypatch.setattr(tools.config, "ENABLE_CODE_EXECUTION", enabled)
    monkeypatch.setattr(confine, "unavailable_reason", lambda: reason)

    offered = tools.available_tools()

    assert (tools.RUN_PYTHON_TOOL in offered) is (enabled and reason is None)
    assert tools.FETCH_URL_TOOL in offered
    assert tools.REMEMBER_TOOL in offered
