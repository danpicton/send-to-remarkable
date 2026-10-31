"""Public-web fetcher. Never use this client's policy for trusted rmfakecloud traffic."""

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass

import aiohttp
from aiohttp.abc import AbstractResolver
from yarl import URL

from app.errors import AppError

# Reject transition mechanisms that could encode an otherwise forbidden IPv4 host.
TRANSITION = tuple(
    ipaddress.ip_network(n)
    for n in (
        "64:ff9b::/96",
        "64:ff9b:1::/48",
        "2002::/16",
        "2001::/32",
    )
)


def check_address(value: str) -> None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise AppError("unsafe_url", "The hostname did not resolve to an IP address.") from exc
    if (
        not address.is_global
        or address.is_multicast
        or address.is_reserved
        or getattr(address, "ipv4_mapped", None)
        or any(address in network for network in TRANSITION)
    ):
        raise AppError("unsafe_url", "Only public internet addresses are allowed.")


def validate_url(value: str) -> URL:
    try:
        if len(value) > 4096 or re.search(r"[\x00-\x20\x7f\\]", value):
            raise ValueError
        url = URL(value)
        host = url.host
        if (
            url.scheme not in ("http", "https")
            or not host
            or url.user is not None
            or url.password is not None
            or url.port not in (80, 443)
        ):
            raise ValueError
        host = host.rstrip(".").lower()
        if host == "localhost" or host.endswith(
            (".localhost", ".local", ".internal", ".home", ".lan")
        ):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            # Reject legacy inet_aton numeric notations before DNS resolution.
            try:
                socket.inet_aton(host)
            except OSError:
                if "." not in host:
                    raise ValueError from None
            else:
                raise ValueError from None
        else:
            check_address(host)
        return url.with_fragment(None)
    except (ValueError, UnicodeError) as exc:
        raise AppError("unsafe_url", "Use a public HTTP or HTTPS URL on port 80 or 443.") from exc


class PublicResolver(AbstractResolver):
    def __init__(self, upstream=None):
        self.upstream = upstream or aiohttp.resolver.ThreadedResolver()

    async def resolve(self, host, port=0, family=socket.AF_INET):
        records = await self.upstream.resolve(host, port, family)
        if not records:
            raise AppError("fetch_failed", "The article hostname could not be resolved.", 422)
        for record in records:
            check_address(record["host"])
        # The connector dials these validated numeric addresses, without resolving again.
        return records

    async def close(self):
        await self.upstream.close()


@dataclass(frozen=True)
class FetchedPage:
    content: bytes
    url: str


class PublicFetcher:
    def __init__(self, max_bytes=4 * 1024 * 1024, timeout=20, max_redirects=5):
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.max_redirects = max_redirects

    async def fetch(self, value: str) -> FetchedPage:
        url = validate_url(value)
        resolver = PublicResolver()
        connector = aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False, force_close=True)
        try:
            async with asyncio.timeout(self.timeout):
                async with aiohttp.ClientSession(
                    connector=connector,
                    trust_env=False,
                    auto_decompress=False,
                    cookie_jar=aiohttp.DummyCookieJar(),
                    timeout=aiohttp.ClientTimeout(total=self.timeout, sock_connect=5, sock_read=8),
                    headers={
                        "User-Agent": "SendToRemarkable/0.1",
                        "Accept-Encoding": "identity",
                        "Accept": "text/html,application/xhtml+xml",
                    },
                ) as session:
                    for hop in range(self.max_redirects + 1):
                        async with session.get(url, allow_redirects=False) as response:
                            if response.status in (301, 302, 303, 307, 308):
                                location = response.headers.get("Location")
                                if not location or hop == self.max_redirects:
                                    raise AppError(
                                        "redirect_limit", "The page has too many redirects.", 422
                                    )
                                url = validate_url(str(url.join(URL(location))))
                                continue
                            if response.status != 200:
                                raise AppError(
                                    "fetch_failed",
                                    f"The website returned HTTP {response.status}.",
                                    422,
                                )
                            if response.content_type not in ("text/html", "application/xhtml+xml"):
                                raise AppError(
                                    "not_html", "The URL must point to an HTML article.", 422
                                )
                            if (
                                response.headers.get("Content-Encoding", "identity").lower()
                                != "identity"
                            ):
                                raise AppError(
                                    "compressed_page",
                                    "This site requires compressed responses, "
                                    "which are not supported yet.",
                                    422,
                                )
                            if response.content_length and response.content_length > self.max_bytes:
                                raise AppError(
                                    "page_too_large", "The webpage exceeds the download limit.", 413
                                )
                            body = bytearray()
                            async for chunk in response.content.iter_chunked(65536):
                                body.extend(chunk)
                                if len(body) > self.max_bytes:
                                    raise AppError(
                                        "page_too_large",
                                        "The webpage exceeds the download limit.",
                                        413,
                                    )
                            return FetchedPage(bytes(body), str(url))
        except TimeoutError as exc:
            raise AppError(
                "fetch_timeout", "The article website took too long to respond.", 504
            ) from exc
        except (aiohttp.ClientError, OSError, ValueError) as exc:
            raise AppError(
                "fetch_failed",
                "Could not fetch the article. Check the URL and website TLS certificate.",
                422,
            ) from exc
        finally:
            await connector.close()
            await resolver.close()
        raise AppError("fetch_failed", "Could not fetch the article.", 422)
