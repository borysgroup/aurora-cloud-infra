"""Export the all-printed stud mount's parts in print orientation, threads included, and check the assemblies.

    python printed/export_printed_stls.py            # writes printed/stl/*.stl, prints sizes and an overhang check
    python printed/export_printed_stls.py --check    # also: overlaps inside each head, and head vs yoke/stud/knob/
                                                     # screws at tilts -10..90 deg

Threads are cut (internal) or added (external) at mesh level with manifold3d; see threads.py.
Orientation: yokes on their ceiling face; thumb nut on its clamp face; tilt screw on its knob; Pi Zero case, HQ tub,
carrier and Wide nose on their front faces; back cover, HQ retainer and Pi 5 retainer on their back faces.
"""

from __future__ import annotations

import argparse
import itertools
import math
import pathlib
import sys

import numpy as np
import trimesh

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import stud_mount_printed as spm  # noqa: E402
import threads as th  # noqa: E402

OUT = HERE / "stl"
X_UP = [((1, 0, 0), 90)]            # head frame: front face (min y) down
BACK_DOWN = [((1, 0, 0), -90)]      # head frame: back face (max y) down
FLIP = [((1, 0, 0), 180)]


def _zero():
    return spm.head_zero_parts()


def _hq():
    return spm.head_hq_parts()


PARTS = {
    # name: (maker, thread ops (part frame), print rotation, copies for 2 Pi Zero mounts + 1 HQ mount)
    "yoke_zero": (lambda: spm.yoke("zero"), lambda: [], FLIP, 2),
    "yoke_hq": (lambda: spm.yoke("hq"), lambda: [], FLIP, 1),
    "stud_thumb_nut": (spm.stud_knob, spm.stud_knob_ops, FLIP, 3),
    "tilt_screw": (lambda: spm.tilt_screw_local("zero"), lambda: spm.tilt_screw_ops_local("zero"), [], 6),
    "head_zero_case": (lambda: _zero()["case"][0], lambda: spm.head_thread_ops("zero"), X_UP, 2),
    "head_zero_back_cover": (lambda: _zero()["back cover"][0], lambda: [], BACK_DOWN, 2),
    "head_hq_tub": (lambda: _hq()["tub"][0], lambda: spm.head_thread_ops("hq"), X_UP, 1),
    "head_hq_retainer": (lambda: _hq()["HQ retainer"][0], lambda: [], BACK_DOWN, 1),
    "head_hq_carrier": (lambda: _hq()["carrier"][0], lambda: [], X_UP, 1),
    "head_hq_pi5_retainer": (lambda: _hq()["Pi 5 retainer"][0], lambda: [], BACK_DOWN, 1),
    "head_hq_wide_nose": (lambda: _hq()["Wide nose"][0], lambda: [], X_UP, 1),
}
assert spm.screw_len("zero") == spm.screw_len("hq")   # one tilt screw fits both heads


def to_trimesh(wp, tol=0.02):
    verts, tris = [], []
    for sol in wp.vals():
        v, t = sol.tessellate(tol, 0.1)
        off = len(verts)
        verts += [(p.x, p.y, p.z) for p in v]
        tris += [(a + off, b + off, c + off) for a, b, c in t]
    return trimesh.Trimesh(np.array(verts), np.array(tris), process=True)


def thread_tool(op):
    if op["thread"] == "stud":
        t = spm.STUD_THREAD
        if op["kind"] != "tap":
            raise ValueError(op)
        tool = th.tap(t["d"], t["p"], op["length"], t["allowance"], entry_chamfer=t["entry_chamfer"],
                      blind=op.get("blind", False))
    else:
        t = spm.TILT_THREAD
        if op["kind"] == "tap":
            tool = th.tap(t["d"], t["p"], op["length"], t["int_allowance"], entry_chamfer=t["entry_chamfer"],
                          blind=op.get("blind", False))
        else:
            tool = th.external(t["d"], t["p"], op["length"], t["ext_allowance"])
    return th.frame(tool, op["origin"], op["axis"])


def with_threads(wp, ops):
    m = to_trimesh(wp)
    if not ops:
        return m
    man = th.to_manifold(m.vertices, m.faces)
    for op in ops:
        tool = thread_tool(op)
        man = man - tool if op["kind"] == "tap" else man + tool
    v, f = th.to_arrays(man)
    return trimesh.Trimesh(v, f, process=False)   # manifold3d output is already merged; re-merging can pinch slivers


def rotate(m, steps):
    for axis, deg in steps:
        m.apply_transform(trimesh.transformations.rotation_matrix(math.radians(deg), axis))
    return m


def overhang_area(m, limit_deg=45.0, bed_tol=0.05):
    n = m.face_normals
    down = n[:, 2] < -math.cos(math.radians(limit_deg))
    off_bed = m.triangles_center[:, 2] > bed_tol
    return float(m.area_faces[down & off_bed].sum())


def export():
    OUT.mkdir(exist_ok=True)
    rows = []
    for name, (make, ops, steps, n) in PARTS.items():
        m = rotate(with_threads(make(), ops()), steps)
        lo, hi = m.bounds
        m.apply_translation([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
        assert m.is_watertight, name
        m.export(OUT / f"{name}.stl")
        rows.append((name, n, *np.round(m.extents, 1), round(m.volume / 1000, 2), round(overhang_area(m), 1),
                     len(m.faces)))
    print(f"{'part':22s} n  {'x':>6s} {'y':>6s} {'z':>6s}   cm3  overhang>45deg mm2  triangles")
    for r in rows:
        print(f"{r[0]:22s} {r[1]}  {r[2]:6.1f} {r[3]:6.1f} {r[4]:6.1f}  {r[5]:5.2f}  {r[6]:9.1f}  {r[7]:9d}")
    return rows


# ---------------------------------------------------------------------------------------------- checks
def _vol_common(a, b):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    op = BRepAlgoAPI_Common(a, b)
    op.Build()
    if not op.IsDone():
        return float("nan")
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(op.Shape(), g)
    return g.Mass()


def _shape(wp, loc=None):
    import cadquery as cq
    vals = [v for v in wp.vals() if isinstance(v, cq.Shape)]
    s = vals[0] if len(vals) == 1 else cq.Compound.makeCompound(vals)
    return (s.moved(loc) if loc is not None else s).wrapped


def check(tol=0.05):
    import cadquery as cq
    problems = []
    for kind in ("zero", "hq"):
        head = spm.head_zero_parts() if kind == "zero" else spm.head_hq_parts()
        names = [n for n in head if "lead" not in n and "ribbon" not in n]
        printed = {"case", "back cover", "tub", "HQ retainer", "carrier", "Pi 5 retainer", "Wide nose"}
        n_pairs = 0
        for a, b in itertools.combinations(names, 2):
            if a not in printed and b not in printed:
                continue                                   # vendor-vs-vendor is byu-vcl's model
            n_pairs += 1
            v = _vol_common(_shape(head[a][0]), _shape(head[b][0]))
            if not v <= tol:
                problems.append((kind, "head", a, b, round(v, 3)))
        print(f"{kind}: {n_pairs} pairs inside the head checked")
        # head vs yoke, stud, thumb nut, screws at several tilts (pan 0)
        pc = spm.parts(kind)
        others = {**pc["fixed"], **pc["pan"]}
        depth = spm.tilt_depth(kind)
        for tilt in (-10, 0, 30, 60, 90):
            loc = cq.Location(cq.Vector(0, 0, -depth)) * cq.Location(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), tilt)
            for a in names:
                sa = _shape(head[a][0], loc)
                for b, (wb, _) in others.items():
                    v = _vol_common(sa, _shape(wb))
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
