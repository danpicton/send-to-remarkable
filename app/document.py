from dataclasses import dataclass


@dataclass(frozen=True)
class Document:
    data: bytes
    filename: str
    media_type: str
