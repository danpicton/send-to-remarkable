"""One bounded extraction/conversion job, executed by pipeline.py, never a server."""

import json
import math
import resource
import sys
from pathlib import Path


def main():
    directory = Path(sys.argv[1])
    options = json.loads((directory / "options.json").read_text())
    memory = options["memory_mb"] * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    cpu = math.ceil(options["timeout"]) + 1
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_FSIZE, (options["max_document_bytes"],) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    from app.errors import AppError
    from app.extraction.article import TrafilaturaExtractor

    try:
        article = TrafilaturaExtractor().extract(
            (directory / "source.html").read_bytes(), options["url"]
        )
        if len(article.html) > options["max_article_chars"]:
            raise AppError(
                "article_too_large", "The extracted article is too long to convert.", 413
            )
        result = {"article": article.model_dump()}
        if options["format"]:
            from app.conversion.documents import convert

            document = convert(article, options["format"])
            if len(document.data) > options["max_document_bytes"]:
                raise AppError(
                    "document_too_large", "The generated document exceeds the size limit.", 413
                )
            (directory / "document").write_bytes(document.data)
            result.update(filename=document.filename, media_type=document.media_type)
    except AppError as exc:
        result = {"error": {"code": exc.code, "message": exc.message, "status": exc.status}}
    except Exception:
        result = {
            "error": {
                "code": "conversion_failed",
                "message": "Could not process this article. Try another format or webpage.",
                "status": 422,
            }
        }
    (directory / "result.json").write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
