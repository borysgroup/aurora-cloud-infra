"""Pan/tilt camera pod that hangs from one of the glovebox's welded ceiling studs.

    python design/aurora-stud-mount/stud_pan_tilt_mount.py

Writes STL (to print) and STEP (for Onshape/SolidWorks) for three parts:

    pod_base     plate that clamps up against the ceiling on one stud. The Pi Zero 2 W
                 hangs under one end of it; a hinge plate with tilt-index holes hangs
                 from the other end
    stud_knob    knurled thumb knob with a trapped hex nut. It threads onto the stud
                 under the base and clamps the base to the ceiling
    cm3_cradle   hinge disc, arm and a plate carrying a Camera Module 3 on four standoffs

Pan: loosen the knob, turn the whole pod about the stud (any angle), tighten.
Tilt: an M4 bolt with a nyloc nut is the hinge. An M2 x 12 screw through one of seven
holes in the hinge plate, self-tapped into the cradle, sets the tilt every 15 deg from
straight down (0) to horizontal (90), so an angle can be set again exactly and the pin
can't drop out. Without it the hinge holds by friction.

The hinge, index pin and camera cradle follow the PiPER enclosure camera head
(vertical-cloud-lab/robot-arms PR #9, robot-arm/enclosure/cameras/build.py); the PVC
pipe clamp is replaced by a stud clamp and the Pi Zero rides on the same pod.

Installed frame (mm): the ceiling is z = 0 and the pod hangs below it (z < 0); the
stud is the z axis; +x runs from the stud towards the hinge; the hinge axis is y.
At tilt 0 the camera looks straight down, at tilt 90 it looks along +x.

Values marked MEASURE are assumptions from photos, not measurements.
"""

from pathlib import Path

import numpy as np

try:
    import cadquery as cq
except ImportError:  # the dimensions and pose helpers below work without CadQuery
    cq = None

HERE = Path(__file__).resolve().parent

# --- Glovebox stud ---------------------------------------------------------------
STUD_D = 6.0          # MEASURE: assumed M6. For 1/4"-20 use 6.35 and NUT_AF = 11.11
STUD_CLEAR = STUD_D + 0.6
NUT_AF = 10.0         # M6 hex nut across flats
NUT_H = 5.0
WELD_RELIEF = (13.0, 1.2)  # dia, depth on the ceiling face, clears the weld fillet at the stud root

# --- Pod base --------------------------------------------------------------------
BASE_T = 5.0
BASE_HALF_W = 18.0
CORNER_R = 8.0
KNOB_D, KNOB_H = 28.0, 12.0

# Raspberry Pi Zero 2 W: 65 x 30 mm, 4x M2.5 holes on 58 x 23 mm, 3.5 mm in from the edges
ZERO_L, ZERO_W = 65.0, 30.0
ZERO_HOLES = (58.0, 23.0)
ZERO_STANDOFF = 10.0  # keeps the board, and its Wi-Fi antenna, 15 mm off the steel ceiling
ZERO_GAP = 3.0        # between the knob and the end of the Pi
ZERO_CX = -(KNOB_D / 2 + ZERO_GAP + ZERO_L / 2)
M25_TAP = 2.2

# --- Hinge (from the PiPER camera head) ---------------------------------------------
TAB_T = 5.0           # hinge plates
DISC = 16.0           # hinge disc radius
M4 = 4.4
PIN = 2.2             # M2 x 12 screw used as the index pin
INDEX_R = 11.0
TILTS = list(range(0, 91, 15))
PIVOT_X = KNOB_D / 2 + 6.0 + DISC   # clear of the knob
PIVOT_Z = -(BASE_T + DISC + 3.0)    # the cradle disc clears the base's underside

# --- Camera Module 3 (Raspberry Pi drawing): 25 x 23.862 mm board, M2 holes 21 x 12.5 mm
BOARD = (25.0, 23.862, 1.0)          # s (along the ribbon-connector edge), t (in from it), thickness
HOLE_S, HOLE_T = 10.5, (9.36, 21.86)
LENS_T = 9.46                        # lens axis, in from the connector edge
CUT_T = 6.3                          # plate stops this far in from the connector edge, so the ribbon leaves freely
PLATE_S, PLATE_T1 = 14.2, 25.6
PLATE_AT, PLATE_T = 22.0, 3.0        # camera plate: back face below the pivot, thickness
STANDOFF = 3.0
M2_TAP = 1.8
CRADLE_Y = PLATE_S                   # board centre line (s = 0) in y: the plate starts at the disc face, so it prints flat


def _box(lo, hi):
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    c = (lo + hi) / 2
    return cq.Workplane("XY").box(*(hi - lo)).translate(tuple(c))


def _cyl(r, h, axis="z", center=(0, 0, 0)):
    """Cylinder of radius r and length h along axis, centred on center."""
    d = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis]
    c = np.asarray(center, float) - np.asarray(d, float) * h / 2
    solid = cq.Solid.makeCylinder(r, h, cq.Vector(*c), cq.Vector(*d))
    return cq.Workplane("XY").add(solid)


def _hex_prism(af, h, center):
    return (cq.Workplane("XY").polygon(6, af / np.cos(np.pi / 6)).extrude(h)
            .translate((center[0], center[1], center[2] - h / 2)))


def index_points():
    """Index-hole centres on the hinge plate (x, z), one per tilt."""
    return [(PIVOT_X + INDEX_R * np.sin(np.radians(a)), PIVOT_Z - INDEX_R * np.cos(np.radians(a))) for a in TILTS]


def pod_base():
    # plate against the ceiling, from the end of the Pi to the far side of the hinge disc
    x0, x1 = ZERO_CX - ZERO_L / 2 - 4.0, PIVOT_X + DISC
    plate = (cq.Workplane("XY").center((x0 + x1) / 2, 0).rect(x1 - x0, 2 * BASE_HALF_W).extrude(BASE_T)
             .edges("|Z").fillet(CORNER_R).translate((0, 0, -BASE_T)))
    # hinge plate hanging from the hinge end, y in [-TAB_T, 0]
    strip = _box((PIVOT_X - DISC, -TAB_T, PIVOT_Z), (PIVOT_X + DISC, 0, -BASE_T + 0.01))
    disc = _cyl(DISC, TAB_T, "y", (PIVOT_X, -TAB_T / 2, PIVOT_Z))
    # gusset between the hinge plate and the base, on the side away from the cradle
    gusset = (cq.Workplane("YZ").polyline([(-TAB_T, -BASE_T), (-TAB_T - 8, -BASE_T), (-TAB_T, -BASE_T - 8)]).close()
              .extrude(2 * DISC - 4).translate((PIVOT_X - DISC + 2, 0, 0)))
    body = plate.union(strip).union(disc).union(gusset)
    # Pi Zero 2 W standoffs on the underside
    hx, hy = ZERO_HOLES[0] / 2, ZERO_HOLES[1] / 2
    for sx in (-1, 1):
        for sy in (-1, 1):
            body = body.union(_cyl(3.2, ZERO_STANDOFF, "z", (ZERO_CX + sx * hx, sy * hy, -BASE_T - ZERO_STANDOFF / 2 + 0.01)))
    # cuts: stud, weld relief, Pi screws, pivot, index holes
    body = body.cut(_cyl(STUD_CLEAR / 2, 40, "z", (0, 0, 0)))
    body = body.cut(_cyl(WELD_RELIEF[0] / 2, 2 * WELD_RELIEF[1], "z", (0, 0, 0)))
    for sx in (-1, 1):
        for sy in (-1, 1):
            body = body.cut(_cyl(M25_TAP / 2, 2 * (BASE_T + ZERO_STANDOFF) - 4,
                                 "z", (ZERO_CX + sx * hx, sy * hy, -BASE_T - ZERO_STANDOFF)))
    body = body.cut(_cyl(M4 / 2, 30, "y", (PIVOT_X, 0, PIVOT_Z)))
    for x, z in index_points():
        body = body.cut(_cyl(PIN / 2, 30, "y", (x, 0, z)))
    return body


def stud_knob():
    """Knob under the base; its top face (z = 0 here) bears on the base. The nut is trapped in that face."""
    knob = _cyl(KNOB_D / 2, KNOB_H, "z", (0, 0, -KNOB_H / 2))
    for k in range(18):
        a = 2 * np.pi * k / 18
        knob = knob.cut(_cyl(1.6, KNOB_H + 2, "z", (KNOB_D / 2 * np.cos(a), KNOB_D / 2 * np.sin(a), -KNOB_H / 2)))
    knob = knob.cut(_cyl(STUD_CLEAR / 2, KNOB_H + 2, "z", (0, 0, -KNOB_H / 2)))
    knob = knob.cut(_hex_prism(NUT_AF + 0.3, NUT_H + 0.4, (0, 0, -(NUT_H + 0.4) / 2 + 0.01)))
    return knob


def board_point(s, t, h=0.0):
    """Cradle frame (pivot at the origin, tilt 0): s along the connector edge (y), t in from it (+x),
    h below the board's back face (towards the scene)."""
    back_z = -(PLATE_AT + PLATE_T + STANDOFF)
    return np.array([-LENS_T + t, CRADLE_Y + s, back_z - h])


def cm3_cradle():
    disc = _cyl(DISC, TAB_T, "y", (0, TAB_T / 2, 0))
    arm = _box((-8, 0, -(PLATE_AT + 0.5)), (8, TAB_T, 0))
    lo = board_point(-PLATE_S, CUT_T, -STANDOFF - PLATE_T)
    hi = board_point(PLATE_S, PLATE_T1, -STANDOFF)
    plate = _box(np.minimum(lo, hi), np.maximum(lo, hi))
    body = disc.union(arm).union(plate)
    holes = [(s * HOLE_S, t) for s in (-1, 1) for t in HOLE_T]
    for s, t in holes:
        body = body.union(_cyl(2.6, STANDOFF, "z", board_point(s, t, -STANDOFF / 2) + (0, 0, 0.01)))
    body = body.cut(_cyl(M4 / 2, 30, "y", (0, 0, 0)))
    body = body.cut(_cyl(M2_TAP / 2, 30, "y", (0, 0, -INDEX_R)))  # the index screw self-taps into the cradle
    for s, t in holes:
        body = body.cut(_cyl(M2_TAP / 2, 2 * (PLATE_T + STANDOFF), "z", board_point(s, t, -STANDOFF)))
    return body


def lens_axis():
    """Lens centre on the board's front face and the viewing direction, cradle frame at tilt 0."""
    return board_point(0.0, LENS_T, BOARD[2]), np.array([0.0, 0.0, -1.0])


def tilt_matrix(deg):
    """Rotation of the cradle about the hinge (y axis through the pivot): tilt 0 looks down,
    tilt 90 looks along +x."""
    a = np.radians(deg)
    r = np.array([[np.cos(a), 0, -np.sin(a)], [0, 1, 0], [np.sin(a), 0, np.cos(a)]])
    m = np.eye(4)
    m[:3, :3] = r
    m[:3, 3] = (PIVOT_X, 0, PIVOT_Z) - r @ np.zeros(3)
    return m


def check():
    """Cradle pin hole lands on an index hole at every tilt; nothing collides at any tilt."""
    pin_local = np.array([0.0, 0.0, -INDEX_R, 1.0])
    for a, (x, z) in zip(TILTS, index_points()):
        p = tilt_matrix(a) @ pin_local
        assert np.allclose(p[[0, 2]], (x, z), atol=1e-6), (a, p, x, z)
    base = pod_base().val()
    knob = stud_knob().val()
    cradle = cm3_cradle().val()
    out = {}
    knob = knob.translate(cq.Vector(0, 0, -BASE_T))
    for a in TILTS:
        moved = cradle.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 1, 0), -a).translate(cq.Vector(PIVOT_X, 0, PIVOT_Z))
        clash = moved.intersect(base).Volume() + moved.intersect(knob).Volume()
        out[a] = round(clash, 3)
    return out


def export_all(out_dir=HERE):
    parts = {
        # print orientations: base ceiling face down, knob nut-trap face down, cradle disc face down
        "pod_base": pod_base().rotate((0, 0, 0), (1, 0, 0), 180),
        "stud_knob": stud_knob().rotate((0, 0, 0), (1, 0, 0), 180),
        "cm3_cradle": cm3_cradle().rotate((0, 0, 0), (1, 0, 0), 90),
    }
    stats = {}
    for name, wp in parts.items():
        cq.exporters.export(wp, str(out_dir / f"{name}.stl"), tolerance=0.02, angularTolerance=0.1)
        cq.exporters.export(wp, str(out_dir / f"{name}.step"))
        bb = wp.val().BoundingBox()
        stats[name] = dict(volume_cm3=round(wp.val().Volume() / 1000, 1),
                           size_mm=[round(bb.xlen, 1), round(bb.ylen, 1), round(bb.zlen, 1)])
    return stats


if __name__ == "__main__":
    print("clash volume (mm3) by tilt:", check())
    for k, v in export_all().items():
        print(k, v)
