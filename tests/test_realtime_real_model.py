import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.audio import decode_audio
from app.config import ROOT, SAMPLE_RATE
from app.main import app
from tests.test_realtime import receive_until, send_pcm


@pytest.mark.real_model
@pytest.mark.parametrize("language,filename", [("zh", "chinese.wav"), ("en", "english.wav")])
def test_real_streaming_chinese_and_english_before_stop(language, filename):
    path = ROOT / "samples" / filename
    audio = decode_audio(path.read_bytes(), filename)
    pcm = (np.clip(audio.samples, -1, 1) * 32767).astype("<i2").tobytes()
    with TestClient(app).websocket_connect("/api/realtime") as websocket:
        websocket.send_json({"type": "start", "language": language, "sample_rate": SAMPLE_RATE, "format": "pcm_s16le"})
        assert websocket.receive_json()["type"] == "ready"
        send_pcm(websocket, pcm[:SAMPLE_RATE * 2 * 8])
        first = receive_until(websocket, "segment")[-1]
        assert first["text"].strip(), "Expected real text before stop"
        send_pcm(websocket, pcm[SAMPLE_RATE * 2 * 8:])
        websocket.send_json({"type": "stop"})
        final = receive_until(websocket, "final")[-1]
        assert final["text"].strip()
        assert ("语音" in final["text"]) if language == "zh" else ("speech recognition" in final["text"].lower())
        assert final["duration_seconds"] == pytest.approx(audio.duration_seconds, abs=0.02)
        assert len(final["text"]) > len(first["text"])
        print(f"realtime {language}: {final['text']} | {final['processing_seconds']} s inference")
