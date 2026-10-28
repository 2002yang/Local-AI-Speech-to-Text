from pathlib import Path
from io import BytesIO
import wave

import pytest
from fastapi.testclient import TestClient

from app.config import MODEL_FILE, ROOT, TOKENS_FILE
from app.main import app


@pytest.mark.real_model
@pytest.mark.parametrize("language,filename", [("zh", "chinese.wav"), ("en", "english.wav")])
def test_real_chinese_and_english(language, filename):
    assert MODEL_FILE.is_file() and TOKENS_FILE.is_file(), "Run python -m scripts.download_model first"
    sample = ROOT / "samples" / filename
    with sample.open("rb") as audio:
        response = TestClient(app).post("/api/transcribe", data={"language": language}, files={"file": (filename, audio, "audio/wav")})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["language"] == language
    assert result["text"].strip(), "Expected real model to recognize spoken words"
    assert 5 <= result["duration_seconds"] <= 15
    print(f"{language}: {result['text']} (processing: {result['processing_seconds']} s)")


@pytest.mark.real_model
def test_long_audio_is_chunked_and_processed():
    assert MODEL_FILE.is_file() and TOKENS_FILE.is_file(), "Run python -m scripts.download_model first"
    with wave.open(str(ROOT / "samples" / "english.wav"), "rb") as source:
        rate, channels, width = source.getframerate(), source.getnchannels(), source.getsampwidth()
        speech = source.readframes(source.getnframes())
    payload = BytesIO()
    with wave.open(payload, "wb") as output:
        output.setframerate(rate)
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.writeframes((speech + b"\0" * (rate * channels * width // 2)) * 3)
    result = TestClient(app).post(
        "/api/transcribe", data={"language": "en"}, files={"file": ("long.wav", payload.getvalue(), "audio/wav")}
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert 30 < body["duration_seconds"] < 35
    assert body["text"].lower().count("speech recognition") >= 2
    print(f"long audio: {body['duration_seconds']} s, processed in {body['processing_seconds']} s")


@pytest.mark.real_model
def test_actual_browser_encoded_webm_with_local_model():
    assert MODEL_FILE.is_file() and TOKENS_FILE.is_file(), "Run python -m scripts.download_model first"
    sample = ROOT / "tests" / "fixtures" / "browser-recorded.webm"
    result = TestClient(app).post(
        "/api/transcribe", data={"language": "en"}, files={"file": (sample.name, sample.read_bytes(), "audio/webm")}
    )
    assert result.status_code == 200, result.text
    assert "speech recognition" in result.json()["text"].lower()
    print(f"browser WebM: {result.json()['text']}")
