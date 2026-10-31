import io
import zipfile
from xml.etree import ElementTree as ET

import pytest
from pypdf import PdfReader

from app.conversion.documents import convert, deny_resource, safe_filename
from app.extraction.article import Article


@pytest.fixture
def article():
    return Article(
        title="A quiet <garden> & more",
        author="Alex Green",
        published="2024-04-12",
        url="https://example.org/garden?a=1&b=2",
        html="<h2>First steps</h2><p>A garden is a place to read and think.</p>",
    )


def test_pdf_has_readable_content_and_metadata(article):
    doc = convert(article, "pdf")
    assert doc.data.startswith(b"%PDF-")
    pdf = PdfReader(io.BytesIO(doc.data))
    text = "\n".join(page.extract_text() for page in pdf.pages)
    assert "garden" in text and "Alex Green" in text and "2024-04-12" in text
    assert "First steps" in text and "example.org" in text
    assert doc.media_type == "application/pdf"
    assert pdf.metadata.title == article.title


def test_epub_container_navigation_and_xhtml(article):
    doc = convert(article, "epub")
    with zipfile.ZipFile(io.BytesIO(doc.data)) as archive:
        assert archive.namelist()[0] == "mimetype"
        assert archive.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        assert archive.read("mimetype") == b"application/epub+zip"
        ET.fromstring(archive.read("META-INF/container.xml"))
        for name in archive.namelist():
            if name.endswith((".xhtml", ".opf", ".ncx")):
                ET.fromstring(archive.read(name))
        chapter = archive.read("EPUB/article.xhtml").decode()
        assert "Alex Green" in chapter and "https://example.org" in chapter
        assert "A quiet &lt;garden&gt; &amp; more" in chapter
        opf = archive.read("EPUB/content.opf").decode()
        assert "Alex Green" in opf and "nav" in opf and "dc:source" in opf


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "https://example.org/a.png", "data:text/plain,secret"]
)
def test_renderer_cannot_fetch_resources(url):
    with pytest.raises(ValueError):
        deny_resource(url)


def test_safe_filenames():
    assert safe_filename("../../evil\r\nfile", "pdf") == "evil-file.pdf"
    assert safe_filename("日本語", "epub") == "article.epub"
    assert len(safe_filename("x" * 500, "pdf")) <= 84


def test_extracted_title_is_not_printed_twice(article):
    from lxml import html

    from app.conversion.documents import article_body

    article.html = "<h1>A quiet &lt;garden&gt; &amp; more</h1><p>Article body.</p>"
    body = html.fromstring(article_body(article))
    assert len(body.xpath("//h1")) == 1
    assert "Article body." in body.text_content()
