import re
import unicodedata


def safe_filename(title: str, format: str) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    name = re.sub(r"[^a-zA-Z0-9_-]+", "-", ascii_title).strip("-_")[:80].rstrip("-_")
    return f"{name or 'article'}.{format}"
