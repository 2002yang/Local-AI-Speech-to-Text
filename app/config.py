"""Central limits and local-only model paths."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
MODEL_DIR = ROOT / "models" / "sensevoice-small-int8"
MODEL_FILE = MODEL_DIR / "model.int8.onnx"
TOKENS_FILE = MODEL_DIR / "tokens.txt"

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_AUDIO_SECONDS = 65
MAX_RECORDING_SECONDS = 60
SAMPLE_RATE = 16_000
MAX_CHUNK_SECONDS = 20
SUPPORTED_EXTENSIONS = {".wav", ".webm", ".weba", ".ogg"}
