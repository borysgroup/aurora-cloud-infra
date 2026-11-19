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

## Stills (2026-11-19 18:22 UTC)

Grabbed within 2 s of each other with `pull_feed.py N still`. Before
publishing, [`vision/privacy_blur.py`](vision/privacy_blur.py) keeps sharp
only what is known to be the glovebox interior, segments the Epson on every
frame so it stays sharp wherever it is, and blurs everything else and any
faces (see [Privacy blur](#privacy-blur)). No one was in either frame.

| Exfoliation Overhead 1 (`192.168.3.150`) | Exfoliation Overhead 2 (`192.168.3.151`) |
|---|---|
| ![Exfoliation Overhead 1](captures/2026-11-19_1822Z_cam0_192.168.3.150.jpg) | ![Exfoliation Overhead 2](captures/2026-11-19_1822Z_cam1_192.168.3.151.jpg) |
| Wide view: the Epson SCARA, the microscope, the exfoliator and the chip tray | Close view: the XY gantry with the chip tray and the antechamber-end wall; the microscope camera, out of focus, blocks the lower right |

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
2. **The Epson, wherever it is:** SAM 2.1 runs again on every frame, prompted
   on the robot's fixed base and controller box, with negative prompts on the
   room next to it. It returns the whole robot in its current pose, and only
   the part inside the camera's `robot_zone` is kept sharp. If the
   segmentation misses part of the arm, that part is blurred, never the room.
   About 3 s per frame on 4 CPU cores.
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

On the 18:22 UTC frames this keeps 61.5 % of Overhead 1 and 82.1 % of
Overhead 2 sharp (Overhead 2's lower right is the out-of-focus microscope
camera). The robot's segmentation has only been seen in its parked pose; the
arm did not move during this work.

Re-run `build_inside_mask.py --cam N FRAME.jpg` after re-aiming a camera or
moving equipment that stands in front of a window, and check the reference it
writes.

This covers the published stills, not the live streams. Running it on the
streams would mean decoding and re-encoding both 1080p feeds on the Pi 5,
which has no hardware encoder and already software-encodes the picam, and SAM
is far too slow there for 20 fps. A static mask (steps 1, 4 and 5 without the
robot) could run in `ffmpeg` at reduced resolution; the cameras' own privacy
masks are solid boxes and would also apply to any other viewer, such as a
recorder.

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
| Overhead 1 (`.150`) | (348, 294, 700) | along the box, 13° towards the far window, 40° down |
| Overhead 2 (`.151`) | (1015, 338, 702) | back towards the antechamber wall, 36° towards the far window, 46° down |

Both cameras come out about 90 mm below the 790 mm ceiling, which fits a turret
mount. The chamber model's own landmarks do not agree with each other at this
level: once the two cameras are tied together by the tray, they miss by 9 to
38 px (worst: the Epson J1, 38 px). The model's numbers come from the
walkthrough video and are good to a few centimetres.

**Independent checks:**

- **A tape reel matched by eye in the two frames** triangulates with a 2 mm gap
  between the two rays. A second reel gives 31 mm.
- **The gantry's X-axis ball screw**, back-projected separately from each view,
  lands on the same line (y = 497 to 520 mm from Overhead 1, 501 to 518 mm from
  Overhead 2).
- **The antechamber door** back-projected onto the wall plane has a
  180-190 mm radius. Its 15-inch antechamber datasheet value is 190 mm.
- **Breadboard holes:** a breadboard lying on the deck in Overhead 2 has its
  hole rows 25 mm apart at a top height of 30 to 37 mm. That is a metric
  breadboard (M6 on 25 mm) of usual thickness on the deck.
- **The QR sign's bottom edge** back-projects to 242 mm. The model calls the
  sign US Letter landscape (279 mm), so either it is a smaller sheet or the
  annotated corners are not its corners.

The tray pocket pitch comes out at 9.5 ± 1.1 mm (tray 57 x 95 mm). A ruler
reading of the tray would pin the scale at about 1 %.

### CAD reconstruction

[`reconstruction/`](reconstruction/) models the glovebox interior as
individual parts in the same frame. Each part takes its size from a
datasheet or standard size where one exists, its position from the two
calibrated cameras, and its colour from the frames.
[`reconstruction/scene.py`](reconstruction/scene.py) holds every number;
[`reconstruction/out/parts.json`](reconstruction/out/parts.json) lists each
part with its bounds, colour and source.

![The model from the open side, both cameras in red](reconstruction/out/overview_open_side.png)

![An orbit around the model](reconstruction/out/turntable.gif)

| Overhead 1: published frame, and the model seen from the camera | Overhead 2 |
|---|---|
| ![](reconstruction/out/view_cam0.jpg) | ![](reconstruction/out/view_cam1.jpg) |

The model blended over each frame, with its edges in yellow:
[Overhead 1](reconstruction/out/overlay_cam0.jpg),
[Overhead 2](reconstruction/out/overlay_cam1.jpg). The renders apply the
cameras' measured lens distortion
([`reconstruction/render.py`](reconstruction/render.py)), so they compare
pixel for pixel with the photos.

**How each part is placed:**

- **Two views:** the chip tray (its lattice in both views, with every chip
  drawn in its pocket from `chip_tray.json`: 3 empty, 1 rotated) and the two
  tape reels (ray intersections).
- **Silhouette fit, two views:** the Epson T6-B602S. Its outline is from
  Epson's T6-B drawing: arm lengths 325 + 275 mm, arm 1 and arm 2 heights and
  widths, the controller box above J1, shaft and stroke. J1's position, the
  base's facing and height, the riser height and the two arm angles are
  fitted to the robot's SAM 2.1 masks in both frames
  ([`reconstruction/silhouette.py`](reconstruction/silhouette.py)).
  Overlap: IoU 0.64 in Overhead 1 and 0.20 in Overhead 2, where only the
  side of arm 2 and the duct are in view. The fit puts the base's underside at
  177 mm, matching the chamber model's 180 mm riser reading. Arm 2's tip is held
  inside the box; left free, the fit pushes it 30 mm past the modelled far end.
- **One view, onto a known plane:** the breadboards (edges back-projected at
  their heights), the gantry's posts, plate, screws and motors (Overhead 2),
  the exfoliator housing, stage and motors, the microscope and its elevated
  breadboard, the Thorlabs stage box and the two black docking fixtures
  (Overhead 1), and the tape measure on the deck.
- **Standard sizes:** M6 holes on a 25 mm grid on 12.7 mm breadboards; NEMA 23
  (56.4 mm) and NEMA 17 (42.3 mm) steppers; 16 mm ball screws; 40 x 60 mm
  slotted duct.
- **The shell** is the chamber model's: 1200 x 1120 x 790 mm, sloped long
  windows. The far end is drawn as a window frame, because the room shows
  through it in Overhead 1.

**Accuracy:** parts placed from two views or the silhouette fit sit within
about 10 to 20 px of the photo in both frames. Parts placed from one view are
right in that view, but their depth along the ray rests on an assumed height,
and they can be off by 20 to 50 mm in the other view. Hidden geometry is
inferred: breadboard extents behind equipment, the far end, and the backs of
parts. The cables, tubing and wiring are not modelled.

**Files:** `out/glovebox.glb` (all 114 parts, coloured, one node per part; opens
in any glTF viewer), `out/stl/<group>.stl` (one per group: glovebox, ducts,
breadboards, epson, gantry, exfoliator, microscope, deck), the renders above,
an orbit (`out/turntable.gif`) and `out/parts.json`. Rebuild with
`xvfb-run -a python reconstruction/build_reconstruction.py` (numpy, opencv,
trimesh, pyvista, scipy).

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
5. **Blurring the live streams** (see [Privacy blur](#privacy-blur)), if wanted.
6. **Chamber model:** the QR sign versus door conflict (see
   [Registration](#registration-to-the-chamber-model)), and a tape-measured
   distance in view of both cameras would pin down the poses and the scale far
   better than the 3 or 4 landmarks per camera used here.

## Files

- [`amcrest_relay.py`](amcrest_relay.py): the relay (runs on the Pi 5).
- [`systemd/`](systemd/): the units and per-camera settings installed on the Pi 5.
- [`pi5/aurora-cams.conf`](pi5/aurora-cams.conf): chrony's NTP service for the camera subnet.
- [`camera_time.py`](camera_time.py): read or set the cameras' time zone, DST and NTP, with the admin login over stdin.
- [`pull_feed.py`](pull_feed.py): probe a feed, measure it, or grab a still,
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
  (`calibrate_two_view.py`), with results in `vision/out/`.
- [`reconstruction/`](reconstruction/): the CAD reconstruction of the glovebox
  interior, its exports and renders.
- [`captures/`](captures/): the stills above, blurred.
