from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.document import Document
from app.extraction.article import Article
from app.main import create_app

ORIGINS = ["https://reader.example", "https://reading.other.example", "https://books.example:8443"]


def test_origin_list_from_environment_overrides_legacy_base(monkeypatch):
    monkeypatch.setenv(
        "APP_ALLOWED_ORIGINS", '["https://Reader.Example/", "https://reading.other.example"]'
    )
    settings = Settings(_env_file=None, app_base_url="http://localhost:8000")
    assert settings.public_origins == ORIGINS[:2]


def test_legacy_base_url_remains_supported():
    assert Settings(_env_file=None, app_base_url="https://Reader.Example:443/").public_origins == [
        ORIGINS[0]
    ]


@pytest.mark.parametrize(
    "origins",
    [
        [],
        ["*"],
        ["https://*.example"],
        ["ftp://reader.example"],
        ["https://reader.example/path"],
        ["https://user:secret@reader.example"],
        ["https://@reader.example"],
        ["https://reader.example?query"],
        ["https://reader.example#fragment"],
        ["https://reader.example:bad"],
        ["https://reader.example:99999"],
        ["https://reader.example\n"],
        ["https://reader.example\\evil"],
        ["http://reader.example", "https://reader.example"],
    ],
)
def test_invalid_or_ambiguous_origins_fail_at_startup(origins):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_allowed_origins=origins)


@pytest.fixture
def multi_app(tmp_path):
    app = create_app(Settings(_env_file=None, app_allowed_origins=ORIGINS, temp_dir=tmp_path))
    app.state.pipeline.process = AsyncMock(
        return_value=(
            Article(title="Article", url="https://example.org", html="<p>Text</p>"),
            Document(b"%PDF-test", "Article.pdf", "application/pdf"),
        )
    )
    return app


@pytest.mark.parametrize("origin", ORIGINS)
async def test_each_configured_origin_serves_shell_config_and_conversion(multi_app, origin):
    # The internal connection remains HTTP behind TLS termination; do not derive
    # the public scheme from the ASGI scope or untrusted forwarded headers.
    authority = httpx.URL(origin).netloc.decode()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=multi_app),
        base_url="http://internal:8000",
        headers={
            "Host": authority,
            "Origin": origin,
            "X-Auth-Request-User": "reader",
            "X-Requested-With": "SendToRemarkable",
        },
    ) as client:
        assert (await client.get("/?url=https://example.org/article")).status_code == 200
        config = await client.get(
            "/api/config",
            headers={
                "X-Forwarded-Host": "evil.example",
                "X-Forwarded-Proto": "http",
            },
        )
        assert config.json() == {"base_url": origin}
        assert config.headers["cache-control"] == "no-store"
        response = await client.post("/api/convert", json={"url": "https://example.org"})
        assert response.status_code == 200
        assert response.content == b"%PDF-test"


@pytest.mark.parametrize(
    "origin", [ORIGINS[1], "http://reader.example", "https://evil.example", "", "null"]
)
async def test_cross_origin_posts_blocked_even_between_allowed_hosts(multi_app, origin):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=multi_app),
        base_url=ORIGINS[0],
        headers={
            "X-Auth-Request-User": "reader",
            "X-Requested-With": "SendToRemarkable",
        },
    ) as client:
        response = await client.post(
            "/api/convert", headers={"Origin": origin}, json={"url": "https://example.org"}
        )
        assert response.status_code == 403
        multi_app.state.pipeline.process.assert_not_called()


@pytest.mark.parametrize("host", ["localhost:8000", "unlisted.example", "books.example"])
async def test_unlisted_hosts_and_wrong_ports_remain_blocked(multi_app, host):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=multi_app), base_url=ORIGINS[0]
    ) as client:
        response = await client.get(
            "/api/config",
            headers={
                "Host": host,
                "X-Forwarded-Host": "reader.example",
                "X-Auth-Request-User": "reader",
            },
        )
        assert response.status_code == 400


@pytest.mark.parametrize("origin", ORIGINS)
async def test_authentication_required_on_every_origin(multi_app, origin):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=multi_app), base_url=origin
    ) as client:
        assert (await client.get("/api/config")).status_code == 401
