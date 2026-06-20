# Phase 3b — Document Input Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin drop a `.txt`/`.docx`/digital `.pdf` and have its text injected (whole-doc) into the announcement as a toggleable input that combines with the existing sources.

**Architecture:** A new `documents.py` isolates all file-format knowledge (validate → extract → normalize → size-cap), raising `DocumentError` with admin-facing messages. The pipeline gains an optional `document_text` that, when present, is appended as one more context fragment — so the engine/pipeline stay format-blind. The console gets an upload + a document toggle that combines with the source toggles; the CLI gets `--document`.

**Tech Stack:** Python 3.11+ (uv), python-docx, pypdf, python-multipart, FastAPI, pytest, ruff. Run commands with `uv --directory cloud run ...` (do NOT `cd` into cloud).

---

## File Structure

```
cloud/cito/documents.py    (new)  extract_text(), normalize_text(), document_fragment(), DocumentError
cloud/cito/pipeline.py     (mod)  generate_announcement(source_keys, voice=None, document_text="")
cloud/cito/web/app.py      (mod)  POST /upload; document_text on GenerateRequest/PreviewRequest
cloud/cito/web/index.html  (mod)  Document fieldset: upload + toggle + clear; thread document_text
cloud/cito/run.py          (mod)  --document PATH
cloud/pyproject.toml       (mod)  + python-docx, pypdf, python-multipart
cloud/tests/test_documents.py (new)
cloud/tests/test_pipeline.py  (mod)  document_text threading
cloud/tests/test_web.py       (mod)  /upload + /generate document_text
```

---

## Task 1: Add dependencies

**Files:**
- Modify: `cloud/pyproject.toml`

- [ ] **Step 1: Add the three runtime deps**

In `cloud/pyproject.toml`, in `[project].dependencies`, add `python-docx`, `pypdf`, and `python-multipart` so the list reads:
```toml
dependencies = [
    "httpx",
    "python-dotenv",
    "gTTS",
    "yfinance",
    "fastapi",
    "uvicorn",
    "python-docx",
    "pypdf",
    "python-multipart",
]
```

- [ ] **Step 2: Sync and verify imports**

Run:
```bash
uv --directory cloud sync
uv --directory cloud run python -c "import docx, pypdf, multipart; print('ok')"
```
Expected: `ok` (the import name for python-docx is `docx`; for python-multipart it is `multipart`).

- [ ] **Step 3: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/pyproject.toml cloud/uv.lock
git commit -m "Add doc deps: python-docx, pypdf, python-multipart"
```

---

## Task 2: documents.py — extraction module

**Files:**
- Create: `cloud/cito/documents.py`
- Test: `cloud/tests/test_documents.py`

- [ ] **Step 1: Write the failing tests**

Create `cloud/tests/test_documents.py`:
```python
import io

import pytest

from cito import documents
from cito.documents import DocumentError, document_fragment, extract_text, normalize_text


def test_normalize_collapses_whitespace_and_strips_control_chars():
    assert normalize_text("a\x00b\n\n   c\t d") == "ab c d"


def test_extract_txt():
    assert extract_text("memo.txt", b"Picnic on Friday at noon.") == "Picnic on Friday at noon."


def test_extract_docx_reads_paragraphs():
    from docx import Document
    d = Document()
    d.add_paragraph("Hello team.")
    d.add_paragraph("Meeting at noon.")
    buf = io.BytesIO()
    d.save(buf)
    out = extract_text("memo.docx", buf.getvalue())
    assert "Hello team." in out
    assert "Meeting at noon." in out


def test_extract_pdf_digital(monkeypatch):
    class FakePage:
        def extract_text(self):
            return "Quarterly results are strong."

    class FakeReader:
        def __init__(self, *a, **k):
            self.pages = [FakePage()]

    monkeypatch.setattr("cito.documents.PdfReader", FakeReader)
    assert "Quarterly results are strong." in extract_text("r.pdf", b"%PDF-fake")


def test_scanned_pdf_rejected(monkeypatch):
    class BlankPage:
        def extract_text(self):
            return ""

    class FakeReader:
        def __init__(self, *a, **k):
            self.pages = [BlankPage()]

    monkeypatch.setattr("cito.documents.PdfReader", FakeReader)
    with pytest.raises(DocumentError, match="scan"):
        extract_text("scan.pdf", b"%PDF-fake")


def test_unsupported_extension_rejected():
    with pytest.raises(DocumentError, match="Unsupported"):
        extract_text("evil.exe", b"data")


def test_oversize_bytes_rejected():
    big = b"x" * (documents.MAX_UPLOAD_BYTES + 1)
    with pytest.raises(DocumentError, match="too large"):
        extract_text("big.txt", big)


def test_over_char_cap_rejected():
    big_text = ("word " * (documents.MAX_DOC_CHARS)).encode("utf-8")
    with pytest.raises(DocumentError, match="too long"):
        extract_text("long.txt", big_text)


def test_empty_document_rejected():
    with pytest.raises(DocumentError, match="empty"):
        extract_text("blank.txt", b"   ")


def test_document_fragment_wraps_text():
    frag = document_fragment("All-hands at 3pm Thursday.")
    assert "All-hands at 3pm Thursday." in frag
    assert "summarize" in frag.lower()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv --directory cloud run pytest tests/test_documents.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cito.documents'`.

- [ ] **Step 3: Implement**

Create `cloud/cito/documents.py`:
```python
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv --directory cloud run pytest tests/test_documents.py -v`
Expected: 10 PASS. Then `uv --directory cloud run ruff check .` → clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/documents.py cloud/tests/test_documents.py
git commit -m "Add document extraction pipeline (txt/docx/pdf + guards)"
```

---

## Task 3: Thread document_text through the pipeline

**Files:**
- Modify: `cloud/cito/pipeline.py`
- Test: `cloud/tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Append to `cloud/tests/test_pipeline.py`:
```python
def test_generate_announcement_appends_document_fragment(monkeypatch):
    captured = {}

    def fake_generate_script(fragments, voice=""):
        captured["fragments"] = fragments
        return "ok"

    monkeypatch.setattr("cito.pipeline.SOURCES", {})
    monkeypatch.setattr("cito.pipeline.generate_script", fake_generate_script)
    monkeypatch.setattr("cito.pipeline.config.load_config", lambda: {"voice": "", "preset": "Friendly"})
    from cito import pipeline
    pipeline.generate_announcement([], document_text="Quarterly memo body.")
    assert any("Quarterly memo body." in f for f in captured["fragments"])


def test_generate_announcement_ignores_blank_document(monkeypatch):
    captured = {}

    def fake_generate_script(fragments, voice=""):
        captured["fragments"] = fragments
        return "ok"

    monkeypatch.setattr("cito.pipeline.SOURCES", {})
    monkeypatch.setattr("cito.pipeline.generate_script", fake_generate_script)
    monkeypatch.setattr("cito.pipeline.config.load_config", lambda: {"voice": "", "preset": "Friendly"})
    from cito import pipeline
    pipeline.generate_announcement([], document_text="   ")
    assert captured["fragments"] == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv --directory cloud run pytest tests/test_pipeline.py -k document -v`
Expected: FAIL (`generate_announcement` takes no `document_text`).

- [ ] **Step 3: Implement**

In `cloud/cito/pipeline.py`:

(a) Change `from cito import audio, config, tts` to:
```python
from cito import audio, config, documents, tts
```

(b) Replace the `generate_announcement` function with:
```python
def generate_announcement(
    source_keys: list[str], voice: str | None = None, document_text: str = ""
) -> str:
    """Combine toggled sources (and an optional document) into a clean script.

    `voice` overrides the saved personality; when None, the saved voice is loaded.
    `document_text` is already-extracted text — when present it is added as one
    more context fragment.
    """
    if voice is None:
        voice = config.load_config().get("voice", "")
    fragments = []
    for key in source_keys:
        source = SOURCES.get(key)
        if source is None:
            continue
        try:
            data = source.fetch()
            fragments.append(source.prompt_fragment(data))
        except Exception:  # a flaky source must not sink the whole announcement
            continue
    if document_text.strip():
        fragments.append(documents.document_fragment(document_text))
    return generate_script(fragments, voice=voice)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv --directory cloud run pytest tests/test_pipeline.py -v`
Expected: all PASS (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/pipeline.py cloud/tests/test_pipeline.py
git commit -m "Thread document_text into generate_announcement"
```

---

## Task 4: Console /upload endpoint + document_text on requests

**Files:**
- Modify: `cloud/cito/web/app.py`
- Test: `cloud/tests/test_web.py`

- [ ] **Step 1: Write the failing tests**

Append to `cloud/tests/test_web.py`:
```python
def test_upload_txt_returns_text():
    from fastapi.testclient import TestClient
    from cito.web import app as webapp
    client = TestClient(webapp.app)
    r = client.post("/upload", files={"file": ("memo.txt", b"Picnic on Friday.", "text/plain")})
    assert r.status_code == 200
    body = r.json()
    assert "Picnic on Friday." in body["text"]
    assert body["chars"] == len(body["text"])


def test_upload_bad_extension_400():
    from fastapi.testclient import TestClient
    from cito.web import app as webapp
    client = TestClient(webapp.app)
    r = client.post("/upload", files={"file": ("x.exe", b"data", "application/octet-stream")})
    assert r.status_code == 400


def test_generate_threads_document_text(monkeypatch):
    from fastapi.testclient import TestClient
    from cito.web import app as webapp
    monkeypatch.setattr(
        "cito.web.app.pipeline.generate_announcement",
        lambda sources, voice=None, document_text="": f"DOC[{document_text}]",
    )
    client = TestClient(webapp.app)
    r = client.post("/generate", json={"sources": [], "document_text": "hello"})
    assert r.json()["text"] == "DOC[hello]"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv --directory cloud run pytest tests/test_web.py -k "upload or document" -v`
Expected: FAIL (`/upload` route and `document_text` field don't exist).

- [ ] **Step 3: Implement**

In `cloud/cito/web/app.py`:

(a) Change the FastAPI import line to add `UploadFile`, and add `documents` to the cito import:
```python
from fastapi import FastAPI, HTTPException, UploadFile
```
```python
from cito import config, documents, pipeline
```

(b) Add `document_text` to both request models:
```python
class GenerateRequest(BaseModel):
    sources: list[str] = []
    document_text: str = ""


class PreviewRequest(BaseModel):
    sources: list[str] = []
    voice: str = ""
    document_text: str = ""
```

(c) Replace the `/generate` and `/preview` route bodies to pass `document_text`:
```python
@app.post("/generate")
def generate(req: GenerateRequest) -> dict:
    return {"text": pipeline.generate_announcement(req.sources, document_text=req.document_text)}
```
```python
@app.post("/preview")
def preview(req: PreviewRequest) -> dict:
    return {"text": pipeline.generate_announcement(
        req.sources, voice=req.voice, document_text=req.document_text)}
```

(d) Add the upload route after `/preview`:
```python
@app.post("/upload")
async def upload(file: UploadFile) -> dict:
    data = await file.read()
    try:
        text = documents.extract_text(file.filename or "", data)
    except documents.DocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"text": text, "chars": len(text), "filename": file.filename}
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv --directory cloud run pytest tests/test_web.py -v`
Expected: all PASS (existing + 3 new). Then `uv --directory cloud run ruff check .` → clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/web/app.py cloud/tests/test_web.py
git commit -m "Add /upload endpoint and document_text on generate/preview"
```

---

## Task 5: Console UI — document upload + toggle

**Files:**
- Modify: `cloud/cito/web/index.html`

- [ ] **Step 1: Add the Document fieldset**

In `cloud/cito/web/index.html`, insert this block immediately AFTER the Data pipelines `</fieldset>` (the one containing the Weather/Stocks checkboxes) and BEFORE the Voice/personality `<fieldset>`:
```html
  <fieldset>
    <legend>Document</legend>
    <input type="file" id="doc-file" accept=".txt,.docx,.pdf" />
    <button id="doc-load">Load document</button>
    <span id="doc-toggle-wrap" style="display:none;">
      <label><input type="checkbox" id="doc-include" checked /> <span id="doc-name"></span></label>
      <button id="doc-clear">Clear</button>
    </span>
    <div id="doc-status" style="margin-top:.4rem; color:#555;"></div>
  </fieldset>
```

- [ ] **Step 2: Add the document JavaScript**

In the `<script>`, immediately AFTER the `loadConfig();` line, add:
```javascript
    // --- document upload ---
    let DOC_TEXT = "";
    function docIncluded() { return DOC_TEXT && $("doc-include").checked; }
    $("doc-load").onclick = async () => {
      const f = $("doc-file").files[0];
      if (!f) { $("doc-status").textContent = "Choose a file first."; return; }
      $("doc-status").textContent = "Loading " + f.name + "...";
      const fd = new FormData(); fd.append("file", f);
      const r = await fetch("/upload", { method: "POST", body: fd });
      if (!r.ok) {
        DOC_TEXT = "";
        $("doc-toggle-wrap").style.display = "none";
        $("doc-status").textContent = "Rejected: " + ((await r.json()).detail || "upload failed");
        return;
      }
      const data = await r.json();
      DOC_TEXT = data.text;
      $("doc-name").textContent = "Document: " + data.filename + " (" + data.chars + " chars)";
      $("doc-include").checked = true;
      $("doc-toggle-wrap").style.display = "inline";
      $("doc-status").textContent = "Loaded.";
    };
    $("doc-clear").onclick = () => {
      DOC_TEXT = "";
      $("doc-toggle-wrap").style.display = "none";
      $("doc-file").value = "";
      $("doc-status").textContent = "Document cleared.";
    };
```

- [ ] **Step 3: Make Generate and Preview include the document**

Replace the existing `$("generate").onclick = async () => { ... };` handler with:
```javascript
    $("generate").onclick = async () => {
      const sources = selectedSources();
      const document_text = docIncluded() ? DOC_TEXT : "";
      if (sources.length === 0 && !document_text) {
        status("Tick a source or load a document first."); return;
      }
      status("Generating...");
      try {
        const r = await fetch("/generate", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ sources, document_text }),
        });
        const data = await r.json();
        $("text").value = data.text;
        status("Generated. Edit if you like, then Send.");
      } catch (e) { status("Generate failed: " + e); }
    };
```
And replace the existing `$("preview").onclick = async () => { ... };` handler with:
```javascript
    $("preview").onclick = async () => {
      const sources = selectedSources();
      const document_text = docIncluded() ? DOC_TEXT : "";
      if (sources.length === 0 && !document_text) {
        status("Tick a source or load a document to preview."); return;
      }
      status("Previewing...");
      const r = await fetch("/preview", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ sources, voice: $("voice").value, document_text }),
      });
      const data = await r.json();
      $("preview-out").textContent = "Preview: " + data.text;
      status("Preview ready (not sent).");
    };
```

- [ ] **Step 4: Smoke-test the page + upload route**

Run (one command so the server doesn't outlive the call):
```bash
cd /Users/dwightbritton/Desktop/Cito
uv --directory cloud run uvicorn cito.web.app:app --port 8012 & SRV=$!
sleep 4
curl -s -o /dev/null -w "GET / -> %{http_code}\n" http://127.0.0.1:8012/
printf 'Picnic on Friday.' > /tmp/memo.txt
curl -s -w "\n/upload -> ok\n" -F "file=@/tmp/memo.txt" http://127.0.0.1:8012/upload | head -c 200
kill $SRV
```
Expected: `GET / -> 200` and an `/upload` JSON body containing `"Picnic on Friday."` and `"chars"`.

- [ ] **Step 5: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/web/index.html
git commit -m "Add document upload + toggle to the console"
```

---

## Task 6: CLI --document

**Files:**
- Modify: `cloud/cito/run.py`

- [ ] **Step 1: Add the flag and wire it in**

In `cloud/cito/run.py`:

(a) Add this argument after the `--voice` argument:
```python
    ann.add_argument("--document", help="path to a .txt/.docx/.pdf to base the announcement on")
```

(b) Replace the `if args.message ... else: ...` block (the generation branch) with:
```python
    if args.message and args.message.strip():
        text = args.message
    else:
        document_text = ""
        if args.document:
            from cito import documents
            try:
                with open(args.document, "rb") as f:
                    document_text = documents.extract_text(args.document, f.read())
            except documents.DocumentError as exc:
                parser.error(str(exc))
            except OSError as exc:
                parser.error(f"could not read {args.document}: {exc}")
        if not args.sources and not document_text:
            parser.error("provide --message, --document, or at least one --source")
        text = pipeline.generate_announcement(
            args.sources, voice=args.voice, document_text=document_text)
```

- [ ] **Step 2: Verify it runs (no send)**

Run:
```bash
cd /Users/dwightbritton/Desktop/Cito
printf 'The office picnic is this Friday at noon in the courtyard.' > /tmp/memo.txt
uv --directory cloud run python -m cito.run announce --document /tmp/memo.txt --print 2>&1 | tail -2
```
Expected: a `Script:` line referencing the picnic (Gemma-generated if the key is set, else the template fallback) with no error.

- [ ] **Step 3: Run full suite + lint**

Run:
```bash
uv --directory cloud run ruff check . && uv --directory cloud run pytest -q
```
Expected: ruff clean; all tests green.

- [ ] **Step 4: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add cloud/cito/run.py
git commit -m "Add --document to the CLI"
```

---

## Task 7: Live verification + README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Verify each format end to end (CLI, no send)**

Run:
```bash
cd /Users/dwightbritton/Desktop/Cito
printf 'All-hands meeting Thursday at 3pm in the main hall. Bring your laptops.' > /tmp/memo.txt
uv --directory cloud run python -m cito.run announce --document /tmp/memo.txt --print 2>&1 | tail -2
uv --directory cloud run python -m cito.run announce --source weather --document /tmp/memo.txt --print 2>&1 | tail -2
```
Expected: the first prints an announcement about the all-hands; the second combines weather + the memo into one announcement. (If Gemma is unavailable it falls back to the template — still a valid announceable line.)

- [ ] **Step 2: Update the README**

In `README.md`, under "Running the Phase 1 console", after the voice paragraph, add:
```markdown
Drop in a **document** (.txt / .docx / digital .pdf) to base an announcement on it: in
the console click **Load document** — it appears as a toggle alongside Weather/Stocks and
combines into one announcement. The CLI accepts `--document path/to/file`. Scanned PDFs
and over-long documents are rejected with a clear message.
```

- [ ] **Step 3: Commit**

```bash
cd /Users/dwightbritton/Desktop/Cito
git add README.md
git commit -m "Document the document-input feature"
```

---

## Exit Criteria (verify all)

- [ ] A `.txt`, a `.docx`, and a digital `.pdf` each produce a spoken announcement of their content (CLI `--print` or console), played in VLC.
- [ ] A scanned/image PDF (no text layer) is rejected with the "may be a scan" message.
- [ ] A document over the char cap is rejected with the "too long for now" message.
- [ ] In the console, the document toggle combines with Weather/Stocks into one announcement; unticking it leaves the document out.
- [ ] `uv --directory cloud run pytest -q` all green; `ruff check .` clean.
