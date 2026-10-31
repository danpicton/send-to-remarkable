import asyncio
from urllib.parse import urlsplit

from starlette.responses import JSONResponse


class SecurityMiddleware:
    """Enforce security and bounded request bodies before FastAPI parses multipart/JSON."""

    def __init__(self, app, settings):
        self.app = app
        self.settings = settings
        self.authority = urlsplit(settings.app_base_url).netloc.lower()
        self.active = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode("latin-1") for k, v in scope["headers"]}
        path, method = scope["path"], scope["method"]

        async def secured_send(message):
            if message["type"] == "http.response.start":
                extra = [
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                    (
                        b"content-security-policy",
                        b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
                        b"connect-src 'self'; worker-src 'self'; manifest-src 'self'; "
                        b"object-src 'none'; base-uri 'none'; "
                        b"frame-ancestors 'none'; form-action 'self'",
                    ),
                ]
                message["headers"] = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in {key for key, _ in extra}
                ] + extra
            await send(message)

        async def reject(code, text, status):
            await JSONResponse({"error": {"code": code, "message": text}}, status_code=status)(
                scope, receive, secured_send
            )

        if path == "/api/health" and method == "GET":
            return await self.app(scope, receive, secured_send)
        if headers.get("host", "").lower() != self.authority:
            return await reject("invalid_host", "Unexpected host. Check APP_BASE_URL.", 400)
        if path.startswith("/api/"):
            if self.settings.auth_mode == "proxy" and not headers.get(
                self.settings.auth_header.lower()
            ):
                return await reject(
                    "authentication_required",
                    "Sign in through the configured authenticating proxy.",
                    401,
                )
            if headers.get("sec-fetch-site") in ("cross-site", "same-site"):
                return await reject("cross_site", "Cross-site API requests are not allowed.", 403)
            if method not in ("GET", "HEAD"):
                if (
                    headers.get("origin") != self.settings.app_base_url
                    or headers.get("x-requested-with") != "SendToRemarkable"
                ):
                    return await reject("cross_site", "A same-origin request is required.", 403)
                if self.active >= self.settings.max_conversions + 2:
                    return await reject(
                        "busy", "The server is busy. Please try again shortly.", 429
                    )
                self.active += 1
                try:
                    limit = (
                        self.settings.max_document_bytes + 65536 if path == "/api/send" else 8192
                    )
                    body = bytearray()
                    try:
                        async with asyncio.timeout(15):
                            while True:
                                message = await receive()
                                if message["type"] == "http.disconnect":
                                    return
                                body.extend(message.get("body", b""))
                                if len(body) > limit:
                                    return await reject(
                                        "request_too_large",
                                        "The request exceeds the size limit.",
                                        413,
                                    )
                                if not message.get("more_body"):
                                    break
                    except TimeoutError:
                        return await reject(
                            "request_timeout", "The request body took too long to arrive.", 408
                        )
                    delivered = False

                    async def buffered_receive():
                        nonlocal delivered
                        if not delivered:
                            delivered = True
                            return {"type": "http.request", "body": bytes(body), "more_body": False}
                        return await receive()

                    return await self.app(scope, buffered_receive, secured_send)
                finally:
                    self.active -= 1
        await self.app(scope, receive, secured_send)
