#!/usr/bin/env python3
"""Fetch the OpenCV Zoo SFace recognition model for local face identity.

Downloads ``face_recognition_sface_2021dec.onnx`` (~37 MB, Apache-2.0) into
``deeptutor/models/``. Until the model is present, identity verification
transparently falls back to the geometric (landmark-ratio) embedding, which
CANNOT distinguish real people — enrolling with ``identity_mode: "sface"`` is
what makes IDENTITY_MISMATCH actually detect an impostor.

Usage: python scripts/fetch_sface_model.py
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEST = REPO_ROOT / "deeptutor" / "models" / "face_recognition_sface_2021dec.onnx"

URLS = [
    # Official OpenCV mirror on Hugging Face.
    "https://huggingface.co/opencv/face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx",
    # OpenCV Zoo via Git LFS media redirect.
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    # Raw GitHub (OpenCV Zoo master).
    "https://github.com/opencv/opencv_zoo/raw/master/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
]


def main() -> int:
    if DEST.is_file() and DEST.stat().st_size > 10_000_000:
        print(f"SFace model already present: {DEST}")
        return 0
    DEST.parent.mkdir(parents=True, exist_ok=True)
    for url in URLS:
        try:
            print(f"Downloading {url} ...")
            with urllib.request.urlopen(url, timeout=120) as resp, open(DEST, "wb") as out:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            size = DEST.stat().st_size
            if size < 10_000_000:
                raise RuntimeError(f"suspiciously small download ({size} bytes)")
            print(f"Saved {size / 1e6:.1f} MB → {DEST}")
            print("Restart the backend to activate SFace identity verification.")
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"  failed: {exc}", file=sys.stderr)
    print("All download sources failed. Place the model manually at:", DEST, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
