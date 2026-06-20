"""Document input pipeline: extract clean text from a dropped file.

All file-format knowledge lives here; everything downstream (pipeline, engine)
sees only already-extracted, normalized text. Implements spec 3.7 Stages 1-4 + 6.
The large-document RAG path (Stage 5) is deferred — over-cap docs are rejected.
"""

import io
import re
import unicodedata
from pathlib import Path

from docx import Document
from pypdf import PdfReader

ALLOWED_EXTS = {".txt", ".docx", ".pdf"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024   # 5 MB
MAX_DOC_CHARS = 6000                 # "a page or two"; larger => RAG path (deferred)
_MIN_PDF_TEXT_CHARS = 20             # below this, a PDF is probably a scan


class DocumentError(ValueError):
    """A dropped document could not be used; the message is admin-facing."""


def normalize_text(s: str) -> str:
    """Strip control characters, collapse whitespace, normalize to UTF-8."""
    s = unicodedata.normalize("NFKC", s)
    s = "".join(ch for ch in s if ch in "\n\t " or not unicodedata.category(ch).startswith("C"))
    return re.sub(r"\s+", " ", s).strip()


def _extract_txt(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _extract_docx(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


def _extract_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


_EXTRACTORS = {".txt": _extract_txt, ".docx": _extract_docx, ".pdf": _extract_pdf}


def extract_text(filename: str, data: bytes) -> str:
    """Validate, extract, normalize, and size-check a dropped document."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise DocumentError(f"Unsupported file type '{ext or filename}'. Use .txt, .docx, or .pdf.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentError("That file is too large (over 5 MB).")

    text = normalize_text(_EXTRACTORS[ext](data))

    if ext == ".pdf" and len(text) < _MIN_PDF_TEXT_CHARS:
        raise DocumentError("Couldn't read this PDF — it may be a scan (no text layer).")
    if not text:
        raise DocumentError("The document appears to be empty.")
    if len(text) > MAX_DOC_CHARS:
        raise DocumentError(
            f"This document is too long for now ({len(text)} characters); "
            "large-document support is coming later."
        )
    return text


def document_fragment(text: str) -> str:
    """Frame the document text for the engine as summarize-this context."""
    return (
        "Base the announcement on this document; summarize its key points "
        f"for a short spoken announcement: {text}"
    )
