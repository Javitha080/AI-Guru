"""Probe webcam frame delivery: DSHOW vs MSMF, warm-up latency, read failures."""

import sys
import time

import cv2


def probe(name: str, backend: int, index: int = 0, reads: int = 60) -> None:
    print(f"\n=== {name} (index {index}) ===")
    try:
        cap = cv2.VideoCapture(index, backend)
    except Exception as exc:
        print(f"open raised: {exc}")
        return
    if cap is None or not cap.isOpened():
        print("open FAILED (isOpened False)")
        return
    t_open = time.perf_counter()
    first_frame = None
    fails = 0
    ok = 0
    for i in range(reads):
        got, frame = cap.read()
        if got and frame is not None:
            ok += 1
            if first_frame is None:
                first_frame = time.perf_counter() - t_open
                print(f"first frame after {first_frame:.2f}s ({frame.shape[1]}x{frame.shape[0]})")
        else:
            fails += 1
        time.sleep(1.0 / 15)
    print(f"reads={reads} ok={ok} failed={fails}")
    if first_frame is None:
        print("NEVER delivered a frame")
    cap.release()


if __name__ == "__main__":
    index = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    probe("CAP_DSHOW", cv2.CAP_DSHOW, index)
    probe("CAP_MSMF", cv2.CAP_MSMF, index)
