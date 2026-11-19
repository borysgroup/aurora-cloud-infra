#!/usr/bin/env python3
"""
Relay one Amcrest security camera to a YouTube live broadcast, from the Pi 5.

The camera's H.264 main stream is pulled over RTSP on eth0 and pushed to
YouTube without re-encoding (``-c:v copy``). A silent AAC track is added
because the cameras send no audio and YouTube expects an audio track. The
broadcast comes from the same picam Lambda the Pi 5's own stream uses: ``end``
(any broadcast still live for this workflow), then ``create``.

Secrets
  * Viewer login: read from ``~/.config/aurora-security-cams/cams.env``
    (``AMCREST_CAM_{HOST,USERNAME,PASSWORD}_<n>``). The credentialed RTSP URL
    is written only to a mode-600 ffconcat file in a mode-700 runtime
    directory, so it never appears on a command line or in the process list.
  * Lambda URL: ``$LAMBDA_FUNCTION_URL``, or ``LAMBDA_FUNCTION_URL`` parsed
    (not imported) from the picam's ``my_secrets.py``.
  * Every line ffmpeg prints is redacted (RTSP logins, stream keys), and the
    broadcast's video ID, URL and stream key are never logged.

Why RTMPS: the Pi 5's ``stream-watchdog.sh`` judges the picam stream by the
RTMP (port 1935) socket with the most bytes ACKed. A relay on port 1935 could
mask a stalled picam stream, or make the watchdog restart a healthy one, so
the relay pushes to YouTube's RTMPS ingest on port 443 instead.

Restarts: the camera is probed before the Lambda is asked for a broadcast, so
a camera that is down does not leave empty scheduled broadcasts behind. A
stalled or failed ffmpeg is restarted against the same broadcast (it has
auto-stop off, so it resumes). After 5 quick failures in a row the script
exits non-zero, and systemd's Restart=/StartLimitBurst= decide whether a fresh
broadcast is created. Independently of the Pi's 8-hourly reboot, a broadcast
is ended and replaced after ``--max-hours`` (default 11), so none runs past
YouTube's 12 h archive limit even when a reboot is held off. On SIGTERM it
stops ffmpeg and ends the broadcast, so a reboot leaves a finished archive.

Playlist privacy: the Lambda adds each broadcast to the first playlist whose
title contains the workflow name, and only when there is none does it create
one, with the broadcast's privacy. So the first ``create`` for a new workflow
name decides the playlist's privacy: run it once with ``--privacy private``
for a private playlist, then run ``--privacy unlisted`` from then on.

Run (as the user that owns cams.env, normally via amcrest-relay@.service)::

    python3 -I amcrest_relay.py --cam 0 \\
        --workflow-name "Aurora security cam 150" --cam-name amcrest-150

Test the camera side without YouTube (writes a local FLV and exits)::

    python3 -I amcrest_relay.py --cam 0 --test-output /tmp/cam0.flv --test-seconds 20
"""
import argparse
import ast
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_CAMS_ENV = "~/.config/aurora-security-cams/cams.env"
DEFAULT_SECRETS = "~/ac-training-lab/src/ac_training_lab/picam/my_secrets.py"

_REDACT = [
    (re.compile(r"(rtsps?://)[^/@\s'\"]+@"), r"\1<redacted>@"),
    (re.compile(r"(rtmps?://[^\s'\"]+?/live2?/)[^\s'\"]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(https://)[^/\s'\"]+(\.lambda-url\.)"), r"\1<redacted>\2"),
    # video / broadcast IDs, e.g. in a YouTube API error the Lambda passes on
    (re.compile(r"([?&](?:id|v|videoId)=)[\w-]{6,}"), r"\1<redacted>"),
    (re.compile(r"(youtu\.be/|/live/|/watch/)[\w-]{6,}"), r"\1<redacted>"),
]


def redact(text):
    for rx, rep in _REDACT:
        text = rx.sub(rep, text)
    return text


def log(msg):
    print(redact(f"[relay] {msg}"), flush=True)


def load_env_file(path):
    out = {}
    with open(os.path.expanduser(path)) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    return out


def lambda_url(secrets_path):
    if os.environ.get("LAMBDA_FUNCTION_URL"):
        return os.environ["LAMBDA_FUNCTION_URL"]
    with open(os.path.expanduser(secrets_path)) as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "LAMBDA_FUNCTION_URL" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise RuntimeError(f"LAMBDA_FUNCTION_URL not set and not found in {secrets_path}")


def call_lambda(url, action, cam_name, workflow_name, privacy):
    payload = {
        "action": action,
        "cam_name": cam_name,
        "workflow_name": workflow_name,
        "privacy_status": privacy,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=150) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Lambda '{action}' returned HTTP {e.code}: {detail}") from None
    if isinstance(body, dict) and "statusCode" in body and "body" in body:
        body = body["body"]
    if isinstance(body, str):
        body = json.loads(body)
    return body


def to_rtmps(url):
    """rtmp://a.rtmp.youtube.com/live2/KEY -> rtmps://a.rtmps.youtube.com:443/live2/KEY"""
    u = urllib.parse.urlsplit(url)
    host = u.hostname or ""
    if u.scheme == "rtmp" and host.endswith(".rtmp.youtube.com"):
        host = host[: -len(".rtmp.youtube.com")] + ".rtmps.youtube.com"
        return urllib.parse.urlunsplit(("rtmps", f"{host}:443", u.path, u.query, u.fragment))
    return url


def write_concat(run_dir, cam, subtype, cams_env):
    env = load_env_file(cams_env)
    q = lambda s: urllib.parse.quote(s, safe="")  # noqa: E731
    url = (
        f"rtsp://{q(env[f'AMCREST_CAM_USERNAME_{cam}'])}:{q(env[f'AMCREST_CAM_PASSWORD_{cam}'])}"
        f"@{env[f'AMCREST_CAM_HOST_{cam}']}:554/cam/realmonitor?channel=1&subtype={subtype}"
    )
    path = os.path.join(run_dir, f"cam{cam}.ffconcat")
    if os.path.exists(path):
        os.remove(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write("ffconcat version 1.0\n")
        fh.write(f"file '{url}'\n")
        fh.write("option rtsp_transport tcp\n")
        fh.write("option timeout 10000000\n")  # socket I/O timeout, microseconds
    return path, env[f"AMCREST_CAM_HOST_{cam}"]


def camera_ok(concat_path):
    """True if the camera answers with an H.264 stream (about 2-5 s)."""
    try:
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-f", "concat", "-safe", "0",
             "-protocol_whitelist", "file,rtsp,rtp,tcp,udp", "-i", concat_path,
             "-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "csv=p=0"],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        log("camera probe timed out")
        return False
    if "h264" in p.stdout:
        return True
    log(f"camera probe failed: {redact(p.stderr.strip())[-300:] or 'no video stream'}")
    return False


def ffmpeg_cmd(concat_path, output, test_seconds=None):
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning", "-nostats",
        "-progress", "pipe:1", "-stats_period", "5",
        "-f", "concat", "-safe", "0", "-protocol_whitelist", "file,rtsp,rtp,tcp,udp",
        "-i", concat_path,
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
    ]
    if test_seconds:
        cmd += ["-t", str(test_seconds)]
    else:
        cmd += ["-rw_timeout", "20000000"]
    cmd += ["-flvflags", "no_duration_filesize", "-f", "flv", output]
    return cmd


class Relay:
    def __init__(self, args):
        self.args = args
        self.stop = threading.Event()
        self.proc = None
        self.progress_at = time.monotonic()
        self.total_size = -1

    def _pump_stderr(self, stream):
        for line in iter(stream.readline, ""):
            line = line.rstrip()
            if line:
                print(redact(f"[ffmpeg] {line}"), flush=True)

    def _pump_progress(self, stream):
        for line in iter(stream.readline, ""):
            if line.startswith("total_size="):
                try:
                    size = int(line.split("=", 1)[1])
                except ValueError:
                    continue
                if size > self.total_size:
                    self.total_size = size
                    self.progress_at = time.monotonic()

    def run_ffmpeg(self, concat_path, output, deadline=None):
        """Run ffmpeg until it exits, stalls, the deadline passes or we are stopped."""
        cmd = ffmpeg_cmd(concat_path, output, self.args.test_seconds)
        self.total_size = -1
        self.progress_at = time.monotonic()
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
        )
        threading.Thread(target=self._pump_stderr, args=(self.proc.stderr,), daemon=True).start()
        threading.Thread(target=self._pump_progress, args=(self.proc.stdout,), daemon=True).start()
        last_report = time.monotonic()
        while self.proc.poll() is None:
            if self.stop.wait(1):
                break
            now = time.monotonic()
            if deadline and now >= deadline:
                break
            if now - self.progress_at > self.args.stall_sec:
                log(f"no output progress for {self.args.stall_sec:.0f} s; restarting ffmpeg")
                break
            if now - last_report >= self.args.report_sec:
                last_report = now
                log(f"streaming, {self.total_size / 1e6:.0f} MB sent by this ffmpeg")
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        return self.proc.returncode

    def new_broadcast(self, url, cam_name, workflow):
        a = self.args
        try:
            ended = call_lambda(url, "end", cam_name, workflow, a.privacy)
            log(f"Lambda end: {ended.get('status')}")
        except Exception as e:  # nothing to end is fine
            log(f"Lambda end failed, continuing: {e}")
        made = call_lambda(url, "create", cam_name, workflow, a.privacy)
        res = made["result"]
        pl = str(res.get("playlist_add_status", "?"))
        log(f"Lambda create: '{res.get('title')}', privacy {res.get('privacy_status')}, "
            f"playlist {'added' if pl == 'added' else pl.split(' - ')[0]}")
        output = res["ffmpeg_url"] if a.no_rtmps else to_rtmps(res["ffmpeg_url"])
        parts = urllib.parse.urlsplit(output)
        log(f"pushing to {parts.scheme} ingest {parts.hostname}")
        return output

    def main(self):
        a = self.args
        own_dir = None
        run_dir = os.environ.get("RUNTIME_DIRECTORY", "").split(":")[0]
        if not run_dir:
            run_dir = own_dir = tempfile.mkdtemp(prefix="amcrest-relay-")
        concat_path, host = write_concat(run_dir, a.cam, a.subtype, a.cams_env)
        octet = host.rsplit(".", 1)[-1]
        cam_name = a.cam_name or f"amcrest-{octet}"
        workflow = a.workflow_name or f"Aurora security cam {octet}"
        url = None
        try:
            if a.test_output:
                log(f"test: cam {a.cam} ({host}) subtype {a.subtype} -> {a.test_output}, "
                    f"{a.test_seconds} s")
                rc = self.run_ffmpeg(concat_path, a.test_output)
                log(f"ffmpeg exited rc={rc}")
                return rc
            log(f"cam {a.cam} ({host}) subtype {a.subtype}: workflow '{workflow}', "
                f"cam_name '{cam_name}', privacy {a.privacy}")
            if not camera_ok(concat_path):
                log("camera not answering; not creating a broadcast")
                return 1
            url = lambda_url(a.secrets)
            while not self.stop.is_set():  # one pass per broadcast
                output = self.new_broadcast(url, cam_name, workflow)
                deadline = time.monotonic() + a.max_hours * 3600
                quick_fails = 0
                while not self.stop.is_set() and time.monotonic() < deadline:
                    started = time.monotonic()
                    rc = self.run_ffmpeg(concat_path, output, deadline)
                    ran = time.monotonic() - started
                    if self.stop.is_set() or time.monotonic() >= deadline:
                        break
                    quick_fails = quick_fails + 1 if ran < 120 else 0
                    log(f"ffmpeg exited rc={rc} after {ran:.0f} s "
                        f"(quick failures in a row: {quick_fails})")
                    if quick_fails >= 5:
                        log("giving up on this broadcast; exiting for systemd to decide")
                        return 1
                    if self.stop.wait(min(5 * 2 ** max(quick_fails - 1, 0), 60)):
                        break
                    # Re-read cams.env in case the login was rotated.
                    concat_path, _ = write_concat(run_dir, a.cam, a.subtype, a.cams_env)
                if not self.stop.is_set():
                    log(f"broadcast reached {a.max_hours} h; replacing it")
            return 0
        finally:
            if url and not a.no_end_on_exit:
                try:
                    ended = call_lambda(url, "end", cam_name, workflow, a.privacy)
                    log(f"Lambda end on exit: {ended.get('status')}")
                except Exception as e:
                    log(f"Lambda end on exit failed: {e}")
            try:
                os.remove(concat_path)
            except OSError:
                pass
            if own_dir:
                shutil.rmtree(own_dir, ignore_errors=True)


def main():
    env = os.environ.get
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cam", type=int, required=True, help="slot in cams.env (0 = .150, 1 = .151)")
    ap.add_argument("--cam-name", default=env("CAM_NAME"))
    ap.add_argument("--workflow-name", default=env("WORKFLOW_NAME"),
                    help="also the playlist name; must not contain, or be contained in, "
                         "another device's workflow name (the Lambda matches substrings)")
    ap.add_argument("--privacy", default=env("PRIVACY_STATUS", "unlisted"),
                    choices=("public", "unlisted", "private"))
    ap.add_argument("--subtype", type=int, default=int(env("RTSP_SUBTYPE", "0")),
                    help="0 = main stream (1080p20, 4 Mbit/s CBR, 2 s GOP as configured)")
    ap.add_argument("--cams-env", default=env("CAMS_ENV", DEFAULT_CAMS_ENV))
    ap.add_argument("--secrets", default=env("PICAM_SECRETS", DEFAULT_SECRETS),
                    help="picam my_secrets.py to read LAMBDA_FUNCTION_URL from")
    ap.add_argument("--no-rtmps", action="store_true", help="push to the Lambda's rtmp:// URL as is")
    ap.add_argument("--no-end-on-exit", action="store_true")
    ap.add_argument("--max-hours", type=float, default=float(env("MAX_HOURS", "11")),
                    help="end and replace the broadcast after this long (YouTube archives 12 h)")
    ap.add_argument("--stall-sec", type=float, default=60)
    ap.add_argument("--report-sec", type=float, default=600)
    ap.add_argument("--test-output", help="write FLV here instead of YouTube (no Lambda calls)")
    ap.add_argument("--test-seconds", type=float, default=20)
    args = ap.parse_args()
    if not args.test_output:
        args.test_seconds = None

    relay = Relay(args)

    def on_signal(signum, _frame):
        log(f"signal {signum}; stopping")
        relay.stop.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    return relay.main()


if __name__ == "__main__":
    sys.exit(main())
