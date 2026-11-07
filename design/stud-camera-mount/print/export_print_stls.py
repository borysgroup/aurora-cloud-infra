"""Export the stud mount's printed parts in print orientation (z up, lying on z = 0), for slicing.

    python print/export_print_stls.py          # writes print/stl/*.stl and prints an overhang check

Orientation: yoke on its ceiling face; thumb nut and tilt knobs with their pockets up; Pi Zero case, back cover,
HQ camera plate and Wide nose on their front faces; each HQ cheek on its inner face, boss (and insert hole) up.
The overhang check lists down-facing area steeper than 45 deg that is not on the bed. Bridges over the small
horizontal holes show up there and print without supports.
"""

from __future__ import annotations

import math
import pathlib
import sys

import cadquery as cq
import numpy as np
import trimesh

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import stud_mount as sm  # noqa: E402

OUT = HERE / "stl"

# name: (maker, [(axis, deg), ...] applied in order)
X_UP = [((1, 0, 0), 90)]           # head frame: front face (y = min) down
PARTS = {
    "yoke_zero": (lambda: sm.yoke("zero"), [((1, 0, 0), 180)]),
    "yoke_hq": (lambda: sm.yoke("hq"), [((1, 0, 0), 180)]),
    "stud_thumb_nut": (sm.stud_knob, []),
    "tilt_knob": (sm._one_tilt_knob, []),
    "head_zero_case": (lambda: sm.head_zero_parts()["case"][0], X_UP),
    "head_zero_back_cover": (lambda: sm.head_zero_parts()["back cover"][0], X_UP),
    "head_hq_camera_plate": (lambda: sm.head_hq_parts()["camera plate"][0], X_UP),
    "head_hq_pi_carrier": (lambda: sm.head_hq_parts()["Pi carrier"][0], X_UP),
    "head_hq_wide_nose": (lambda: sm.head_hq_parts()["Wide nose"][0], X_UP),
    "head_hq_cheek_right": (lambda: _cheek(+1), [((0, 1, 0), -90)]),
    "head_hq_cheek_left": (lambda: _cheek(-1), [((0, 1, 0), 90)]),
}

# copies for the planned layout: two Pi Zero mounts (unpacking, mother tape) and one HQ mount (tray)
COPIES = {"yoke_zero": 2, "head_zero_case": 2, "head_zero_back_cover": 2, "yoke_hq": 1, "head_hq_camera_plate": 1,
          "head_hq_pi_carrier": 1, "head_hq_wide_nose": 1, "head_hq_cheek_right": 1, "head_hq_cheek_left": 1,
          "stud_thumb_nut": 3, "tilt_knob": 6}


def _cheek(side):
    solids = sm.head_hq_parts()["cheeks"][0].solids().vals()
    pick = max(solids, key=lambda s: side * s.Center().x)
    return cq.Workplane("XY").add(pick)


def to_trimesh(wp, tol=0.02):
    verts, tris = [], []
    for sol in wp.vals():
        v, t = sol.tessellate(tol, 0.1)
        off = len(verts)
        verts += [(p.x, p.y, p.z) for p in v]
        tris += [(a + off, b + off, c + off) for a, b, c in t]
    return trimesh.Trimesh(np.array(verts), np.array(tris), process=True)


def overhang_area(m, limit_deg=45.0, bed_tol=0.05):
    n = m.face_normals
    down = n[:, 2] < -math.cos(math.radians(limit_deg))
    zc = m.triangles_center[:, 2]
    off_bed = zc > bed_tol
    return float(m.area_faces[down & off_bed].sum())


def main():
    OUT.mkdir(exist_ok=True)
    rows = []
    for name, (make, steps) in PARTS.items():
        wp = make()
        for axis, deg in steps:
            wp = wp.rotate((0, 0, 0), axis, deg)
        m = to_trimesh(wp)
        lo, hi = m.bounds
        m.apply_translation([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
        assert m.is_watertight, name
        m.export(OUT / f"{name}.stl")
        rows.append((name, COPIES[name], *np.round(m.extents, 1), round(m.volume / 1000, 2),
                     round(overhang_area(m), 1)))
    print(f"{'part':24s} n  {'x':>6s} {'y':>6s} {'z':>6s}  cm3  overhang>45deg mm2")
    for r in rows:
        print(f"{r[0]:24s} {r[1]}  {r[2]:6.1f} {r[3]:6.1f} {r[4]:6.1f}  {r[5]:5.2f}  {r[6]:7.1f}")


if __name__ == "__main__":
    main()
