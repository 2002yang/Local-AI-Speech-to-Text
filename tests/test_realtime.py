from types import SimpleNamespace

from fastapi.testclient import TestClient
import numpy as np
import pytest
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app import realtime
from app.config import SAMPLE_RATE


START = {"type": "start", "language": "zh", "sample_rate": 16000, "format": "pcm_s16le"}


@pytest.fixture
def mock_model(monkeypatch):
    calls = []
    def transcribe(samples, language):
        calls.append((len(samples), language))
        if not np.any(samples):
            return ""
        return f"第{len(calls)}段"
    monkeypatch.setattr(realtime, "recognizer", SimpleNamespace(prepare=lambda language: None, transcribe=transcribe))
    return calls


def pcm(seconds, amplitude=0.1):
    return np.full(int(seconds * SAMPLE_RATE), int(amplitude * 32767), dtype="<i2").tobytes()


def send_pcm(websocket, data):
    for index in range(0, len(data), 3200):
        websocket.send_bytes(data[index:index + 3200])


def receive_until(websocket, kind):
    messages = []
    for _ in range(100):
        item = websocket.receive_json()
        messages.append(item)
        assert item["type"] != "error", item
        if item["type"] == kind:
            return messages
    raise AssertionError(f"No {kind} message")


def test_continuous_speech_has_result_before_stop_and_tail_is_kept(mock_model):
    with TestClient(app).websocket_connect("/api/realtime") as websocket:
        websocket.send_json(START)
        assert websocket.receive_json()["type"] == "ready"
        send_pcm(websocket, pcm(4))
        first = receive_until(websocket, "segment")[-1]
        assert first["sequence"] == 1 and first["text"] == "第1段"
        send_pcm(websocket, pcm(0.35))
        websocket.send_json({"type": "stop"})
        tail = receive_until(websocket, "final")
        assert tail[-1]["text"] == "第3段"  # final whole-recording correction
        assert tail[-1]["duration_seconds"] == 4.35
        assert [item["sequence"] for item in tail if item["type"] == "segment"] == [2]
    assert mock_model == [(64000, "zh"), (5600, "zh"), (69600, "zh")]


def test_silence_final_and_repeated_sessions(mock_model):
    for _ in range(2):
        with TestClient(app).websocket_connect("/api/realtime") as websocket:
            websocket.send_json({**START, "language": "en"})
            assert websocket.receive_json()["type"] == "ready"
            send_pcm(websocket, pcm(0.75, amplitude=0))
            websocket.send_json({"type": "stop"})
            final = receive_until(websocket, "final")[-1]
            assert final["text"] == ""
            assert final["language"] == "en"
            assert final["duration_seconds"] == 0.75
    assert mock_model == [(12000, "en"), (12000, "en")]


@pytest.mark.parametrize("message", [
    {**START, "language": "fr"}, {**START, "sample_rate": 48000},
    {**START, "format": "float32"}, {"type": "stop"}, [],
])
def test_invalid_start(message, mock_model):
    with TestClient(app).websocket_connect("/api/realtime") as websocket:
        websocket.send_json(message)
        assert websocket.receive_json()["type"] == "error"


@pytest.mark.parametrize("data", [b"", b"1", b"0" * 16002])
def test_invalid_pcm(data, mock_model):
    with TestClient(app).websocket_connect("/api/realtime") as websocket:
        websocket.send_json(START)
        assert websocket.receive_json()["type"] == "ready"
        websocket.send_bytes(data)
        assert websocket.receive_json()["type"] == "error"


def test_model_not_ready(monkeypatch):
    from app.asr import ModelUnavailable
    def missing(language): raise ModelUnavailable("model missing")
    monkeypatch.setattr(realtime, "recognizer", SimpleNamespace(prepare=missing))
    with TestClient(app).websocket_connect("/api/realtime") as websocket:
        websocket.send_json(START)
        assert websocket.receive_json() == {"type": "error", "message": "model missing"}


def test_inference_failure_is_explicit(mock_model, monkeypatch):
    def failed(samples, language): raise RuntimeError("private failure")
    monkeypatch.setattr(realtime.recognizer, "transcribe", failed)
    with TestClient(app).websocket_connect("/api/realtime") as websocket:
        websocket.send_json(START)
        assert websocket.receive_json()["type"] == "ready"
        send_pcm(websocket, pcm(0.3))
        websocket.send_json({"type": "stop"})
        messages = [websocket.receive_json() for _ in range(3)]
        assert messages[-1]["type"] == "error"
        assert "private failure" not in str(messages)


def test_queue_overflow_is_an_error_not_silent_audio_loss(mock_model, monkeypatch):
    monkeypatch.setattr(realtime, "QUEUE_LIMIT", 1)
    monkeypatch.setattr(realtime.Segmenter, "feed", lambda self, samples: [samples, samples])
    with TestClient(app).websocket_connect("/api/realtime") as websocket:
        websocket.send_json(START)
        assert websocket.receive_json()["type"] == "ready"
        websocket.send_bytes(pcm(0.1))
        message = websocket.receive_json()
        if message["type"] == "processing": message = websocket.receive_json()
        assert message["type"] == "error"
        assert "队列已满" in message["message"]


def test_server_enforces_60_second_limit(mock_model):
    with TestClient(app).websocket_connect("/api/realtime") as websocket:
        websocket.send_json(START)
        assert websocket.receive_json()["type"] == "ready"
        send_pcm(websocket, pcm(60, amplitude=0))
        messages = receive_until(websocket, "final")
        assert any(item["type"] == "limit" for item in messages)
        assert messages[-1]["duration_seconds"] == 60
        assert mock_model == [(960000, "zh")]


def test_disconnect_then_reconnect(mock_model):
    client = TestClient(app)
    with client.websocket_connect("/api/realtime") as websocket:
        websocket.send_json(START)
        assert websocket.receive_json()["type"] == "ready"
        websocket.send_bytes(pcm(0.1))
    with client.websocket_connect("/api/realtime") as websocket:
        websocket.send_json(START)
        assert websocket.receive_json()["type"] == "ready"
        websocket.send_json({"type": "stop"})
        assert receive_until(websocket, "final")[-1]["text"] == ""


def test_reject_cross_origin_browser(mock_model):
    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect("/api/realtime", headers={"origin": "https://unrelated.example"}):
            pass


def test_segmenter_pause_and_partial_tail():
    segmenter = realtime.Segmenter()
    assert segmenter.feed(np.zeros(3200, dtype="float32")) == []
    speech = np.full(16000, 0.1, dtype="float32")
    assert segmenter.feed(speech) == []
    segments = segmenter.feed(np.zeros(9600, dtype="float32"))
    assert len(segments) == 1
    assert len(segments[0]) == 28800  # 0.2 preroll + 1 speech + 0.6 pause
    assert segmenter.feed(np.full(1000, 0.1, dtype="float32")) == []
    assert len(segmenter.finish()[0]) == 1000
    assert segmenter.finish() == []


def test_segmenter_does_not_overlap_or_drop_continuous_speech():
    original = np.full(143211, 0.1, dtype="float32")
    segmenter = realtime.Segmenter()
    parts = []
    for index in range(0, len(original), 987):
        parts.extend(segmenter.feed(original[index:index + 987]))
    parts.extend(segmenter.finish())
    np.testing.assert_array_equal(np.concatenate(parts), original)
    assert max(map(len, parts)) <= 4 * SAMPLE_RATE
