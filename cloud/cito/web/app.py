"""One-page dev console over the headless pipeline."""

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from cito import announcements, config, documents, pipeline, scheduler
from cito.announcements import AnnouncementError, AnnouncementNotFound

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield


app = FastAPI(title="Cito Console", lifespan=lifespan)
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


class CalendarRequest(BaseModel):
    url: str = ""


class AnnouncementBody(BaseModel):
    name: str = ""
    kind: str = "sources"
    sources: list[str] = []
    message: str = ""
    time: str = ""
    days: list[str] = []


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
            "presets": config.PRESETS, "calendar_url": cfg.get("calendar_url", "")}


@app.post("/voice")
def save_voice(req: VoiceRequest) -> dict:
    saved = config.save_config({"voice": req.voice, "preset": req.preset})
    return {"ok": True, **saved}


@app.post("/calendar")
def save_calendar(req: CalendarRequest) -> dict:
    url = req.url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Enter a valid http(s) calendar feed URL.")
    saved = config.save_config({"calendar_url": url})
    return {"ok": True, "calendar_url": saved["calendar_url"]}


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


@app.get("/announcements")
def list_announcements() -> list:
    return announcements.list_announcements()


@app.post("/announcements")
def create_announcement(body: AnnouncementBody) -> dict:
    try:
        rec = announcements.create(body.model_dump())
    except AnnouncementError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    scheduler.reschedule(rec)
    return rec


@app.put("/announcements/{ann_id}")
def update_announcement(ann_id: str, body: AnnouncementBody) -> dict:
    try:
        rec = announcements.update(ann_id, body.model_dump())
    except AnnouncementNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AnnouncementError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    scheduler.reschedule(rec)
    return rec


@app.delete("/announcements/{ann_id}")
def delete_announcement(ann_id: str) -> dict:
    try:
        announcements.delete(ann_id)
    except AnnouncementNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    scheduler.unschedule(ann_id)
    return {"ok": True}


@app.post("/announcements/{ann_id}/run")
def run_announcement_now(ann_id: str) -> dict:
    try:
        rec = announcements.get(ann_id)
    except AnnouncementNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "text": scheduler.run_announcement(rec)}


@app.get("/announcements-ui", response_class=HTMLResponse)
def announcements_ui() -> str:
    return (Path(__file__).parent / "announcements.html").read_text()
