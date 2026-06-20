"""One-page dev console over the headless pipeline."""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from cito import config, documents, pipeline

load_dotenv()
app = FastAPI(title="Cito Console")
_INDEX = Path(__file__).parent / "index.html"


class GenerateRequest(BaseModel):
    sources: list[str] = []
    document_text: str = ""


class SendRequest(BaseModel):
    text: str


class VoiceRequest(BaseModel):
    voice: str = ""
    preset: str = ""


class PreviewRequest(BaseModel):
    sources: list[str] = []
    voice: str = ""
    document_text: str = ""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX.read_text()


@app.post("/generate")
def generate(req: GenerateRequest) -> dict:
    return {"text": pipeline.generate_announcement(req.sources, document_text=req.document_text)}


@app.post("/send")
def send(req: SendRequest) -> dict:
    try:
        result = pipeline.send_announcement(req.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "packets": result.packets}


@app.get("/config")
def get_config() -> dict:
    cfg = config.load_config()
    return {"voice": cfg.get("voice", ""), "preset": cfg.get("preset", config.DEFAULT_PRESET),
            "presets": config.PRESETS}


@app.post("/voice")
def save_voice(req: VoiceRequest) -> dict:
    saved = config.save_config({"voice": req.voice, "preset": req.preset})
    return {"ok": True, **saved}


@app.post("/preview")
def preview(req: PreviewRequest) -> dict:
    return {"text": pipeline.generate_announcement(
        req.sources, voice=req.voice, document_text=req.document_text)}


@app.post("/upload")
async def upload(file: UploadFile) -> dict:
    data = await file.read()
    try:
        text = documents.extract_text(file.filename or "", data)
    except documents.DocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"text": text, "chars": len(text), "filename": file.filename}
