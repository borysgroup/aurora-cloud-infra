# Pi 5 cataloging stage overhead cam (`picam-2wp0`)

A Raspberry Pi 5 with a Raspberry Pi HQ Camera (IMX477) and an 8–50 mm zoom lens. Until
2026-11-10 it was the OT-2 lid camera in BYU's Vertical Cloud Lab (VCL). It now stays in the
Borys lab at the University of Utah as the overhead camera for the cataloging stage. The
handover is described below, and the full session transcript (redacted) is in
[`sessions/2026-11-10-pi5-cataloging-cam-handover-transcript.md`](sessions/2026-11-10-pi5-cataloging-cam-handover-transcript.md).

## Current state (2026-11-10)

| | |
| --- | --- |
| Hardware | Pi 5, HQ Camera + 8–50 mm zoom (C-mount on a CS body, with a C–CS spacer), Raspberry Pi OS (Debian 13 trixie, arm64, desktop) |
| Network | U of Utah `ULink` Wi-Fi. No wired profiles (the OT-2 link-local profiles were removed) |
| Tailnet | borysgroup, tagged `tag:stream-cam-test` + `tag:tailscale-ssh`, Tailscale SSH on. Joined with a single-use tagged auth key; key expiry is disabled because the node is tagged. The VCL tailnet profile and node were removed |
| CI access | aurora-cloud-infra: slot `_6`, `RPI_STREAM_CAM_*_6` (PR 32, renamed to streamingLambda's slot names in PR 36). streamingLambda: slot `_6`, `RPI_STREAM_CAM_*_6` (streamingLambda PR 22). Tested from CI on 2026-11-10 (PR 32 comment): all checks passed |
| Stream | Lab-patched AC picam client (`device.py` + `picam_source.py`) in `~/ac-training-lab/src/ac_training_lab/picam/`. It runs as `device.service`, with `stream-watchdog.timer` (stall restarts) and `stream-reboot.timer` (reboots at 05:00/13:00/21:00, held off by `systemd-inhibit` shutdown blocks) |
| Lambda | This org's `picam-lambda-function` (us-east-2). The URL is in `my_secrets.py` on the Pi and in the `LAMBDA_FUNCTION_URL` secret |
| YouTube | Aurora PCL Hardware Streams. `CAM_NAME = "picam-2wp0"`, `WORKFLOW_NAME = "Cataloging stage overhead"`, `PRIVACY_STATUS = "unlisted"`. Broadcasts are titled *Cataloging stage overhead stream picam-2wp0, <UTC time>* and go into the *Cataloging stage overhead Livestreams Playlist*, which the Lambda created on the first broadcast |
| Encoding | 1920×1440 (4:3, full sensor) at 3 fps. Raw frames go to ffmpeg/libx264 `veryfast` with a 4 Mbit/s cap (a Pi 5 has no hardware H.264 encoder). Timestamp overlay on. `SETUP_OVERLAY = True` (centre cross + live focus score) for aiming and focusing. `SETUP_BOX = None` |
| Stills | `curl http://127.0.0.1:8081/still.jpg` on the Pi gives a full-resolution JPEG (4056×3040) from the same picamera2 process, without interrupting the stream |
| Power | 5 A USB-PD supply (swapped in 2026-11-10): EXT5V about 5.15 V, `throttled=0x0`. See "Power" below |

## What was done on 2026-11-10

1. **Stream re-pointed.** The old VCL broadcast was ended through the VCL Lambda. `my_secrets.py` was then switched to this org's Lambda, with the new names and unlisted privacy. Before choosing `WORKFLOW_NAME`, the existing playlist titles on Aurora PCL Hardware Streams (`aurora-<suffix>`) were checked: the Lambda's `end` and playlist matching are case-insensitive substring matches, so names must not contain one another.
2. **VCL-only pieces disabled or removed.**
   - The `cubos.service` unit (CubOS gantry API; no robot is attached here).
   - The OT-2 link-local Ethernet profiles and the RTL8153 USB-Ethernet udev rule.
   - BYU's device Wi-Fi profile.
   - The plate-outline setup box sized for the OT-2 deck.
3. **VCL data archived, then wiped.** About 13 GB in the home directory: OT-2 run data, the atomizer video cache, CubOS, Pico sensor backups holding credentials, and browser and RPi Connect profiles. BYU archived it first, so the home directory now holds only the stream checkout and stock dotfiles (18 MB).
4. **New sudo password** (the old one was stale). It is stored only in the GitHub secrets above and in Sterling's local settings.
5. **Tailnet switched** from VCL to borysgroup. The steps:
   - Mint a single-use auth key with both tags, 1-day expiry, in the borysgroup admin console.
   - Copy it to the Pi over SSH stdin into a root-only file.
   - Arm a 20-minute `systemd-run` timer that would `tailscale switch` back to VCL if the new login failed.
   - Run `tailscale login --auth-key=file:...` detached, so the dropped SSH session could not kill it.
   - Shred the key file after the login.
   - Confirm SSH over borysgroup, then cancel the rollback.
   - Remove the old node from the VCL admin console and run `tailscale switch remove` on its profile.
6. **Repos.** aurora-cloud-infra PR 32 (env vars + CLAUDE.md table) and streamingLambda PR 22 (slot `_6`, slot table, and the `WORKFLOW_NAME` substring rule) were both merged.

## Power

On the supply it arrived with, the Pi negotiated only 3 A and sat at 4.88–4.93 V. It logged
24 under-voltage events in about 15 minutes (`throttled=0x50000`) and rebooted three times
under load. After the swap to a 5 A USB-PD supply (`/proc/device-tree/chosen/power/max_current` = 5000 mA),
it reads 5.15 V with `throttled=0x0`. If unexplained reboots come back, check first:

```bash
vcgencmd get_throttled            # 0x0 is healthy; bit 0 = under-voltage now, bit 16 = since boot
vcgencmd pmic_read_adc EXT5V_V    # want ~5.1 V
od -An -tx1 /proc/device-tree/chosen/power/max_current   # 00 00 13 88 = 5000 mA
```

## Still open

- **Field of view.** When last checked the camera was not yet aimed or focused; stills were a grey blur. Once it is mounted, grab a still and confirm it covers the cataloging stage. If it ends up watching something else, rename `WORKFLOW_NAME`, after first ending the current broadcast by hand: the device only ends broadcasts that match its *current* name.
- **Focus, then turn the setup overlay off.** The HQ lens has manual zoom, focus and iris. The overlay's focus score helps; set `SETUP_OVERLAY = False` and restart `device.service` when done. Record the final ring positions, since the VCL lost theirs.
- **Pick a resolution and frame rate.** 3 fps at 1920×1440 suited a slow robot deck; a cataloging stage may want more.

## Where it came from

The stream stack and lid-mount design are from vertical-cloud-lab/byu-vcl PR 234
(`ot2-overhead-camera/lid-mount/camera/stream/`). The material needed to rebuild a replacement OT-2 camera at
BYU is in vertical-cloud-lab/digital-wetlab (PR 91, issue 92).
