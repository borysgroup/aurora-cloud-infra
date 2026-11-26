"""Time the Epson segmentation model with onnxruntime, as the live blur would run it on the Pi 5.

    python bench_pi.py MODEL.onnx [RUNS]

Median and 90th percentile of RUNS forward passes (after 3 warm-up runs) at 1 and 2 threads, on a
448 x 256 input. If OpenCV is installed, also the full EpsonSeg call (letterbox, NMS, masks) on a
1350 x 700 robot-zone crop. Prints one JSON line.
"""
import json
import sys
import time

import numpy as np
import onnxruntime as ort


def timeit(fn, runs):
    for _ in range(3):
        fn()
    t = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        t.append(1000 * (time.perf_counter() - t0))
    return dict(median_ms=round(float(np.median(t)), 1), p90_ms=round(float(np.percentile(t, 90)), 1))


def main(path, runs=20):
    out = dict(onnxruntime=ort.__version__, model=path.split("/")[-1])
    x = np.random.default_rng(0).random((1, 3, 256, 448), dtype=np.float32)
    for th in (1, 2):
        so = ort.SessionOptions()
        so.intra_op_num_threads, so.inter_op_num_threads = th, 1
        s = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
        name = s.get_inputs()[0].name
        out[f"forward_{th}thread"] = timeit(lambda: s.run(None, {name: x}), runs)
    try:
        import cv2  # noqa: F401
        sys.path.insert(0, __file__.rsplit("/", 1)[0])
        from yolo_onnx import EpsonSeg
        seg = EpsonSeg(path, threads=1)
        img = np.random.default_rng(1).integers(0, 255, (700, 1350, 3), dtype=np.uint8)
        out["full_call_1thread"] = timeit(lambda: seg(img), runs)
    except ImportError as e:
        out["full_call_1thread"] = f"skipped ({e})"
    print(json.dumps(out))


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 20)
