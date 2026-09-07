import pytest

from app import tools


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
    assert "Only http and https" in tools.run_tool("fetch_url", {"url": "file:///etc/passwd"})


def test_rejects_loopback_address():
    result = tools.run_tool("fetch_url", {"url": "http://localhost:8000/api/messages"})

    assert "Refusing to fetch a private address" in result


def test_rejects_unknown_tool():
    assert "Unknown tool" in tools.run_tool("rm_rf", {})


def test_fetch_returns_text(monkeypatch):
    class FakeResponse:
        text = "<html><body><p>Loupe docs</p></body></html>"

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(tools, "_reject_private_address", lambda host: None)
    monkeypatch.setattr(tools.httpx, "get", lambda *args, **kwargs: FakeResponse())

    assert tools.run_tool("fetch_url", {"url": "https://example.com"}) == "Loupe docs"


def test_truncates_long_pages(monkeypatch):
    class FakeResponse:
        text = "<p>" + ("word " * 5000) + "</p>"

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(tools, "_reject_private_address", lambda host: None)
    monkeypatch.setattr(tools.httpx, "get", lambda *args, **kwargs: FakeResponse())

    assert len(tools.fetch_url("https://example.com")) == tools.MAX_CONTENT_CHARS


def test_raises_on_unresolvable_host():
    with pytest.raises(tools.ToolError, match="Could not resolve host"):
        tools._reject_private_address("not-a-real-host.invalid")
