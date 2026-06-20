"""One-page dev console over the headless pipeline."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from cito import pipeline

app = FastAPI(title="Cito Console")
_INDEX = Path(__file__).parent / "index.html"


class GenerateRequest(BaseModel):
    sources: list[str] = []


class SendRequest(BaseModel):
    text: str


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _INDEX.read_text()


@app.post("/generate")
def generate(req: GenerateRequest) -> dict:
    return {"text": pipeline.generate_announcement(req.sources)}


@app.post("/send")
def send(req: SendRequest) -> dict:
    try:
        result = pipeline.send_announcement(req.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "packets": result.packets}
