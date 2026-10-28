from fastapi.testclient import TestClient
from pathlib import Path
import pytest

from app import config
from app.main import app


client = TestClient(app)


def test_health_and_page():
    assert client.get("/health").json() == {"status": "ok"}
    page = client.get("/")
    assert page.status_code == 200
    assert "Start Recording" in page.text
    assert client.get("/static/app.js").status_code == 200


def test_transcription_languages(monkeypatch, wav_bytes):
    calls = []
    def mock_transcribe(samples, language):
        calls.append((language, len(samples)))
        return "你好" if language == "zh" else "hello"
    monkeypatch.setattr("app.main.recognizer.transcribe", mock_transcribe)
    for language, expected in (("zh", "你好"), ("en", "hello")):
        response = client.post("/api/transcribe", data={"language": language}, files={"file": ("voice.wav", wav_bytes(), "audio/wav")})
        assert response.status_code == 200
        body = response.json()
        assert body["text"] == expected
        assert body["language"] == language
        assert 0.49 < body["duration_seconds"] < 0.51
        assert body["processing_seconds"] >= 0
    assert calls == [("zh", 8000), ("en", 8000)]


@pytest.mark.parametrize("filename", ["recording.webm", "recording.weba"])
def test_browser_mediarecorder_file_uses_same_api(monkeypatch, filename):
    monkeypatch.setattr("app.main.recognizer.transcribe", lambda samples, language: "browser audio")
    path = Path(__file__).parent / "fixtures" / "browser-recorded.webm"
    response = client.post("/api/transcribe", data={"language": "en"}, files={"file": (filename, path.read_bytes(), "audio/webm")})
    assert response.status_code == 200
    assert response.json()["text"] == "browser audio"
    assert response.json()["duration_seconds"] > 10


def test_invalid_fields(monkeypatch, wav_bytes):
    for data, files in (({}, {}), ({"language": "xx"}, {"file": ("x.wav", wav_bytes())}), ({"language": "zh"}, {})):
        assert client.post("/api/transcribe", data=data, files=files).status_code == 422


def test_invalid_audio_and_format(monkeypatch):
    for filename, payload, status in (("voice.wav", b"", 400), ("voice.wav", b"garbage", 400), ("voice.mp3", b"garbage", 415)):
        response = client.post("/api/transcribe", data={"language": "zh"}, files={"file": (filename, payload)})
        assert response.status_code == status
        assert response.json()["detail"]


def test_upload_limit(monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 8)
    response = client.post("/api/transcribe", data={"language": "en"}, files={"file": ("x.wav", b"ninebytes")})
    assert response.status_code == 413


def test_model_missing(monkeypatch, wav_bytes):
    from app.asr import ModelUnavailable
    def unavailable(*args):
        raise ModelUnavailable("model missing")
    monkeypatch.setattr("app.main.recognizer.transcribe", unavailable)
    response = client.post("/api/transcribe", data={"language": "zh"}, files={"file": ("x.wav", wav_bytes())})
    assert response.status_code == 503
    assert response.json()["detail"] == "model missing"


def test_inference_failure(monkeypatch, wav_bytes):
    def failed(*args):
        raise RuntimeError("internal secret")
    monkeypatch.setattr("app.main.recognizer.transcribe", failed)
    response = client.post("/api/transcribe", data={"language": "zh"}, files={"file": ("x.wav", wav_bytes())})
    assert response.status_code == 500
    assert "internal secret" not in response.text


def test_empty_transcript_is_valid(monkeypatch, wav_bytes):
    monkeypatch.setattr("app.main.recognizer.transcribe", lambda *args: "")
    response = client.post("/api/transcribe", data={"language": "en"}, files={"file": ("x.wav", wav_bytes(amplitude=0))})
    assert response.status_code == 200
    assert response.json()["text"] == ""
