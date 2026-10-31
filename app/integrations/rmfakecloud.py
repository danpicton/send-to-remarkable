"""rmfakecloud web API; source contract documented in docs/rmfakecloud-api.md."""

import asyncio
import json
import ssl

import httpx
from pydantic import BaseModel

from app.config import Settings
from app.document import Document
from app.errors import AppError


class Folder(BaseModel):
    id: str
    name: str
    path: str
    parent: str


class UploadResult(BaseModel):
    id: str
    name: str


def protocol_error():
    return AppError(
        "cloud_protocol", "Unexpected rmfakecloud response. Check server compatibility.", 502
    )


def parse_folders(tree) -> list[Folder]:
    if not isinstance(tree, dict) or "Entries" not in tree:
        raise protocol_error()
    result = [Folder(id="", name="Root", path="/", parent="")]
    seen = {""}
    count = 0

    def walk(entries, parent, path, depth):
        nonlocal count
        if entries is None:
            return
        if not isinstance(entries, list) or depth > 64:
            raise protocol_error()
        for entry in entries:
            count += 1
            if count > 10_000 or not isinstance(entry, dict):
                raise protocol_error()
            if entry.get("isFolder") is not True:
                continue
            id, name = entry.get("id"), entry.get("name")
            if (
                not isinstance(id, str)
                or not id
                or len(id) > 128
                or id in seen
                or id in {"trash", "root"}
                or not isinstance(name, str)
            ):
                raise protocol_error()
            seen.add(id)
            full_path = f"{path}/{name}"
            result.append(Folder(id=id, name=name, path=full_path, parent=parent))
            walk(entry.get("children"), id, full_path, depth + 1)

    walk(tree["Entries"], "", "", 0)
    return [result[0], *sorted(result[1:], key=lambda folder: folder.path.casefold())]


class RMFakeCloud:
    def __init__(self, settings: Settings, transport=None):
        self.settings = settings
        verify = settings.rmfakecloud_verify_tls
        if verify and settings.rmfakecloud_ca_bundle:
            verify = ssl.create_default_context(cafile=settings.rmfakecloud_ca_bundle)
        self.http = httpx.AsyncClient(
            verify=verify,
            follow_redirects=False,
            trust_env=False,
            timeout=settings.rmfakecloud_timeout,
            transport=transport,
        )
        self.token = None
        self.login_lock = asyncio.Lock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.http.aclose()

    async def _request(self, method, path, **kwargs):
        try:
            async with asyncio.timeout(self.settings.rmfakecloud_timeout):
                async with self.http.stream(
                    method, self.settings.rmfakecloud_url + "/ui/api" + path, **kwargs
                ) as response:
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 4 * 1024 * 1024:
                            raise protocol_error()
                    # Discard cookies: only the in-memory bearer token is used.
                    self.http.cookies.clear()
                    return httpx.Response(response.status_code, content=bytes(body))
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise AppError(
                "cloud_timeout",
                "rmfakecloud timed out. If sending, check the tablet before retrying; "
                "the upload may have succeeded.",
                504,
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                "cloud_unavailable",
                "Cannot reach rmfakecloud. Check its address and TLS certificate. "
                "Your download is still available.",
                502,
            ) from exc

    async def _login(self, stale=None):
        async with self.login_lock:
            if self.token and self.token != stale:
                return
            if not (
                self.settings.rmfakecloud_url
                and self.settings.rmfakecloud_username
                and self.settings.rmfakecloud_password.get_secret_value()
            ):
                raise AppError(
                    "cloud_unconfigured",
                    "rmfakecloud is not configured. You can still download articles.",
                    503,
                )
            response = await self._request(
                "POST",
                "/login",
                json={
                    "email": self.settings.rmfakecloud_username,
                    "password": self.settings.rmfakecloud_password.get_secret_value(),
                },
            )
            self._check(response)
            token = response.text.strip()
            if not token or len(token) > 8192 or any(c.isspace() for c in token) or "<" in token:
                raise protocol_error()
            self.token = token

    @staticmethod
    def _check(response):
        if response.status_code in (401, 403):
            raise AppError("cloud_auth", "rmfakecloud rejected the configured credentials.", 502)
        if response.status_code == 409:
            raise AppError(
                "cloud_conflict",
                "rmfakecloud reports this document already exists. "
                "Check the destination before retrying.",
                409,
            )
        if response.status_code != 200:
            raise AppError(
                "cloud_unavailable",
                f"rmfakecloud returned HTTP {response.status_code}. "
                "Your download is still available.",
                502,
            )

    async def _authenticated(self, method, path, **kwargs):
        await self._login()
        token = self.token
        response = await self._request(
            method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs
        )
        if response.status_code == 401:
            # A 401 comes from middleware before any upload side effect.
            await self._login(stale=token)
            response = await self._request(
                method, path, headers={"Authorization": f"Bearer {self.token}"}, **kwargs
            )
        self._check(response)
        try:
            return response.json()
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise protocol_error() from exc

    async def folders(self) -> list[Folder]:
        return parse_folders(await self._authenticated("GET", "/documents"))

    async def upload(self, document: Document, parent: str) -> UploadResult:
        if parent not in {folder.id for folder in await self.folders()}:
            raise AppError(
                "folder_missing",
                "The selected folder no longer exists. Refresh folders and choose a destination.",
                409,
            )
        result = await self._authenticated(
            "POST",
            "/documents/upload",
            data={"parent": parent},
            files={"file": (document.filename, document.data, document.media_type)},
        )
        if (
            not isinstance(result, list)
            or len(result) != 1
            or not isinstance(result[0], dict)
            or not isinstance(result[0].get("ID"), str)
            or not result[0]["ID"]
        ):
            raise protocol_error()
        return UploadResult(id=result[0]["ID"], name=document.filename)
