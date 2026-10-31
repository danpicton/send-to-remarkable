import io
from html import escape
from uuid import uuid4

from ebooklib import epub
from lxml import etree, html
from weasyprint import HTML

from app.document import Document
from app.extraction.article import Article, sanitize_html
from app.filenames import safe_filename

CSS = """
@page { size: A5; margin: 16mm 14mm 18mm;
  @bottom-center { content: counter(page); font-size: 9pt; color: #555; }
}
body { font-family: "DejaVu Serif", Georgia, serif;
  font-size: 12pt; line-height: 1.5; color: #111; }
h1 { font-size: 22pt; line-height: 1.2; } h2 { font-size: 17pt; } h3 { font-size: 14pt; }
h1, h2, h3, h4 { break-after: avoid; } p { margin: 0 0 .8em; orphans: 3; widows: 3; }
a { color: inherit; text-decoration: underline; overflow-wrap: anywhere; }
.byline, .source { font-family: sans-serif; font-size: 9pt; color: #444; }
header { border-bottom: 1px solid #aaa; margin-bottom: 1.5em; padding-bottom: .7em; }
blockquote { border-left: 2px solid #888; margin: 1em 0; padding-left: 1em; }
li { margin-bottom: .35em; } pre { white-space: pre-wrap; } code { overflow-wrap: anywhere; }
table { border-collapse: collapse; width: 100%; font-size: .85em; }
td, th { border: 1px solid #aaa; padding: .3em; overflow-wrap: anywhere; }
"""


def deny_resource(url, *args, **kwargs):
    raise ValueError("Document resources are disabled")


def article_body(article: Article) -> str:
    content = html.fromstring(sanitize_html(article.html, article.url))
    heading = content.find(".//h1")
    if heading is not None and " ".join(heading.text_content().split()) == " ".join(
        article.title.split()
    ):
        heading.drop_tree()
    body = etree.tostring(content, encoding="unicode", method="xml")
    byline = " · ".join(escape(x) for x in (article.author, article.published) if x)
    return (
        f'<header><h1>{escape(article.title)}</h1><p class="byline">{byline}</p>'
        f'<p class="source">Source: <a href="{escape(article.url, quote=True)}">'
        f"{escape(article.url)}</a></p></header>" + body
    )


def convert(article: Article, format: str) -> Document:
    body = article_body(article)
    if format == "pdf":
        markup = (
            f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<title>{escape(article.title)}</title><meta name="author" '
            f'content="{escape(article.author or "", quote=True)}">'
            f"<style>{CSS}</style></head><body>{body}</body></html>"
        )
        data = HTML(string=markup, url_fetcher=deny_resource).write_pdf()
        mime = "application/pdf"
    elif format == "epub":
        book = epub.EpubBook()
        book.set_identifier(str(uuid4()))
        book.set_title(article.title)
        book.set_language(article.language)
        if article.author:
            book.add_author(article.author)
        if article.published:
            book.add_metadata("DC", "date", article.published)
        book.add_metadata("DC", "source", article.url)
        chapter = epub.EpubHtml(
            title=article.title, file_name="article.xhtml", lang=article.language
        )
        chapter.content = body
        style = epub.EpubItem(
            uid="style",
            file_name="style.css",
            media_type="text/css",
            content=b"body { line-height: 1.5; } p { margin: 0 0 .8em; } "
            b"blockquote { margin: 1em; } a { overflow-wrap: anywhere; }",
        )
        chapter.add_item(style)
        book.add_item(style)
        book.add_item(chapter)
        book.toc = (epub.Link("article.xhtml", article.title, "article"),)
        book.spine = ["nav", chapter]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        output = io.BytesIO()
        epub.write_epub(output, book, {})
        data = output.getvalue()
        mime = "application/epub+zip"
    else:
        raise ValueError("Unknown document format")
    return Document(data=data, filename=safe_filename(article.title, format), media_type=mime)
