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


def test_html_title_takes_precedence_over_article_metadata():
    content = FIXTURE.read_bytes().replace(
        b"<title>The quiet garden</title>",
        b"<title>  The garden: a guide &amp; more | Site  </title>"
        b'<meta property="og:title" content="Other title">',
    )
    article = TrafilaturaExtractor().extract(content, "https://example.org/garden")
    assert article.title == "The garden: a guide & more | Site"


def test_missing_html_title_falls_back_to_extracted_title():
    content = FIXTURE.read_bytes().replace(b"<title>The quiet garden</title>", b"")
    article = TrafilaturaExtractor().extract(content, "https://example.org/garden")
    assert article.title == "The quiet garden"


def test_unicode_html_title_without_charset():
    content = FIXTURE.read_bytes().replace(
        b"<title>The quiet garden</title>",
        "<title>Café: a reader’s guide — 日本語</title>".encode(),
    )
    article = TrafilaturaExtractor().extract(content, "https://example.org/garden")
    assert article.title == "Café: a reader’s guide — 日本語"
