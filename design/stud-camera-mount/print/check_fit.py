"""Interference check of both stud mounts with all hardware: boards, cameras, lens, ribbons, screws, inserts, tilt
bolts and washers, the stud's washer and nut. Every pair of solids inside the head is checked, and the head against
the yoke, knobs, bolts and stud at several tilts. Contacts that are there by design are listed in EXPECTED.

    python print/check_fit.py          # from design/stud-camera-mount
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import cadquery as cq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stud_mount as sm  # noqa: E402

TOL = 0.5                       # mm^3; smaller overlaps are tessellation-level and ignored
TILTS = (-10.0, 0.0, 30.0, 60.0, 90.0)
# (a, b) name fragments whose overlap is intended: thread-forming screws in pilot holes, heat-set inserts in their
# holes (they melt in), bolts in inserts, ribbons in their connectors, the zoom's thread in the HQ mount.
EXPECTED = [("screws", "case"), ("screws", "back cover"), ("screws", "frame"), ("screws", "carrier"),
            ("screws", "nose"), ("screws", "board"), ("inserts", "case"), ("inserts", "frame"),
            ("ribbon", "connector"), ("zoom lens", "HQ mount"), ("tilt bolts", "inserts"),
            ("tilt bolts", "tilt knobs"), ("ceiling stud", "stud thumb nut"), ("lens screws", "zoom lens")]


def expected(a, b):
    return any((x in a and y in b) or (x in b and y in a) for x, y in EXPECTED)


def overlap(s1, s2):
    try:
        v = s1.intersect(s2).val().Volume()
    except Exception:            # an empty intersection can come back as an empty compound
        v = 0.0
    return v


def bbox_hit(s1, s2):
    a, b = s1.val().BoundingBox(), s2.val().BoundingBox()
    return not (a.xmax < b.xmin or b.xmax < a.xmin or a.ymax < b.ymin or b.ymax < a.ymin or
                a.zmax < b.zmin or b.zmax < a.zmin)


def check(kind):
    pc = sm.parts(kind)
    depth = sm.tilt_depth(kind)
    head = {n: s for n, (s, _) in pc["head"].items() if "lead" not in n}
    pan = {n: s for n, (s, _) in pc["pan"].items()}
    pan.update({n: s for n, (s, _) in pc["fixed"].items()})
    hits = []
    for (a, sa), (b, sb) in itertools.combinations(head.items(), 2):
        if expected(a, b) or not bbox_hit(sa, sb):
            continue
        v = overlap(sa, sb)
        if v > TOL:
            hits.append(("head", a, b, round(v, 2)))
    for (a, sa), (b, sb) in itertools.combinations(pan.items(), 2):
        if expected(a, b) or not bbox_hit(sa, sb):
            continue
        v = overlap(sa, sb)
        if v > TOL:
            hits.append(("yoke", a, b, round(v, 2)))
    for t in TILTS:
        posed = {n: s.rotate((0, 0, 0), (1, 0, 0), t).translate((0, 0, -depth)) for n, s in head.items()}
        for (a, sa), (b, sb) in itertools.product(posed.items(), pan.items()):
            if expected(a, b) or not bbox_hit(sa, sb):
                continue
            v = overlap(sa, sb)
            if v > TOL:
                hits.append((f"tilt {t:g}", a, b, round(v, 2)))
    return hits


if __name__ == "__main__":
    bad = 0
    for kind in ("zero", "hq"):
        hits = check(kind)
        print(f"{kind}: {len(hits)} unexpected overlaps")
        for h in hits:
            print("   ", h)
        bad += len(hits)
    sys.exit(1 if bad else 0)
