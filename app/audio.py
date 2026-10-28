"""Bounded, shared audio decoding for uploads and browser recordings."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import av
import numpy as np

from app.config import MAX_AUDIO_SECONDS, SAMPLE_RATE, SUPPORTED_EXTENSIONS


class AudioError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class DecodedAudio:
    samples: np.ndarray
    duration_seconds: float


def decode_audio(data: bytes, filename: str) -> DecodedAudio:
    if not data:
        raise AudioError("音频文件为空。")
    if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise AudioError("不支持的音频格式；请上传 WAV、WebM（.webm / .weba）或 OGG。", 415)

    try:
        with av.open(BytesIO(data), mode="r") as container:
            if not any(name in container.format.name.split(",") for name in ("wav", "matroska", "webm", "ogg")):
                raise AudioError("音频容器格式不受支持。", 415)
            streams = [stream for stream in container.streams if stream.type == "audio"]
            if len(streams) != 1:
                raise AudioError("文件必须只包含一条有效音轨。")
            stream = streams[0]
            if stream.codec_context.name not in {"pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_u8", "opus", "vorbis"}:
                raise AudioError("音频编码不受支持。", 415)

            resampler = av.audio.resampler.AudioResampler(format="fltp", layout="mono", rate=SAMPLE_RATE)
            chunks: list[np.ndarray] = []
            source_duration = 0.0
            output_samples = 0
            for frame in container.decode(stream):
                source_duration += frame.samples / frame.sample_rate
                if source_duration > MAX_AUDIO_SECONDS + 1e-6:
                    raise AudioError(f"音频时长不能超过 {MAX_AUDIO_SECONDS} 秒。")
                for output in resampler.resample(frame):
                    part = output.to_ndarray().reshape(-1).copy()
                    chunks.append(part)
                    output_samples += len(part)
                    if output_samples > SAMPLE_RATE * (MAX_AUDIO_SECONDS + 1):
                        raise AudioError(f"音频时长不能超过 {MAX_AUDIO_SECONDS} 秒。")
            for output in resampler.resample(None):
                part = output.to_ndarray().reshape(-1).copy()
                chunks.append(part)
                output_samples += len(part)
            if not chunks or output_samples == 0 or source_duration <= 0:
                raise AudioError("文件中没有可解码的音频。")
            if source_duration > MAX_AUDIO_SECONDS + 1e-6:
                raise AudioError(f"音频时长不能超过 {MAX_AUDIO_SECONDS} 秒。")
            samples = np.concatenate(chunks)
            return DecodedAudio(samples=samples, duration_seconds=source_duration)
    except AudioError:
        raise
    except (av.FFmpegError, ValueError, OSError, OverflowError, ZeroDivisionError) as exc:
        raise AudioError("音频无法解码，请检查文件是否损坏或格式是否正确。") from exc


def split_audio(samples: np.ndarray, max_seconds: int = 20) -> list[np.ndarray]:
    """Prefer low-energy 0.1s boundaries near 20s to avoid arbitrary word cuts."""
    chunk_size = max_seconds * SAMPLE_RATE
    if len(samples) <= chunk_size:
        return [samples]
    result: list[np.ndarray] = []
    start = 0
    window = SAMPLE_RATE // 10
    while len(samples) - start > chunk_size:
        center = start + chunk_size
        low = max(start + SAMPLE_RATE * 15, center - SAMPLE_RATE * 2)
        high = min(len(samples) - window, center + SAMPLE_RATE * 2)
        candidates = range(low, high + 1, window)
        boundary = min(candidates, key=lambda index: float(np.mean(samples[index:index + window] ** 2)))
        result.append(samples[start:boundary])
        start = boundary
    result.append(samples[start:])
    return result
