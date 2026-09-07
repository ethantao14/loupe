import httpx
import pytest

from app import tools


def use_fake_network(monkeypatch, handler, address="93.184.216.34"):
    """Resolve every host to one public address and serve responses from handler."""
    monkeypatch.setattr(tools, "_resolve_public_address", lambda host, port: address)
    monkeypatch.setattr(
        tools,
        "_make_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(handler), follow_redirects=False
        ),
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


def test_rejects_non_http_scheme():
    result = tools.run_tool("fetch_url", {"url": "file:///etc/passwd"})

    assert "Only http and https" in result


def test_rejects_malformed_url():
    assert "Not a valid URL" in tools.run_tool("fetch_url", {"url": "http://[bad"})
    assert "Not a valid URL" in tools.run_tool("fetch_url", {"url": "http://host:abc"})


def test_rejects_unknown_tool():
    assert "Unknown tool" in tools.run_tool("rm_rf", {})


def test_rejects_private_address(monkeypatch):
    monkeypatch.setattr(
        tools.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 80))]
    )

    result = tools.run_tool("fetch_url", {"url": "http://sneaky.example"})

    assert "Refusing to fetch a private address" in result


def test_rejects_when_any_resolved_address_is_private(monkeypatch):
    monkeypatch.setattr(
        tools.socket,
        "getaddrinfo",
        lambda *a, **k: [
            (2, 1, 6, "", ("93.184.216.34", 80)),
            (2, 1, 6, "", ("169.254.169.254", 80)),
        ],
    )

    result = tools.run_tool("fetch_url", {"url": "http://sneaky.example"})

    assert "Refusing to fetch a private address" in result


def test_fetch_returns_text(monkeypatch):
    use_fake_network(
        monkeypatch,
        lambda request: httpx.Response(200, text="<p>Loupe docs</p>"),
    )

    assert tools.run_tool("fetch_url", {"url": "https://example.com"}) == "Loupe docs"


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


def test_redirect_to_private_address_is_refused(monkeypatch):
    def handler(request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1:8000/admin"})

    monkeypatch.setattr(
        tools,
        "_make_client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(handler), follow_redirects=False
        ),
    )
    real_resolve = tools._resolve_public_address

    def resolve(host, port):
        if host == "127.0.0.1":
            return real_resolve(host, port)
        return "93.184.216.34"

    monkeypatch.setattr(tools, "_resolve_public_address", resolve)

    result = tools.run_tool("fetch_url", {"url": "https://example.com/start"})

    assert "Refusing to fetch a private address" in result


def test_gives_up_after_too_many_redirects(monkeypatch):
    use_fake_network(
        monkeypatch,
        lambda request: httpx.Response(
            302, headers={"location": "https://example.com/next"}
        ),
    )

    assert "Too many redirects" in tools.run_tool(
        "fetch_url", {"url": "https://example.com/start"}
    )


def test_reports_http_errors(monkeypatch):
    use_fake_network(monkeypatch, lambda request: httpx.Response(404))

    assert "Could not fetch" in tools.run_tool("fetch_url", {"url": "https://example.com"})


def test_caps_response_size(monkeypatch):
    oversized = "<p>" + ("word " * 1_000_000) + "</p>"
    use_fake_network(monkeypatch, lambda request: httpx.Response(200, text=oversized))

    assert len(tools.fetch_url("https://example.com")) == tools.MAX_CONTENT_CHARS


def test_raises_on_unresolvable_host():
    with pytest.raises(tools.ToolError, match="Could not resolve host"):
        tools._resolve_public_address("not-a-real-host.invalid", 80)
