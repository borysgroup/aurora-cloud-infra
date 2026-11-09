"""Simplified solids of the chamber in CadQuery, for STEP/STL export and for use in other CAD models.

    from aurora_chamber import cad
    parts = cad.build_parts()            # {name: (cadquery Shape, colour)}
    cad.export("design/aurora-chamber/cad")

Built from the same numbers and specs as the PyVista scene. The robot is in the
walkthrough's parked pose at the design riser (RISER_H); the swept volume covers
the whole riser range. Glass, gloves, cables and the stand are left out or reduced
to plates.
"""

import json
from pathlib import Path

import cadquery as cq
import numpy as np
from cadquery import Solid, Vector

from . import robot, scene, specs
from .params import (ANTE_DOOR_C, ANTE_DOOR_R, BACK_LEAN, CEILING_STUD_LEN, DOME_C, FLANGE_STUD_LEN, FRONT_LEAN,
                     GB_D, GB_H, GB_W, MINI_C, MINI_R, OPENING, RISER_H, RISER_RANGE, SCALE, SHELF_T, STUD_D,
                     WALL_T)

GLASS_T = 10.0   # window thickness (drawing only)


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def to_cq(spec):
    """CadQuery solid of one primitive spec (None for drawing-only kinds)."""
    k = spec["kind"]
    if k == "box":
        lo, hi = spec["lo"], spec["hi"]
        return Solid.makeBox(*(hi - lo), pnt=Vector(*lo))
    if k == "obox":
        sx, sy, sz = spec["size"]
        s = Solid.makeBox(sx, sy, sz, pnt=Vector(-sx / 2, -sy / 2, -sz / 2))
        return s.rotate(Vector(0, 0, 0), Vector(0, 0, 1), spec["yaw"]).translate(Vector(*spec["center"]))
    if k == "cyl":
        d = _unit(spec["direction"])
        base = spec["center"] - d * spec["h"] / 2
        return Solid.makeCylinder(spec["r"], spec["h"], Vector(*base), Vector(*d))
    if k == "ring":
        n = _unit(spec["normal"])
        base = Vector(*(spec["center"] - n * spec["t"] / 2))
        s = Solid.makeCylinder(spec["r_out"], spec["t"], base, Vector(*n))
        if spec["r_in"] > 0:
            s = s.cut(Solid.makeCylinder(spec["r_in"], spec["t"], base, Vector(*n)))
        return s
    if k == "tube":
        pts = [Vector(*p) for p in spec["points"]]
        path = cq.Wire.assembleEdges([cq.Edge.makeSpline(pts)])
        prof = cq.Wire.makeCircle(spec["r"], pts[0], path.tangentAt(0))
        try:
            return Solid.sweep(prof, [], path, makeSolid=True, isFrenet=False, transitionMode="right")
        except Exception:   # fall back to straight segments between the points
            segs = []
            for a, b in zip(spec["points"][:-1], spec["points"][1:]):
                d = b - a
                segs.append(Solid.makeCylinder(spec["r"], float(np.linalg.norm(d)), Vector(*a), Vector(*_unit(d))))
            return cq.Compound.makeCompound(segs)
    return None


def _compound(shapes):
    shapes = [s for s in shapes if s is not None]
    return shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)


def _yz_prism(pts_yz, x0, x1):
    """Polygon given in (y, z), extruded along x from x0 to x1."""
    wp = cq.Workplane("YZ", origin=(x0, 0, 0)).polyline([tuple(p) for p in pts_yz]).close()
    return wp.extrude(x1 - x0).val()


def shell():
    fy, by = scene.front_window_y, scene.back_window_y
    section = [(0, 0), (GB_D, 0), (by(GB_H), GB_H), (fy(GB_H), GB_H)]
    return _compound([
        Solid.makeBox(GB_W, GB_D, WALL_T, pnt=Vector(0, 0, -WALL_T)),                 # deck
        _yz_prism(section, -WALL_T, 0.0),                                              # antechamber-end wall
        _yz_prism(section, GB_W, GB_W + WALL_T),                                       # far end wall
        Solid.makeBox(GB_W, by(GB_H) - fy(GB_H), WALL_T, pnt=Vector(0, fy(GB_H), GB_H)),   # ceiling
    ])


def windows():
    """Both long-side windows as plates following their slopes."""
    front = [(0, 0), (FRONT_LEAN, GB_H), (FRONT_LEAN - GLASS_T, GB_H), (-GLASS_T, 0)]
    back = [(GB_D, 0), (GB_D - BACK_LEAN, GB_H), (GB_D - BACK_LEAN + GLASS_T, GB_H), (GB_D + GLASS_T, 0)]
    return _compound([_yz_prism(front, 0, GB_W), _yz_prism(back, 0, GB_W)])


def window_frames():
    """Flanges round both window openings (beams and posts), with their welded studs."""
    out = []
    x0, x1, z0, z1 = OPENING
    for side in ("front", "back"):
        y_at = scene.front_window_y if side == "front" else scene.back_window_y
        o = 30.0 * np.sign(scene.window_normal(side)[1])
        for za, zb in ((-10.0, z0), (z1, GB_H + 10.0)):
            out.append(_yz_prism([(y_at(za), za), (y_at(za) + o, za), (y_at(zb) + o, zb), (y_at(zb), zb)],
                                 -10.0, GB_W + 10.0))
        for xa, xb in ((-10.0, x0), (x1, GB_W + 10.0)):
            out.append(_yz_prism([(y_at(z0), z0), (y_at(z0) + o, z0), (y_at(z1) + o, z1), (y_at(z1), z1)], xa, xb))
    return _compound(out)


def flange_studs():
    return _compound([Solid.makeCylinder(STUD_D / 2, FLANGE_STUD_LEN, Vector(*p), Vector(*n))
                      for side in ("front", "back") for p, n in scene.flange_studs(side)])


def ceiling_studs():
    return _compound([Solid.makeCylinder(STUD_D / 2, CEILING_STUD_LEN, Vector(st["xy"][0], st["xy"][1],
                                                                           GB_H - CEILING_STUD_LEN), Vector(0, 0, 1))
                      for st in scene.CEILING_STUDS.values()])


def antechamber_doors():
    _, cy, cz = ANTE_DOOR_C
    _, my, mz = MINI_C
    x = Vector(1, 0, 0)
    return _compound([
        Solid.makeCylinder(ANTE_DOOR_R, 12.0, Vector(2.0, cy, cz), x),                 # inner door
        Solid.makeCylinder(22.0, 18.0, Vector(7.0, cy, cz), x),                        # hub
        Solid.makeCylinder(MINI_R, 110.0, Vector(0.0, my, mz), x),                     # mini tube, inside
        Solid.makeCylinder(MINI_R + 8.0, 12.0, Vector(106.0, my, mz), x),              # mini inner door
    ])


def swept_volume(risers=None):
    """The Epson's swept volume over the riser range (see robot.py), clipped to the box."""
    cyls = [to_cq(sp) for sp in specs.envelope_specs(risers)]
    vol = cyls[0]
    for c in cyls[1:]:
        vol = vol.fuse(c)
    return vol.intersect(Solid.makeBox(GB_W, GB_D, GB_H, pnt=Vector(0, 0, 0))).clean()


def build_parts(robot_target=None, risers=None):
    """{name: (shape, colour)} of the simplified chamber."""
    exf = specs.exfoliator_specs()
    epson, _ = specs.scara_specs(target=robot_target)
    bx, by = robot.SCARA_XY
    shelf = specs.Box((bx - 240, by - 190, 0), (min(bx + 240, GB_W - 20), min(by + 260, GB_D - 30), SHELF_T),
                      specs.BLACK, "shelf")
    dome = cq.Solid.makeSphere(48.0, Vector(*(DOME_C - (0, 0, 40))), angleDegrees1=-90, angleDegrees2=90)
    return {
        "chamber_shell": (shell(), "#c9ced3"),
        "windows": (windows(), "#bfe3ff"),
        "window_frames": (window_frames(), "#9aa1a8"),
        "flange_studs": (flange_studs(), "#8a9097"),
        "ceiling_studs": (ceiling_studs(), "#16b364"),
        "antechamber_doors": (antechamber_doors(), "#c9ced3"),
        "exfoliator": (_compound([to_cq(s) for s in exf if s["name"] != "substrate plate"]), "#26282b"),
        "substrate_plate": (to_cq(specs.substrate_plate_spec()), "#e6e8ea"),
        "chip_tray": (to_cq(specs.tray_spec()), "#c3c8cd"),
        "robot_shelf": (to_cq(shelf), "#26282b"),
        "epson_t6_parked": (_compound([to_cq(s) for s in epson if s["kind"] != "tube"]), "#eceef0"),
        "epson_duct": (_compound([to_cq(s) for s in epson if s["kind"] == "tube"]), "#26282b"),
        "epson_swept_volume": (swept_volume(risers), "#7c3aed"),
        "ceiling_items": (_compound([to_cq(s) for s in specs.ceiling_specs()] + [dome]), "#f2f2f2"),
    }


def _rgb(hex_color):
    return tuple(int(hex_color[k:k + 2], 16) / 255 for k in (1, 3, 5))


def export(out_dir, robot_target=None):
    """Writes aurora_chamber.step (one assembly, named and coloured parts), stl/<part>.stl and parts.json."""
    out_dir = Path(out_dir)
    (out_dir / "stl").mkdir(parents=True, exist_ok=True)
    parts = build_parts(robot_target)
    assy = cq.Assembly(name="aurora_chamber")
    meta = dict(units="mm", frame="scene frame of aurora_chamber/params.py: x along the box from the antechamber-end "
                                   "wall, y from the open side, z up from the deck",
                scale=SCALE, riser_mm=RISER_H, riser_range_mm=list(RISER_RANGE),
                robot_pose="walkthrough's parked pose" if robot_target is None else list(map(float, robot_target)),
                parts={})
    for name, (shape, color) in parts.items():
        assy.add(shape, name=name, color=cq.Color(*_rgb(color)))
        shape.exportStl(str(out_dir / "stl" / f"{name}.stl"), tolerance=0.3, angularTolerance=0.3)
        bb = shape.BoundingBox()
        meta["parts"][name] = dict(bounds_mm=[round(v, 1) for v in (bb.xmin, bb.xmax, bb.ymin, bb.ymax, bb.zmin, bb.zmax)],
                                   volume_cm3=round(shape.Volume() / 1000.0, 1))
    step = out_dir / "aurora_chamber.step"
    if hasattr(assy, "export"):
        assy.export(str(step))
    else:
        assy.save(str(step))
    (out_dir / "parts.json").write_text(json.dumps(meta, indent=1) + "\n")
    return parts, meta
