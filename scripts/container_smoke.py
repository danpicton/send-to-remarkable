"""Run inside the built image with tests/fixtures mounted read-only at /fixtures."""

import asyncio
import io
import os
import tempfile
import zipfile
from pathlib import Path

from app.config import Settings
from app.extraction.fetch import FetchedPage
from app.pipeline import run_worker


async def main():
    assert os.getuid() != 0, "The runtime must not run as root"
    page = FetchedPage(Path("/fixtures/article.html").read_bytes(), "https://example.org/garden")
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(temp_dir=Path(directory), max_conversions=1)
        for format, magic in [("pdf", b"%PDF-"), ("epub", b"PK")]:
            article, document = await run_worker(page, format, settings)
            assert article.title == "The quiet garden"
            assert document.data.startswith(magic)
            assert len(document.data) < settings.max_document_bytes
            if format == "epub":
                with zipfile.ZipFile(io.BytesIO(document.data)) as archive:
                    assert archive.read("mimetype") == b"application/epub+zip"
            assert list(Path(directory).iterdir()) == [], "Worker left temporary files behind"
            print(f"{format.upper()}: generated {len(document.data)} bytes; worker cleaned up")


if __name__ == "__main__":
    asyncio.run(main())
