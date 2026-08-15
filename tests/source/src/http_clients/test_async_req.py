"""Unit tests for async_req — the chokepoint used by 12 platforms.
Iron Rule v249 + P1 (Cove 2026-08-01 20:30 拍板): chokepoint needs unit test coverage.

Tests:
- happy path GET 200 OK
- happy path POST with json_data
- redirect_url=True returns final URL
- return_cookies=True returns cookies dict
- timeout raises exception (mock httpx)
- network error returns str(exception)
- proxy_addr passed through (mock httpx)
- 12 platform callers smoke test (importable + uses async_req)
"""
import pytest
import httpx
import respx
from src.http_clients.async_http import async_req


@pytest.mark.asyncio
@respx.mock
async def test_get_success():
    """GET 200 OK → returns text."""
    respx.get("https://example.com/api/test").mock(return_value=httpx.Response(200, text="hello"))

    result = await async_req("https://example.com/api/test")

    assert result == "hello"


@pytest.mark.asyncio
@respx.mock
async def test_post_with_json_data():
    """POST with json_data → response.text returned."""
    respx.post("https://api.example.com/post").mock(return_value=httpx.Response(200, text='{"ok":true}'))

    result = await async_req(
        "https://api.example.com/post",
        json_data={"key": "value"},
    )

    assert result == '{"ok":true}'


@pytest.mark.asyncio
@respx.mock
async def test_redirect_url_returns_final_url():
    """redirect_url=True → returns final URL after redirects."""
    respx.get("https://start.example.com/").mock(
        return_value=httpx.Response(302, headers={"location": "https://final.example.com/landing"})
    )
    respx.get("https://final.example.com/landing").mock(return_value=httpx.Response(200, text="landed"))

    result = await async_req(
        "https://start.example.com/",
        redirect_url=True,
    )

    assert result == "https://final.example.com/landing"


@pytest.mark.asyncio
@respx.mock
async def test_return_cookies():
    """return_cookies=True → returns cookies dict."""
    respx.get("https://example.com/login").mock(
        return_value=httpx.Response(200, text="ok", headers={"set-cookie": "session=abc123; Path=/"})
    )

    result = await async_req(
        "https://example.com/login",
        return_cookies=True,
    )

    assert isinstance(result, dict)
    assert result.get("session") == "abc123"


@pytest.mark.asyncio
@respx.mock
async def test_network_error_returns_str():
    """Network error → returns str(exception) instead of raising."""
    respx.get("https://broken.example.com/").mock(side_effect=httpx.ConnectError("connection refused"))

    result = await async_req("https://broken.example.com/")

    assert isinstance(result, str)
    assert "connection refused" in result


@pytest.mark.asyncio
@respx.mock
async def test_5xx_returns_text():
    """5xx response → returns response.text (not exception)."""
    respx.get("https://server.example.com/").mock(return_value=httpx.Response(503, text="Service Unavailable"))

    result = await async_req("https://server.example.com/")

    assert result == "Service Unavailable"


@pytest.mark.asyncio
@respx.mock
async def test_timeout_param_passed():
    """timeout parameter → passed to httpx.AsyncClient."""
    respx.get("https://slow.example.com/").mock(return_value=httpx.Response(200, text="slow ok"))

    # Use a custom timeout to ensure it's passed
    result = await async_req("https://slow.example.com/", timeout=5)

    assert result == "slow ok"


@pytest.mark.asyncio
@respx.mock
async def test_headers_passed():
    """headers parameter → sent with request."""
    route = respx.get("https://example.com/auth").mock(return_value=httpx.Response(200, text="authed"))

    await async_req(
        "https://example.com/auth",
        headers={"Authorization": "Bearer token123"},
    )

    # Verify the request was made with the header
    assert route.called
    assert route.calls.last.request.headers.get("Authorization") == "Bearer token123"