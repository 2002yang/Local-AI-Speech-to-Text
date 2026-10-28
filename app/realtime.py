"""Bounded near-real-time PCM segmentation and WebSocket protocol.

This is short-segment offline inference, not native streaming or partial-token ASR.
"""

import asyncio
from collections import deque
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
import numpy as np

from app.asr import ModelUnavailable, recognizer
from app.config import MAX_RECORDING_SECONDS, SAMPLE_RATE

router = APIRouter()
logger = logging.getLogger(__name__)
FRAME_SAMPLES = SAMPLE_RATE // 10  # 100 ms analysis frames
MAX_MESSAGE_BYTES = SAMPLE_RATE  # at most 0.5 s int16 per binary message
QUEUE_LIMIT = 4


class StreamError(ValueError):
    pass


class Segmenter:
    """Energy-based activity gating, 0.2s preroll, 0.6s pause, max 4s.

    Silence detection is deliberately simple: noise is not reliably rejected.
    No active segment is overlapped with the next one or silently discarded.
    """

    def __init__(self) -> None:
        self.pending = np.empty(0, dtype=np.float32)
        self.preroll: deque[np.ndarray] = deque(maxlen=2)
        self.active: list[np.ndarray] = []
        self.silent_frames = 0

    def feed(self, samples: np.ndarray) -> list[np.ndarray]:
        self.pending = np.concatenate((self.pending, samples))
        segments = []
        while len(self.pending) >= FRAME_SAMPLES:
            frame = self.pending[:FRAME_SAMPLES].copy()
            self.pending = self.pending[FRAME_SAMPLES:]
            rms = float(np.sqrt(np.mean(frame ** 2)))
            audible = rms >= 0.0006
            if not self.active:
                if not audible:
                    self.preroll.append(frame)
                    continue
                self.active.extend(self.preroll)
                self.preroll.clear()
            self.active.append(frame)
            self.silent_frames = 0 if audible else self.silent_frames + 1
            if self.silent_frames >= 6:
                segments.append(np.concatenate(self.active))
                self.active.clear()
                self.silent_frames = 0
            elif len(self.active) >= 40:
                # Prefer a quiet boundary within the last second instead of
                # always slicing a phoneme at exactly four seconds.
                cut = min(range(30, 41), key=lambda index: (float(np.mean(self.active[index - 1] ** 2)), -index))
                segments.append(np.concatenate(self.active[:cut]))
                self.active = self.active[cut:]
                self.silent_frames = 0
                for tail in reversed(self.active):
                    if float(np.sqrt(np.mean(tail ** 2))) >= 0.0006:
                        break
                    self.silent_frames += 1
        return segments

    def finish(self) -> list[np.ndarray]:
        if len(self.pending):
            if self.active:
                self.active.append(self.pending.copy())
            elif float(np.max(np.abs(self.pending))) >= 0.002:
                self.active.extend(self.preroll)
                self.active.append(self.pending.copy())
        self.pending = np.empty(0, dtype=np.float32)
        self.preroll.clear()
        if not self.active:
            return []
        result = np.concatenate(self.active)
        self.active.clear()
        self.silent_frames = 0
        return [result]


@router.websocket("/api/realtime")
async def realtime(websocket: WebSocket) -> None:
    # Browser connections must originate from this same local application.
    origin = websocket.headers.get("origin")
    expected_origin = f"{'https' if websocket.url.scheme == 'wss' else 'http'}://{websocket.headers.get('host')}"
    if origin and origin.rstrip("/") != expected_origin:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    tasks: list[asyncio.Task] = []
    send_lock = asyncio.Lock()

    async def send(payload: dict) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=15)
        if len(raw) > 1024:
            raise StreamError("实时识别初始化消息过大。")
        try:
            start = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise StreamError("实时识别初始化消息必须是 JSON。") from exc
        if not isinstance(start, dict) or start.get("type") != "start":
            raise StreamError("请先发送 start 消息。")
        language = start.get("language")
        if not isinstance(language, str) or language not in {"zh", "en"}:
            raise StreamError("语言必须是 zh 或 en。")
        if start.get("sample_rate") != SAMPLE_RATE or start.get("format") != "pcm_s16le":
            raise StreamError("实时音频必须为 16000 Hz 单声道 PCM int16 little-endian。")

        await run_in_threadpool(recognizer.prepare, language)
        await send({"type": "ready", "language": language, "max_seconds": MAX_RECORDING_SECONDS})
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_LIMIT)
        segmenter = Segmenter()
        total_samples = 0
        captured: list[np.ndarray] = []  # bounded by 60 seconds (~3.84 MB float32)
        texts: list[str] = []
        processing_seconds = 0.0
        session_started = time.monotonic()

        def enqueue(parts: list[np.ndarray]) -> None:
            for part in parts:
                try:
                    queue.put_nowait(part)
                except asyncio.QueueFull as exc:
                    raise StreamError("识别处理跟不上录音，队列已满。此次录音已停止，请缩短录音或改用普通识别。") from exc

        async def receive_audio() -> None:
            nonlocal total_samples
            while True:
                remaining_wall_time = 75 - (time.monotonic() - session_started)
                if remaining_wall_time <= 0:
                    raise StreamError("实时会话超过允许时长，请重新开始录音。")
                message = await asyncio.wait_for(websocket.receive(), timeout=min(15, remaining_wall_time))
                if message["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect(message.get("code", 1000))
                payload = message.get("bytes")
                if payload is not None:
                    if not payload or len(payload) % 2 or len(payload) > MAX_MESSAGE_BYTES:
                        raise StreamError("PCM 音频分片无效或过大。")
                    samples = np.frombuffer(payload, dtype="<i2").astype(np.float32) / 32768.0
                    remaining = SAMPLE_RATE * MAX_RECORDING_SECONDS - total_samples
                    accepted = samples[:remaining]
                    captured.append(accepted)
                    total_samples += len(accepted)
                    enqueue(segmenter.feed(accepted))
                    if total_samples >= SAMPLE_RATE * MAX_RECORDING_SECONDS:
                        await send({"type": "limit", "message": "已达到 60 秒上限，正在完成最后一段。"})
                        break
                else:
                    text = message.get("text", "")
                    if len(text) > 1024:
                        raise StreamError("控制消息过大。")
                    try:
                        control = json.loads(text)
                    except (ValueError, TypeError) as exc:
                        raise StreamError("无效的实时识别控制消息。") from exc
                    if not isinstance(control, dict) or control.get("type") != "stop":
                        raise StreamError("实时录音只接受 PCM 分片或 stop 消息。")
                    break
            enqueue(segmenter.finish())
            await send({"type": "finishing", "message": "录音已停止，正在处理剩余音频。"})
            await queue.put(None)

        async def infer_segments() -> None:
            nonlocal processing_seconds
            sequence = 0
            while True:
                part = await queue.get()
                if part is None:
                    break
                sequence += 1
                await send({"type": "processing", "sequence": sequence})
                before = time.perf_counter()
                text = await run_in_threadpool(recognizer.transcribe, part, language)
                processing_seconds += time.perf_counter() - before
                if text:
                    texts.append(text)
                await send({
                    "type": "segment", "sequence": sequence, "text": text,
                    "full_text": ("" if language == "zh" else " ").join(texts),
                    "language": language, "duration_seconds": round(total_samples / SAMPLE_RATE, 2),
                    "processing_seconds": round(processing_seconds, 3),
                })
            final_text = ""
            if total_samples:
                # One final pass, not repeated whole-recording inference while
                # speaking. It restores context lost at short preview boundaries.
                await send({"type": "finalizing", "message": "分段已处理，正在校正整段最终文字。"})
                before = time.perf_counter()
                final_text = await run_in_threadpool(recognizer.transcribe, np.concatenate(captured), language)
                processing_seconds += time.perf_counter() - before
            await send({
                "type": "final", "text": final_text,
                "language": language, "duration_seconds": round(total_samples / SAMPLE_RATE, 2),
                "processing_seconds": round(processing_seconds, 3),
            })

        tasks = [asyncio.create_task(receive_audio()), asyncio.create_task(infer_segments())]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            task.result()
    except WebSocketDisconnect:
        pass
    except (StreamError, ModelUnavailable, asyncio.TimeoutError) as exc:
        message = str(exc) if not isinstance(exc, asyncio.TimeoutError) else "实时连接等待音频超时，请重新开始录音。"
        try:
            await send({"type": "error", "message": message})
        except (RuntimeError, WebSocketDisconnect):
            pass
    except Exception:
        logger.exception("Real-time ASR failed")
        try:
            await send({"type": "error", "message": "实时识别失败，请重试或使用普通识别。"})
        except (RuntimeError, WebSocketDisconnect):
            pass
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        try:
            await websocket.close()
        except (RuntimeError, WebSocketDisconnect):
            pass
