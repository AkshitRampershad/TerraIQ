"""Load ordinance source text from a local file.

Deliberately local-only. The point of a transcription pipeline is that the
source is a document you can put your hands on and re-read later, not a URL
that may have changed since.
"""

from __future__ import annotations

import re
from pathlib import Path


class SourceUnavailable(RuntimeError):
    pass


def normalize(text: str) -> str:
    """Collapse whitespace so excerpt matching survives PDF line wrapping."""
    return re.sub(r"\s+", " ", text).strip()


def load_text(path: str | Path) -> str:
    """Read ordinance text from .txt/.md directly, or .pdf via pypdf."""
    path = Path(path)
    if not path.is_file():
        raise SourceUnavailable(f"{path} does not exist")

    if path.suffix.lower() in (".txt", ".md"):
        return path.read_text(errors="replace")

    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise SourceUnavailable(
                "Reading a PDF needs pypdf: pip install pypdf. Alternatively "
                "extract the text yourself and pass a .txt file."
            ) from exc
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)

    raise SourceUnavailable(
        f"Unsupported source type {path.suffix!r}; use .txt, .md or .pdf"
    )


def contains_excerpt(source: str, excerpt: str, *, min_length: int = 12) -> bool:
    """Is this excerpt actually in the source document?

    The guard that makes machine extraction trustworthy enough to review: a
    value whose quoted authority does not appear in the document it claims to
    come from is a fabrication, and is rejected before a human ever sees it.
    """
    if not excerpt or len(excerpt.strip()) < min_length:
        return False
    return normalize(excerpt).lower() in normalize(source).lower()
