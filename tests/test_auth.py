from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app

ORIGIN = "https://reader.example"
HEADERS = {"Origin": ORIGIN, "X-Requested-With": "SendToRemarkable"}
CREDENTIALS = {"username": "reader", "password": "test-password"}


def settings(**kwargs):
    return Settings(
        _env_file=None,
        auth_mode="session",
        app_base_url=ORIGIN,
        auth_session_secret="test-only-secret-" * 3,
        rmfakecloud_username="reader",
        rmfakecloud_password="test-password",
        **kwargs,
    )


def client(config=None):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(config or settings())),
        base_url=ORIGIN,
        headers=HEADERS,
    )


async def test_login_cookie_restart_expiry_and_logout():
    async with client() as browser:
        assert (await browser.get("/")).status_code == 200
        assert (await browser.get("/api/health")).status_code == 200
        assert (await browser.get("/api/config")).status_code == 401
        assert (await browser.get("/api/auth/session")).json() == {
            "enabled": True,
            "authenticated": False,
        }
        response = await browser.post("/api/auth/login", json=CREDENTIALS)
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        for attribute in ("HttpOnly", "Secure", "SameSite=strict", "Max-Age=2592000", "Path=/"):
            assert attribute in cookie
        assert "Domain=" not in cookie
        assert (await browser.get("/api/config")).status_code == 200
        assert (await browser.get("/api/auth/session")).json()["authenticated"]
        async with client() as restarted:
            restarted.cookies.update(browser.cookies)
            assert (await restarted.get("/api/config")).status_code == 200
        with patch("itsdangerous.timed.TimestampSigner.get_timestamp", return_value=9999999999):
            assert (await browser.get("/api/config")).status_code == 401
        assert (await browser.post("/api/auth/logout")).status_code == 200
        assert (await browser.get("/api/config")).status_code == 401


async def test_reject_tampering_spoofed_identity_and_credential_rotation():
    async with client() as browser:
        assert (
            await browser.get("/api/config", headers={"X-Auth-Request-User": "reader"})
        ).status_code == 401
        await browser.post("/api/auth/login", json=CREDENTIALS)
        config = settings()
        config.rmfakecloud_username = "changed"
        async with client(config) as rotated:
            rotated.cookies.update(browser.cookies)
            assert (await rotated.get("/api/config")).status_code == 401
        token = browser.cookies.get("__Host-rm-send-session")
        browser.cookies.clear()
        browser.cookies.set("__Host-rm-send-session", token + "tampered")
        assert (await browser.get("/api/config")).status_code == 401


async def test_login_csrf_limits_and_errors():
    async with client() as browser:
        for headers in ({"Origin": "https://evil.example"}, {"X-Requested-With": ""}):
            assert (
                await browser.post("/api/auth/login", json=CREDENTIALS, headers=headers)
            ).status_code == 403
        assert (await browser.post("/api/auth/login", content="x" * 9000)).status_code == 413
        for _ in range(5):
            response = await browser.post(
                "/api/auth/login", json={**CREDENTIALS, "password": "wrong"}
            )
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "invalid_login"
        assert (await browser.post("/api/auth/login", json=CREDENTIALS)).status_code == 429
        with patch("app.auth.time.monotonic", return_value=9999999999):
            assert (await browser.post("/api/auth/login", json=CREDENTIALS)).status_code == 200
        assert (
            await browser.post("/api/auth/logout", headers={"Origin": "https://evil.example"})
        ).status_code == 403
        assert (await browser.get("/api/config")).status_code == 200


async def test_session_bound_to_origin():
    config = settings(app_allowed_origins=[ORIGIN, "https://other.example"])
    async with client(config) as browser:
        await browser.post("/api/auth/login", json=CREDENTIALS)
        token = browser.cookies.get("__Host-rm-send-session")
        response = await browser.get(
            "https://other.example/api/config",
            headers={"Cookie": f"__Host-rm-send-session={token}"},
        )
        assert response.status_code == 401


@pytest.mark.parametrize(
    "overrides",
    [
        {"auth_session_secret": ""},
        {"rmfakecloud_password": ""},
        {"app_base_url": "http://reader.example"},
        {"auth_session_days": 0},
    ],
)
def test_session_configuration_fails_closed(overrides):
    values = settings().model_dump()
    values.update(overrides)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)
