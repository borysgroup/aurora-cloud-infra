# Picamera2 mount for AgileX PiPER end effector — design requirements & resources

Tracking issue: [#5](https://github.com/borysgroup/monark-cloud-infra/issues/5)

**Updated system architecture (per @sgbaird, 2026-09-04):** the compute host will likely be a
**Raspberry Pi 5 driving two cameras simultaneously**, potentially two *different* camera types
(e.g., one eye-in-hand camera plus one of a different modality). The mount design should
therefore plan for **two camera positions** near the gripper (or one on-mount + one elsewhere on
the arm), and for routing **two ribbon cables** back to the Pi 5.

---

## 1. Raspberry Pi 5 dual-camera platform

| Item | Spec | Source |
|---|---|---|
| Camera ports | **2× combined MIPI CSI/DSI**, mini **22-pin, 0.5 mm pitch** FPC connectors | [Pi 5 product documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html) |
| Dual-camera operation | Both ports can run cameras **simultaneously** (CAM0 + CAM1) | [Tom's Hardware guide](https://www.tomshardware.com/raspberry-pi/how-to-use-dual-cameras-on-the-raspberry-pi-5), [Little Bird guide](https://learn.littlebirdelectronics.com.au/guides/how-to-connect-two-cameras-to-the-raspberry-pi-5) |
| Cabling | Pi 5 needs the **"Standard–Mini" camera cable** (22-pin mini on the Pi end, 15-pin standard on the camera end). Two cables required. Stock lengths 200/300/500 mm. | [Camera documentation](https://www.raspberrypi.com/documentation/accessories/camera.html) |
| Power | USB-C, 5 V / 5 A (25 W) recommended | [Pi 5 product documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html) |
| Board size | 85 × 56 mm, 4× M2.5 mounting holes (see mechanical drawing/STEP on product page) | [Pi 5 product documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html) |

Software: `picamera2` supports both cameras natively — `Picamera2(0)` and `Picamera2(1)` select
CAM0/CAM1 and can capture concurrently
([picamera2 manual, PDF](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf)).
Mixed camera types on the two ports are fine since each port gets its own pipeline. Note one
reported caveat: dual-camera operation has had issues when booting to console-only (works in
desktop environments) — see this
[Raspberry Pi forum thread](https://forums.raspberrypi.com/viewtopic.php?t=363418).

```python
from picamera2 import Picamera2

cam0 = Picamera2(0)   # CAM0 — e.g. eye-in-hand Camera Module 3 Wide
cam1 = Picamera2(1)   # CAM1 — e.g. Global Shutter / NoIR / AI Camera
cam0.start(); cam1.start()
cam0.capture_file("cam0.jpg"); cam1.capture_file("cam1.jpg")
```

## 2. Candidate cameras — mechanical specs

All specs from the official
[Raspberry Pi camera hardware documentation](https://www.raspberrypi.com/documentation/accessories/camera.html),
which also links the mechanical drawings (PDF/STEP) needed for the CAD work.

| Camera | Board size (mm) | Weight | Sensor / resolution | Focus | Notes for mount |
|---|---|---|---|---|---|
| **Camera Module 3** (Std/NoIR) | ~25 × 24 × 11.5 | 4 g | IMX708, 11.9 MP | Powered autofocus | 4× **M2** holes (same pattern as Camera Module 2, 21 × 12.5 mm spacing — confirm against mechanical drawing) |
| **Camera Module 3 Wide** (Std/NoIR) | ~25 × 24 × 12.4 | 4 g | IMX708, 11.9 MP, 120° | Powered autofocus | Same board/holes as CM3; wide FoV is attractive for close-range eye-in-hand use (cf. [ac-dev-lab#527](https://github.com/AccelerationConsortium/ac-dev-lab/issues/527) where a wide-angle swap was considered) |
| **AI Camera** | 25 × 24 × 11.9 | 6 g | IMX500, 12.3 MP + on-sensor inference | Fixed | Same footprint class as CM3; offloads NN inference from the Pi |
| **High Quality Camera** | 38 × 38 × 18.4 (excl. lens) | 30.4 g | IMX477, 12.3 MP | Manual, C/CS or M12 lens | 30 mm hole spacing + 1/4"-20 tripod boss; heavier and bulkier — better suited to an off-arm overview position |
| **Global Shutter Camera** | 38 × 38 × 19.8 | 34 g | IMX296, 1.58 MP | C/CS lens | Global shutter = no motion artifacts while the arm moves; same board family as HQ |

**Practical pairing suggestions** (two different types, per the requirement):
- CM3 Wide (eye-in-hand, autofocus, close range) + Global Shutter (motion-robust) — best for imaging during motion
- CM3 (RGB) + CM3 NoIR (IR-sensitive) — same mount pattern twice, simplest CAD
- CM3 Wide + AI Camera — on-sensor detection on one stream

## 3. AgileX PiPER arm & gripper constraints

From the official [PiPER Quick Start User Manual (PDF)](https://static.generation-robots.com/media/agilex-piper-user-manual.pdf), §5 Technical Specifications:

| Parameter | Value |
|---|---|
| DOF | 6 |
| Effective payload | **1.5 kg** |
| Arm weight | 4.2 kg |
| Repeatability | ±0.1 mm |
| Working radius | 626.75 mm |
| Two-finger gripper | **500 g**, flange-mounted, 0–70 mm opening, 40 N rated / 50 N max clamp |
| End tooling | "The end can be equipped with other tools via a flange" (§2.4) |
| Base mounting | 70 × 70 mm, 4× M5 |
| Comms / power | CAN, DC 24 V |

**Weight budget:** gripper (500 g) leaves ~1 kg of payload. Two CM3-class cameras (≈8–12 g) plus a
printed mount (≈20–50 g in PETG) are negligible; even adding the Pi 5 itself (~45 g bare, more with
case/cooler) is feasible, though mounting the Pi off-arm is still preferable (see §5).

## 4. CAD sources

- **PiPER URDF + meshes (official):** [agilexrobotics/agx_arm_urdf](https://github.com/agilexrobotics/agx_arm_urdf) (URDF/Xacro + `.dae` meshes for Piper/Piper H/L/X), [agilexrobotics/piper_ros](https://github.com/agilexrobotics/piper_ros), [agilexrobotics/piper_isaac_sim](https://github.com/agilexrobotics/piper_isaac_sim) (USD models)
- **Gripper & flange STEP files:** `AgileX_Gripper.STEP` and `AgileX_Flange.STP` are distributed with the arm — see the [Génération Robots PiPER gripper page](https://www.generationrobots.com/en/404354-gripper-for-piper-robotic-arm-agilex.html) / [OpenELAB gripper page](https://openelab.io/products/agilex-piper-robotic-arm-gripper); AgileX support (support@agilex.ai) can supply them directly
- **Camera mechanical drawings (PDF/STEP):** linked from the [camera hardware documentation](https://www.raspberrypi.com/documentation/accessories/camera.html); e.g. the [Camera Module 3 product brief](https://pip-assets.raspberrypi.com/categories/786-raspberry-pi-camera-module-3/documents/RP-008151-DS-1-camera-module-3-product-brief.pdf)
- **Pi 5 mechanical drawing + STEP:** linked from the [Pi 5 product documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html)
- **SDKs for integration:** [piper_sdk (Python)](https://github.com/agilexrobotics/piper_sdk)

## 5. Design implications of the Pi 5 + two-camera requirement

1. **Pi 5 location.** FPC ribbon cables tolerate limited length (stock Standard–Mini cables top out
   around 500 mm) and dislike repeated flexing through joints. With a 626.75 mm working radius, a
   base-mounted Pi cannot reach the wrist with stock cables through all poses. Recommended options,
   in order of preference:
   - Mount the Pi 5 on the **forearm/lower link** so only 1–2 joints are between Pi and cameras,
     with generous service loops and strain relief at each joint.
   - Mount the Pi 5 **at/near the end effector** (the ~1 kg remaining payload allows it) — shortest
     cables, but adds bulk near the gripper.
   - Keep the Pi off-arm only if the cameras also move off the wrist (defeats eye-in-hand purpose).
2. **Two camera seats.** The mount (or a pair of mounts) should provide two distinct poses, e.g. one
   camera boresighted along the gripper approach axis and one angled for context/overview — or make
   the second seat a clip-on module so single-camera use stays slim.
3. **Support both hole patterns.** Designing the plate to take the CM3/AI-camera M2 pattern *and*
   (optionally, via an adapter) the 38 × 38 mm HQ/GS pattern keeps camera choice open.
4. **Keep the gripper clear.** Per [ac-dev-lab#527](https://github.com/AccelerationConsortium/ac-dev-lab/issues/527),
   the camera had to be shifted forward so the gripper didn't block the view — same consideration
   applies here, doubly so with two FoVs.
5. **Cable management is part of the mount.** Add channels/tie-down points for two ribbon cables;
   FPC connectors are fragile, so the mount should provide strain relief right behind each camera.
6. **Print material:** PETG worked well in the xArm precedent (tilted print orientation to minimize
   supports on mating surfaces).

## 6. Prior art in AccelerationConsortium/ac-dev-lab

- **[#527 — Camera mount for xarm gripper](https://github.com/AccelerationConsortium/ac-dev-lab/issues/527)** (closed, working):
  the closest precedent. Fusion 360 designs: [picam mount](https://a360.co/4kbOj6e),
  [camera stand from SDL2](https://a360.co/4ihv4Z0)
  ([install video](https://youtu.be/VnL-PbB5gLM)), and
  [@pranshu-ui's latest iteration](https://a360.co/486dxhx). Printed in PETG.

  <img width="600" alt="pranshu-ui initial iteration" src="https://github.com/user-attachments/assets/2ccaba4d-1b75-4e7d-b6ce-7e2027f8b65a" />
  <img width="600" alt="mount moved forward toward gripper" src="https://github.com/user-attachments/assets/fe551c22-dbbe-415c-a264-d9ddb9f495e2" />
  <img width="400" alt="printed PETG mount installed" src="https://github.com/user-attachments/assets/7a02547f-8ccb-465b-bfeb-805674d79e9c" />

- [#158 — Custom toolhead camera for Bambu Lab A1 Mini](https://github.com/AccelerationConsortium/ac-dev-lab/issues/158) (open)
- [#11 — Equipment monitoring using Pi Zero 2 W cameras](https://github.com/AccelerationConsortium/ac-dev-lab/issues/11) (open)
- [#296 — Fix bill of materials for picam](https://github.com/AccelerationConsortium/ac-dev-lab/issues/296) (closed — BOM reference)
- [#181 — SDL0 bimanual robot project](https://github.com/AccelerationConsortium/ac-dev-lab/issues/181) (open — Piper arms context)

## 7. Draft bill of materials

| Qty | Item | Notes |
|---|---|---|
| 1 | Raspberry Pi 5 (4 GB+) + 25 W USB-C PSU + active cooler | dual CSI host |
| 2 | Cameras (mixed types OK — see §2 pairings) | |
| 2 | Standard–Mini camera cable (22-pin↔15-pin), length per Pi placement | 200/300/500 mm stock |
| 1 | Printed mount (PETG), 2 camera seats + cable strain relief | this design |
| — | M2 screws/standoffs (CM3/AI cam), M2.5 for Pi 5, fasteners to gripper flange/body | per mechanical drawings |

## 8. Open questions

1. Which two camera types? (Drives whether the mount needs one or two hole patterns.)
2. Where does the Pi 5 live — forearm strap-on mount, end-effector, or off-arm?
3. Does the mount attach to the gripper body, the flange stack, or clamp the wrist link?
4. Required camera boresights/FoVs for the intended workflow (eye-in-hand servoing vs. documentation/monitoring)?
