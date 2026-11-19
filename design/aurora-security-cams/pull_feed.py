"""Pull the RTSP feed of Amcrest cam N with the viewer login from cams.env.

The credentialed URL only ever lives in a mode-600 ffconcat file in a 700
directory (never on a command line), and every line ffmpeg/ffprobe prints is
redacted before it is shown.
Runs on the Pi 5 as the owner of cams.env:

    python3 -I pull_feed.py N probe            # codec, size, frame rate
    python3 -I pull_feed.py N packets SECONDS  # measured fps, bitrate, keyframe gaps
    python3 -I pull_feed.py N still OUT.jpg    # one full-size frame
"""
import json, os, re, subprocess, sys, tempfile, urllib.parse

ENV = os.path.expanduser("~/.config/aurora-security-cams/cams.env")
RED = [(re.compile(r"(rtsps?://)[^/@\s'\"]+@"), r"\1<redacted>@"),
       (re.compile(r"(rtmps?://[^\s'\"]+?/live2?/)[^\s'\"]+"), r"\1<redacted>")]

def redact(s):
    for rx, rep in RED:
        s = rx.sub(rep, s)
    return s

def load_env(path=ENV):
    out = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out

def rtsp_url(n, subtype=0):
    e = load_env()
    q = lambda s: urllib.parse.quote(s, safe="")
    return (f"rtsp://{q(e[f'AMCREST_CAM_USERNAME_{n}'])}:{q(e[f'AMCREST_CAM_PASSWORD_{n}'])}"
            f"@{e[f'AMCREST_CAM_HOST_{n}']}:554/cam/realmonitor?channel=1&subtype={subtype}")

def concat_file(n, subtype=0):
    d = tempfile.mkdtemp(prefix="amcrest-")  # mode 700
    path = os.path.join(d, f"cam{n}.ffconcat")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("ffconcat version 1.0\n")
        f.write(f"file '{rtsp_url(n, subtype)}'\n")
        f.write("option rtsp_transport tcp\n")
        f.write("option timeout 10000000\n")
    return path

CONCAT_IN = ["-f", "concat", "-safe", "0",
             "-protocol_whitelist", "file,rtsp,rtp,tcp,udp,crypto,data"]

def run(cmd, timeout=60):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, redact(p.stdout), redact(p.stderr)

if __name__ == "__main__":
    n, mode = int(sys.argv[1]), sys.argv[2]
    path = concat_file(n)
    try:
        if mode == "probe":
            rc, out, err = run(["ffprobe", "-v", "error", *CONCAT_IN, "-i", path,
                                "-show_entries", "stream=codec_name,profile,width,height,pix_fmt,"
                                "r_frame_rate,avg_frame_rate,has_b_frames,codec_type,sample_rate,channels",
                                "-of", "json"])
            print("rc", rc, err.strip()[-400:])
            print(json.dumps([{k: v for k, v in s.items() if k != "disposition"} for s in json.loads(out or '{"streams":[]}')["streams"]]))
        elif mode == "packets":
            secs = float(sys.argv[3])
            rc, out, err = run(["ffprobe", "-v", "error", *CONCAT_IN, "-i", path, "-select_streams", "v:0",
                                "-read_intervals", f"%+{secs}", "-show_entries", "packet=pts_time,size,flags",
                                "-of", "csv=p=0"], timeout=secs + 40)
            raw = [l.split(",") for l in out.splitlines() if l.count(",") >= 2]
            pk = [(float(r[0]), int(r[1]), r[2]) for r in raw if r[0] not in ("", "N/A")]
            if not pk:
                print("rc", rc, "no packets", err.strip()[-400:]); sys.exit(1)
            dur = pk[-1][0] - pk[0][0]
            keys = [t for t, s, f in pk if "K" in f]
            gaps = [round(b - a, 2) for a, b in zip(keys, keys[1:])]
            print(f"rc {rc} packets={len(pk)} span={dur:.1f}s fps~{(len(pk)-1)/dur:.2f} "
                  f"video kbit/s~{sum(s for _, s, _ in pk)*8/dur/1000:.0f} keyframes={len(keys)} key gaps s={gaps}")
        elif mode == "still":
            out_jpg = sys.argv[3]
            rc, out, err = run(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *CONCAT_IN,
                                "-i", path, "-frames:v", "1", "-q:v", "3", out_jpg])
            print("rc", rc, err.strip()[-400:], os.path.getsize(out_jpg) if os.path.exists(out_jpg) else "no file")
    finally:
        os.remove(path); os.rmdir(os.path.dirname(path))
