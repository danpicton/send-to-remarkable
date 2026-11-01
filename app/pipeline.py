import asyncio
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config import Settings
from app.errors import AppError
from app.extraction.article import Article
from app.extraction.fetch import FetchedPage, PublicFetcher


async def run_worker(
    page: FetchedPage, format: str | None, settings: Settings, title: str | None = None
):
    # Importing the light document value class must not import WeasyPrint in the API process.
    from app.document import Document

    settings.temp_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with TemporaryDirectory(dir=settings.temp_dir) as tmp:
        directory = Path(tmp)
        (directory / "source.html").write_bytes(page.content)
        options = dict(
            url=page.url,
            format=format,
            title=title,
            memory_mb=settings.worker_memory_mb,
            timeout=settings.conversion_timeout,
            max_document_bytes=settings.max_document_bytes,
            max_article_chars=settings.max_article_chars,
        )
        (directory / "options.json").write_text(json.dumps(options))
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.worker",
            tmp,
            cwd=Path(__file__).resolve().parent.parent,
            env={"LANG": "C.UTF-8", "TMPDIR": tmp, "XDG_CACHE_HOME": tmp},
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(settings.conversion_timeout):
                await process.wait()
        except TimeoutError as exc:
            raise AppError("conversion_timeout", "Article processing took too long.", 504) from exc
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        result_file = directory / "result.json"
        if process.returncode or not result_file.exists():
            raise AppError(
                "conversion_failed", "Article processing failed or exceeded a resource limit.", 422
            )
        result = json.loads(result_file.read_text())
        if "error" in result:
            raise AppError(**result["error"])
        article = Article.model_validate(result["article"])
        document = None
        if format:
            data = await asyncio.to_thread((directory / "document").read_bytes)
            document = Document(
                data=data, filename=result["filename"], media_type=result["media_type"]
            )
        return article, document


class Pipeline:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.active = 0
        self.fetcher = PublicFetcher(settings.max_page_bytes, settings.fetch_timeout)

    @asynccontextmanager
    async def slot(self):
        # All access happens in the one event loop, with no await between check and increment.
        if self.active >= self.settings.max_conversions:
            raise AppError("busy", "The server is busy. Please try again shortly.", 429)
        self.active += 1
        try:
            yield
        finally:
            self.active -= 1

    async def process(self, url: str, format: str | None, title: str | None = None):
        async with self.slot():
            page = await self.fetcher.fetch(url)
            return await run_worker(page, format, self.settings, title)
