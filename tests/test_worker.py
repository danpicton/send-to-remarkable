import asyncio
from pathlib import Path

import pytest

from app.config import Settings
from app.errors import AppError
from app.extraction.fetch import FetchedPage
from app.pipeline import Pipeline, run_worker


@pytest.mark.parametrize("format,magic", [("epub", b"PK"), ("pdf", b"%PDF-")])
async def test_worker_converts_and_cleans_files(tmp_path, format, magic):
    settings = Settings(temp_dir=tmp_path)
    page = FetchedPage(
        (Path(__file__).parent / "fixtures/article.html").read_bytes(), "https://example.org/story"
    )
    article, doc = await run_worker(page, format, settings)
    assert article.title == "The quiet garden"
    assert doc.data.startswith(magic)
    assert list(tmp_path.iterdir()) == []


async def test_worker_deadline_kills_and_cleans(tmp_path):
    settings = Settings(temp_dir=tmp_path, conversion_timeout=0.001)
    with pytest.raises(AppError, match="too long"):
        await run_worker(FetchedPage(b"<html/>", "https://example.org"), "pdf", settings)
    assert list(tmp_path.iterdir()) == []


async def test_concurrency_gate_rejects_instead_of_queuing(tmp_path):
    pipeline = Pipeline(Settings(temp_dir=tmp_path, max_conversions=1))
    entered = asyncio.Event()
    release = asyncio.Event()

    async def hold():
        async with pipeline.slot():
            entered.set()
            await release.wait()

    task = asyncio.create_task(hold())
    await entered.wait()
    with pytest.raises(AppError) as error:
        async with pipeline.slot():
            pass
    assert error.value.status == 429
    release.set()
    await task
    async with pipeline.slot():
        pass


async def test_cancellation_kills_worker_and_cleans_directory(tmp_path, monkeypatch):
    class Process:
        returncode = None
        killed = False

        def __init__(self):
            self.waiting = asyncio.Event()
            self.stopped = asyncio.Event()

        async def wait(self):
            self.waiting.set()
            await self.stopped.wait()

        def kill(self):
            self.killed = True
            self.returncode = -9
            self.stopped.set()

    from unittest.mock import AsyncMock

    process = Process()
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    task = asyncio.create_task(
        run_worker(
            FetchedPage(b"<html/>", "https://example.org"), "pdf", Settings(temp_dir=tmp_path)
        )
    )
    await process.waiting.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.killed
    assert list(tmp_path.iterdir()) == []
    assert not any("RMFAKECLOUD" in key for key in spawn.call_args.kwargs["env"])
