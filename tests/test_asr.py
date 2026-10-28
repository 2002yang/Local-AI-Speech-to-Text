import numpy as np
import pytest

from app import asr


def test_language_is_used_and_recognizers_reused(monkeypatch):
    created = []
    class FakeStream:
        def accept_waveform(self, rate, samples):
            assert rate == 16_000 and len(samples)
        @property
        def result(self):
            return type("Result", (), {"text": " hello "})()
    class FakeRecognizer:
        def create_stream(self): return FakeStream()
        def decode_stream(self, stream): pass
    def fake_get(self, language):
        created.append(language)
        return FakeRecognizer()
    monkeypatch.setattr(asr.SpeechRecognizer, "_get_recognizer", fake_get)
    engine = asr.SpeechRecognizer()
    signal = np.full(16_000, 0.1, dtype="float32")
    assert engine.transcribe(signal, "en") == "hello"
    assert engine.transcribe(signal, "zh") == "hello"
    assert created == ["en", "zh"]


def test_silence_does_not_invoke_inference(monkeypatch):
    monkeypatch.setattr(asr.SpeechRecognizer, "_get_recognizer", lambda self, language: object())
    assert asr.SpeechRecognizer().transcribe(np.zeros(16_000, dtype="float32"), "zh") == ""


def test_punctuation_only_is_not_a_transcript(monkeypatch):
    class FakeStream:
        def accept_waveform(self, *args): pass
        @property
        def result(self): return type("Result", (), {"text": "。 "})()
    class FakeRecognizer:
        def create_stream(self): return FakeStream()
        def decode_stream(self, stream): pass
    monkeypatch.setattr(asr.SpeechRecognizer, "_get_recognizer", lambda self, language: FakeRecognizer())
    assert asr.SpeechRecognizer().transcribe(np.full(16_000, 0.1, dtype="float32"), "zh") == ""


def test_missing_model_and_language(monkeypatch, tmp_path):
    monkeypatch.setattr(asr, "MODEL_FILE", tmp_path / "missing.onnx")
    engine = asr.SpeechRecognizer()
    with pytest.raises(ValueError):
        engine._get_recognizer("fr")
    with pytest.raises(asr.ModelUnavailable):
        engine._get_recognizer("zh")
