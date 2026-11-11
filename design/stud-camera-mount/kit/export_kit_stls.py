"""Export the nylon-kit stud mount's printed parts in print orientation, threads included, and check the assemblies.

    python kit/export_kit_stls.py            # writes kit/stl/*.stl, prints sizes and an overhang check
    python kit/export_kit_stls.py --check    # also: overlaps inside each head (kit screws, nuts and standoffs
                                             # included), and head vs yoke/stud/thumb nut/tilt screws at tilts -10..90

The thumb nut is the all-printed mount's (../printed/stl/stud_thumb_nut.stl). Threads are cut or added at mesh level
with manifold3d (../printed/threads.py). Orientation: yokes on their ceiling face; tilt screw on its knob; Pi Zero
case, HQ tub, carrier and Wide nose on their front faces; back cover on its back face.
"""

from __future__ import annotations

import argparse
import itertools
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "printed"))
import export_printed_stls as epx  # noqa: E402
import stud_mount_kit as sk  # noqa: E402

OUT = HERE / "stl"
X_UP, BACK_DOWN, FLIP = epx.X_UP, epx.BACK_DOWN, epx.FLIP

PARTS = {
    # name: (maker, thread ops (part frame), print rotation, copies for 2 Pi Zero mounts + 1 HQ mount)
    "yoke_zero": (lambda: sk.yoke("zero"), lambda: [], FLIP, 2),
    "yoke_hq": (lambda: sk.yoke("hq"), lambda: [], FLIP, 1),
    "tilt_screw": (sk.tilt_screw_local, sk.tilt_screw_ops_local, [], 6),
    "head_zero_case": (lambda: sk.head_zero_parts()["case"][0], lambda: sk.head_thread_ops("zero"), X_UP, 2),
    "head_zero_back_cover": (lambda: sk.head_zero_parts()["back cover"][0], lambda: [], BACK_DOWN, 2),
    "head_hq_tub": (lambda: sk.head_hq_parts()["tub"][0], lambda: sk.head_thread_ops("hq"), X_UP, 1),
    "head_hq_carrier": (lambda: sk.head_hq_parts()["carrier"][0], lambda: [], X_UP, 1),
    "head_hq_wide_nose": (lambda: sk.head_hq_parts()["Wide nose"][0], lambda: [], X_UP, 1),
    "fit_coupon": (sk.fit_coupon, lambda: [], [], 1),
}
PRINTED = {"case", "back cover", "tub", "carrier", "Wide nose"}


def KIT(name):
    return name.startswith(("M2 ", "M2.5 "))


def export():
    OUT.mkdir(exist_ok=True)
    rows = []
    for name, (make, ops, steps, n) in PARTS.items():
        m = epx.rotate(epx.with_threads(make(), ops()), steps)
        lo, hi = m.bounds
        m.apply_translation([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
        assert m.is_watertight, name
        m.export(OUT / f"{name}.stl")
        rows.append((name, n, *np.round(m.extents, 1), round(m.volume / 1000, 2), round(epx.overhang_area(m), 1),
                     len(m.faces)))
    print(f"{'part':22s} n  {'x':>6s} {'y':>6s} {'z':>6s}   cm3  overhang>45deg mm2  triangles")
    for r in rows:
        print(f"{r[0]:22s} {r[1]}  {r[2]:6.1f} {r[3]:6.1f} {r[4]:6.1f}  {r[5]:5.2f}  {r[6]:9.1f}  {r[7]:9d}")
    return rows


def check(tol=0.05):
    import cadquery as cq
    problems = []
    for kind in ("zero", "hq"):
        head = sk.head_zero_parts() if kind == "zero" else sk.head_hq_parts()
        names = [n for n in head if "lead" not in n and "ribbon" not in n]
        n_pairs = 0
        for a, b in itertools.combinations(names, 2):
            if a not in PRINTED and b not in PRINTED and not KIT(a) and not KIT(b):
                continue                                   # vendor-vs-vendor is byu-vcl's model
            n_pairs += 1
            v = epx._vol_common(epx._shape(head[a][0]), epx._shape(head[b][0]))
            if not v <= tol:
                problems.append((kind, "head", a, b, round(v, 3)))
        print(f"{kind}: {n_pairs} pairs inside the head checked")
        pc = sk.parts(kind)
        others = {**pc["fixed"], **pc["pan"]}
        depth = sk.tilt_depth(kind)
        for tilt in (-10, 0, 30, 60, 90):
            loc = cq.Location(cq.Vector(0, 0, -depth)) * cq.Location(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), tilt)
            for a in names:
                sa = epx._shape(head[a][0], loc)
                for b, (wb, _) in others.items():
                    v = epx._vol_common(sa, epx._shape(wb))
                    if not v <= tol:
                        problems.append((kind, f"tilt {tilt}", a, b, round(v, 3)))
        print(f"{kind}: poses checked")
    if problems:
        print("OVERLAPS:")
        for p in problems:
            print("  ", p)
    else:
        print("no overlaps above", tol, "mm3")
    return problems


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--no-export", action="store_true")
    a = ap.parse_args()
    if not a.no_export:
        export()
    if a.check:
        check()
