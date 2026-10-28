import numpy as np
import pytest
from pathlib import Path

from app.audio import AudioError, decode_audio, split_audio
from app.config import SAMPLE_RATE


def test_decode_wav_and_resample(wav_bytes):
    audio = decode_audio(wav_bytes(seconds=1.25), "test.wav")
    assert audio.duration_seconds == pytest.approx(1.25, abs=0.01)
    assert len(audio.samples) == 20_000
    assert audio.samples.dtype == np.float32


@pytest.mark.parametrize("filename", ["recording.webm", "recording.weba", "recording.WEBA"])
def test_decode_actual_chrome_mediarecorder_webm(filename):
    fixture = Path(__file__).parent / "fixtures" / "browser-recorded.webm"
    audio = decode_audio(fixture.read_bytes(), filename)
    assert 10 < audio.duration_seconds < 11
    assert len(audio.samples) > SAMPLE_RATE * 10
    assert audio.samples.dtype == np.float32


@pytest.mark.parametrize("filename,data,status", [
    ("a.wav", b"", 400),
    ("a.wav", b"broken", 400),
    ("a.mp3", b"broken", 415),
    ("a.weba", b"broken", 400),
])
def test_reject_invalid(filename, data, status):
    with pytest.raises(AudioError) as error:
        decode_audio(data, filename)
    assert error.value.status_code == status


def test_duration_boundary(wav_bytes):
    assert decode_audio(wav_bytes(seconds=65), "a.wav").duration_seconds == pytest.approx(65, abs=0.01)
    with pytest.raises(AudioError, match="65"):
        decode_audio(wav_bytes(seconds=65.02), "a.wav")


def test_split_preserves_every_sample():
    samples = np.ones(51 * SAMPLE_RATE, dtype="float32")
    chunks = split_audio(samples)
    assert len(chunks) >= 3
    np.testing.assert_array_equal(np.concatenate(chunks), samples)
    assert all(len(chunk) <= 22 * SAMPLE_RATE for chunk in chunks)
