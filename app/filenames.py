import re
import unicodedata


def safe_filename(title: str, format: str) -> str:
    """Keep readable Unicode names, excluding paths and multipart delimiters."""
    name = unicodedata.normalize("NFC", title)
    name = "".join(
        " " if char in "/\\" or unicodedata.category(char).startswith("C") else char
        for char in name
    )
    # Multipart implementations escape ASCII double quotes inconsistently.
    name = name.replace('"', "”")
    name = re.sub(r"\s+", " ", name).strip(" .")
    # Bound bytes (not characters), leaving room for extensions on local filesystems.
    name = name.encode("utf-8")[:180].decode("utf-8", "ignore").rstrip(" .")
    return f"{name or 'article'}.{format}"
