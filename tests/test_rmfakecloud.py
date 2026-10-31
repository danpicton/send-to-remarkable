import json
from email.parser import BytesParser
from email.policy import default

import httpx
import pytest

from app.config import Settings
from app.document import Document
from app.errors import AppError
from app.integrations.rmfakecloud import RMFakeCloud, parse_folders

TREE = {
    "Entries": [
        {
            "id": "a",
            "name": "Reading",
            "isFolder": True,
            "children": [
                {"id": "b", "name": "Science", "isFolder": True, "children": []},
                {"id": "doc", "name": "Book", "type": "pdf"},
            ],
        }
    ],
    "Trash": [{"id": "trash-folder", "name": "Deleted", "isFolder": True, "children": []}],
}


def settings():
    return Settings(
        rmfakecloud_url="https://cloud.example",
        rmfakecloud_username="reader",
        rmfakecloud_password="secret",
    )


def test_nested_folders_exclude_documents_and_trash():
    folders = parse_folders(TREE)
    assert [(f.id, f.path) for f in folders] == [
        ("", "/"),
        ("a", "/Reading"),
        ("b", "/Reading/Science"),
    ]
    assert folders[2].parent == "a"
    assert len(parse_folders({"Entries": None, "Trash": None})) == 1


@pytest.mark.parametrize("tree", [{}, [], {"Entries": "bad"}, {"Entries": [{"isFolder": True}]}])
def test_bad_tree_is_reported(tree):
    with pytest.raises(AppError):
        parse_folders(tree)


async def test_login_and_real_multipart_contract():
    seen = []

    def handle(request):
        seen.append(request.url.path)
        if request.url.path == "/ui/api/login":
            assert json.loads(request.content) == {"email": "reader", "password": "secret"}
            return httpx.Response(200, text="jwt-token")
        assert request.headers["Authorization"] == "Bearer jwt-token"
        if request.url.path == "/ui/api/documents":
            return httpx.Response(200, json=TREE)
        assert request.url.path == "/ui/api/documents/upload"
        message = BytesParser(policy=default).parsebytes(
            b"Content-Type: "
            + request.headers["content-type"].encode()
            + b"\r\n\r\n"
            + request.content
        )
        parts = {p.get_param("name", header="content-disposition"): p for p in message.iter_parts()}
        assert parts["parent"].get_payload(decode=True) == b"b"
        assert parts["file"].get_filename() == "Garden.pdf"
        assert parts["file"].get_content_type() == "application/pdf"
        assert parts["file"].get_payload(decode=True) == b"%PDF-1.7 test"
        return httpx.Response(200, json=[{"ID": "new-id", "Name": "Garden"}])

    async with RMFakeCloud(settings(), transport=httpx.MockTransport(handle)) as cloud:
        assert (await cloud.folders())[2].id == "b"
        result = await cloud.upload(
            Document(b"%PDF-1.7 test", "Garden.pdf", "application/pdf"), "b"
        )
        assert result.id == "new-id"
    assert seen.count("/ui/api/login") == 1
    assert seen.count("/ui/api/documents") == 2  # Revalidate immediately before upload.


async def test_missing_folder_prevents_upload():
    def handle(request):
        if request.url.path.endswith("/login"):
            return httpx.Response(200, text="token")
        assert request.method == "GET"
        return httpx.Response(200, json=TREE)

    async with RMFakeCloud(settings(), transport=httpx.MockTransport(handle)) as cloud:
        with pytest.raises(AppError) as error:
            await cloud.upload(Document(b"%PDF-", "a.pdf", "application/pdf"), "missing")
        assert error.value.code == "folder_missing"


async def test_expired_token_reauthenticates_once():
    logins = 0

    def handle(request):
        nonlocal logins
        if request.url.path.endswith("/login"):
            logins += 1
            return httpx.Response(200, text=f"token{logins}")
        if request.headers["Authorization"] == "Bearer token1":
            return httpx.Response(401)
        return httpx.Response(200, json=TREE)

    async with RMFakeCloud(settings(), transport=httpx.MockTransport(handle)) as cloud:
        assert len(await cloud.folders()) == 3
    assert logins == 2


@pytest.mark.parametrize(
    "status,code", [(401, "cloud_auth"), (500, "cloud_unavailable"), (302, "cloud_unavailable")]
)
async def test_cloud_errors_do_not_leak_credentials(status, code):
    async with RMFakeCloud(
        settings(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, text="secret internal detail")
        ),
    ) as cloud:
        with pytest.raises(AppError) as error:
            await cloud.folders()
        assert error.value.code == code
        assert "secret" not in str(error.value)


async def test_timeout_is_useful_and_not_retried():
    calls = 0

    def handle(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("secret URL")

    async with RMFakeCloud(settings(), transport=httpx.MockTransport(handle)) as cloud:
        with pytest.raises(AppError) as error:
            await cloud.folders()
        assert error.value.code == "cloud_timeout"
    assert calls == 1
