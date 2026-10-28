"""Local SenseVoice ONNX inference; recognizers are cached per language."""

import threading
import unicodedata

import numpy as np

from app.config import MAX_CHUNK_SECONDS, MODEL_FILE, SAMPLE_RATE, TOKENS_FILE
from app.audio import split_audio


class ModelUnavailable(RuntimeError):
    pass


class SpeechRecognizer:
    def __init__(self) -> None:
        self._recognizers: dict[str, object] = {}
        self._lock = threading.Lock()

    def _get_recognizer(self, language: str):
        if language not in {"zh", "en"}:
            raise ValueError("language must be zh or en")
        if language not in self._recognizers:
            if not MODEL_FILE.is_file() or not TOKENS_FILE.is_file():
                raise ModelUnavailable("本地模型尚未准备好。请先按 README 运行模型初始化命令。")
            try:
                import sherpa_onnx

                self._recognizers[language] = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=str(MODEL_FILE),
                    tokens=str(TOKENS_FILE),
                    language=language,
                    use_itn=True,
                    num_threads=3,
                    provider="cpu",
                )
            except Exception as exc:
                raise ModelUnavailable("本地语音模型加载失败，请检查模型文件和安装环境。") from exc
        return self._recognizers[language]

    def transcribe(self, samples: np.ndarray, language: str) -> str:
        with self._lock:
            recognizer = self._get_recognizer(language)
            texts: list[str] = []
            for part in split_audio(samples, MAX_CHUNK_SECONDS):
                if not len(part) or float(np.max(np.abs(part))) < 0.002:
                    continue
                stream = recognizer.create_stream()
                stream.accept_waveform(SAMPLE_RATE, part)
                recognizer.decode_stream(stream)
                text = stream.result.text.strip()
                if text and any(not unicodedata.category(character).startswith(("P", "Z")) for character in text):
                    texts.append(text)
            return ("" if language == "zh" else " ").join(texts)

    def prepare(self, language: str) -> None:
        """Load and validate the language model before real-time capture starts."""
        with self._lock:
            self._get_recognizer(language)


recognizer = SpeechRecognizer()
