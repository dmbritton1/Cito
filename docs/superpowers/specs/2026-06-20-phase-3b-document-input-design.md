# Phase 3b — Document Input Pipeline (Design)

**Date:** 2026-06-20
**Status:** Approved (building)
**Scope:** The second Phase 3 sub-project (spec §3.7) — drop in a `.txt`/`.docx`/digital
`.pdf`, extract it to clean text, and inject the whole document into the announcement
prompt as a toggleable context input that combines with the existing sources.

## Goal

Let an admin drop a document (a memo, an events list, a one-pager) and have Cito read out
an announcement based on it. The document is a first-class, **toggleable** input that
**combines** with weather/stocks into one announcement — not a separate "doc-only" mode.

## Approach

A dropped document becomes another **context fragment** feeding the same engine. All
file-format knowledge is isolated in one new module (`documents.py`); the pipeline and
engine stay format-blind — they only ever see already-extracted text.

```
upload file → documents.extract_text(filename, bytes) → clean text
            → documents.document_fragment(text)  ("Summarize this for a spoken announcement: …")
            → appended to the toggled source fragments → engine (Gemma + <say> + voice)
            → one combined announcement
```

This implements spec §3.7 Stages 1–4 + 6 (ingest/validate → extract → normalize → size
decision → whole-doc injection). Stage 5 (pgvector RAG) is deferred: over-cap documents are
rejected with a clear message.

## Decisions (locked during brainstorming)

| Decision | Choice |
|---|---|
| Formats | `.txt`, `.docx`, digital `.pdf` |
| Over-cap document | **Reject** with a clear message (RAG path deferred) |
| Retention | **Ephemeral** — upload, use, discard (no storage/library) |
| Integration | Toggleable input that **combines** with sources into one announcement |
| Scanned PDF | Flag back to the admin ("may be a scan"), no OCR |

## Components

### `cito/documents.py` (new — the only place that knows file formats)
- `ALLOWED_EXTS = {".txt", ".docx", ".pdf"}`, `MAX_UPLOAD_BYTES ≈ 5 MB`,
  `MAX_DOC_CHARS ≈ 6000` ("a page or two").
- `class DocumentError(ValueError)` — carries a human-readable message for the UI/CLI.
- `extract_text(filename: str, data: bytes) -> str`:
  1. Validate extension is in `ALLOWED_EXTS` (else `DocumentError`).
  2. Enforce `len(data) <= MAX_UPLOAD_BYTES` (else `DocumentError`).
  3. Route to the per-format extractor.
  4. `normalize_text` the result.
  5. Enforce `len(normalized) <= MAX_DOC_CHARS` (else `DocumentError`, "too long for now;
     large-document support is coming later").
  6. Return the normalized text.
- Per-format extractors (format knowledge isolated here):
  - `.txt` → `data.decode("utf-8", errors="replace")`.
  - `.docx` → `python-docx` reading paragraph text from `io.BytesIO(data)`.
  - `.pdf` → `pypdf` text-layer extraction across pages. **Digital-vs-scanned guard:** if
    the extracted text is empty/near-empty (< ~20 chars after normalize), raise
    `DocumentError("couldn't read this PDF — it may be a scan")`.
- `normalize_text(s) -> str`: strip control characters, collapse runs of whitespace,
  normalize to UTF-8, trim. After this the text is format-agnostic.
- `document_fragment(text: str) -> str`: wrap the text with summarize framing so the
  engine produces a short spoken announcement, e.g.
  `"Base the announcement on this document; summarize its key points: <text>"`.

### `cito/pipeline.py` (modify)
- `generate_announcement(source_keys, voice=None, document_text="")` — build the toggled
  source fragments as today; if `document_text.strip()`, append
  `documents.document_fragment(document_text)` to the fragments; then `generate_script`.
- The pipeline never imports a file-format library — it receives extracted text only.

### `cito/web/app.py` (modify)
- `POST /upload` (multipart `file`) → `documents.extract_text(file.filename, await file.read())`
  → `{"text": ..., "chars": len, "filename": ...}`; on `DocumentError` → **400** with the
  message.
- `GenerateRequest` and `PreviewRequest` gain `document_text: str = ""`, threaded into
  `generate_announcement(..., document_text=...)`.

### `cito/web/index.html` (modify)
- A file `<input>` + **Load document** button → `POST /upload`. On success, store the
  returned text in JS and show a **Document toggle** (a checkbox labelled
  `Document: <filename>`, checked by default) next to the Weather/Stocks toggles, plus a
  **Clear** control that removes it.
- Generate and Preview include `document_text` **only when the document toggle is ticked**.
  The existing source toggles + the document toggle combine into one announcement.

### `cito/run.py` (modify)
- `--document PATH` → read bytes → `documents.extract_text` → pass as `document_text` to
  `generate_announcement`. On `DocumentError`, exit with the clear message (no traceback).

## New dependencies

`python-docx`, `pypdf`, `python-multipart` (FastAPI multipart/file uploads).

## Data flow (combined doc + sources)

1. Admin ticks Weather, loads `events.docx` (toggle appears, ticked).
2. **Generate** → `/generate {sources:["weather"], document_text:"<events text>"}`.
3. Pipeline builds the weather fragment + the document fragment → `generate_script` →
   Gemma wraps the answer in `<say>` → extracted, cleaned → one announcement covering both.
4. **Send** → TTS → µ-law → RTP (unchanged).

## Error handling

- Unsupported extension / oversize bytes / scanned PDF / over-char-cap → `DocumentError`
  → `/upload` returns 400 with the message; CLI prints it and exits non-zero.
- A document that extracts but the model can't use → the engine's existing `<say>`/fallback
  path applies (defensive parsing unchanged).
- Empty/whitespace document text → treated as "no document" (not appended).

## Testing

- `extract_text`:
  - `.txt` bytes → expected text.
  - `.docx` built in-memory with `python-docx` → expected paragraph text.
  - `.pdf` digital → text (with `pypdf.PdfReader` mocked to return page text).
  - scanned/empty PDF (mocked to return no text) → `DocumentError`.
  - unsupported extension → `DocumentError`.
  - oversize bytes → `DocumentError`.
  - over-char-cap text → `DocumentError`.
- `normalize_text`: collapses whitespace, strips control characters.
- `document_fragment`: contains the document text and the summarize framing.
- `pipeline.generate_announcement`: with `document_text`, a document fragment is appended
  (assert via mocked `generate_script` capturing fragments); empty `document_text` appends
  nothing.
- web: `POST /upload` happy path (`.txt`) → `{text, chars, filename}`; bad extension → 400;
  `POST /generate` threads `document_text` into the pipeline (mocked).
- Existing tests stay green.

## Exit criteria

- Dropping a `.txt`, `.docx`, and a digital `.pdf` each produces a spoken announcement of
  the document's content, played in VLC.
- A scanned/image PDF is rejected with the "may be a scan" message (not silent empty).
- A document over the char cap is rejected with the clear "too long for now" message.
- The document toggle combines with Weather/Stocks into one announcement, and unticking it
  leaves the document out.
- `uv --directory cloud run pytest -q` all green; `ruff check .` clean.

## Deferred (per spec §3.7)

Stage 5 pgvector RAG / chunk-embed-retrieve (the reject path stands in for now), OCR for
scanned PDFs, a document library (storage/reuse/delete), per-document metadata persistence.
