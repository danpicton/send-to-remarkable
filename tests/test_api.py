from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import Settings
from app.document import Document
from app.extraction.article import Article
from app.integrations.rmfakecloud import Folder, UploadResult
from app.main import create_app

HEADERS = {
    "Origin": "https://reader.example",
    "X-Requested-With": "SendToRemarkable",
    "X-Auth-Request-User": "reader",
}


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(app_base_url="https://reader.example", temp_dir=tmp_path))


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://reader.example", headers=HEADERS
    ) as client:
        yield client


async def test_health_and_auth(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://reader.example"
    ) as client:
        assert (await client.get("/api/health")).status_code == 200
        assert (await client.get("/api/folders")).status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Origin": ""},
        {"X-Requested-With": ""},
        {"Sec-Fetch-Site": "cross-site"},
        {"Host": "evil.example"},
    ],
)
async def test_cross_site_and_host_protection(client, headers):
    response = await client.post(
        "/api/convert", json={"url": "https://example.org"}, headers=headers
    )
    assert response.status_code in (400, 403)
    assert "error" in response.json()


async def test_convert_returns_attachment_without_cache(client, app):
    article = Article(title="Garden", url="https://example.org", html="<p>Text</p>")
    app.state.pipeline.process = AsyncMock(
        return_value=(article, Document(b"%PDF-test", "Garden.pdf", "application/pdf"))
    )
    response = await client.post(
        "/api/convert", json={"url": "https://example.org", "format": "pdf"}
    )
    assert response.status_code == 200
    assert response.content == b"%PDF-test"
    assert "attachment" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    assert "secret" not in response.headers


async def test_typed_validation_does_not_echo_payload(client):
    response = await client.post("/api/convert", json={"url": "secret", "format": "exe"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "secret" not in response.text


async def test_send_multipart_and_error_download_independence(client, app):
    cloud = AsyncMock()
    cloud.upload.return_value = UploadResult(id="id", name="Garden.pdf")
    app.state.cloud = cloud
    response = await client.post(
        "/api/send",
        data={"folder": "a"},
        files={"file": ("Garden.pdf", b"%PDF-1.7 abc", "application/pdf")},
    )
    assert response.status_code == 200
    assert response.json()["id"] == "id"
    assert cloud.upload.call_args.args[1] == "a"


async def test_invalid_upload_and_oversized_body(client, app):
    response = await client.post(
        "/api/send", files={"file": ("bad.html", b"<script>", "text/html")}
    )
    assert response.status_code == 422
    response = await client.post(
        "/api/convert", content=b"x" * 9000, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


async def test_public_config_contains_only_base_url(client):
    response = await client.get("/api/config")
    assert response.json() == {"base_url": "https://reader.example"}
    assert response.headers["cache-control"] == "no-store"


async def test_folder_api(client, app):
    app.state.cloud = AsyncMock()
    app.state.cloud.folders.return_value = [Folder(id="", name="Root", path="/", parent="")]
    response = await client.get("/api/folders")
    assert response.json() == {"folders": [{"id": "", "name": "Root", "path": "/", "parent": ""}]}


async def test_unexpected_errors_are_safe_json(app):
    app.state.pipeline.process = AsyncMock(side_effect=RuntimeError("secret internal detail"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="https://reader.example",
        headers=HEADERS,
    ) as client:
        response = await client.post("/api/convert", json={"url": "https://example.org"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret" not in response.text
    assert response.headers["cache-control"] == "no-store"


async def test_fixture_to_download_then_mock_cloud(client, app):
    from pathlib import Path

    from app.extraction.fetch import FetchedPage
    from app.integrations.rmfakecloud import RMFakeCloud

    app.state.pipeline.fetcher.fetch = AsyncMock(
        return_value=FetchedPage(
            (Path(__file__).parent / "fixtures/article.html").read_bytes(),
            "https://example.org/story",
        )
    )
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/login"):
            return httpx.Response(200, text="jwt")
        if request.url.path.endswith("/documents"):
            return httpx.Response(200, json={"Entries": [], "Trash": []})
        assert "application/epub+zip" in request.content.decode("latin-1")
        return httpx.Response(200, json=[{"ID": "uploaded"}])

    settings = Settings(
        rmfakecloud_url="https://cloud.example",
        rmfakecloud_username="reader",
        rmfakecloud_password="password",
    )
    async with RMFakeCloud(settings, transport=httpx.MockTransport(handle)) as cloud:
        app.state.cloud = cloud
        response = await client.post(
            "/api/convert", json={"url": "https://example.org", "format": "epub"}
        )
        assert response.status_code == 200, response.text
        assert response.content.startswith(b"PK")
        uploaded = await client.post(
            "/api/send",
            data={"folder": ""},
            files={"file": ("Garden.epub", response.content, "application/epub+zip")},
        )
        assert uploaded.status_code == 200
        assert uploaded.json()["id"] == "uploaded"
    assert calls == ["/ui/api/login", "/ui/api/documents", "/ui/api/documents/upload"]
