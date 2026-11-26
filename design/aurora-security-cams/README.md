# Exfoliation Overhead cameras (Amcrest) → Pi 5 → YouTube

The two **Amcrest security cameras** in the Aurora glovebox, **Exfoliation
Overhead 1** (`192.168.3.150`) and **Exfoliation Overhead 2** (`192.168.3.151`),
stream to YouTube through the **Pi 5** (the ex-OT-2 overhead HQ camera, now
the "cataloging stage overhead" stream). The Pi 5 reaches the cameras through
an Ethernet switch on its `eth0`. This follows the 2026-11-06 analysis in issue
#23 ([comment](https://github.com/borysgroup/aurora-cloud-infra/issues/23#issuecomment-6697495676)).

## Status (2026-11-19)

- **Streaming, installed for good.** `amcrest-relay@0` and `@1` on the Pi 5
  copy each camera's H.264 (no re-encode) to its own **unlisted** YouTube
  broadcast, in a **private** playlist per camera. They start at boot, so each
  of the Pi's scheduled reboots (05:00, 13:00, 21:00) starts fresh broadcasts,
  as for the picam. See [Pi 5 setup](#pi-5-setup-2026-11-19).
- **`eth0` has a fixed address,** `192.168.3.199/24`, from
  `amcrest-eth0.service`: no gateway, never the default route, an in-memory
  NetworkManager profile. `ip_forward` stays 0.
- **Camera clocks fixed.** The Pi runs chrony and serves NTP to the camera
  subnet only. Both cameras sync to it every 10 minutes, on Mountain time with
  the US DST rule, so DST changes need nothing. See [Camera clocks](#camera-clocks).
- **No audio,** as intended. The cameras' microphones stay disabled; the relay
  sends a silent track because YouTube expects one.
- **Vision** on the stills: everything but the glovebox interior and any
  face blurred before publishing, with the Epson segmented on every frame; the
  chip tray read from both views; lens intrinsics; both cameras calibrated
  together; and a CAD reconstruction of the interior, part by part. See
  [Vision](#vision).
- **No pan/tilt/zoom.** See [Angle and image controls](#angle-and-image-controls).
- **Camera outage, 2026-11-19 to 2026-11-23.**
  - **Exfoliation Overhead 1 (`.150`)** has not answered since 2026-11-19
    21:54 UTC (no ARP reply; `eth0` up with `.199`). It is probably the camera
    the lab took down to fit other equipment. Its relay stays `failed`
    (open item 9).
  - **Exfoliation Overhead 2 (`.151`)** dropped on 2026-11-20; its relay
    ended the broadcast at 18:12 UTC. It came back on 2026-11-23 at 20:36 UTC
    (13:36 MST), after one NTP request at 20:20 UTC and a few minutes off
    again. It is aimed as before: features in a new frame sit a median 1.5 px
    from `vision/masks/reference_cam1.jpg`. Its clock is right. Its relay was
    restarted by hand at 20:43 UTC and streams again, with health "good".
  - **The scene in Overhead 2 has changed:** the chip tray is off the gantry
    stage, a clear acrylic rack stands on the deck, and the Epson's arm 2 is
    parked in the frame's upper right.
  - The picam was unaffected throughout.
- **A segmentation model for the Epson,** for live blurring, trained here on
  mixed-reality images from Epson's own CAD. See
  [Epson segmentation model](#epson-segmentation-model-trained-2026-11-20).

## Stills (2026-11-19 18:22 UTC)

Grabbed within 2 s of each other with `pull_feed.py N still`. Before
publishing, [`vision/privacy_blur.py`](vision/privacy_blur.py) keeps sharp
only what is known to be the glovebox interior, segments the Epson on every
frame so it stays sharp wherever it is, and blurs everything else and any
faces (see [Privacy blur](#privacy-blur)). No one was in either frame.

| Exfoliation Overhead 1 (`192.168.3.150`) | Exfoliation Overhead 2 (`192.168.3.151`) |
|---|---|
| ![Exfoliation Overhead 1](captures/2026-11-19_1822Z_cam0_192.168.3.150.jpg) | ![Exfoliation Overhead 2](captures/2026-11-19_1822Z_cam1_192.168.3.151.jpg) |
| Wide view: the Epson SCARA, the microscope, the exfoliator and the chip tray | Close view: the XY gantry with the chip tray and the antechamber-end wall; the Epson's arm 2 passes just under the camera, out of focus at the lower right, and is blurred |

The earlier stills in `captures/` (00:23 and 16:38 UTC) are re-blurred the
same way.

## Camera settings (read 2026-11-19)

Read with [`read_camera_config.py`](read_camera_config.py) (admin login over
stdin, `getConfig`/`getCaps` only). Both cameras are configured identically:

| Stream | Enabled | Codec | Size | fps | GOP | Rate control | Bitrate |
|---|---|---|---|---|---|---|---|
| Main (`subtype=0`) | yes | H.264 Main | 1920x1080 | 20 | 40 (2 s) | CBR | 4096 kbit/s |
| Sub 1 (`subtype=1`) | **no** | H.264 Main | 704x480 | 20 | 40 | CBR | 512 kbit/s |
| Sub 2 (`subtype=2`) | **no** | H.264 Main | 704x480 | - | - | CBR | 1024 kbit/s |

Audio is disabled on every stream (`AudioEnable=false`). The sensor is 5 MP,
but the main stream is set to 1080p.

Measured over 12 s on the Pi 5 ([`pull_feed.py`](pull_feed.py) `N packets 12`):
19.97 fps, 4208 and 4270 kbit/s, keyframes exactly 2.0 s apart, no B-frames.

Other settings seen:

- **On-screen text:** channel title `IPC` (the default) bottom left, date and
  time top right. A title per camera would identify the feeds on YouTube.
- **Image:** `Flip=false`, `Mirror=false`, `Rotate90=0`, infrared off,
  day/night auto.
- **Sessions:** the cameras' active-user list showed only the read itself, so
  no web UI or SDK client (such as an NVR) was logged in. RTSP clients don't
  appear in that list (the relays' own sessions didn't), so it can't rule out
  another RTSP viewer.
### Camera clocks

**Found** (read 16:45 UTC): on both cameras `NTP.Enable=false` (server
`time.windows.com`, unreachable without an internet path), time zone
`NTP.TimeZone=26` (GMT-06:00, "CentralAmerica") and `Locales.DSTEnable=false`.
The burned-in clocks read 1 h 01 min 48 s (`.150`) and 1 h 01 min 41 s (`.151`)
ahead of Mountain Standard Time: an hour from the wrong zone, the rest drift.

**Changed** (16:47 UTC, [`camera_time.py`](camera_time.py) `ntp`, admin login
over stdin, one camera at a time, both read back):

| Setting | Before | After |
|---|---|---|
| `NTP.Enable` | `false` | `true` |
| `NTP.Address` | `time.windows.com` | `192.168.3.199` (the Pi 5's `eth0`) |
| `NTP.TimeZone` | `26` (GMT-06:00) | `27` (GMT-07:00) |
| `NTP.UpdatePeriod` | `10` | `10` (minutes) |
| `Locales.DSTEnable` | `false` | `true` |
| `Locales.DSTStart` / `DSTEnd` | 2nd Sunday of March 02:00 / 1st Sunday of November 02:00 | unchanged |

Straight after, both cameras showed the Pi's time to the second (09:47:32 MST
at 16:47:32 UTC), and chrony on the Pi listed both as clients.
`NTP.TimeZoneDesc` still reads `CentralAmerica`: the firmware didn't update
that label, and the time shown is GMT-07:00.

So the overlay shows local time: MST now, MDT from the second Sunday of March,
with the camera switching by itself, and NTP from the Pi removing drift every
10 minutes. The switch itself can only be seen on 2027-03-14. For UTC on the
overlay instead, set `NTP.TimeZone=0` and `Locales.DSTEnable=false`.

**The NTP server.** Debian's `chrony` package replaced systemd-timesyncd on the
Pi 5 (default Debian pool sources, stratum 3 at install).
[`pi5/aurora-cams.conf`](pi5/aurora-cams.conf), in `/etc/chrony/conf.d/`,
allows clients from `192.168.3.0/24` only. Until chrony has synchronised (after
a reboot without network, say), it answers as unsynchronised, so the cameras
keep their own time rather than taking a wrong one.

### Angle and image controls

The cameras can't be aimed remotely. Each reports:

- `ptz.cgi?action=getStatus` → `400 Bad Request`, and the PTZ protocol caps hold
  only `AutoFocus=false`.
- `devVideoInput.cgi?action=getCaps`: `ElectricFocus=false`, `Iris=false`,
  `SyncFocus=false` (fixed lens, no motorized zoom or focus), but `Flip=true`,
  `Mirror=true`, `Rotate90=true`.
- ONVIF lists no PTZ service (only `device`, `media`, `media2`, `imaging`,
  `analytics`, `events`).

So the view only changes by hand, by loosening the turret and re-aiming it.
Remotely, the image can be flipped, mirrored or rotated 90°, and exposure,
day/night and infrared can be changed. A "digital zoom" would mean cropping on
the Pi, which needs a re-encode instead of the copy relay.

## Relay to YouTube

### How it works

[`amcrest_relay.py`](amcrest_relay.py) runs on the Pi 5, one instance per
camera:

1. Probes the camera (about 3 s). If it doesn't answer, it exits without asking
   for a broadcast, so a camera that is down leaves no empty scheduled
   broadcasts behind.
2. Calls the picam Lambda (the one in the Pi 5's `my_secrets.py`) with `end`,
   then `create`, as `device.py` does. The Lambda creates the stream key and
   the broadcast and adds the broadcast to the workflow's playlist.
3. Runs `ffmpeg`: RTSP over TCP in, `-c:v copy` (no decode or encode), a silent
   AAC track added (`anullsrc`, 128 kbit/s, because YouTube expects audio), FLV
   out to YouTube's **RTMPS** ingest.
4. Restarts `ffmpeg` against the same broadcast if it exits or makes no
   progress for 60 s. The broadcast has auto-stop off, so it resumes. After 5
   quick failures in a row it exits and leaves the next step to systemd.
5. Ends and replaces its broadcast after 11 h, so none runs past YouTube's
   12 h archive limit even when the Pi's 8-hourly reboot is held off.
6. On `SIGTERM` (stop or reboot) it stops `ffmpeg` and calls `end`, so the
   broadcast closes cleanly and its archive is kept.

`--test-output FILE` writes a short local FLV instead (no Lambda calls), for
checking the camera side.

### Secrets

- **Viewer login:** read from `~/.config/aurora-security-cams/cams.env` on the
  Pi. `ffmpeg` gets the camera through an `ffconcat` file (mode 600, in a
  mode-700 runtime directory) holding the credentialed RTSP URL, so the login
  never appears on a command line or in the process list. ffmpeg 7.1 can't
  load `-i` from a file (`-/i` is rejected). The concat demuxer's `option`
  lines carry `rtsp_transport tcp` and the socket timeout through (checked:
  the relays' `ffmpeg` has no UDP sockets).
- **Lambda URL:** parsed (not imported) from the picam's `my_secrets.py`, or
  taken from `$LAMBDA_FUNCTION_URL`.
- **Logs:** every line `ffmpeg` prints is redacted (RTSP logins, stream keys,
  video IDs), and the relay never logs the stream key, video ID or broadcast
  URL, so the journal is safe to read out. (`device.py` itself does print its
  stream URL to the journal.)

### Playlist privacy

The Lambda adds each new broadcast to the first playlist whose title contains
the workflow name. Only if none exists does it create
`"<workflow> Livestreams Playlist"`, **with the broadcast's privacy**. So a new
workflow's first `create` decides the playlist's privacy for good. To get a
private playlist with unlisted broadcasts, as the picam devices have:

1. Run the relay once with `--privacy private` for about a minute: this creates
   the private playlist (and a short private broadcast).
2. From then on, run it with `--privacy unlisted` (the default, and what the
   units use).

A cleaner fix would be an optional `playlist_privacy_status` field in
`create_broadcast_and_bind_stream` in
[`borysgroup/streamingLambda`](https://github.com/borysgroup/streamingLambda/blob/main/chalicelib/ytb_api_utils.py)
(default `private`).

### Names

| Slot | Camera | `CAM_NAME` | `WORKFLOW_NAME` (and playlist) |
|---|---|---|---|
| `_0` | `192.168.3.150` | `amcrest-150` | `Exfoliation Overhead 1` |
| `_1` | `192.168.3.151` | `amcrest-151` | `Exfoliation Overhead 2` |

Broadcast titles read `Exfoliation Overhead 1 stream amcrest-150, <date> UTC
<time>`. The Lambda matches **substrings** for both `end` (which ends every
live broadcast whose title contains the workflow name) and the playlist lookup.
So a workflow name must not contain, or be contained in, another device's
name: `Exfoliation Overhead 1` and `... 2` don't overlap each other or
`Cataloging stage overhead`, but adding an `Exfoliation Overhead 10` later
would let camera 1's `end` end it. Renaming starts a new playlist (and needs the
private first run again). The cameras' on-screen title is still `IPC`.

### Why RTMPS, and what it costs

The Pi 5's `stream-watchdog.sh` restarts `device.service` when the RTMP
**port 1935** socket with the most bytes ACKed stops growing. A relay on port
1935 could hide a stalled picam stream, or, once it stalls itself, make the
watchdog restart a healthy picam stream. So the relay rewrites the Lambda's
`rtmp://a.rtmp.youtube.com/live2/<key>` to
`rtmps://a.rtmps.youtube.com:443/live2/<key>` (same key). During the test,
`ss` showed exactly one port-1935 socket (the picam's), and the watchdog
logged nothing.

The cost is upload. Each relay sends about **5.7 Mbit/s** for a 4.4 Mbit/s
camera feed, about 28 % more. That fits ffmpeg's RTMP client writing 128-byte
chunks, each of which becomes its own TLS record (about 29 bytes of overhead).
Plain RTMP should need about 4.6 Mbit/s per camera (an estimate, not
measured). To get that back, make the
watchdog look only at the picam's own socket (add
`cgroup /system.slice/device.service` to its `ss` filter), then run the relays
with `--no-rtmps`. That changes the picam's watchdog, so it was not done here.

### Measured on the Pi 5 (2026-11-19, both relays running)

| | Before | With both relays |
|---|---|---|
| `wlan0` upload | 0.6 Mbit/s | 12.5 Mbit/s (5.7 + 5.7 relays, 0.64 picam, plus TCP/IP) |
| `eth0` download | 0 | 8.8 Mbit/s |
| Load average | 0.08 | 0.08 to 0.3 |
| Relay CPU | | about 3 % of one core each (copy, plus AAC of silence) |
| SoC temperature | 51.8 °C | 52.7 °C |
| TCP retransmits on the YouTube sockets | | under 0.1 % |
| Picam on YouTube | health `ok`, `bitrateLow` | unchanged (`ok`, `bitrateLow`) |
| `device.service` | 0 restarts | 0 restarts |

Wi-Fi was 5.8 GHz at -34 dBm with an 86.6 Mbit/s link rate. Both relays held
stream health `good`. The only issue YouTube raised was `audioBitrateLow` (the
silent track), which the picams get too. In total the relays add about
11 Mbit/s of sustained upload, roughly 5 GB per hour.

### What is on YouTube

On *Aurora PCL Hardware Streams*, all playlists **private**:

| Playlist | Holds |
|---|---|
| `Exfoliation Overhead 1 Livestreams Playlist`, `... 2 ...` | a 1-minute private broadcast (16:48 UTC on 2026-11-19, which created the playlist), then the unlisted broadcasts from 16:50 UTC on; each reboot of the Pi adds one per camera |
| `Aurora security cam 150 Livestreams Playlist`, `... 151 ...` | the first test (2026-11-19 00:22 to 04:00 UTC): a 1-minute private broadcast, a 3 to 4 minute unlisted one and an unlisted one of about 3.5 h |

Checked with the read-only token at 16:51 UTC: both relays live, `unlisted`,
stream health `good`, no configuration issues; the picam on the same Pi
unchanged (`ok`, `bitrateLow`). The upload token can't delete or edit videos,
and nothing was deleted.

## Pi 5 setup (2026-11-19)

| What | Where | Notes |
|---|---|---|
| `amcrest-eth0.service` | `/etc/systemd/system/`, enabled | creates the in-memory NetworkManager profile `cam-link` at boot: `192.168.3.199/24`, no gateway, `ipv4.never-default`, no DNS, no IPv6, duplicate-address detection, autoconnect priority 50 so it comes back after a link drop (the DHCP profile `netplan-eth0` has 0) |
| `amcrest-relay@0`, `@1` | `/etc/systemd/system/amcrest-relay@.service`, enabled | `~/aurora-security-cams/amcrest_relay.py` as `vcl`, names from `~/.config/aurora-security-cams/relay-N.env` (mode 600, no secrets), `Nice=10`, at most 3 starts an hour |
| chrony | Debian package (replaced systemd-timesyncd) | `/etc/chrony/conf.d/aurora-cams.conf`: serves `192.168.3.0/24` only |

Unchanged: `device.service` (0 restarts after the install), the watchdog and
reboot timers, `ip_forward=0`, the default route on `wlan0`, `cams.env`.

**Why `.199`:** the segment has no DHCP server, `.199` drew no reply to a
duplicate-address probe (`arping -D`) on 2026-11-19, and every session since
2026-11-11 has used it without a conflict. If someone keeps an address plan for
this network, `.199` should go in it. The `.1` gateway that never answers
doesn't matter to the relay; while nothing answers there, the cameras have no
route to the internet. If a router ever appears at `.1`, they would have one.

Install, as done here (on the Pi 5, from a checkout of this directory):

```bash
mkdir -p ~/aurora-security-cams && cp amcrest_relay.py ~/aurora-security-cams/
install -m 600 systemd/relay-0.env systemd/relay-1.env ~/.config/aurora-security-cams/
sudo apt-get install chrony    # replaces systemd-timesyncd
sudo install -m 644 pi5/aurora-cams.conf /etc/chrony/conf.d/ && sudo systemctl restart chrony
sudo cp systemd/amcrest-eth0.service systemd/amcrest-relay@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now amcrest-eth0.service
# new workflow names only: one private run per camera first (see Playlist privacy)
sudo systemctl enable --now amcrest-relay@0.service amcrest-relay@1.service
```

Stop or undo:

```bash
sudo systemctl disable --now amcrest-relay@0 amcrest-relay@1   # ends both broadcasts
sudo systemctl disable --now amcrest-eth0                      # eth0 back to no address
sudo apt-get install systemd-timesyncd                          # replaces chrony; the cameras lose their time source
```

## Vision

Scripts in [`vision/`](vision/) work on stills from `pull_feed.py`; results
are in [`vision/out/`](vision/out/). The raw stills stay off the repo, because
they show the lab around the glovebox. Below, camera 1 and camera 2 are
Exfoliation Overhead 1 (`.150`) and 2 (`.151`); the scripts call them `cam0`
and `cam1`, after their `cams.env` slots.

### Privacy blur

[`vision/privacy_blur.py`](vision/privacy_blur.py) `--cam N IN.jpg OUT.jpg`
keeps a pixel sharp only if it is known to show the glovebox interior. The
walls on both long sides are clear, so most of each frame's edge is the room,
seen through them, and it is blurred:

1. **Static interior:** [`vision/masks/inside_camN.png`](vision/masks), built
   once per view by [`vision/build_inside_mask.py`](vision/build_inside_mask.py)
   from [`vision/inside_masks.json`](vision/inside_masks.json). That file
   holds hand-drawn polygons for the deck, the walls and the bulk of the
   equipment, plus point prompts for SAM 2.1 (`sam2.1_b`, through
   `ultralytics`), which outlines each piece of equipment that stands in front
   of a window to the pixel. The robot's moving parts are not in this mask.
2. **The Epson, wherever it is:** SAM 2.1 runs again on every frame. Its
   prompts sit only on parts of the robot that never move: the base, the riser
   and the controller box, which Epson's T-B drawing shows fixed to the base.
   Negative prompts sit on the room next to it. SAM returns the robot in its
   current pose, arm included.
   - A prompt whose patch no longer matches the reference is dropped, for
     example when the arm passes in front of it.
   - Only the part inside the camera's `robot_zone` is kept.
   - Only pixels that the reference frame also had as robot, or that have
     changed since, are kept. A mask that spills onto the unchanged room
     behind the robot is cut back.
   - If the segmentation misses part of the arm, that part is blurred, never
     the room. On the reference frame, the upper part of arm 2's housing is
     blurred for this reason.
   - Overhead 2 sees no fixed part of the Epson, only arm 2, which passes
     just under the camera: its housing at the right edge and a black unit on
     it, out of focus at the lower right. Both are simply blurred.
   - About 3 s per frame on 4 CPU cores.
   - `--robot yolo` runs the trained model from
     [Epson segmentation model](#epson-segmentation-model-trained-2026-11-20)
     on the robot zone instead, with the same zone and reference checks.
3. **Change guard:** interior pixels that differ from
   [`vision/masks/reference_camN.jpg`](vision/masks) (the blurred frame the
   mask was built on), in a blob that touches the blurred region, are blurred
   too. This covers equipment moved away from a window, which would otherwise
   expose the room through the static mask. Changes in the middle of the deck,
   such as the stage moving, are not touched.
4. **Faces:** deface's CenterFace model (`deface` 1.5.0 with onnxruntime) on
   the whole unmodified frame, at deface's default threshold of 0.2, and an
   elliptical blur over each detection.
5. **Burned-in date and time** are kept: only small near-white strokes with a
   dark outline are copied back, so no patch of a bright background behind
   the clock comes through.

On the 18:22 UTC frames this keeps 61.3 % of Overhead 1 and 62.5 % of
Overhead 2 sharp. The robot's segmentation has only been seen in its parked
pose; the arm did not move during this work.

Re-run `build_inside_mask.py --cam N FRAME.jpg` after re-aiming a camera or
moving equipment that stands in front of a window, and check the reference it
writes.

This covers the published stills, not the live streams. The cameras' own
privacy masks are solid boxes and would also apply to any other viewer, such
as a recorder.

### Live blur on the Pi 5 (measured 2026-11-19)

The stills pipeline can't run live: SAM 2.1 takes about 3 s per frame on the
runner's four x86 cores, and the Pi 5 has no hardware video encoder. What the
Pi can do was measured on the Pi itself with
[`vision/live_bench.py`](vision/live_bench.py), at `nice 19` on two of its four
cores while the picam and the Overhead 2 relay ran. The picam uses about
0.5 core. Results are in
[`vision/out/live_bench_pi5.json`](vision/out/live_bench_pi5.json).

**Decode, blur and re-encode** per camera, on a 20 s copy of Overhead 2's main
stream (1080p, 20 fps). One core at 20 fps is 50 ms per frame.

| Output | CPU per frame | Cores at 20 fps |
|---|---|---|
| Decode only | 9.4 ms | 0.19 |
| 1080p, x264 superfast, no blur | 39.8 ms | 0.80 |
| 1080p, static-mask blur, x264 superfast | 66.0 ms | 1.32 |
| 720p, x264 superfast, no blur | 27.0 ms | 0.54 |
| 720p, static-mask blur, x264 superfast | 46.7 ms | 0.93 |
| 720p, static-mask blur, x264 ultrafast | 41.7 ms | 0.83 |
| 720p, static-mask blur, x264 veryfast | 52.5 ms | 1.05 |

The blur is done in `ffmpeg`: the frame at 1/8 scale, Gaussian-blurred and
scaled back, with the sharp frame laid over it through the mask. In this test
`ffmpeg` decoded the mask PNG again for every frame. On a single thread the
720p superfast run took 43.5 ms per frame, so one core keeps up with one camera
(23 fps).

**Segmentation models,** onnxruntime 1.32 on the Pi's CPU, median of 15 runs:

| Model | Input | 1 thread | 2 threads |
|---|---|---|---|
| YOLO11n-seg | 640 x 640 | 518 ms | 293 ms |
| YOLO11n-seg | 320 x 320 | 113 ms | 63 ms |
| YOLO11n-seg | 256 x 256 | 73 ms | 40 ms |
| EdgeSAM (point prompts, like SAM) | encoder 1024 x 1024, then decoder | 2.54 s + 0.28 s | 1.58 s + 0.19 s |

YOLO11n-seg was timed with Ultralytics' COCO weights. A model trained only on
the Epson has the same network and costs the same.

**What fits.** Both cameras at 1080p would need 2.6 cores on top of the
picam, which leaves too little. At 720p:

| | Cores |
|---|---|
| Picam, as now | 0.5 |
| Overhead 2: static mask, 720p | 0.9 |
| Overhead 1: static mask, 720p | 0.9 |
| Overhead 1: YOLO11n-seg on the robot zone, 5 times a second, one thread | 0.7 |
| **Total, of 4** | **3.0** |

How the Epson step would work live:

- The model runs on Overhead 1's `robot_zone` (1350 x 700 px), fed at
  448 x 232 in a 448 x 256 input: 123 ms on one thread, measured with the
  trained model (see
  [Epson segmentation model](#epson-segmentation-model-trained-2026-11-20)),
  plus about 20 ms for pre- and post-processing.
- Between runs, each frame reuses the last mask, cut back to the pixels that
  have not changed since the frame it was computed on. A spot the arm leaves
  changes from robot to room and is blurred at once. So a lagging mask can
  blur part of the arm but never shows the room. During a fast move, the arm
  is blurred where it crosses a window until it slows down.
- Overhead 2 needs no robot step: its view of the arm is blurred anyway.
- Faces: the static mask, the robot step and the change guard already keep
  the room blurred. A face detector at 1 to 2 fps could act as a tripwire that
  blurs the whole frame for a few seconds on a hit.

What it needs first:

- **Training data.** COCO has no class for a robot arm, so the model has to be
  trained on this camera's view of the Epson. Done without footage of the arm
  moving, from Epson's CAD: see
  [Epson segmentation model](#epson-segmentation-model-trained-2026-11-20).
  A few minutes of the arm moving, recorded on the Pi with
  `pull_feed.py 0 record SECONDS OUT.mp4`, are still the best test.
- **720p output** for both cameras.

Alternatives:

- **Joint angles instead of a model.** If the lab's software can publish the
  Epson's joint angles, the calibrated CAD model (`reconstruction/scene.py`)
  can draw the arm's mask for each frame directly. The current fit (IoU 0.64
  in Overhead 1) is too loose for that unless the model is refined or the mask
  shrunk.
- **Hardware.** A Raspberry Pi AI HAT+ (Hailo) on the Pi 5's free PCIe
  connector would take the model off the CPU, but the encoders are the larger
  cost. A small x86 machine with Intel Quick Sync on the camera switch could
  encode both feeds in hardware at 1080p.
- **EdgeSAM** takes SAM 2.1's prompts and needs no training. At about 1.8 s
  per frame on two cores, it could update the mask only every few seconds.

### Epson segmentation model (trained 2026-11-20)

[`vision/robotseg/`](vision/robotseg/) trains the YOLO11n-seg for the live
robot step without any footage of the arm moving. The training images are
mixed reality: real frames of each camera with Epson's own CAD robot drawn
into them at random joint angles. Everything ran on the runner's four CPU
cores, no GPU.

**Epson's CAD.** Epson publishes the T6-B602S as a STEP assembly (base, arm 1,
arm 2, shaft, user duct) on its support page.
[`reconstruction/epson_cad.py`](reconstruction/epson_cad.py) downloads it,
meshes each link with gmsh and articulates it at J1, J2, Z and U, within the
manual's limits (J1 ±132°, J2 ±150°, Z 200 mm). The STEP file and the meshes
are not redistributed here.

**Where the robot is.** [`fit_pose.py`](vision/robotseg/fit_pose.py) fits the
base (J1 position, height and yaw) and the parked joint angles to the SAM 2.1
silhouette in Overhead 1. Silhouette IoU in the robot zone is 0.78, against
0.57 for the hand-built model in `scene.py`. Much of the remaining gap is the
SAM mask's: it misses the top of arm 2's housing and includes the riser block
and the cables above the controller. Result:
[`vision/out/epson_pose.json`](vision/out/epson_pose.json).

**Training images** ([`synth.py`](vision/robotseg/synth.py), drawn by
[`epson_render.py`](vision/robotseg/epson_render.py)):

- **Plate:** one of the stored frames of either camera. The parked robot (its
  CAD silhouette and SAM mask, dilated) is cut out and filled with a room
  from a robot-free shot of the AURORA video: labs, people, a server room.
- **Outside the glovebox:** often replaced by an unblurred room crop. The
  stored stills are blurred there and the live feed is not. This also puts
  people, benches and screens next to the arm as hard negatives.
- **Robot:** Epson's CAD at random J1, J2, Z and U over the full range (a
  third near the parked pose), drawn through the camera's calibrated pose and
  lens distortion. The renderer is a painter's algorithm in OpenCV: about
  0.3 s per image, no OpenGL. The label is the rendered mask, so it fits the
  drawn robot exactly.
- **Also randomised:** the base position (σ 8 mm), height (σ 5 mm) and yaw
  (σ 1°), the camera's rotation (σ 0.4°), a stand-in end effector, blur,
  noise, JPEG quality, and occluders cut from the plate.
- **Crop:** Overhead 1 images are its robot zone (1350 x 700 px), as the live
  step would run it. Overhead 2 images are the whole frame.

Two models were trained:

| | v1 | v2 (committed) |
|---|---|---|
| Images (train + validation) | 1,600 + 160 | 2,000 + 200 |
| Robot's look | flat-shaded, random grey level, tint and light | 55 % textured: each face takes its colour from Overhead 1's 18:22 frame, where the camera saw it at the parked pose, and keeps it at any other pose |
| Cameras | the two calibrated ones | also 40 % random pinhole cameras, 0.35 to 1.5 m from the robot, from any side, up to 65° above it, over a room crop or a plate |
| Training | from COCO weights, 10 epochs, 29 min | from v1, 8 epochs, 24 min |
| Validation mask mAP50-95 (synthetic) | 0.90 (epoch 10, its own set) | 0.86 (epoch 7, its own set, with random cameras) |

**The video.** The [AURORA video](https://www.youtube.com/watch?v=moBCWzP9Izw)
(60 s) has two shots with a T6. It was downloaded through the Pi 5, because
YouTube blocks the runner's IP, at 800 KB/s, and is not redistributed.
[`label_video.py`](vision/robotseg/label_video.py) labels both shots with SAM
2.1's video predictor. The "retrieval" shot shows another T6, and SAM left
part of that robot out, so it is not used. The "transfer" shot shows this
glovebox's T6 moving under a handheld camera. It is held out as a test.

**Results on real frames held out from training**
([`evaluate.py`](vision/robotseg/evaluate.py), with the ONNX model run by
[`yolo_onnx.py`](vision/robotseg/yolo_onnx.py) exactly as on the Pi;
[`vision/out/robotseg_eval.json`](vision/out/robotseg_eval.json) for v2):

| Test frames | v1: IoU / precision / recall | v2: IoU / precision / recall |
|---|---|---|
| Overhead 1, the unblurred 00:23 still, arm parked | 0.80 / 0.93 / 0.85 | 0.88 / 0.90 / 0.97 |
| Overhead 1, the three published (blurred) stills | 0.76 / 0.87 / 0.86 | 0.87 / 0.91 / 0.96 |
| AURORA video, transfer shot, 30 frames | 0.00 (nothing detected) | 0.03 / 0.07 / 0.03 |

- **Ground truth** is SAM 2.1 in both cases: point prompts on the stills, the
  video predictor on the shot. It has its own errors. On the blurred stills
  the top of arm 2's housing is patchy, so some of the model's "false
  positives" there are robot.
- **Independence.** v1 never saw a real pixel of this robot. v2's textures
  come from Overhead 1's 18:22 frame, so its Overhead 1 scores are not
  independent: same parked robot, same place (18:22 itself scores IoU 0.91).
  The video is independent for both: another camera, other light, the arm
  moving.
- **The video is a failure for both.** Neither model finds the robot in the
  handheld views, where it is close, large and cut off by the frame edge.
  Cropped nearer the training scale, a frame scores 0.5 to 0.6, so it is
  mostly viewpoint and scale, but v2's random cameras did not cover it.
  Treat the model as specific to the calibrated views.
- **Precision is what matters for privacy:** a false positive keeps a patch
  sharp. In the pipeline the robot mask is also cut to the robot zone, and to
  pixels that were robot in the reference or have changed since, as with SAM.

| v2 on two published stills | v2 on two held-out video frames |
|---|---|
| ![](vision/out/robotseg_cam0.jpg) | ![](vision/out/robotseg_video.jpg) |

Green: model and ground truth agree. Red: model only. Blue: ground truth only.

**On the Pi 5,** measured with [`bench_pi.py`](vision/robotseg/bench_pi.py) on
2026-11-20 (onnxruntime 1.32, 448 x 256 input, median of 20 runs at `nice 19`
while the picam streamed):

| | 1 thread | 2 threads |
|---|---|---|
| Forward pass, median | 123 ms | 68 ms |
| Forward pass, 90th percentile | 147 ms | 95 ms |

That matches the stock model's 113 ms at 320 x 320, scaled for the larger
input. Letterboxing, NMS and the masks add 2.3 ms on the runner, where the
forward pass takes 12.5 ms. The Pi is about 10 times slower here, so that is
roughly 20 ms more on the Pi (an estimate: the Pi has no OpenCV, which
`yolo_onnx.py` needs). Five runs a second on one thread is then about 0.7 of
a core, the figure now in the "What fits" table above. The picam had 0
restarts before and after, and nothing was left on the Pi.

**Use:** `python vision/privacy_blur.py --cam 0 --robot yolo IN.jpg OUT.jpg`
runs the model ([`vision/robotseg/models/epson_t6_seg.onnx`](vision/robotseg/models/epson_t6_seg.onnx),
11.6 MB) on the robot zone instead of SAM. SAM stays the default for stills.

**To rebuild.** The STEP and the video are fetched, not stored here. The
unblurred 00:23 stills are in this branch's history at fa312e2; `synth.py`
tells the cameras apart by `cam0`/`cam1` in the file name.

```
python reconstruction/epson_cad.py                 # Epson's STEP -> meshes in ~/.cache
yt-dlp -f 137 -o VIDEO.mp4 https://www.youtube.com/watch?v=moBCWzP9Izw   # from a residential IP
cd vision/robotseg
python fit_pose.py                                  # -> ../out/epson_pose.json
python label_video.py VIDEO.mp4 VLABELS             # SAM 2.1 labels for both T6 shots
S="python synth.py --raw raw0023_cam0.jpg raw0023_cam1.jpg --video VIDEO.mp4"
$S --out V1 -n 1600 --seed 1 && $S --out V1VAL -n 160 --seed 2
python train.py --syn-train V1 --syn-val V1VAL --work W1 --epochs 10
$S --out V2 -n 2000 --seed 11 --textured 0.55 --virtual 0.4
$S --out V2VAL -n 200 --seed 12 --textured 0.55 --virtual 0.4
python train.py --syn-train V2 --syn-val V2VAL --work W2 --epochs 8 --init W1/train/weights/best.pt
python evaluate.py --stills raw0023_cam0.jpg --video-labels VLABELS
```

**Limits:**

- **No frame of Overhead 1 with the arm away from its parked pose exists
  yet.** The first live footage of the arm moving is the real test.
  `pull_feed.py 0 record` can capture it. `evaluate.py`'s SAM prompts assume
  the parked pose, so those frames need their own.
- **A camera that comes back in another place** needs
  `calibrate_two_view.py`, the inside masks and `fit_pose.py` redone, then new
  training images and a retrain: about 30 min on four cores.
- **The end effector** in the training renders is a stand-in box. The real
  tool, as the AURORA video shows it, is in the CAD reconstruction since
  2026-11-25 but not yet in these renders.

### Chip tray

[`vision/chip_tray.py`](vision/chip_tray.py) `CAM0.jpg CAM1.jpg --out DIR`
finds the tray in each view, fits the pocket lattice with a homography,
rectifies it, and classifies every pocket. It then compares the two views in
one tray frame: row 0 is the handwritten edge, and columns keep the same
handedness seen from above. That mapping comes from tray features only, not
from which pockets are full, so the occupancy comparison is an independent
check.

![Chip tray, both views](vision/out/chip_tray_views.png)

On the 16:38 UTC stills:

- The tray is a **6 x 10 grid** (60 pockets). The chamber model's "8 x 8" was
  a different tray.
- **Both views agree on all 60 pockets:** 56 chips, 3 empty, 1 misplaced.
- **Empty:** (column 2, row 5), (0, 8) and (1, 9).
- **Misplaced:** the chip at (0, 1) is rotated about 11° in its pocket (10.9°
  from camera 1, 12.5° from camera 2, the same way round). It is centred and
  of normal size. Most chips sit within 4°; the threshold is 10°, so this flag
  depends on it.
- As a separate check, of the 4 rotations and flips that fit a 6 x 10 grid,
  only the feature-based one matches all 60 pockets (the others match 54).
- Fit residuals: 0.5 px median (pitch 20 px) on camera 1, 0.2 px (pitch 14 px)
  on camera 2. Camera 2 sees the tray at a low angle, so it can't resolve
  rotations under about 5° or offsets under about 0.1 pitch.

Per-pocket results, angles and offsets are in
[`vision/out/chip_tray.json`](vision/out/chip_tray.json). The tray moves with
the stage, so the script searches a region of interest per camera (an option)
rather than fixed pixels; an edge row or column with no chips at all would be
missed.

### Lens intrinsics

Both cameras are the same model, so they are estimated together and checked
against each other. All values are for the 1920x1080 main stream, with the
principal point taken at the frame centre (not estimated).
[`vision/intrinsics.py`](vision/intrinsics.py) writes
[`vision/out/intrinsics.json`](vision/out/intrinsics.json).

**Published** (Amcrest spec sheet, which matches Dahua's IPC-HDW2541T-S (S2)):
1/2.7" CMOS, 2.8 mm F1.6 M12 lens, FOV H 111° / V 58° / D 132°, largest main
stream 2960x1668. The sensor and its pixel pitch are not published.

**Distortion:** strong barrel. The two-parameter division model
`p_u - c = (p_d - c) / (1 + l1 r² + l2 r⁴)` (r in units of 1000 px) is fitted
to 7 long straight edges ([`vision/plumbline.py`](vision/plumbline.py),
[`vision/plumb_lines.json`](vision/plumb_lines.json)): l1 = -0.289,
l2 = -0.090, with 0.48 px residual. Per camera it is (-0.298, -0.085) and
(-0.280, -0.109), so the two lenses agree. OpenCV's 8-coefficient rational
model reproduces it to 0.004 px (in `intrinsics.json`); the 5-coefficient form
is off by up to 16 px in the corners.

**Focal length (px):**

| Source | Camera 1 | Camera 2 |
|---|---|---|
| Published 2.8 mm, assuming a 2.0 µm pitch and the whole 2960-px width scaled to 1920 | 908 | 908 |
| Published FOV H / V / D, with the measured distortion | 1004 / 1073 / 949 | same |
| Chip tray as a planar target ([`vision/tray_focal.py`](vision/tray_focal.py)) | 1062 (1015 to 1111) | 1089 (998 to 1199) |
| Registration with f free | 1474 ± 328 | 1170 ± 1054 |
| **Adopted** | **1070 ± 45** | **1070 ± 45** |

The chip-tray value uses the orthogonality constraint on the tray's
homography after undistortion, which holds whatever the pocket pitch. Without
the distortion correction the same method gives inconsistent numbers (1311 and
1679, and worse for the other constraint), which also supports the distortion
fit. With f = 1070 px, the pose fits below have lower residuals than with 950
(6.5 against 7.6 px, and 0.8 against 1.4 px), and the implied FOV is
H 107.6° / V 58.1° / D 126.7°. The vertical matches the published 58°.
1070 px is 13 to 18 % above the whole-sensor value, which fits a 1080p stream
scaled from a central window of about 2560x1440 rather than from the whole
2960x1668 area. No published source confirms that.

### Camera poses

[`vision/calibrate_two_view.py`](vision/calibrate_two_view.py) fits both
cameras together, in the frame of the measured chamber model
(`design/aurora-chamber` on branch `claude/issue-23-20261109-2222`; x along
the box from the antechamber-end wall, y from the open side, z up from the
deck). Results are in [`vision/out/cameras.json`](vision/out/cameras.json).

- **What ties the views together** is the chip tray. Its 6 x 10 lattice is
  fitted in both frames, and the pocket correspondence between the views is
  known from tray features alone. That gives 60 shared points on a plane, with
  0.4 px (Overhead 1) and 0.18 px (Overhead 2) RMS residuals.
- **What places and scales the pair** are the chamber model's landmarks from
  [`vision/landmarks.json`](vision/landmarks.json): the microscope objective,
  the Epson's J1, the supply spool, the antechamber door hub and three deck
  ducts. They are weighted by the model's stated uncertainties.
- **Unknowns:** a shared focal length (fitted 1073 ± 39 px, against a prior of
  1070 ± 45), each camera's pose, and the tray's centre, yaw and pocket pitch.
  The tray is assumed level.

| | Camera centre (mm) | Looking |
|---|---|---|
| Overhead 1 (`.150`) | (348, 294, 700) | along the box, 16° towards the far window, 40° down |
| Overhead 2 (`.151`) | (1015, 338, 702) | back towards the antechamber wall, 36° towards the far window, 46° down |

Both cameras come out about 90 mm below the 790 mm ceiling, which fits a turret
mount. The chamber model's own landmarks do not agree with each other at this
level: once the two cameras are tied together by the tray, they miss by 9 to
38 px (worst: the Epson J1, 38 px). The model's numbers come from the
walkthrough video and are good to a few centimetres.

**Independent checks:**

- **The two tape reels, matched by eye in the two frames,** triangulate with
  gaps of 2 and 9 mm between the two rays.
- **The gantry's X-axis ball screw**, back-projected separately from each view,
  lands on the same line: y = 497 to 520 mm from Overhead 1, and 501 to 518 mm
  from Overhead 2. The model's axis runs along it.
- **The antechamber door** back-projected onto the wall plane has a
  180-190 mm radius. Its 15-inch antechamber datasheet value is 190 mm.
- **Breadboard holes:** a breadboard lying on the deck in Overhead 2 has its
  hole rows 25 mm apart at a top height of 30 to 37 mm. That is a metric
  breadboard (M6 on 25 mm) of usual thickness on the deck.
- **The QR sign's bottom edge** back-projects to 242 mm. The model calls the
  sign US Letter landscape (279 mm), so either it is a smaller sheet or the
  annotated corners are not its corners.

The tray pocket pitch comes out at 9.5 ± 1.1 mm (a 57 x 95 mm pocket field). A ruler
reading of the tray would pin the scale at about 1 %.

### CAD reconstruction

[`reconstruction/`](reconstruction/) models the glovebox interior as
individual parts in the same frame. Each part takes its size from a
datasheet or standard size where one exists, its position from the two
calibrated cameras, and its colour from the frames. It is built in two
layers:

- [`reconstruction/scene.py`](reconstruction/scene.py) holds the
  positions, sizes and sources of every part (the first, primitive-only
  model is still there as `build_outline`).
- [`reconstruction/scene_detail.py`](reconstruction/scene_detail.py) draws
  each part in detail at those positions, from the part library in
  [`reconstruction/detail.py`](reconstruction/detail.py), and gives it a
  finish ([`reconstruction/materials.py`](reconstruction/materials.py)) and
  its printed marks ([`reconstruction/decals.py`](reconstruction/decals.py)).

[`reconstruction/out/parts.json`](reconstruction/out/parts.json) lists each
part with its finish, bounds, face count and source.

![The model from the open side (ceiling and open-side window hidden), Blender Cycles](reconstruction/out/render_open_side.jpg)

| Overhead 1: published frame, and the model through the same camera and lens | Overhead 2 |
|---|---|
| ![](reconstruction/out/view_cam0.jpg) | ![](reconstruction/out/view_cam1.jpg) |

| Inside, towards the Epson and microscope | Inside, towards the gantry and exfoliator |
|---|---|
| ![](reconstruction/out/render_epson.jpg) | ![](reconstruction/out/render_gantry.jpg) |

From the far end: [`render_far_end.jpg`](reconstruction/out/render_far_end.jpg);
from above: [`render_top.jpg`](reconstruction/out/render_top.jpg). The model
blended over each frame, with its edges in yellow (the geometric check):
[Overhead 1](reconstruction/out/overlay_cam0.jpg),
[Overhead 2](reconstruction/out/overlay_cam1.jpg). The camera views apply the
cameras' measured lens distortion
([`reconstruction/build_reconstruction.py`](reconstruction/build_reconstruction.py)),
so they compare pixel for pixel with the photos. Each view has its own
exposure, as the cameras' auto exposure does: the camera views are 0.3 stop
brighter than the outside views, the views with the ceiling removed 0.8 to
1.2 stops darker.

**Detail (2026-11-24):**

- **Epson T6-B602S:** Epson's own STEP (base with the controller box, both
  arms, the shaft and the user duct), meshed finely by gmsh
  (`epson_cad.links(hi=True)`: about 200k faces), on a machined aluminium
  riser. The STEP models the EPSON wordmark in relief on both sides of arm 2
  (81 x 18 mm); those faces get the print's blue. A badge, the warning
  triangle and a rating label on the base are decals, placed by eye from
  Overhead 1 (within about 40 px of the photo).
- **Breadboards:** a skin with every M6 hole cut (25 mm grid, 12.5 mm from
  the edges), 2 mm corner radii, steel posts.
- **Steppers:** NEMA 17/23 to the flange drawings: chamfered die-cast end
  caps, the laminated stack with its grooves, the boss, a D-flat shaft, the
  four mounting holes, the cable exit with four leads, and the round labels
  on the motors that show one.
- **Linear axes:** threaded SFU1605 screws (16 mm, 5 mm lead, a rounded
  groove), flanged ball nuts, BK12/BF12 end supports, HGR15 rails with
  their profile and four blocks with end seals, the carriage plate, and
  couplings to the motors.
- **Drag chains:** link by link (side plates and crossbars, 17 mm pitch)
  along the old paths.
- **Ducts:** Panduit Type G with its base, finger walls on a 12.7 mm pitch
  and cover lips, cover off as in the frames.
- **Tape reels:** revolved flanges and tape, the hub with a 12-spline bore.
- **Exfoliator:** machined housing with screws, the Teknic ClearPath servo
  (Teknic's CAD since 2026-11-25, with its label rectified from Overhead 1),
  the EXFOLIATOR label on its stage.
- **Microscope:** revolved objective (front lens, taper, green 20x band,
  knurled grip), nosepiece, the BX3-URA filter drum with its scale, filleted
  module housings, the camera, the ASI stage as two carriages with the
  acrylic insert and its screws, the mounting plate with its relief cut,
  the light source's fins, the THORLABS mark on the Thorlabs box, slotted
  docking fixtures with cap screws.
- **Chip tray:** 60 real pockets, each chip as a thin chamfered square
  (rotated where `chip_tray.json` says so), and the handwritten edge as a
  texture rectified from Overhead 1.
- **Shell:** window panes, flanges, outer clamp bars and acorn nuts on the
  studs (every ~95 mm, from the chamber model), the dished antechamber
  door with its hub, clamp bar and centre screw, and the QR sign's visible
  lower part as a texture rectified from Overhead 2.
- **Cameras:** both Amcrest balls at their calibrated poses (mounts not
  modelled).
- **Finishes:** brushed stainless (deck, walls, frames, door),
  bead-blasted and machined aluminium, ground steel, black oxide and
  anodising, painted housings, plastics, rubber, glass. They are PBR
  materials in the glTF; Blender adds the brushed grain and the glass.
- **Printed marks:** the arm's EPSON wordmarks are Epson's own relief. The
  badge, THORLABS and EXFOLIATOR are typeset in Liberation Sans, which is
  close to the printed lettering but not the vendors' logo artwork. Marks
  too small or specific to typeset (the QR sign, the handwriting, the
  servo's label) are textures taken from the published stills through the
  calibrated camera and lens.

**What the detail changed:**

- **The Epson's pose.** Fitted to Overhead 1's silhouette alone, Epson's CAD
  reaches IoU 0.78 (`vision/out/epson_pose.json`, used for the segmentation
  training data), but that pose parks J3 at x = 1416 mm, past the far end of
  the 1200 mm box: Overhead 1 looks along the box and can't see the arm's
  depth. `fit_epson_cad.py` keeps J2 and J3 near the two-view fit of the
  outline (which also used Overhead 2's view of arm 2) and refits: IoU 0.633
  in Overhead 1 (the outline had 0.64), base underside at 182 mm, J3 at
  (1188, 359) mm, 81 mm from the outline's J3. The segmentation training
  data (`vision/robotseg/`) was rendered on the base pose in
  `epson_pose.json`, which sits 34 mm (across) and 47 mm (in height) from
  this one.
- **No glove ports.** The chamber model assumes 8-inch ports at x = 348 and
  852 mm, z = 400 mm on both long sides. All four spots show the room through
  clear window in the unblurred 00:23 UTC frames, so none are modelled.

**Still approximate:** the stage and docking fixtures are built to their
sizes and the frames, not from vendor CAD (the BX3 microscope modules use
Evident's CAD since 2026-11-25, below); the backs of parts no camera sees are
inferred. Cables and tubing traced by colour were
added on 2026-11-25 (below); black and grey cables are still missing.

**How each part is placed:**

- **Two views:** the chip tray (its lattice in both views, with every chip
  drawn in its pocket from `chip_tray.json`: 3 empty, 1 rotated) and the two
  tape reels (ray intersections).
- **Silhouette fit, two views:** the Epson T6-B602S. The first model's shape
  was a hand-built outline from Epson's dimensioned T-B drawing (T-B manual
  Rev.13, pp. 43, 45, 52 and 162; kept as `scene.build_outline`):
  - base flange and sloped column
  - controller box (226 x 130 x 193 mm, underside at 272 mm), fixed to the
    base on a rear column, with its top-rear chamfer
  - arm 1, 103 mm wide, from 60 mm behind J1 to 51 mm past J2
  - arm 2, 135.5 mm wide, its top falling towards the tip
  - the ø20 J3 shaft (410 mm long, 200 mm stroke)
  - the 32 mm corrugated duct between fittings over J1 and J2, flattened to
    stay under the ceiling

  J1's position, the base's facing and height, the riser height and both arm
  angles are fitted to the robot's SAM 2.1 masks in both frames
  ([`reconstruction/silhouette.py`](reconstruction/silhouette.py)), within
  J1 ±132° and J2 ±150°. Overlap: IoU 0.64 in Overhead 1 and 0.82 in
  Overhead 2. The fit puts the base's underside at 161 mm (the chamber model
  reads 150 to 180) and parks J3 63 mm from the microscope objective.
  - **Epson's own CAD:** the detailed model draws the robot from Epson's
    STEP instead (below), posed by
    [`reconstruction/fit_epson_cad.py`](reconstruction/fit_epson_cad.py).
  - **The black object in Overhead 2:** this fit identifies the out-of-focus
    black object at its lower right. The model alone matches Overhead 2's
    white housing plus that object at IoU 0.77, so the object rides on
    arm 2. It is modelled as a black unit on arm 2; its make is not known.
- **Datasheet modules:**
  - the microscope is Olympus/Evident BX3 modules on a custom plate: a
    BX3-URA illuminator (drum 180 mm, body 402.5 mm long with the lamp port),
    a U-DP dual port (88 x 151 x 57 mm) and a U-TLU tube (ø60 x 57.6 mm).
    Since 2026-11-25 all three are Evident's own CAD (`evident_cad.py`)
  - a 20x objective (green ring)
  - the stage is probably an ASI OE-1250 (228.6 x 215.9 x 45.1 mm)
  - the large black THORLABS box has no connectors, so it is drawn as a
    breadboard platform rather than a controller
- **One view, onto a known plane:** the breadboards (edges back-projected at
  their heights), the gantry's posts, plate, screws and motors (Overhead 2),
  the exfoliator housing, stage and motors, the microscope's elevated
  breadboard, the Thorlabs platform and the two black docking fixtures
  (Overhead 1), and the tape measure on the deck.
- **Standard sizes:** M6 holes on a 25 mm grid (12.5 mm from the edge) on
  12.7 mm Thorlabs breadboards; NEMA 23 (57.2 mm) and NEMA 17 (42.3 mm)
  steppers; 16 mm ball screws; Panduit Type G 1 x 2 in slotted duct
  (32 x 54 mm).
- **The shell** is the chamber model's: 1200 x 1120 x 790 mm, sloped long
  windows. The far end is drawn as a window frame, because the room shows
  through it in Overhead 1.

**Accuracy:**

- **Parts placed from both views** reproject closely in both frames. The tray
  is within 0.4 px, and the two reels within 2 and 9 px.
- **The Epson** overlaps its masks at the IoU above (0.64 and 0.82) as the
  outline. Epson's CAD overlaps Overhead 1's mask at IoU 0.633; Overhead 2's
  mask of arm 2 wasn't kept, so the CAD isn't scored there.
- **Parts placed from one view** sit right in that view, but their depth along
  the ray rests on an assumed height. In the other view they can be off by 20
  to 50 mm.
- **Hidden geometry is inferred:** the breadboards' extents behind equipment,
  the far end, and the backs of parts.
- **Cables:** blue cables, green tubing and red wires traced in the stills since
  2026-11-25 (below); black and grey cables are not modelled.

**Files:** `out/glovebox.glb` (every part as its own node, with PBR
finishes and textured decals; opens in any glTF viewer),
`out/stl/<group>.stl` (one per group, decimated to at most 40k faces for
GitHub's STL viewer), the renders above and `out/parts.json`. The GLB and
`stl/epson.stl` contain a tessellation of Epson's published T6-B602S CAD, and
the GLB and `stl/exfoliator.stl` one of Teknic's ClearPath CAD; both STEP files
are downloaded at build time and not stored here. Rebuild with

```
cd reconstruction
python fit_epson_cad.py                    # optional: refit the Epson (writes out/epson_cad_pose.json)
xvfb-run -a python cables.py               # optional: re-trace the cables (out/cables.json)
BLENDER=/path/to/blender-4.2/blender xvfb-run -a python build_reconstruction.py
python motion.py                           # the Epson's allowable motion (out/epson_motion.*)
# the AURORA video (frames dumped as FRAMES/NNNN.jpg, from a residential IP):
xvfb-run -a python video_register.py FRAMES          # out/video_cameras.json, about 15 min on 4 cores
BLENDER=... xvfb-run -a python build_reconstruction.py --renders-only --video-frames FRAMES \
    --views video_transfer_612 video_transfer_640    # needs out/video_robot_poses.json
```

(numpy, opencv, trimesh, shapely, pyvista, scipy, scikit-image, gmsh,
fast-simplification; torch and kornia for LoFTR in `video_register.py`;
Blender 4.2 LTS for the Cycles renders, about 15 minutes on 4 CPU cores.
Without Blender the build still writes the model and the overlays.)

### Refinement from the AURORA video, vendor CAD and motion (2026-11-25)

**The video.** The [AURORA video](https://www.youtube.com/watch?v=moBCWzP9Izw)
(2026-07-22, 60 s, 1080p at 29.97 fps) was downloaded again through the Pi 5
at 800 KB/s (YouTube blocks the runner) and gone through frame by frame. Two
shots show this glovebox:

- **Sample Transfer, frames 600 to 662:** the Epson carries the chip tray past
  the docking fixtures, under a handheld camera.
- **Exfoliation, frames 675 to 746:** a close-up of the exfoliator head: a
  Montalvo X-series load cell (50 N / 10 lb), a blue tape reel, STEPPERONLINE
  NEMA 23 steppers, a ball-screw stage marked "400mm", a drag chain, and blue
  tubing in yellow printed clips.

The other shots are other stations: the Utah sample-retrieval T6, optical
cataloging on an ASI stage, archival, and the Arkansas 2D-QMaP glovebox.

**Structure from motion doesn't work on this footage.** COLMAP 4.2 (pycolmap)
was run on every frame of both shots:

- The default mapper finds no initial pair.
- With relaxed thresholds, the self-calibrated focal length runs off: fx 3700
  against fy 1460 px with an OPENCV model, and 2500 to 17,000 px with
  SIMPLE_RADIAL.
- The handheld camera pans more than it moves, so the scene gives too little
  parallax to calibrate itself.

**Registration against the calibrated cameras instead**
([`reconstruction/video_register.py`](reconstruction/video_register.py)).
Each frame is placed in the chamber frame through the published stills, whose
cameras are calibrated:

1. LoFTR (kornia, outdoor weights) matches the frame against the Overhead 1
   still. On frame 604 it finds 108 consistent matches. SIFT finds 31, nearly
   all on the Epson's base labels: the change of viewpoint and scale is too
   large for it.
2. MAGSAC on the fundamental matrix keeps the consistent matches.
3. Each matched still pixel is lifted to 3D through Overhead 1's pose and lens
   onto the model's depth.
4. PnP with RANSAC places the frame.
5. One focal length and one radial term for the shot (SIMPLE_RADIAL,
   principal point at the centre) and every frame's pose are refined together
   by robust least squares over all frames.

| Shot | Frames | Placed | Focal length (px) | k1 | Horizontal FOV | Median error | Inliers a frame |
|---|---|---|---|---|---|---|---|
| Sample Transfer | 63 | 63 | 1064 ± 4 | −0.008 | 84.1° | 4.4 px | 79 |
| Exfoliation | 72 (every sixth tried) | 0 | | | | | |

- **The video camera** has a focal length of 1064 px at 1920 x 1080 (about 21 mm full-frame equivalent).
  - **Distortion:** almost none is left (k1 −0.008 ± 0.004), as expected of a phone's corrected video.
  - **Position:** about (375, 185, 531) mm, 185 mm in from the open side and 531 mm above the deck. The open-side window must have been off in July.
  - **Movement:** 134 mm between the first and last frame, mostly a pan. Per-frame positions scatter by about 13 mm around a 9-frame mean.
  - **The first pass,** on every third frame, agrees: 1072 ± 6 px.
- **The Exfoliation shot doesn't register.** None of the 12 frames tried (every sixth) could be placed. LoFTR finds only 23 to 30 matches a frame against both stills, against about 130 a frame in the transfer shot. That is too few for PnP, which needs 25 inliers.
  The head has been rebuilt since July: the reels are red in November, not
  blue.
- **What the 3D points rest on:** the model. Parts that moved between July and
  November drop out as outliers rather than bending the pose, which is why
  only about 60 % of the matches are inliers.

The model from two registered frames, rendered with Cycles through the video
camera (its focal length and radial term), with the robot posed as in each
frame. The pose comes from the shaft collar and J2 picked in the frame, then
inverse kinematics on the fitted base
([`out/video_robot_poses.json`](reconstruction/out/video_robot_poses.json)).
The frame is on the left. The chip tray stays on the gantry in the model,
while in the video the gripper is carrying it:

![Frame 612 of the AURORA video (left) and the model through the registered camera (right)](reconstruction/out/video_transfer_612.jpg)

![Frame 640 (left) and the model (right)](reconstruction/out/video_transfer_640.jpg)



**What the video and the references added to the model:**

- **Teknic ClearPath servo.** The pin-fin unit with the QR label is a Teknic
  ClearPath CPM NEMA 23 integrated servo. The evidence:
  - its pin-fin rear cap, QR label and green status LED in the video
  - Teknic's own CAD has the same rear cap

  The scene now uses Teknic's STEP for the CPM-231x (keyed shaft), from
  [teknic.com](https://teknic.com/files/downloads/CPM-231x.zip) without a login
  ([`clearpath_cad.py`](reconstruction/clearpath_cad.py), meshed by gmsh,
  60k faces). Its rear cap faces Overhead 1, as in the still. The stack length
  is assumed. The STEP is fetched at build time and not stored here.
- **The Epson's end effector,** from the Sample Transfer shot and a
  [Borys lab photo](https://www.boryslab.com/) of this T6:
  - a dark-blue collar where the shaft leaves arm 2
  - a stainless body on the shaft end, with a loop of clear-green tubing
  - a black parallel gripper with finger plates
  - three teal tubes from arm 2 into the hollow shaft's top
  - the orange status lamp on the base

  Sizes are scaled from the ø20 mm shaft. The November stills don't show the
  tool.
- **Cables and tubing**
  ([`reconstruction/cables.py`](reconstruction/cables.py), `out/cables.json`).
  They were the most visible gap in both views.
  - **Traced by colour** in both published stills, inside the glovebox mask:
    21 runs of blue cable, 6 runs of green tubing, 5 runs of red wire.
  - **Lifted onto the model's depth:** the nearest surface behind each run,
    less the cable's radius.
  - **Limit:** a cable is right in the view it was traced from, and lies on
    the surfaces under it from any other view.
  - **Not traced:** black cables, which can't be told from black anodised
    parts by colour, and grey ones.

**Equipment identified** (desk research; vendor CAD only where it downloads
without a login):

| Part | Identification | CAD or drawing |
|---|---|---|
| Pin-fin servo | Teknic ClearPath CPM NEMA 23 (medium confidence on the frame size; stack length unknown) | STEP, no login; [dimensional drawing](https://teknic.com/files/downloads/23xx%20CPM%20Dimensional%20Drawing.pdf): 59.1 mm flange, ø38.10 mm pilot, ø9.53 mm keyed shaft |
| Load cell | Montalvo X-series, Size 0, standard mount, 50 N / 10 lb (high confidence on series and size) | Body ø55 x 50 mm, M12 4-pin connector (datasheet X-US-12); Montalvo's CAD needs an account |
| Steppers | StepperOnline NEMA 23 and NEMA 17 | Datasheet PDFs without a login: NEMA 23 flange 57.3 mm, NEMA 17 42.3 mm; STEP needs an account |
| "400mm" stage | Low confidence: FUYU FSK40/FSL40 (40 mm wide) or a generic SFU1605 stage (80 mm wide) | Measuring the base width would settle it |
| "THORLABS" box | Probably a Thorlabs Nexus breadboard seen edge-on | STEP per item without a login (found later the same day, see [Vendor CAD](#vendor-cad-what-downloads-freely-and-what-needs-a-sign-in)) |
| Glovebox | LC Technology Solutions, custom; 15 in round antechamber | No public drawings; LC Tech provides SolidWorks models on request |
| Amcrest turret | IP5M-T1179EW-AI-V3: ø109.9 x 100.9 mm, mounting holes on ø84 mm | Manual drawing |

Further references, not used yet: the
[MonArk Foundry site](https://www.monarkfoundry.org/) has photos of the
exfoliator outside the box and of the optical cataloger. Montana State's
YouTube video `LR3gITOB_OI` ("Shaping the Future of Science at the MonArk
Quantum Foundry") may show the hardware.

**Allowable motion**
([`reconstruction/motion.py`](reconstruction/motion.py),
[`out/epson_motion.json`](reconstruction/out/epson_motion.json)):

- **Method:** every (J1, J2) pair within the manual's limits (J1 ±132°,
  J2 ±150°), on a 2° grid, is posed with Epson's CAD on the fitted base, with
  the shaft up.
- **Collision test:** points on arm 1, arm 2, the unit on arm 2 and the shaft
  are tested against the box (walls, sloped windows, ceiling) and against a
  10 mm voxel grid of every other part.
- **Left out:** the user duct, which flexes with J2.

- **Result** (re-run on 2026-11-25 with Evident's microscope CAD): 25 % of the manual's J1 x J2 range is free. 56 % puts the arm through a wall, a window or the ceiling, and 19 % through equipment, mostly with the gripper, which hangs to 234 mm above the deck with the shaft up.
- **J1** is usable from −98° to +50° of its ±132°. Beyond that range, the arm runs into a wall or a window.
- **The J3 shaft can reach** x = 337 to 1128 mm and y = 275 to 1013 mm (the green area below).

![Epson joint space and J3 reach inside the box](reconstruction/out/epson_motion.png)

**Checked against the video.** The two robot poses read off the video
(below), frames 612 (J1 −48.6°, J2 81.6°) and 640 (J1 −33.0°, J2 42.5°), are
within Epson's limits:

- **Frame 612** is collision-free in the model.
- **Frame 640** puts arm 2 through the November supply reel (z = 386 to
  460 mm). That fits the head having been rebuilt since July.

**A conflict in the model, found by the sweep.** At the parked pose fitted to
Overhead 1 (J1 25.1°, J2 34.2°), arm 2:

- reaches x = 1245 mm, 45 mm past the far-end window of the 1200 mm box
- overlaps the microscope's U-DP dual port and camera

Arm 2 and the shaft really do sit by the microscope, so one of these is off:
the base pose, the box length, or the microscope's placement. A tape-measured
inside length of the box would decide between the first two.

### Vendor CAD: what downloads freely and what needs a sign-in

Checked on 2026-11-25. Two corrections to the table above: Thorlabs offers
STEP files on each item page without a login, and Evident's BX3 modules
download directly too.

**Needs a free account:**

| Part | Product page | CAD | Sign-up |
|---|---|---|---|
| Montalvo X-series load cell (10 lb / 50 N) | [X-series](https://montalvo.com/products/narrow-web-pulley-load-cells-x-series/) | [standard-mount drawings](https://montalvo.com/download/x-series-load-cell-drawings-standard-mount/), [flange-mount](https://montalvo.com/download/x-series-load-cell-drawings-flange-mount/) (PDF, DWG, SLDPRT) | [create an account](https://montalvo.com/create-an-account/) |
| StepperOnline NEMA 23, e.g. 23HS22-2804S | [23HS22-2804S](https://www.omc-stepperonline.com/nema-23-bipolar-1-8deg-1-26nm-178-4oz-in-2-8a-2-5v-57x57x56mm-4-wires-23hs22-2804s), [all NEMA 23](https://www.omc-stepperonline.com/nema-23-stepper-motor) | STEP on the product page's Download tab | [register](https://www.omc-stepperonline.com/register) |
| StepperOnline NEMA 17, e.g. 17HS19-2004S1 | [17HS19-2004S1](https://www.omc-stepperonline.com/nema-17-bipolar-59ncm-84oz-in-2a-42x48mm-4-wires-w-1m-cable-connector-17hs19-2004s1), [all NEMA 17](https://www.omc-stepperonline.com/nema-17-stepper-motor) | same | same |
| HIWIN HGR15 rail, HGH15CA block | [HG series](https://hiwin.com/products/linear-guideways/hg-series/) | [configurator](https://configure.hiwin.com/?pl=Linear%20Guideways) (or [hiwinsupport.com](https://www.hiwinsupport.com/cad_download/linear_guideway.aspx)) | sign-up at the end of the configurator |
| FUYU FSK40 stage (one candidate for the "400mm" stage) | [FSK40 in FUYU's CAD library](https://catalogs.fuyumotion.com/#/pages/product/detail?id=10004) | Download button on that page | email or QR-code login |

The motor models are typical ones: which StepperOnline motors these are isn't
known. The StepperOnline pages refuse automated access, so those two links
come from a search index and weren't opened.

**On request:** LC Technology Solutions builds its gloveboxes in SolidWorks
and shares the models per project
([contact form](https://lctechinc.com/contact/); the
[LC-1 page](https://lctechinc.com/lc-1-standard-glovebox-systems/) for the
standard boxes).

**No sign-in:**

| Part | CAD | Status |
|---|---|---|
| Evident BX3-URA, U-DP, U-TLU | [BX3-URA](https://adobeassets.evidentscientific.com/content/dam/mis/3d-objectives/BX3-URA.zip), [U-DP](https://adobeassets.evidentscientific.com/content/dam/mis/3d-objectives/U-DP.zip), [U-TLU](https://adobeassets.evidentscientific.com/content/dam/mis/3d-objectives/U-TLU.zip) (from [OEM downloads](https://evidentscientific.com/en/downloads/oem)) | used, below |
| Thorlabs breadboards, e.g. [MB3030/M](https://www.thorlabs.com/item/mb3030_m), Nexus [B3030A](https://www.thorlabs.com/item/B3030A) | STEP on each item page | not used: the boards in the box are cut to other sizes, and the THORLABS box isn't identified |
| ASI OE-1250 stage | [technical drawings](https://www.asiimaging.com/support/technical-drawings/) ("OE-1250 ASSEMBLY (CATALOG MODEL).zip") | not fetched: the site's bot check blocks the runner |
| Panduit G1X2 duct | 2D only (DWG, DXF, PDF on the [product page](https://www.panduit.com/en/products/wire-routing-management-protection/wiring-duct-accessories/wiring-duct-duct-covers/g1x2lg6.html)) | the duct is already built to it |

**Evident's CAD in the model** ([`reconstruction/evident_cad.py`](reconstruction/evident_cad.py)).
The hand-built BX3-URA, U-DP and U-TLU are replaced by Evident's own STEP
files: appearance models, meshed by gmsh at build time and not stored here.

- **Placement:** stacked on the optical axis that the hand-built modules
  used, with the illuminator's body on the nosepiece mount (z = 325 mm).
  - The BX3-URA is turned so its filter drum points towards the Epson, as in
    Overhead 1.
  - The U-DP's quarter turn was chosen by its outline over Overhead 1: at 0°
    and 180° it is wider than the white block under the tube, at 90° and 270°
    it matches it, and 270° fits the block's right edge slightly better.
- **Height:** the vendor stack is 17 mm taller than the hand-built one
  (215 mm against 198), so the camera on top moved up by that much.
- **Not changed:** the objective, nosepiece, camera, ASI stage and mounting
  plate.

### Photo textures, a cross-view check, reach and an articulated model (2026-11-25)

**Photo textures** ([`reconstruction/phototexture.py`](reconstruction/phototexture.py),
`out/glovebox_photo.glb`). Every static part now carries the colours the two
cameras saw on it: labels, wear, stains, the microscope drum's scale, and the
cables lying on surfaces.

- **How:**
  - each group of parts gets texture coordinates from xatlas, at 1.5 mm per texel
  - a ray through every pixel of each published 18:22 UTC still (lens distortion undone) is cast into the model with Embree, with the windows left out so rays pass through the glass
  - the first surface each ray hits takes the pixel's colour, weighted by how squarely and how closely the camera saw it
- **Pixels left out:**
  - outside the glovebox-interior mask (the blurred room)
  - on the robot (its SAM mask: the robot moves)
  - the burned-in clock and title
  - next to a jump in depth, where a pose error of a few mm would move one part's colour onto its neighbour
  - views more oblique than 63° (they fade in between 63° and 41°)
- **Where the cameras disagree:** where both cameras saw a texel and their colours differ by more than about 35 levels, one of them is looking at something the model lacks, and the texel falls back towards the part's finish. The deck takes only texels both cameras saw and agree on, because cables lying above it would otherwise be painted far from where they are.
- **White balance:** Overhead 2's colours are scaled to Overhead 1's over the texels both saw (gains B 1.15, G 1.05, R 0.99).
- **Not textured:** the robot, the cables, the camera housings and the decals keep their finishes. The robot's fitted pose (IoU 0.63) isn't tight enough to carry a projected texture.
- **Unseen surfaces** keep their own finish: the texture's metallic-roughness map holds each part's finish where no camera saw it and turns matte where the photo covers it. Its spare red channel carries the photo coverage, which `blender_render.py` uses to emit the photo's colour there instead of lighting it a second time.
- **Limit:** anything the model lacks (black cables, clutter) is painted onto the surface behind it. From the cameras' own viewpoints that looks right; from elsewhere it shows as flat streaks.

| From the open side (Cycles) | Inside, towards the Epson and the microscope |
|---|---|
| ![](reconstruction/out/photo_open_side.jpg) | ![](reconstruction/out/photo_epson.jpg) |

Towards the gantry: [`photo_gantry.jpg`](reconstruction/out/photo_gantry.jpg);
from above: [`photo_top.jpg`](reconstruction/out/photo_top.jpg). Through the
cameras, published frame on the left:
[Overhead 1](reconstruction/out/photo_view_cam0.jpg),
[Overhead 2](reconstruction/out/photo_view_cam1.jpg). Those two reproduce the
photos by construction wherever the model has a surface, so they test
nothing; the cross-view check below does.

**Cross-view check** (`phototexture.py --check`, `out/crossview.jpg`,
`out/crossview.json`). This tests the geometry without any textures:

1. Each pixel of one camera is traced to the model's surface.
2. That surface point is looked up in the other camera's photo, if that camera sees it.
3. With perfect geometry and matte surfaces, the result reproduces the first camera's photo.

The score is the median local normalised cross-correlation (NCC, 15 x 15 px) over textured pixels, per part:

| Parts | Overhead 1 into 2 | Overhead 2 into 1 |
|---|---|---|
| Chip tray, holder and chips (placed from both views) | 0.47 to 0.51 | 0.49 to 0.51 |
| Thorlabs platform | -0.06 | -0.16 |
| Exfoliator stage carriage | -0.15 | -0.11 |
| Main breadboard | -0.02 | -0.04 |
| Exfoliator breadboard | 0.16 | 0.05 |
| All overlapping pixels | -0.01 | 0.08 |

![Cross-view check: each camera's photo carried through the model into the other camera](reconstruction/out/crossview.jpg)

Only the parts placed from both views pass. The parts placed from one view
are off in depth by enough that the other camera sees something else where
the model puts them, which fits the 20 to 50 mm the README already allowed
for them.

**Can the two photos place those parts?** [`reconstruction/refine.py`](reconstruction/refine.py)
slides each of the 11 parts or groups placed from one view along its source
camera's ray, ±100 mm in 10 mm steps. Sliding along that ray keeps the part
where it is in the source frame and moves it in the other one. At each step
the script scores how well the two photos agree on the part's pixels, both ways.
An offset is accepted only if it beats zero by 0.08 and is a single clear
peak.

- **None is accepted,** so every part stays where it was (`out/refine.png`, `out/refine.json`).
- **Five can't be tested:** the docking fixtures, the gantry's Y axis, the printed carriage, the tape measure and the loose breadboard. The other camera doesn't see enough of them.
- **The six tested give jagged curves.** Four have a second peak within 0.06 of the best one, 40 to 180 mm away (the Thorlabs platform's best is -40 mm at 0.20, its rival +90 mm at 0.14). The two breadboards gain less than 0.08 over zero.
- **Why:** the two cameras look at the deck from nearly opposite ends, so few surfaces look alike in both. A third viewpoint, or a few tape readings, would pin these parts.

![Two-camera agreement against the offset along the source camera's ray](reconstruction/out/refine.png)

**Where the Epson can pick and place** ([`reconstruction/reach.py`](reconstruction/reach.py),
`out/epson_reach.json`). This adds the vertical axis and the stations to
`motion.py`'s sweep:

- **Height map:** a ray cast straight down every 5 mm gives the top of whatever is on the deck.
- **Reach map:** inverse kinematics gives both elbow configurations for every 5 mm cell. A configuration counts when:
  - it is within Epson's limits
  - the arm clears the box and every part with the shaft up
  - it lies in the largest free region of joint space (1° grid), so the arm can get there without a collision

  The map then shows how low the gripper's fingertips get coming straight down: the 200 mm stroke, or the tallest part within 35 mm of the shaft, whichever is higher.
- **Fingertips:** 234 mm above the deck with the shaft up, 34 mm at the end of the stroke.

![Epson reach map and joint space](reconstruction/out/epson_reach.png)

What it finds:

- **Reachable area:** 0.27 m² of the deck. Over the free deck towards the far window, the fingertips get down to 34 mm.
- **The chip tray, where the stills show it,** is 610 mm from J1, 10 mm beyond the arm's 600 mm reach. The gantry moves the tray. Assuming its carriages keep 70 mm from the ends of their screws, the tray's travel is x = 350 to 605 mm, y = 342 to 432 mm. Of that travel, 10 % is a hand-off zone the J3 axis can reach with the arm clear: x = 535 to 605 mm, y = 377 to 432 mm. The nearest point of it is 12 mm from where the gantry parked the tray. For this check, the tray and its carriage don't count as obstacles, because the gripper takes the tray by its fork at the tray's height.
- **The ASI stage's sample insert** sits under the microscope, so the gripper can't come down onto it. The stage has to move the insert out first.
- **The docking fixtures conflict with the model.** Their tops (282 mm) are above the fingertips with the shaft up (234 mm), so the arm can't pass over them. The AURORA video shows the tray carried past them. So either the fixtures are lower than the 280 mm read off Overhead 1, or the tool is shorter than the length scaled from the video. A tape reading of the fixtures' height would settle it.
- **The AURORA video's poses:**
  - frame 612 is free, with 10 mm clearance
  - frame 640 hits the supply reel, as `motion.py` found: the head was rebuilt after July

**Articulated model** ([`reconstruction/urdf_export.py`](reconstruction/urdf_export.py),
`out/urdf/aurora_glovebox.urdf`). The cell as a URDF, which simulators and motion planners (ROS, MoveIt, PyBullet, Isaac) load directly:

| Link | Joint | Range |
|---|---|---|
| `glovebox` | fixed | every static part, one mesh |
| `epson_base` | fixed, at the fitted base pose | |
| `epson_arm1` | J1, revolute about z | ±132° |
| `epson_arm2` | J2, revolute, 325 mm out | ±150° |
| `epson_shaft` | J3, prismatic, down, 275 mm out | 0 to 200 mm |
| `epson_tool` | J4, revolute about the shaft | ±360° |

- **Joint values:** the same convention as `epson_cad.py`, so a pose read off the robot's controller can be set directly.
- **Velocity limits:** Epson's maximum operating speeds from the T-series manual's specification table (T6-602S: J3 1000 mm/s, J4 1800°/s). J1 and J2 have only a composite tool speed there (4180 mm/s), so they carry J4's value as a loose bound.
- **Check:** the script loads the URDF with yourdfpy and poses it at the parked pose and the two video poses. Every Epson link lands within 0.0001 mm of `epson_cad.posed()`.
- **Not modelled:** the gantry, exfoliator and stage axes are fixed in the URDF. Which carriage moves what is inferred, not known.

Rebuild (after `build_reconstruction.py`):

```
cd reconstruction
BLENDER=... xvfb-run -a python phototexture.py --check --render   # out/glovebox_photo.glb, out/crossview.*, out/photo_*.jpg
python refine.py                             # out/refine.json, out/refine.png
python reach.py                              # out/epson_reach.*  (~3 min)
python urdf_export.py                        # out/urdf/
```

(xatlas and embreex in addition to the packages above, and yourdfpy for the URDF check.)

## Earlier findings

### The camera segment (2026-11-11)

The switch is **not** an isolated two-camera island. It is a real
`192.168.3.0/24` network with about 9 hosts:

| Host | Vendor (OUI) | What it is |
|---|---|---|
| `192.168.3.150` | Amcrest | Security camera, slot `_0` |
| `192.168.3.151` | Amcrest | Security camera, slot `_1` |
| about 7 others | Dell / Lenovo-class / TI / others | PCs / NVR / lab devices (not probed) |
| `192.168.3.1` | none | Gateway the cameras ARP for, but **nothing answered**: no working router on this segment |

With no live gateway, the cameras have no path to the internet, so their
Dahua-based firmware can't be reached from outside and can't phone home. The
relay keeps it that way (no NAT, `ip_forward=0` on the Pi).

`eth0` is up at 1 Gb/s full duplex. Its own NetworkManager/netplan profile is
DHCP, and there is no DHCP server on the segment, so until 2026-11-19 it had
**no IP** by default and each session gave it a temporary in-memory address.
Since 2026-11-19, `amcrest-eth0.service` gives it `192.168.3.199/24` at boot
(see [Pi 5 setup](#pi-5-setup-2026-11-19)).

### The two cameras

- **Model:** Amcrest **IP5M-T1179EW-AI-V3** (5 MP turret, Dahua OEM),
  firmware `2.880.00AC003.0.R`, build 2025-03-19.
- **Open TCP ports:** `80` (web UI and CGI), `554` (RTSP, Digest auth),
  `37777` (Dahua SDK).
- **ONVIF:** Profile S on `/onvif/device_service`.
- **Latency:** about 0.3 ms round trip from the Pi 5.
- **RTSP URL:**
  `rtsp://<user>:<pass>@192.168.3.15x:554/cam/realmonitor?channel=1&subtype=0`
  (main stream). Never put a real one on a command line or in a log.

### Viewer accounts (2026-11-18)

Using the admin login, a non-admin `relay` account was created on each camera
for the YouTube relay.

- **What was changed on the cameras:** one new user per camera, `relay`, group
  `user`, `Sharable=true` (concurrent sessions allowed), memo `youtube-relay`,
  created with `userManager.cgi?action=addUser`. The request asked for
  `Monitor_01` (live view) only, but the firmware applied the group's full
  rights, so the account holds `Monitor_01` + `Replay_01` (live view and
  playback of recordings). It has no configuration, user-management or network
  rights: the user-management API answers it with `403`. The `admin` account is
  untouched.
- **Where the credentials live:** repo variables `AMCREST_CAM_USERNAME_<n>` and
  secrets `AMCREST_CAM_PASSWORD_<n>` (`_0` = `.150`, `_1` = `.151`), and on the
  Pi 5 in `~/.config/aurora-security-cams/cams.env` (directory `700`, file `600`,
  owner `vcl`), which holds `AMCREST_CAM_{HOST,USERNAME,PASSWORD}_<n>`. The
  admin logins (`AMCREST_CAM_ADMIN_{USERNAME,PASSWORD}_<n>`) are not stored on
  the Pi.
- **To undo:** `userManager.cgi?action=deleteUser&name=relay` with the admin
  login on each camera, and delete the `cams.env` directory on the Pi 5.


## Still open

1. **Names:** `Exfoliation Overhead 1` / `2` are in use for YouTube. Renaming
   again starts new playlists. The on-screen title is still `IPC` on both
   (`ChannelTitle`, one setting per camera, if wanted).
2. **DST:** the cameras' own DST rule takes over on 2027-03-14; that switch
   can't be checked before then.
3. **The network's owner,** if there is one: reserve `.199` for the Pi, and
   say whether the dead `.1` gateway is meant to be that way.
4. **Upload:** about 11 Mbit/s for both cameras over RTMPS, accepted. The
   watchdog change under [Why RTMPS](#why-rtmps-and-what-it-costs) would bring
   it to about 9 Mbit/s.
5. **Blurring the live streams,** if wanted: feasible at 720p (see
   [Live blur on the Pi 5](#live-blur-on-the-pi-5-measured-2026-11-19)). The
   Epson model now exists; it still needs checking on footage of the arm
   moving, and the relay would need the decode, blur and re-encode stage.
6. **Scale and the chamber model:** two tape readings would pin the scale to
   about 1 %. One is the chip tray's long side (the fit gives a 9.5 mm pocket
   pitch, about 95 mm for 10 pockets). The other is the glovebox's inside
   length (1200 mm in the model).
   The chamber model's landmarks disagree with each other by 9 to 38 px once
   the cameras are tied (see [Camera poses](#camera-poses)). Its QR sign also
   conflicts with the door.
7. **The black unit on the Epson's arm 2**, out of focus at Overhead 2's
   lower right, is placed by the robot fit but not identified.
8. **CAD fidelity:** the Epson (Epson's STEP), the ClearPath servo
   (Teknic's STEP) and the BX3 microscope modules (Evident's STEP) are vendor
   CAD; the rest is built to catalogue sizes and the frames. The Montalvo load
   cell, the StepperOnline motors, the HIWIN rails and a FUYU stage have CAD
   behind a free account, and LC Technology shares the glovebox's model on
   request (links in
   [Vendor CAD](#vendor-cad-what-downloads-freely-and-what-needs-a-sign-in)).
   The model's parked Epson pose conflicts with the box length and the
   microscope (same section): a tape-measured inside length would decide it.
9. **Relay restart limit:** a relay that can't reach its camera exits, and
   systemd allows 3 starts an hour (`StartLimitBurst`), so a camera that is
   off for more than about four minutes leaves its relay `failed` until the
   next reboot, even after the camera is back. On 2026-11-19, `.150` stopped
   answering at 21:54 UTC and its relay stayed down from 21:58. Restart by hand
   with
   `sudo systemctl reset-failed amcrest-relay@0 && sudo systemctl start amcrest-relay@0`.
   A relay that waits for its camera, instead of exiting, would avoid it.
   It happened again to both relays after the 2026-11-20 13:00 MST reboot,
   with both cameras off. On 2026-11-23, `.151` came back 35 minutes after
   the 13:00 MST reboot, and its relay was restarted by hand at 13:43 MST.

## Files

- [`amcrest_relay.py`](amcrest_relay.py): the relay (runs on the Pi 5).
- [`systemd/`](systemd/): the units and per-camera settings installed on the Pi 5.
- [`pi5/aurora-cams.conf`](pi5/aurora-cams.conf): chrony's NTP service for the camera subnet.
- [`camera_time.py`](camera_time.py): read or set the cameras' time zone, DST and NTP, with the admin login over stdin.
- [`pull_feed.py`](pull_feed.py): probe a feed, measure it, grab a still or record a clip,
  with the viewer login from `cams.env`.
- [`read_camera_config.py`](read_camera_config.py): read-only dump of the
  encoder, image and PTZ settings, with the admin login over stdin.
- [`probe_camera_link.py`](probe_camera_link.py): the read-only network recon
  from 2026-11-11 (`sniff` / `sweep` / `probe` / `discover`). It never sends
  credentials.
- [`vision/`](vision/): privacy blur (`privacy_blur.py`, `build_inside_mask.py`,
  `inside_masks.json`, `masks/`), chip tray, intrinsics (`plumbline.py`,
  `lensmodel.py`, `intrinsics.py`, `tray_focal.py`), the first per-camera
  registration (`register_chamber.py`) and the joint two-camera calibration
  (`calibrate_two_view.py`), and the Pi 5 live-blur benchmark
  (`live_bench.py`), with results in `vision/out/`.
- [`vision/robotseg/`](vision/robotseg/): the Epson segmentation model: CAD
  rendering through the calibrated cameras (`epson_render.py`), its pose fit
  (`fit_pose.py`), mixed-reality training data (`synth.py`), video labels
  (`label_video.py`), training (`train.py`), held-out evaluation
  (`evaluate.py`, ground truth in `gt/`), onnxruntime inference
  (`yolo_onnx.py`), the Pi 5 timing (`bench_pi.py`) and the model
  (`models/epson_t6_seg.onnx`).
- [`reconstruction/`](reconstruction/): the CAD reconstruction of the glovebox
  interior: positions and sources (`scene.py`), the detailed parts
  (`scene_detail.py`, `detail.py`), finishes (`materials.py`), printed marks
  (`decals.py`), Epson's own T6-B602S CAD, articulated (`epson_cad.py`) and
  posed (`fit_epson_cad.py`), Teknic's ClearPath CAD (`clearpath_cad.py`),
  Evident's BX3 modules (`evident_cad.py`), cables traced in the stills
  (`cables.py`), the AURORA video registered to the chamber
  (`video_register.py`), the Epson's allowable motion (`motion.py`) and
  pick-and-place reach (`reach.py`), photo textures and the cross-view check
  (`phototexture.py`), the photo-consistency test (`refine.py`), the URDF
  (`urdf_export.py`), the Cycles renders (`blender_render.py`), and its
  exports and renders in `out/`.
- [`captures/`](captures/): the stills above, blurred.
