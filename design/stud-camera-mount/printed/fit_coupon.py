"""Thread fit coupons for the all-printed stud mount: print these (with one tilt screw and one thumb nut) before the
real parts, and pick the allowance that fits on your printer.

    python printed/fit_coupon.py     # writes printed/stl/coupon_m6_vertical.stl, printed/stl/coupon_m10_horizontal.stl

  coupon_m6_vertical     three vertical M6 x 1 holes, radial allowance 0.15 / 0.20 / 0.25 mm (one / two / three
                         notches), printed like the thumb nut. Try each on an M6 bolt or on the ceiling stud.
  coupon_m10_horizontal  three horizontal M10 x 1.25 holes, allowance 0.10 / 0.15 / 0.20 mm (notches as above),
                         printed like the head's bosses. Try each with a printed tilt screw.

The design uses 0.20 (M6) and 0.15 (M10): if a different hole fits better, change STUD_THREAD / TILT_THREAD in
stud_mount_printed.py and re-export.
"""

from __future__ import annotations

import pathlib
import sys

import manifold3d as m3d
import numpy as np
import trimesh

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import threads as th  # noqa: E402

OUT = HERE / "stl"


def _box(x0, y0, z0, x1, y1, z1):
    return m3d.Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, y0, z0])


def _notches(body, x, y_face, n, z_top):
    for i in range(n):
        body = body - _box(x - 4 + i * 3.0, y_face - 0.8, z_top - 3, x - 3 + i * 3.0, y_face + 0.01, z_top + 1)
    return body


def m6_vertical():
    pitch_x, h = 16.0, 10.0
    body = _box(-24, -8, 0, 24, 8, h)
    for i, c in enumerate((0.15, 0.20, 0.25)):
        x = (i - 1) * pitch_x
        tool = th.tap(6.0, 1.0, h, c, entry_chamfer=0.8)
        body = body - tool.translate([x, 0, 0])
        body = _notches(body, x, -8, i + 1, h)
    return body


def m10_horizontal():
    pitch_x, depth, zc = 18.0, 12.0, 8.0
    body = _box(-27, 0, 0, 27, depth, zc + 8.0)
    for i, c in enumerate((0.10, 0.15, 0.20)):
        x = (i - 1) * pitch_x
        tool = th.frame(th.tap(10.0, 1.25, depth, c, entry_chamfer=0.6), (x, 0.0, zc), (0, 1, 0))
        body = body - tool
        body = _notches(body, x, 0.0, i + 1, zc + 8.0)
    return body


def export():
    OUT.mkdir(exist_ok=True)
    for name, m in (("coupon_m6_vertical", m6_vertical()), ("coupon_m10_horizontal", m10_horizontal())):
        v, f = th.to_arrays(m)
        t = trimesh.Trimesh(v, f, process=False)
        lo, hi = t.bounds
        t.apply_translation([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
        assert t.is_watertight, name
        t.export(OUT / f"{name}.stl")
        print(name, np.round(t.extents, 1), "cm3 %.2f" % (t.volume / 1000), "tris", len(t.faces))


if __name__ == "__main__":
    export()
