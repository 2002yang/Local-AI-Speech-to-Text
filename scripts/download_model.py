"""Explicit one-time model preparation; never called by application or pytest."""

import hashlib
import shutil
import tarfile
import urllib.request
from pathlib import Path

from app.config import MODEL_DIR

ARCHIVE = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2"
URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{ARCHIVE}"
EXPECTED_SHA256 = {
    "model.int8.onnx": "c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51",
    "tokens.txt": "f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc",
}


def verify_model() -> None:
    for basename, expected in EXPECTED_SHA256.items():
        target = MODEL_DIR / basename
        with target.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"Checksum mismatch for {basename}; remove the incomplete file and retry.")
        print(f"{basename} SHA-256: {actual}")


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = MODEL_DIR / ARCHIVE
    if (MODEL_DIR / "model.int8.onnx").is_file() and (MODEL_DIR / "tokens.txt").is_file():
        verify_model()
        print(f"Model already available: {MODEL_DIR}")
        return
    print(f"Downloading model archive to {MODEL_DIR} (one-time network access required)...", flush=True)
    try:
        if not archive_path.is_file():
            with urllib.request.urlopen(URL, timeout=120) as response, open(archive_path.with_suffix(".part"), "wb") as destination:
                shutil.copyfileobj(response, destination)
            archive_path.with_suffix(".part").replace(archive_path)
        print("Extracting only model.int8.onnx and tokens.txt...", flush=True)
        with tarfile.open(archive_path, "r:bz2") as archive:
            for basename in ("model.int8.onnx", "tokens.txt"):
                members = [item for item in archive.getmembers() if Path(item.name).name == basename and item.isfile()]
                if len(members) != 1:
                    raise ValueError(f"Archive missing or duplicate: {basename}")
                source = archive.extractfile(members[0])
                if source is None:
                    raise ValueError(f"Archive member unreadable: {basename}")
                target = MODEL_DIR / f"{basename}.part"
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.replace(MODEL_DIR / basename)
        verify_model()
        archive_path.unlink()
        print(f"Model ready: {MODEL_DIR}")
    except Exception:
        print("Model preparation failed. Retry after checking network and disk space.")
        raise


if __name__ == "__main__":
    main()
