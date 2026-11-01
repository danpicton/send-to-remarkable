from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException

from app.auth import Login, SessionAuth
from app.config import Settings
from app.document import Document
from app.errors import AppError
from app.extraction.article import Article
from app.integrations.rmfakecloud import Folder, RMFakeCloud, UploadResult
from app.pipeline import Pipeline
from app.security import SecurityMiddleware

STATIC = Path(__file__).parent / "static"


class ConvertRequest(BaseModel):
    url: str = Field(min_length=8, max_length=4096)
    format: Literal["pdf", "epub"] = "pdf"
    title: str | None = Field(default=None, max_length=500)


class ExtractRequest(BaseModel):
    url: str = Field(min_length=8, max_length=4096)


class FolderResponse(BaseModel):
    folders: list[Folder]


class HealthResponse(BaseModel):
    status: str = "ok"


class ConfigResponse(BaseModel):
    base_url: str


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        async with RMFakeCloud(settings) as cloud:
            app.state.cloud = cloud
            yield

    app = FastAPI(
        title="Send to reMarkable",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        responses={
            400: {"model": ErrorResponse},
            422: {"model": ErrorResponse},
            502: {"model": ErrorResponse},
        },
    )
    app.state.pipeline = Pipeline(settings)
    app.state.cloud = None
    auth = SessionAuth(settings) if settings.auth_mode == "session" else None
    app.add_middleware(SecurityMiddleware, settings=settings, auth=auth)

    @app.get("/api/auth/session")
    async def session(request: Request):
        return {"enabled": auth is not None, "authenticated": bool(auth and auth.valid(request))}

    @app.post("/api/auth/login")
    async def login(payload: Login, request: Request):
        if auth is None:
            raise HTTPException(404)
        return auth.login(payload, request)

    @app.post("/api/auth/logout")
    async def logout():
        if auth is None:
            raise HTTPException(404)
        response = JSONResponse({"ok": True})
        response.delete_cookie(auth.cookie, secure=True, httponly=True, samesite="strict")
        return response

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            {
                "error": {
                    "code": "validation_error",
                    "message": "Check the URL, title (up to 500 characters), and selected format.",
                }
            },
            status_code=422,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_request",
                    "message": "The request could not be processed.",
                }
            },
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        # This handler runs outside user middleware in Starlette's error layer.
        return JSONResponse(
            {
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected server error occurred.",
                }
            },
            status_code=500,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @app.get("/api/health", response_model=HealthResponse)
    async def health():
        return HealthResponse()

    @app.get("/api/config", response_model=ConfigResponse)
    async def config(request: Request):
        return ConfigResponse(base_url=request.state.public_origin)

    @app.get("/api/folders", response_model=FolderResponse)
    async def folders():
        return FolderResponse(folders=await app.state.cloud.folders())

    @app.post("/api/extract", response_model=Article)
    async def extract(payload: ExtractRequest):
        article, _ = await app.state.pipeline.process(payload.url, None)
        return article

    @app.post("/api/convert")
    async def convert(payload: ConvertRequest):
        _, document = await app.state.pipeline.process(payload.url, payload.format, payload.title)
        return Response(
            document.data,
            media_type=document.media_type,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="article.{payload.format}"; '
                    f"filename*=UTF-8''{quote(document.filename, safe='')}"
                ),
            },
        )

    @app.post("/api/send", response_model=UploadResult)
    async def send(request: Request):
        async with app.state.pipeline.slot():
            async with request.form(max_files=1, max_fields=1, max_part_size=1024) as form:
                file = form.get("file")
                folder = form.get("folder", "")
                if not isinstance(folder, str) or len(folder) > 128:
                    raise AppError("invalid_folder", "Choose a valid destination folder.", 422)
                if not isinstance(file, UploadFile):
                    raise AppError("invalid_file", "A PDF or EPUB file is required.", 422)
                data = await file.read(settings.max_document_bytes + 1)
                if len(data) > settings.max_document_bytes:
                    raise AppError(
                        "document_too_large", "The document exceeds the upload limit.", 413
                    )
                filename = file.filename or ""
                format = filename.rsplit(".", 1)[-1].lower()
                signatures = {
                    "pdf": (b"%PDF-", "application/pdf"),
                    "epub": (b"PK\x03\x04", "application/epub+zip"),
                }
                if format not in signatures or not data.startswith(signatures[format][0]):
                    raise AppError("invalid_file", "Upload a PDF or EPUB document.", 422)
                # Never trust a multipart filename as a path or header value.
                from app.filenames import safe_filename

                filename = safe_filename(filename.rsplit(".", 1)[0], format)
                return await app.state.cloud.upload(
                    Document(data, filename, signatures[format][1]), folder
                )

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html", headers={"X-App-Shell": "1"})

    # Explicit routes keep the cacheable shell small and prevent directory exposure.
    @app.get("/{filename}")
    async def shell(filename: str):
        allowed = {
            "app.js",
            "preferences.js",
            "styles.css",
            "manifest.webmanifest",
            "sw.js",
            "icon.svg",
            "icon-192.png",
            "icon-512.png",
            "apple-touch-icon.png",
        }
        if filename not in allowed:
            raise HTTPException(404)
        media = "application/manifest+json" if filename.endswith(".webmanifest") else None
        return FileResponse(STATIC / filename, media_type=media, headers={"X-App-Shell": "1"})

    return app


app = create_app()
