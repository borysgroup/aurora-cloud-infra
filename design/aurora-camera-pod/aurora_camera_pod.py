"""Parametric mounts for the Aurora camera pod: Raspberry Pi 5 + 2x HQ Camera.

Generates STEP (for import into Onshape/SolidWorks) and STL (for printing):

    hqcam_cradle   back plate on the HQ Camera's 4x M2.5 holes, arm forward
                   under the lens with a slot the saddle slides along
    lens_saddle    cradle that carries the 148 g zoom lens so its weight is
                   not hanging on the C-CS adapter ring
    pi5_tray       Raspberry Pi 5 carrier with CSI strain relief

Every part presents the same footprint, AURORA-MNT-40: four M4 clearance holes
on a 40 x 40 mm square plus a central 1/4"-20 clearance hole. Anything built
downstream only has to reproduce that pattern.

Dimensions flagged MEASURE come from vendor specifications rather than from a
part in hand, and should be checked before printing.

    python design/aurora-camera-pod/aurora_camera_pod.py
"""

from pathlib import Path

import cadquery as cq

# --- Interface shared by every part in the pod -------------------------------

MNT_PITCH = 40.0  # M4 square pattern, also lands on 20 mm extrusion
M4_CLEAR = 4.5
TRIPOD_CLEAR = 7.0  # 1/4"-20 clearance
TRIPOD_NUT_AF = 11.3  # 1/4"-20 hex nut across flats, slip fit
TRIPOD_NUT_DEPTH = 3.2

# --- Raspberry Pi HQ Camera, CS-mount ----------------------------------------
# hq-camera-mechanical-drawing.pdf: 38 x 38 mm board, 4x dia 2.5 mm holes
# inset 4 mm from each edge, 13.97 mm wide tripod boss below the board.

HQ_BOARD = 38.0
HQ_HOLE_PITCH = 30.0
HQ_HOLE_CLEAR = 2.9  # M2.5 clearance
HQ_BOSS_W = 13.97
HQ_BODY_DEPTH = 18.58  # board back face to front of the lens mount

# Waveshare 8-50 mm zoom lens, C-mount: 40.0 x 68.3 mm, 148 g.  MEASURE.
LENS_DIA = 40.0
LENS_LEN = 68.3
LENS_FIT = 0.8  # radial clearance: the saddle cradles, it does not grip

# --- Raspberry Pi 5 ----------------------------------------------------------
# raspberry-pi-5-mechanical-drawing.pdf: 85 x 56 mm, 4x dia 2.7 mm holes on a
# 58 x 49 mm pattern, 3.5 mm in from the left and top edges.

PI_L, PI_W = 85.0, 56.0
PI_HOLE_X, PI_HOLE_Y = 58.0, 49.0
PI_HOLE_TAP = 2.2  # M2.5 self-taps into the boss; no nut under the mounting face
PI_STANDOFF_H = 6.0  # clears the microSD slot and underside components
PI_STANDOFF_D = 7.0

# --- Print-driven minimums ---------------------------------------------------

PLATE_T = 5.0
ARM_T = 6.0
TRAY_T = 4.0
WALL = 4.0
AXIS_H = 45.0  # optical axis above the mounting face; cradle and saddle share it
ARM_SLOT_W = 4.6  # M4 sliding slots in the arm
ARM_SLOT_X = 14.0  # either side of the centreline, which the 1/4"-20 needs
STRAP_SLOT = (11.0, 2.8)  # zip tie or velcro pass-through


def _mnt_pattern(part, face="<Z", nut_recess=False):
    """Cut AURORA-MNT-40 into the given face."""
    part = (
        part.faces(face)
        .workplane(centerOption="CenterOfBoundBox")
        .rect(MNT_PITCH, MNT_PITCH, forConstruction=True)
        .vertices()
        .hole(M4_CLEAR)
    )
    part = (
        part.faces(face)
        .workplane(centerOption="CenterOfBoundBox")
        .hole(TRIPOD_CLEAR)
    )
    if nut_recess:
        part = (
            part.faces(face)
            .workplane(centerOption="CenterOfBoundBox")
            .polygon(6, TRIPOD_NUT_AF / 0.866)
            .cutBlind(TRIPOD_NUT_DEPTH)
        )
    return part


def hqcam_cradle():
    """Camera-side bracket.

    The camera bolts to the back plate through its four M2.5 holes on 5 mm
    standoffs, so the ribbon connector, the rear components and the tripod boss
    all sit clear of the plate. The arm runs forward under the lens with an
    open slot, so the saddle can be slid to whatever band of the barrel is not
    a zoom, focus or iris ring -- that has to be set against the lens in hand.
    """
    base_w = 56.0
    arm_len = PLATE_T + HQ_BODY_DEPTH + LENS_LEN * 0.85
    plate_h = AXIS_H + HQ_BOARD / 2 + 3.0

    part = cq.Workplane("XY").box(base_w, arm_len, ARM_T, centered=(True, False, False))
    part = part.union(
        cq.Workplane("XY").box(base_w, PLATE_T, plate_h, centered=(True, False, False))
    )

    # side gussets: the plate-to-arm joint is the weak axis when printed flat
    gusset = (
        cq.Workplane("YZ")
        .polyline([(PLATE_T, ARM_T), (PLATE_T, AXIS_H - 6.0), (26.0, ARM_T)])
        .close()
        .extrude(WALL)
    )
    for x in (-base_w / 2, base_w / 2 - WALL):
        part = part.union(gusset.translate((x, 0, 0)))

    # camera mounting holes on the 30 x 30 pattern, board centred on AXIS_H
    holes = [
        (x, AXIS_H + z)
        for x in (-HQ_HOLE_PITCH / 2, HQ_HOLE_PITCH / 2)
        for z in (-HQ_HOLE_PITCH / 2, HQ_HOLE_PITCH / 2)
    ]
    for hx, hz in holes:
        part = part.cut(
            cq.Workplane("XZ")
            .circle(HQ_HOLE_CLEAR / 2)
            .extrude(PLATE_T * 4)
            .translate((hx, PLATE_T * 2, hz))
        )

    # notch at the top so the CSI ribbon leaves the connector on the board's
    # top edge and folds straight down the back of the plate
    part = part.cut(
        cq.Workplane("XZ")
        .rect(HQ_BOSS_W + 2.0, 20.0)
        .extrude(PLATE_T * 4)
        .translate((0, PLATE_T * 2, plate_h))
    )
    # window below the camera: relief for the tripod boss, and a tie-down point
    part = part.cut(
        cq.Workplane("XZ")
        .rect(HQ_BOSS_W + 4.0, 16.0)
        .extrude(PLATE_T * 4)
        .translate((0, PLATE_T * 2, 16.0))
    )

    # sliding slots for the saddle, starting clear of the camera body and kept
    # off the centreline so the 1/4"-20 stays usable
    slot_start = PLATE_T + HQ_BODY_DEPTH + 6.0
    slot_len = arm_len - slot_start - 8.0
    for x in (-ARM_SLOT_X, ARM_SLOT_X):
        part = part.cut(
            cq.Workplane("XY")
            .slot2D(slot_len, ARM_SLOT_W, 90)
            .extrude(ARM_T * 3)
            .translate((x, slot_start + slot_len / 2, -ARM_T))
        )

    return _mnt_pattern(part, "<Z")


def lens_saddle():
    """Cradle under the lens barrel.

    Cut LENS_FIT oversize and held down by a strap rather than clamped, so the
    zoom and focus rings stay free to turn and the barrel is not squeezed.
    Two M4 in the arm slot set the position along the barrel.
    """
    saddle_w = 20.0
    saddle_r = LENS_DIA / 2 + LENS_FIT
    body_w = LENS_DIA + 2 * WALL + 2 * (STRAP_SLOT[0] + 4.0)

    part = cq.Workplane("XY").box(body_w, saddle_w, AXIS_H, centered=(True, True, False))

    # cradle
    part = part.cut(
        cq.Workplane("XZ")
        .circle(saddle_r)
        .extrude(saddle_w + 2)
        .translate((0, saddle_w / 2 + 1, AXIS_H))
    )
    part = part.cut(
        cq.Workplane("XY")
        .box(body_w + 2, saddle_w + 2, saddle_r * 2, centered=(True, True, False))
        .translate((0, 0, AXIS_H))
    )

    # drop the outboard wings to strap height; only the centre carries the lens
    for sx in (-1, 1):
        part = part.cut(
            cq.Workplane("XY")
            .box(body_w / 2 - saddle_r - 1.0, saddle_w + 2, AXIS_H, centered=(True, True, False))
            .translate((sx * (body_w / 2 - (body_w / 2 - saddle_r - 1.0) / 2), 0, 26.0))
        )

    # strap slots outboard of the cradle
    for x in (-(saddle_r + WALL + STRAP_SLOT[0] / 2), saddle_r + WALL + STRAP_SLOT[0] / 2):
        part = part.cut(
            cq.Workplane("XY")
            .slot2D(STRAP_SLOT[0], STRAP_SLOT[1], 0)
            .extrude(AXIS_H * 2)
            .translate((x, 0, -1))
        )

    # two M4 up through the arm slots into nuts captured in the saddle, so the
    # position along the barrel is set once and then locked
    for x in (-ARM_SLOT_X, ARM_SLOT_X):
        part = part.cut(
            cq.Workplane("XY").circle(M4_CLEAR / 2).extrude(20.0).translate((x, 0, -1))
        )
        part = part.cut(
            cq.Workplane("XY")
            .box(7.1, saddle_w + 2, 3.3, centered=(True, True, True))
            .translate((x, 0, 12.0))
        )
    return part


def pi5_tray():
    """Raspberry Pi 5 carrier.

    The Pi sits on standoffs so the microSD slot stays reachable and the Active
    Cooler keeps a free intake. The CSI cables are tied down on the connector
    edge, which also carries USB-C and the micro-HDMI ports, so the tray stops
    short of that edge. With the 200 mm cables that were ordered, this tray has
    to sit within roughly 150 mm of routed length of both cameras.
    """
    pad = 6.0
    tray_l, tray_w = PI_L + 2 * pad, PI_W + 2 * pad
    part = cq.Workplane("XY").box(tray_l, tray_w, TRAY_T)

    for sx in (-1, 1):
        for sy in (-1, 1):
            part = part.union(
                cq.Workplane("XY")
                .circle(PI_STANDOFF_D / 2)
                .extrude(PI_STANDOFF_H)
                .translate((sx * PI_HOLE_X / 2, sy * PI_HOLE_Y / 2, TRAY_T / 2))
            )
    part = (
        part.faces(">Z")
        .workplane(centerOption="CenterOfBoundBox")
        .rect(PI_HOLE_X, PI_HOLE_Y, forConstruction=True)
        .vertices()
        .hole(PI_HOLE_TAP)
    )

    # ventilation, kept clear of the standoff pattern and the mount pattern
    for dx in (-36.0, 36.0):
        part = part.cut(
            cq.Workplane("XY")
            .slot2D(34.0, 9.0, 90)
            .extrude(TRAY_T * 3)
            .translate((dx, 0, -TRAY_T))
        )

    # two pairs of strain-relief slots on the CSI edge, one pair per camera
    for dx in (-22.0, 22.0):
        for dy in (0.0, 8.0):
            part = part.cut(
                cq.Workplane("XY")
                .slot2D(STRAP_SLOT[0], STRAP_SLOT[1], 0)
                .extrude(TRAY_T * 3)
                .translate((dx, -tray_w / 2 + 4.5 + dy, -TRAY_T))
            )

    return _mnt_pattern(part, "<Z", nut_recess=True)


PARTS = {
    "hqcam_cradle": hqcam_cradle,
    "lens_saddle": lens_saddle,
    "pi5_tray": pi5_tray,
}

# --- Preview only: stand-ins for the bought parts, not for printing ----------

STANDOFF_H = 5.0


def _pod_preview():
    cam_back = PLATE_T + STANDOFF_H
    cam = (
        cq.Workplane("XY")
        .box(HQ_BOARD, HQ_BODY_DEPTH, HQ_BOARD, centered=(True, False, True))
        .translate((0, cam_back, AXIS_H))
    )
    lens = (
        cq.Workplane("XZ")
        .circle(LENS_DIA / 2)
        .extrude(-LENS_LEN)
        .translate((0, cam_back + HQ_BODY_DEPTH, AXIS_H))
    )
    saddle_y = cam_back + HQ_BODY_DEPTH + LENS_LEN * 0.55
    saddle = lens_saddle().translate((0, saddle_y, 0))
    cradle = hqcam_cradle()

    tray_at = (0.0, -80.0)
    tray = pi5_tray().translate((*tray_at, 0))
    pi = (
        cq.Workplane("XY")
        .box(PI_L, PI_W, 1.6)
        .translate((*tray_at, TRAY_T / 2 + PI_STANDOFF_H + 0.8))
    )
    cooler = (
        cq.Workplane("XY")
        .box(60.0, 40.0, 11.0, centered=(True, True, False))
        .translate((*tray_at, TRAY_T / 2 + PI_STANDOFF_H + 1.6))
    )
    return cq.Compound.makeCompound(
        [s.val() for s in (cradle, saddle, cam, lens, tray, pi, cooler)]
    )


VIEWS = {
    "hqcam_cradle": (1.3, -1.0, -0.45),
    "lens_saddle": (1.3, -1.0, -0.45),
    "pi5_tray": (1.3, -1.0, -0.8),
    "pod_assembly": (1.3, -1.0, -0.45),
}


def _render(shape, path, direction):
    import cairosvg

    svg = path.with_suffix(".svg")
    cq.exporters.export(
        shape,
        str(svg),
        opt={
            "width": 1400,
            "height": 1000,
            "marginLeft": 40,
            "marginTop": 40,
            "showAxes": False,
            "projectionDir": direction,
            "strokeWidth": 0.3,
            "strokeColor": (40, 40, 40),
            "showHidden": False,
        },
    )
    cairosvg.svg2png(url=str(svg), write_to=str(path), background_color="white", scale=1.0)
    svg.unlink()


def main():
    out = Path(__file__).parent
    shapes = {}
    for name, build in PARTS.items():
        shape = build()
        shapes[name] = shape
        cq.exporters.export(shape, str(out / f"{name}.step"))
        cq.exporters.export(shape, str(out / f"{name}.stl"), tolerance=0.05)
        bb = shape.val().BoundingBox()
        print(f"{name:14s} {bb.xlen:6.1f} x {bb.ylen:6.1f} x {bb.zlen:6.1f} mm")

    shapes["pod_assembly"] = _pod_preview()
    for name, direction in VIEWS.items():
        _render(shapes[name], out / f"{name}.png", direction)
        print(f"rendered {name}.png")


if __name__ == "__main__":
    main()
