"""FastAPI endpoints for local speech-to-text."""

import logging
import time

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.asr import ModelUnavailable, recognizer
from app.audio import AudioError, decode_audio
from app.realtime import router as realtime_router

logger = logging.getLogger(__name__)
app = FastAPI(title="Local AI Speech-to-Text")
app.include_router(realtime_router)
app.mount("/static", StaticFiles(directory=config.STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(config.STATIC / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


def _transcribe(data: bytes, filename: str, language: str, started: float) -> dict:
    audio = decode_audio(data, filename)
    text = recognizer.transcribe(audio.samples, language)
    return {
        "text": text,
        "language": language,
        "duration_seconds": round(audio.duration_seconds, 2),
        "processing_seconds": round(time.perf_counter() - started, 3),
    }


@app.post("/api/transcribe")
async def transcribe(file: UploadFile = File(...), language: str = Form(...)):
    started = time.perf_counter()
    if language not in {"zh", "en"}:
        raise HTTPException(422, detail="语言必须是 zh 或 en。")
    try:
        # Bound the read even when Content-Length is absent or untrusted.
        data = await file.read(config.MAX_UPLOAD_BYTES + 1)
        if len(data) > config.MAX_UPLOAD_BYTES:
            raise HTTPException(413, detail="音频文件不能超过 10 MiB。")
        return await run_in_threadpool(_transcribe, data, file.filename or "", language, started)
    except AudioError as exc:
        raise HTTPException(exc.status_code, detail=str(exc)) from exc
    except ModelUnavailable as exc:
        raise HTTPException(503, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Local ASR inference failed")
        raise HTTPException(500, detail="识别失败，请稍后重试或检查本地模型。") from exc
    finally:
        await file.close()
