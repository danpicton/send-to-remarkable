from typing import Protocol
from urllib.parse import urljoin

import nh3
import trafilatura
from lxml import etree, html
from pydantic import BaseModel
from trafilatura.utils import load_html

from app.errors import AppError

TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "blockquote",
    "strong",
    "em",
    "b",
    "i",
    "a",
    "br",
    "hr",
    "pre",
    "code",
    "sub",
    "sup",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "div",
    "span",
}


class Article(BaseModel):
    title: str
    author: str | None = None
    published: str | None = None
    url: str
    html: str
    language: str = "en"


class Extractor(Protocol):
    def extract(self, content: bytes, url: str) -> Article: ...


def sanitize_html(value: str, base_url: str) -> str:
    clean = nh3.clean(
        value,
        tags=TAGS,
        attributes={"a": {"href", "title"}},
        url_schemes={"http", "https"},
        link_rel=None,
        clean_content_tags={"script", "style", "iframe", "object", "svg", "math"},
    )
    tree = html.fragment_fromstring(clean, create_parent="div")
    for link in tree.iter("a"):
        href = link.get("href")
        if href:
            absolute = urljoin(base_url, href)
            if absolute.startswith(("https://", "http://")):
                link.set("href", absolute)
            else:
                del link.attrib["href"]
    # XML serialization makes void elements valid in EPUB's XHTML.
    return etree.tostring(tree, encoding="unicode", method="xml")


class TrafilaturaExtractor:
    def extract(self, content: bytes, url: str) -> Article:
        doc = trafilatura.bare_extraction(
            content,
            url=url,
            output_format="html",
            include_comments=False,
            include_tables=True,
            include_images=False,
            include_formatting=True,
            include_links=True,
            with_metadata=True,
            as_dict=False,
        )
        if doc is None or doc.body is None:
            raise AppError("extraction_failed", "No readable article was found on this page.", 422)
        # Trafilatura uses its own semantic XML vocabulary internally.
        body = doc.body
        for node in body.iter():
            if node.tag == "head":
                node.tag = (
                    node.get("rend")
                    if node.get("rend") in {"h1", "h2", "h3", "h4", "h5", "h6"}
                    else "h2"
                )
            elif node.tag == "list":
                node.tag = "ol" if node.get("rend") == "ol" else "ul"
            elif node.tag == "item":
                node.tag = "li"
            elif node.tag == "quote":
                node.tag = "blockquote"
            elif node.tag == "hi":
                node.tag = {"#b": "strong", "#i": "em", "#t": "code"}.get(node.get("rend"), "span")
            elif node.tag == "ref":
                node.tag = "a"
                node.set("href", node.get("target", ""))
            elif node.tag == "lb":
                node.tag = "br"
            elif node.tag == "row":
                node.tag = "tr"
            elif node.tag == "cell":
                node.tag = "th" if node.get("role") == "head" else "td"
        cleaned = sanitize_html(etree.tostring(body, encoding="unicode"), url)
        if len("".join(html.fromstring(cleaned).itertext()).strip()) < 100:
            raise AppError("extraction_failed", "No readable article was found on this page.", 422)
        tree = load_html(content)
        page_title = " ".join(tree.xpath("string(//title)").split()) if tree is not None else ""
        return Article(
            title=(page_title or doc.title or "Untitled article")[:500],
            author=doc.author,
            published=doc.date,
            url=url,
            html=cleaned,
        )
