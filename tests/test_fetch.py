import socket
from unittest.mock import AsyncMock

import pytest

from app.errors import AppError
from app.extraction.fetch import PublicResolver, check_address, validate_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://user:pass@example.com",
        "http://127.0.0.1",
        "http://127.1",
        "http://2130706433",
        "http://0x7f000001",
        "http://[::1]",
        "http://[::ffff:127.0.0.1]",
        "http://169.254.169.254/latest",
        "http://10.1.2.3",
        "http://192.168.1.1",
        "http://100.100.100.200",
        "http://224.0.0.1",
        "http://[ff02::1]",
        "http://[64:ff9b::a00:1]",
        "http://example.com:8000",
        "http://example.com\\@localhost",
        "http://example.com/\nfoo",
        "http://localhost",
        "http://thing.local",
    ],
)
def test_unsafe_urls(url):
    with pytest.raises(AppError):
        validate_url(url)


def test_public_url():
    assert (
        str(validate_url("https://example.org/story?q=1#title")) == "https://example.org/story?q=1"
    )
    assert str(validate_url("https://8.8.8.8/")) == "https://8.8.8.8/"


@pytest.mark.parametrize(
    "address", ["0.0.0.0", "192.0.2.1", "198.18.0.1", "fc00::1", "2002:7f00:1::"]
)
def test_special_addresses(address):
    with pytest.raises(AppError):
        check_address(address)


async def test_resolver_checks_all_answers_and_rebinding():
    upstream = AsyncMock()
    public = dict(
        hostname="news.example",
        host="93.184.216.34",
        port=443,
        family=socket.AF_INET,
        proto=0,
        flags=0,
    )
    private = dict(public, host="127.0.0.1")
    upstream.resolve.side_effect = [[public], [public, private]]
    resolver = PublicResolver(upstream)
    assert await resolver.resolve("news.example", 443) == [public]
    with pytest.raises(AppError):
        await resolver.resolve("news.example", 443)
    assert upstream.resolve.await_count == 2


class FakeResponse:
    def __init__(self, status=200, headers=None, chunks=None, mime="text/html", length=None):
        self.status, self.headers, self.content_type = status, headers or {}, mime
        self.content_length = length
        self.chunks = chunks or [b"<html>Article</html>"]
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            yield chunk


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def get(self, url, *, allow_redirects):
        assert allow_redirects is False
        self.urls.append(str(url))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def mock_session(monkeypatch, responses):
    from app.extraction import fetch

    session = FakeSession(responses)

    def factory(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["auto_decompress"] is False
        return session

    monkeypatch.setattr(fetch.aiohttp, "ClientSession", factory)
    return session


async def test_redirect_to_private_host_never_makes_second_request(monkeypatch):
    from app.extraction.fetch import PublicFetcher

    session = mock_session(
        monkeypatch, [FakeResponse(302, {"Location": "http://169.254.169.254/"})]
    )
    with pytest.raises(AppError) as error:
        await PublicFetcher().fetch("https://example.org")
    assert error.value.code == "unsafe_url"
    assert len(session.urls) == 1


async def test_relative_redirect_and_redirect_limit(monkeypatch):
    from app.extraction.fetch import PublicFetcher

    session = mock_session(monkeypatch, [FakeResponse(302, {"Location": "/story"}), FakeResponse()])
    result = await PublicFetcher().fetch("https://example.org")
    assert result.url == "https://example.org/story"
    assert result.content == b"<html>Article</html>"
    assert session.urls[-1] == result.url
    mock_session(monkeypatch, [FakeResponse(302, {"Location": "/again"})] * 3)
    with pytest.raises(AppError) as error:
        await PublicFetcher(max_redirects=2).fetch("https://example.org")
    assert error.value.code == "redirect_limit"


@pytest.mark.parametrize(
    "response,code",
    [
        (FakeResponse(chunks=[b"12345", b"67890"]), "page_too_large"),
        (FakeResponse(length=100), "page_too_large"),
        (FakeResponse(headers={"Content-Encoding": "gzip"}), "compressed_page"),
        (FakeResponse(mime="application/pdf"), "not_html"),
        (FakeResponse(status=403), "fetch_failed"),
        (TimeoutError(), "fetch_timeout"),
    ],
)
async def test_response_limits_and_errors(monkeypatch, response, code):
    from app.extraction.fetch import PublicFetcher

    mock_session(monkeypatch, [response])
    with pytest.raises(AppError) as error:
        await PublicFetcher(max_bytes=8).fetch("https://example.org")
    assert error.value.code == code
