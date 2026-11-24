"""Epson's own T6-B602S CAD, articulated, in the aurora_chamber frame.

Epson publishes the robot as a STEP assembly of five links (base, arm 1, arm 2, shaft and the user
duct) on its T6-B602S support page. The file is not redistributed here: `fetch()` downloads it into a
cache directory and meshes each link with gmsh, in the robot's local frame used by scene.py (origin on
the J1 axis at the base underside, X towards J2 with the arm straight, Y to its left, Z up). In the STEP
frame J1, J2 and J3 sit at x = -62.5, -387.5 and -662.5 mm (325 and 275 mm links), with y up.

    pip install gmsh trimesh fast-simplification     # gmsh also needs libGLU (apt: libglu1-mesa)
    python epson_cad.py                              # fetch, mesh and print the link bounds

Joint angles follow Epson's convention: j1 about the base's own axis (0 = arm pointing at the base's
front), j2 of arm 2 relative to arm 1, z the shaft's travel down from its top stop (0 to 200 mm), u
the shaft's rotation. Limits from the T-B manual: j1 +/-132 deg, j2 +/-150 deg, z 0-200 mm.
"""
import json
import os
import urllib.request

import numpy as np
import trimesh

STEP_URL = "https://download.epson-europe.com/pub/download/6495/epson649576eu.stp"  # T6-B602S - 3D CAD (v1.0)
CACHE = os.environ.get("EPSON_CAD_CACHE", os.path.expanduser("~/.cache/aurora-epson-t6"))
J1_XS = -62.5
L1, L2 = 325.0, 275.0
LIMITS = dict(j1=132.0, j2=150.0, z=200.0)
LINKS = ("base", "arm1", "arm2", "shaft", "cable")
COLORS = dict(base="#d4dad5", arm1="#d4dad5", arm2="#d4dad5", shaft="#c8ccce", cable="#202020",
              unit="#151515")
FACES = dict(base=9000, arm1=3000, arm2=6000, shaft=800, cable=1200)   # decimation targets
FACES_HI = dict(base=90000, arm1=30000, arm2=60000, shaft=8000, cable=20000)   # for renders (hi=True)


def fetch(cache=CACHE, hi=False):
    """Download the STEP (once) and mesh each link into cache/<link>.stl (cache/<link>_hi.stl with
    hi=True: finer curvature-driven meshing for renders). Returns the cache path."""
    os.makedirs(cache, exist_ok=True)
    sfx = "_hi" if hi else ""
    if all(os.path.exists(os.path.join(cache, f"{k}{sfx}.stl")) for k in LINKS):
        return cache
    step = os.path.join(cache, "T6-B602S.stp")
    if not os.path.exists(step):
        urllib.request.urlretrieve(STEP_URL, step)
    import gmsh
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setNumber("Geometry.OCCImportLabels", 1)
    gmsh.model.occ.importShapes(step)
    gmsh.model.occ.synchronize()
    for k, v in (("Mesh.MeshSizeMin", 0.5 if hi else 1.0), ("Mesh.MeshSizeMax", 8.0 if hi else 25.0),
                 ("Mesh.MeshSizeFromCurvature", 28 if hi else 10), ("Mesh.Algorithm", 6)):
        gmsh.option.setNumber(k, v)
    names = {}
    for d, t in gmsh.model.getEntities(3):
        n = gmsh.model.getEntityName(d, t).split("/")[-1]
        if n.endswith("ws"):                     # Epson's work-envelope solid, not a part
            gmsh.model.removeEntities([(d, t)], recursive=True)
            continue
        names[t] = n.replace("_T6-B601S", "").strip(" _").replace(" ", "_")
    gmsh.model.mesh.generate(2)

    def to_local(P):
        return np.c_[-(P[:, 0] - J1_XS), P[:, 2], P[:, 1]]      # STEP (x, y up, z) -> local (X fwd, Y, Z up)

    for t, key in names.items():
        nodes, faces, logo = {}, [], []
        for _, s in gmsh.model.getBoundary([(3, t)], oriented=False, recursive=False):
            nt, nc, _ = gmsh.model.mesh.getNodes(2, s, includeBoundary=True)
            nodes.update({int(g): nc[3 * i:3 * i + 3] for i, g in enumerate(nt)})
            dest = faces
            if hi and key == "arm2" and is_logo_surface(s, to_local):
                dest = logo
            for typ, conn in zip(*gmsh.model.mesh.getElements(2, s)[::2]):
                if typ == 2:
                    dest.append(np.asarray(conn, np.int64).reshape(-1, 3))
        tags = np.array(sorted(nodes))
        lut = np.zeros(tags.max() + 1, np.int64)
        lut[tags] = np.arange(len(tags))
        local = to_local(np.array([nodes[g] for g in tags]))
        m = trimesh.Trimesh(local, lut[np.vstack(faces)], process=True)
        m.merge_vertices()
        target = (FACES_HI if hi else FACES).get(key, 4000)
        if len(m.faces) > target:
            m = m.simplify_quadric_decimation(face_count=target)
        m.export(os.path.join(cache, f"{key}{sfx}.stl"))
        if logo:
            lm = trimesh.Trimesh(local, lut[np.vstack(logo)], process=True)
            lm.remove_unreferenced_vertices()
            lm.export(os.path.join(cache, f"{key}_logo{sfx}.stl"))
    gmsh.finalize()
    return cache


def is_logo_surface(s, to_local):
    """The EPSON wordmark is modelled in relief on both sides of arm 2: about 135 small B-rep faces per
    side, centred near (420, +/-60, 360) mm in the link frame. Picked by size and position."""
    import gmsh
    if gmsh.model.occ.getMass(2, s) > 250:
        return False
    bb = np.array(gmsh.model.getBoundingBox(2, s))
    c = to_local(((bb[:3] + bb[3:]) / 2)[None])[0]
    return abs(c[0] - 420) < 75 and 40 < abs(c[1]) < 80 and abs(c[2] - 360) < 60


def logo(cache=CACHE):
    """The relief EPSON wordmarks on arm 2 (hi-detail meshing only), in arm 2's frame, or None."""
    fetch(cache, hi=True)
    p = os.path.join(cache, "arm2_logo_hi.stl")
    return trimesh.load(p) if os.path.exists(p) else None


_links = {}


def links(cache=CACHE, hi=False):
    if hi not in _links:
        fetch(cache, hi)
        sfx = "_hi" if hi else ""
        _links[hi] = {k: trimesh.load(os.path.join(cache, f"{k}{sfx}.stl")) for k in LINKS}
    return _links[hi]


def rz(deg, about=(0.0, 0.0)):
    T = trimesh.transformations.rotation_matrix(np.radians(deg), (0, 0, 1), (about[0], about[1], 0))
    return T


def tz(dz):
    return trimesh.transformations.translation_matrix((0, 0, dz))


def base_transform(pose):
    """Local -> chamber frame: J1 at pose['j1'] (x, y), base underside at pose['z0'], base front at
    pose['yaw'] degrees from +x."""
    T = rz(pose["yaw"])
    T[:3, 3] = (pose["j1"][0], pose["j1"][1], pose["z0"])
    return T


def link_transforms(j1, j2, z=0.0, u=0.0):
    """Local transforms of each link for joint values (degrees, mm)."""
    A1 = rz(j1)
    A2 = A1 @ rz(j2, about=(L1, 0.0))
    S = A2 @ tz(-z) @ rz(u, about=(L1 + L2, 0.0))
    return dict(base=np.eye(4), arm1=A1, arm2=A2, shaft=S, cable=A1, unit=A2)


def unit_box():
    """The black unit Overhead 2 sees riding on arm 2 (make unknown): 120 x 100 x 45 mm, centred 100 mm
    past J2 on top of arm 2 (scene.py)."""
    b = trimesh.creation.box(extents=(120, 100, 45))
    b.apply_translation((L1 + 100, 0, 465.3 + 22.5))
    return b


def posed(pose, j1, j2, z=0.0, u=0.0, ceiling=None, with_unit=True, hi=False):
    """{name: trimesh} in the chamber frame. ceiling: squash the user duct to stay below this height
    (the duct's free arc is 245 mm tall, more than the glovebox leaves above the base)."""
    B = base_transform(pose)
    L = link_transforms(j1, j2, z, u)
    out = {}
    for k, m in links(hi=hi).items():
        m = m.copy()
        if k == "cable" and ceiling is not None:
            top = ceiling - pose["z0"] - 8.0
            v = m.vertices.copy()
            lo = 443.8
            if v[:, 2].max() > top:
                v[:, 2] = lo + (v[:, 2] - lo) * (top - lo) / (v[:, 2].max() - lo)
                m.vertices = v
        m.apply_transform(B @ L[k])
        out[k] = m
    if with_unit:
        out["unit"] = unit_box().apply_transform(B @ L["unit"])
    return out


def from_scene_robot(r):
    """Convert scene.py's ROBOT dict (absolute arm angles, back direction) to (pose, j1, j2)."""
    yaw = r["back_yaw_deg"] + 180.0
    pose = dict(j1=tuple(r["j1"]), z0=r["base_underside_z"], yaw=yaw)
    j1 = (r["th1_deg"] - yaw + 180.0) % 360.0 - 180.0
    return pose, j1, r["th2_deg"]


if __name__ == "__main__":
    for k, m in links().items():
        print(k, len(m.faces), np.round(m.bounds, 1).tolist())
    print(json.dumps(dict(limits=LIMITS, L1=L1, L2=L2)))
