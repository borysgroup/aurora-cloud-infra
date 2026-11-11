# Aurora security cameras → Pi 5 → YouTube

Reconnaissance and plan for streaming the glovebox-area **Amcrest security
cameras** to YouTube through the **Pi 5** (the ex-OT-2 overhead HQ camera, now
reallocated and renamed to the "cataloging stage overhead" stream). The Pi 5 is
cabled to the security cameras through an Ethernet switch.

This follows the 2026-11-06 analysis in issue #23
([comment](https://github.com/borysgroup/aurora-cloud-infra/issues/23#issuecomment-6697495676)),
which concluded the relay is doable in principle. This pass verifies it against
the **real hardware**: it confirms the cameras exist, what services they expose,
that the Pi can reach them, and exactly what is still missing (credentials).

Nothing here was brute-forced or guessed. The probe is read-only (see
[`probe_camera_link.py`](probe_camera_link.py)), and all identifying strings
(MACs, serials, RTSP realms) are redacted out of anything committed.

## What was done, on real hardware

Reached the Pi 5 over Tailscale SSH (as configured in `claude.yml` / `CLAUDE.md`)
and inspected it read-only first:

- **Pi 5 is healthy and streaming.** `device.service` active, 0 restarts,
  `stream-watchdog.timer` and `stream-reboot.timer` both active. **Its own HQ
  picam stream was never interrupted by this work.**
- **The camera link is live.** `eth0` is up at **1 Gb/s full-duplex**, carrier
  present. By default it carries **no IP** (its NetworkManager/netplan profile
  is DHCP, and there is no DHCP server on the camera segment), so the Pi is
  *not* on the camera network until you put it there. Good for isolation.

To probe, `eth0` was given a temporary, in-memory address
(`192.168.3.199/24`, `ipv4.never-default yes`, `save no`) so the Pi's default
route stayed on Wi-Fi, then **the profile was deleted afterwards**. No
persistent change was left on the Pi, and the probe scripts were removed.

## The camera segment (as found)

The switch is **not** an isolated two-camera island — it is a real
`192.168.3.0/24` network with ~9 hosts, including:

| Host | Vendor (OUI) | What it is |
|---|---|---|
| `192.168.3.150` | Amcrest | **Security camera 1** |
| `192.168.3.151` | Amcrest | **Security camera 2** |
| ~7 others | Dell / Lenovo-class / TI / others | PCs / NVR / lab devices (not probed) |
| `192.168.3.1` | — | Gateway the cameras ARP for, but **nothing answered** — no working router on this segment |

That last point is a feature, not a bug: with no live gateway, the cameras have
no path to the internet, so their Dahua-based firmware can't be reached from
outside and they can't phone home. The relay should keep it that way (no NAT, no
IP forwarding — confirmed `ip_forward=0` on the Pi).

## The two cameras

Both responded identically:

- **Vendor:** Amcrest (Dahua OEM hardware).
- **Open TCP ports:** `80` (HTTP/web UI), `554` (RTSP), `37777` (Dahua/Amcrest
  proprietary SDK port).
- **RTSP (554):** serves `RTSP/1.0 401 Unauthorized` with **Digest**
  authentication. The stream is there; it needs credentials.
- **ONVIF:** responds on `/onvif/device_service`. The unauthenticated
  `GetSystemDateAndTime` succeeded (device clock reads the correct date). The
  advertised services are **Profile S**: `device`, `media`, `media2`,
  `imaging`, `analytics`, `events` — so RTSP URIs are also discoverable via
  ONVIF once authenticated.
- **Latency / bandwidth:** round-trip Pi→camera ≈ **0.3 ms** on the gigabit
  link; `ffmpeg` and `ffprobe` are present on the Pi. A copy-mode relay (no
  re-encode) is comfortably within budget.
- **Model:** not read — the exact model needs the web-UI *Information* page, the
  sticker, or an authenticated `getDeviceType`. The `AMC108…` RTSP realm points
  to an 8MP-class Amcrest, consistent with the turret in the issue photos.

### RTSP URL (once credentials exist)

Standard Amcrest/Dahua format (verify the subtype with `ffprobe`):

```
rtsp://<user>:<pass>@192.168.3.150:554/cam/realmonitor?channel=1&subtype=0   # main stream
rtsp://<user>:<pass>@192.168.3.150:554/cam/realmonitor?channel=1&subtype=1   # substream
```

## What I need from you to go further

Attempting the stream now stops at the camera login. To actually pull the feeds
and (next step) relay them to YouTube from the Pi 5, please provide:

1. **RTSP credentials for each camera** (`192.168.3.150` and `192.168.3.151`) —
   username + password. A dedicated least-privilege **viewer/ONVIF-media**
   account per camera is preferable to the admin login. This is the one hard
   blocker.
2. **Which physical camera is which** (`.150` vs `.151`, and what each is aimed
   at), so the YouTube titles/descriptions are right.
3. **How these should appear on YouTube** — new broadcast(s) per camera, and the
   privacy status (the picam streams are `unlisted`). The Pi 5 already runs one
   broadcast for its own HQ picam, so each Amcrest feed would be an *additional*
   `device.py`-style instance with its own Lambda-provisioned stream key.
4. **Audio or silence** — the cameras have mics; the picam path currently sends
   silent audio. Say if the camera mic should be streamed.
5. **Optional but useful:** the camera web-UI login, so I can confirm/force
   H.264 + CBR + a 2 s keyframe interval (clean RTMP to YouTube) and read the
   exact model.
6. **Confirm** a reserved static IP for the Pi on `eth0` is OK (I used `.199`
   only temporarily) and that the dead `.1` gateway is intentional.

## Planned streaming path (next step, once credentials arrive)

Reuse the RTSP-relay approach from the 2026-11-06 comment (the `start_rtsp_relay`
patch to `ac-training-lab`'s `picam/device.py`): the Pi 5's `ffmpeg` pulls the
camera's H.264 over `eth0` and pushes it to the YouTube RTMP URL the Lambda
hands out — the same broadcast lifecycle the picam stream already uses.

- **Copy mode** (`-c:v copy`) forwards the camera's H.264 untouched: the Pi 5
  does no decoding or encoding, so it can carry its own picam plus both Amcrest
  feeds. Prefer this.
- A static, gateway-less address on `eth0` (as above) keeps the Pi's default
  route on Wi-Fi/ULink and the cameras off the internet.
- One relay instance per camera → one YouTube broadcast per camera.

## Files

- [`probe_camera_link.py`](probe_camera_link.py) — read-only recon tool
  (`sniff` / `sweep` / `probe` / `discover`). No credentials are ever sent or
  guessed; output is redacted. Run the active modes behind a throw-away
  in-memory `eth0` profile and delete it after (the header documents the exact
  commands).

## Not done

- No credentials were tried or guessed; no camera configuration was changed.
- The exact camera model was not read (needs auth or the label).
- Nothing was streamed yet — that is the next step, gated on credentials.
- The other ~7 hosts on the segment were only identified by vendor OUI, not
  probed.
