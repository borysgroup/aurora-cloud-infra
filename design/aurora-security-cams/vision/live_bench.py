"""Measure what blurring the live feeds would cost on the Pi 5.

    python3 -I live_bench.py encode CLIP.mp4 MASK.png [--threads 2] [--only TEXT]  # decode + blur + x264
    python3 live_bench.py model MODEL.onnx [MODEL.onnx ...] [--threads 1 2]  # onnxruntime latency

encode runs ffmpeg over a clip recorded from a camera (pull_feed.py N record 20 clip.mp4) with several
output settings and reports CPU time per frame from ffmpeg's -benchmark (user + system). That figure
does not depend on how many cores the run gets; "cores at 20 fps" is it times 20. The blur is the
static-mask step: the frame scaled to 1/8, Gaussian-blurred and scaled back, with the sharp frame laid
over it through the keep-sharp mask. Timestamps are regenerated at exactly 20 fps, as a live encoder
would: a copied RTSP clip has a few duplicates, which the muxer rejects once x264 reorders frames.

model times onnxruntime inference on random input of each model's own shape (3 warm-up runs, then the
median of 15). A 'decoder' model (EdgeSAM's) is fed a 64x64 embedding and five point prompts.

Run both niced and pinned so the picam keeps priority, e.g. `nice -n 19 taskset -c 2,3 python3 ...`.
Prints one JSON line per measurement.
"""
import argparse
import json
import re
import subprocess
import time

FPS = 20

ENCODE_RUNS = [
    # label, output size, blur, x264 preset, video bitrate (kbit/s)
    ("decode only", None, False, None, None),
    ("1080p, x264 superfast, no blur", (1920, 1080), False, "superfast", 4500),
    ("1080p, blur, x264 superfast", (1920, 1080), True, "superfast", 4500),
    ("720p, x264 superfast, no blur", (1280, 720), False, "superfast", 3000),
    ("720p, blur, x264 superfast", (1280, 720), True, "superfast", 3000),
    ("720p, blur, x264 ultrafast", (1280, 720), True, "ultrafast", 3000),
    ("720p, blur, x264 veryfast", (1280, 720), True, "veryfast", 3000),
]


def count_frames(clip):
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                        "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", clip],
                       capture_output=True, text=True, check=True)
    return int(p.stdout.strip())


def blur_graph(w, h):
    return (f"[0:v]setpts=N/({FPS}*TB),scale={w}:{h}:flags=bilinear,format=yuv420p,split=2[o][b];"
            f"[b]scale={w // 8}:{h // 8}:flags=area,gblur=sigma=1.5,scale={w}:{h}:flags=bilinear[bl];"
            f"[1:v]scale={w}:{h},format=gray[m];"
            "[o][m]alphamerge[om];"
            "[bl][om]overlay=format=yuv420:shortest=1,format=yuv420p[v]")


def encode(clip, mask, threads, only=None):
    frames = count_frames(clip)
    for label, size, blur, preset, kbps in ENCODE_RUNS:
        if only and only not in label:
            continue
        cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "info", "-benchmark",
               "-threads", str(threads), "-i", clip]
        if blur:
            cmd += ["-loop", "1", "-framerate", str(FPS), "-i", mask,
                    "-filter_complex", blur_graph(*size), "-map", "[v]"]
        elif size:
            cmd += ["-vf", f"setpts=N/({FPS}*TB),scale={size[0]}:{size[1]}:flags=bilinear,format=yuv420p"]
        if preset:
            cmd += ["-c:v", "libx264", "-preset", preset, "-threads", str(threads),
                    "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{2 * kbps}k",
                    "-g", str(2 * FPS), "-keyint_min", str(2 * FPS), "-sc_threshold", "0"]
        cmd += ["-frames:v", str(frames), "-an", "-f", "null", "-"]
        t0 = time.time()
        p = subprocess.run(cmd, capture_output=True, text=True)
        wall = time.time() - t0
        m = re.search(r"utime=([\d.]+)s stime=([\d.]+)s rtime=([\d.]+)s", p.stdout + p.stderr)
        if p.returncode or not m:
            print(json.dumps({"run": label, "error": (p.stderr or p.stdout)[-300:]}))
            continue
        cpu = float(m.group(1)) + float(m.group(2))
        print(json.dumps({"run": label, "frames": frames, "threads": threads,
                          "cpu_ms_per_frame": round(1000 * cpu / frames, 2),
                          "cores_at_20fps": round(cpu / frames * FPS, 3),
                          "max_fps_with_these_threads": round(frames / float(m.group(3)), 1),
                          "wall_s": round(wall, 1)}), flush=True)


def model(paths, thread_counts):
    import numpy as np
    import onnxruntime as ort

    rng = np.random.default_rng(0)
    for path in paths:
        for t in thread_counts:
            so = ort.SessionOptions()
            so.intra_op_num_threads = t
            so.inter_op_num_threads = 1
            s = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
            feed = {}
            for i in s.get_inputs():
                if i.name == "point_coords":
                    feed[i.name] = (rng.random((1, 5, 2)) * 1024).astype(np.float32)
                elif i.name == "point_labels":
                    feed[i.name] = np.array([[1, 1, 1, 0, 0]], np.float32)
                else:
                    feed[i.name] = rng.random([d if isinstance(d, int) else 1 for d in i.shape]).astype(np.float32)
            for _ in range(3):
                s.run(None, feed)
            ms = []
            for _ in range(15):
                t0 = time.perf_counter()
                s.run(None, feed)
                ms.append(1000 * (time.perf_counter() - t0))
            ms.sort()
            print(json.dumps({"model": path.rsplit("/", 1)[-1], "threads": t,
                              "input": {i.name: i.shape for i in s.get_inputs()},
                              "median_ms": round(ms[len(ms) // 2], 1), "min_ms": round(ms[0], 1),
                              "max_ms": round(ms[-1], 1), "ort": ort.__version__}), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("encode")
    e.add_argument("clip")
    e.add_argument("mask")
    e.add_argument("--threads", type=int, default=2)
    e.add_argument("--only", help="run only the settings whose label contains this text")
    m = sub.add_parser("model")
    m.add_argument("paths", nargs="+")
    m.add_argument("--threads", type=int, nargs="+", default=[1, 2])
    a = ap.parse_args()
    if a.cmd == "encode":
        encode(a.clip, a.mask, a.threads, a.only)
    else:
        model(a.paths, a.threads)


if __name__ == "__main__":
    main()
