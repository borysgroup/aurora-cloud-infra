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
- **Model:** both are **Amcrest IP5M-T1179EW-AI-V3** (5 MP turret), firmware
  `2.880.00AC003.0.R`, build 2025-03-19 (read with the admin login via
  `magicBox.cgi?action=getDeviceType` / `getSoftwareVersion`).
- **Main stream (`subtype=0`):** H.264, 20 fps, video only (no audio track in
  the SDP), so a `-c:v copy` relay needs a silent audio track added for YouTube.

### RTSP URL (once credentials exist)

Standard Amcrest/Dahua format (verify the subtype with `ffprobe`):

```
rtsp://<user>:<pass>@192.168.3.150:554/cam/realmonitor?channel=1&subtype=0   # main stream
rtsp://<user>:<pass>@192.168.3.150:554/cam/realmonitor?channel=1&subtype=1   # substream
```

## Viewer accounts (2026-11-18)

Using the admin login, a non-admin `relay` account was created on each camera
for the YouTube relay. Only the RTSP viewer login is meant to be used from here
on; the admin login is for camera configuration.

- **What was changed on the cameras:** one new user per camera, `relay`, group
  `user`, `Sharable=true` (concurrent sessions allowed), memo `youtube-relay`,
  created with `userManager.cgi?action=addUser`. The request asked for
  `Monitor_01` (live view) only, but the firmware applied the group's full rights,
  so the account holds `Monitor_01` + `Replay_01` (live view and playback of
  recordings). It has no configuration, user-management or network rights: the
  user-management API answers it with `403`. No other camera setting was changed;
  the `admin` account is untouched.
- **Verified:** `relay` gets `RTSP/1.0 200 OK` on `DESCRIBE` of the main stream
  on both cameras.
- **Where the credentials live:** repo variables `AMCREST_CAM_USERNAME_<n>` and
  secrets `AMCREST_CAM_PASSWORD_<n>` (`_0` = `.150`, `_1` = `.151`), and on the
  Pi 5 in `~/.config/aurora-security-cams/cams.env` (directory `700`, file `600`,
  owner `vcl`), which holds `AMCREST_CAM_{HOST,USERNAME,PASSWORD}_<n>` for both
  cameras. The admin logins are not stored on the Pi.
- **To undo:** `userManager.cgi?action=deleteUser&name=relay` with the admin
  login on each camera, and delete the `cams.env` directory on the Pi 5.
- **Pi 5 state afterwards:** the temporary `cam-probe` NetworkManager profile
  was deleted again, `eth0` is back to no IPv4 address, `ip_forward=0`, and
  `device.service` was untouched (0 restarts).

## What I need from you to go further

Attempting the stream now stops at the camera login. To actually pull the feeds
and (next step) relay them to YouTube from the Pi 5, please provide:

1. ~~**RTSP credentials for each camera**~~ Done: the `relay` viewer account
   above. `claude.yml` passes these through from
   *Settings → Secrets and variables → Actions*:

   | Camera | Repo variable | Repo secret |
   |---|---|---|
   | `192.168.3.150` | `AMCREST_CAM_USERNAME_0` | `AMCREST_CAM_PASSWORD_0` |
   | `192.168.3.151` | `AMCREST_CAM_USERNAME_1` | `AMCREST_CAM_PASSWORD_1` |

   Usernames are variables, not secrets, for the same reason as the
   `RPI_STREAM_CAM_USERNAME_<n>` slots: GitHub masks a secret everywhere it
   appears as a substring, so a short value like `admin` would garble the logs.
2. **Which physical camera is which** (`.150` vs `.151`, and what each is aimed
   at), so the YouTube titles/descriptions are right.
3. **How these should appear on YouTube** — new broadcast(s) per camera, and the
   privacy status (the picam streams are `unlisted`). The Pi 5 already runs one
   broadcast for its own HQ picam, so each Amcrest feed would be an *additional*
   `device.py`-style instance with its own Lambda-provisioned stream key.
4. **Audio or silence** — the cameras have mics; the picam path currently sends
   silent audio. Say if the camera mic should be streamed.
5. ~~**The camera web-UI login**~~ Provided; used to read the model and create
   the viewer account. Still to do with it: confirm H.264 + CBR + a 2 s
   keyframe interval (at 20 fps, a GOP of 40) for clean RTMP to YouTube. The
   admin logins are plumbed separately from the RTSP ones:

   | Camera | Repo variable | Repo secret |
   |---|---|---|
   | `192.168.3.150` | `AMCREST_CAM_ADMIN_USERNAME_0` | `AMCREST_CAM_ADMIN_PASSWORD_0` |
   | `192.168.3.151` | `AMCREST_CAM_ADMIN_USERNAME_1` | `AMCREST_CAM_ADMIN_PASSWORD_1` |
6. **Confirm** a reserved static IP for the Pi on `eth0` is OK (I used `.199`
   only temporarily) and that the dead `.1` gateway is intentional.

## Planned streaming path (next step)

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

- No credentials were guessed. The only camera change is the `relay` account
  above; encoder settings were not read or changed yet.
- Nothing was streamed yet — that is the next step.
- The other ~7 hosts on the segment were only identified by vendor OUI, not
  probed.
