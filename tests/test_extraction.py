from pathlib import Path

import pytest
from lxml import html

from app.errors import AppError
from app.extraction.article import TrafilaturaExtractor, sanitize_html

FIXTURE = Path(__file__).parent / "fixtures/article.html"


def test_extract_article_metadata_and_semantics():
    article = TrafilaturaExtractor().extract(FIXTURE.read_bytes(), "https://example.org/garden")
    assert article.title == "The quiet garden"
    assert article.author == "Alex Green"
    assert article.published == "2024-04-12"
    assert article.url == "https://example.org/garden"
    tree = html.fromstring(article.html)
    for tag in ("h2", "p", "ul", "li", "blockquote", "strong", "em", "a"):
        assert tree.xpath(f"//{tag}"), tag
    assert tree.xpath("//a/@href") == ["https://example.org/field-guide"]
    assert "Subscribe" not in article.html
    assert not tree.xpath("//script | //img | //nav")


def test_sanitizer_blocks_active_content_and_resources():
    clean = sanitize_html(
        '<p onclick="x()">Hello<script>bad()</script></p>'
        '<img src="file:///etc/passwd"><style>@import "http://local";</style>'
        '<a href="javascript:alert(1)">bad</a><iframe src="http://local"></iframe>'
        '<a href="/good">good</a>',
        "https://example.org/a",
    )
    assert "onclick" not in clean and "javascript:" not in clean
    assert "bad()" not in clean and "file:" not in clean and "@import" not in clean
    assert "https://example.org/good" in clean


def test_empty_extraction_is_useful_error():
    with pytest.raises(AppError, match="readable article"):
        TrafilaturaExtractor().extract(b"<html><nav>Home</nav></html>", "https://example.org/")
