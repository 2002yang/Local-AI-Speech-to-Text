"""Default pytest suite never downloads model weights or uses hardware."""

from io import BytesIO
import wave

import numpy as np
import pytest


def pytest_addoption(parser):
    parser.addoption("--run-real-model", action="store_true", help="Run tests using a prepared local SenseVoice model")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-real-model"):
        skip = pytest.mark.skip(reason="Real model test requires --run-real-model and prepared weights")
        for item in items:
            if "real_model" in item.keywords:
                item.add_marker(skip)


@pytest.fixture
def wav_bytes():
    def create(seconds=0.5, frequency=440, amplitude=0.2):
        rate = 16_000
        t = np.arange(int(rate * seconds)) / rate
        data = (np.sin(2 * np.pi * frequency * t) * amplitude * 32767).astype("<i2")
        buffer = BytesIO()
        with wave.open(buffer, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(data.tobytes())
        return buffer.getvalue()
    return create
