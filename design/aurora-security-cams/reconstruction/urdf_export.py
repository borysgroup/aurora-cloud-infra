"""The glovebox cell as an articulated robot description (URDF), for simulators and motion planners.

    python urdf_export.py      # -> out/urdf/aurora_glovebox.urdf, out/urdf/meshes/*.stl

Frames and units follow ROS (metres, radians; the meshes stay in mm with a 0.001 scale). The world frame
is the chamber frame of the reconstruction: x along the box from the antechamber-end wall, y from the
open side, z up from the deck.

Links and joints:

    glovebox      fixed     every static part of the reconstruction (one mesh, decimated)
    epson_base    fixed     Epson's base with its controller box, the riser and the status lamp, at the
                            fitted base pose (out/epson_cad_pose.json)
    epson_arm1    revolute  J1 about z, -132 to +132 deg            (with the user duct, which rides on it)
    epson_arm2    revolute  J2 about z at 325 mm, -150 to +150 deg  (with the black unit and the collar)
    epson_shaft   prismatic J3 down the shaft axis at 275 mm, 0 to 200 mm
    epson_tool    revolute  J4 about the shaft, -360 to +360 deg    (the end effector seen in the AURORA video)

Joint ranges, arm lengths and stroke are Epson's (T-B series manual). Velocity limits are Epson's
maximum operating speeds from the T-series manual's specification table (T6-602S row: J3 1000 mm/s, J4
1800 deg/s); J1 and J2 have only a composite tool speed there (4180 mm/s), so they carry the J4 value as a
loose upper bound (noted in the file). Effort limits are not published per joint and are left at a nominal 100 (unused by kinematic
planners). The joint values in the file are Epson's own convention (epson_cad.py), so a pose read off
the robot's controller can be set directly.

The script checks itself: it loads the URDF with yourdfpy, poses it at the parked joint values and at
the two poses read off the AURORA video, and compares every link's mesh with epson_cad.posed().
"""
import json
import os

import numpy as np
import trimesh

import epson_cad as E
import scene_detail as SD
from cameras import CAL

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "urdf")
MESH = os.path.join(OUT, "meshes")
T6_SPEED = dict(j3_mm_s=1000.0, j4_deg_s=1800.0)    # T-series manual, T6-602S row: J1+J2 4180 mm/s composite, J3 1000 mm/s, J4 1800 deg/s


def tr(x, y, z):
    return trimesh.transformations.translation_matrix((x, y, z))


def save(name, meshes, T=np.eye(4), max_faces=60000):
    m = trimesh.util.concatenate([q.copy() for q in meshes])
    m.apply_transform(T)
    if len(m.faces) > max_faces:
        m = m.simplify_quadric_decimation(face_count=max_faces)
    m.export(os.path.join(MESH, f"{name}.stl"))
    return f"meshes/{name}.stl"


def static_meshes():
    parts = []
    for f in (SD.shell, SD.ducts, SD.breadboards, SD.exfoliator, SD.microscope, SD.deck_items, SD.cables):
        parts += f()
    for f in (SD.tray, SD.gantry):
        parts += f(CAL)
    return [p.mesh for p in parts if getattr(p, "image", None) is None
            and getattr(p, "material", "") not in ("window", "lens_glass")]


def link_xml(name, mesh_file, colour, origin_xyz=(0, 0, 0)):
    xyz = " ".join(f"{v / 1000:.6f}" for v in origin_xyz)
    geo = f'<geometry><mesh filename="{mesh_file}" scale="0.001 0.001 0.001"/></geometry>'
    return (f'  <link name="{name}">\n'
            f'    <visual><origin xyz="{xyz}" rpy="0 0 0"/>{geo}<material name="{name}_mat"><color rgba="{colour}"/>'
            f'</material></visual>\n'
            f'    <collision><origin xyz="{xyz}" rpy="0 0 0"/>{geo}</collision>\n'
            f'  </link>\n')


def joint_xml(name, kind, parent, child, xyz, rpy=(0, 0, 0), axis=(0, 0, 1), lo=None, hi=None, vel=None, note=""):
    s = f'  <joint name="{name}" type="{kind}">\n'
    if note:
        s = f"  <!-- {note} -->\n" + s
    s += f'    <parent link="{parent}"/><child link="{child}"/>\n'
    s += f'    <origin xyz="{" ".join(f"{v:.6f}" for v in xyz)}" rpy="{" ".join(f"{v:.6f}" for v in rpy)}"/>\n'
    if kind != "fixed":
        s += f'    <axis xyz="{" ".join(f"{v:g}" for v in axis)}"/>\n'
        s += f'    <limit lower="{lo:.6f}" upper="{hi:.6f}" effort="100" velocity="{vel:.4f}"/>\n'
    return s + "  </joint>\n"


def build():
    os.makedirs(MESH, exist_ok=True)
    p = json.load(open(os.path.join(HERE, "out", "epson_cad_pose.json")))
    pose = dict(j1=tuple(p["base"]["j1"]), z0=p["base"]["z0"], yaw=p["base"]["yaw"])
    L = E.links(hi=False)
    x3 = E.L1 + E.L2
    # tool and attachments in the links' own frames (scene_detail.end_effector with identity transforms)
    ee = SD.end_effector(np.eye(4), np.eye(4))
    on_arm2 = [q.mesh for q in ee if "collar" in q.name or "into the shaft" in q.name]
    on_tool = [q.mesh for q in ee if q not in on_arm2 and not ("collar" in q.name or "into the shaft" in q.name)]
    unit = E.unit_box()
    h = pose["z0"] - 75.7
    riser = trimesh.creation.box(extents=(288, 179, h)).apply_transform(tr(-71.0, 0, -h / 2))
    files = dict(
        glovebox=save("glovebox", static_meshes(), max_faces=80000),
        epson_base=save("epson_base", [L["base"], riser]),
        epson_arm1=save("epson_arm1", [L["arm1"], L["cable"]]),
        epson_arm2=save("epson_arm2", [L["arm2"], unit] + on_arm2, tr(-E.L1, 0, 0)),
        epson_shaft=save("epson_shaft", [L["shaft"]], tr(-x3, 0, 0)),
        epson_tool=save("epson_tool", on_tool, tr(-x3, 0, 0)),
    )
    white, grey, dark = "0.83 0.85 0.84 1", "0.78 0.80 0.81 1", "0.12 0.12 0.12 1"
    x = '<?xml version="1.0"?>\n'
    x += ("<!-- Aurora exfoliation glovebox: the reconstruction in design/aurora-security-cams/reconstruction as an "
          "articulated model. World frame = chamber frame (x from the antechamber-end wall, y from the open side, "
          "z up from the deck). Written by urdf_export.py. -->\n")
    x += '<robot name="aurora_glovebox">\n'
    x += '  <link name="world"/>\n'
    x += link_xml("glovebox", files["glovebox"], "0.72 0.70 0.66 1")
    x += joint_xml("world_to_glovebox", "fixed", "world", "glovebox", (0, 0, 0))
    x += link_xml("epson_base", files["epson_base"], white)
    x += joint_xml("epson_mount", "fixed", "glovebox", "epson_base",
                   (pose["j1"][0] / 1000, pose["j1"][1] / 1000, pose["z0"] / 1000), (0, 0, np.radians(pose["yaw"])),
                   note="J1 axis at the base's underside; the base's front (Epson local +X) at yaw from +x")
    x += link_xml("epson_arm1", files["epson_arm1"], white)
    x += joint_xml("J1", "revolute", "epson_base", "epson_arm1", (0, 0, 0), lo=-np.radians(132), hi=np.radians(132),
                   vel=np.radians(T6_SPEED["j4_deg_s"]),
                   note="velocity: the spec sheet gives J1 and J2 only as a composite tool speed; J4's limit is used "
                        "as a loose bound")
    x += link_xml("epson_arm2", files["epson_arm2"], white)
    x += joint_xml("J2", "revolute", "epson_arm1", "epson_arm2", (E.L1 / 1000, 0, 0), lo=-np.radians(150),
                   hi=np.radians(150), vel=np.radians(T6_SPEED["j4_deg_s"]))
    x += link_xml("epson_shaft", files["epson_shaft"], grey)
    x += joint_xml("J3", "prismatic", "epson_arm2", "epson_shaft", (E.L2 / 1000, 0, 0), axis=(0, 0, -1), lo=0.0,
                   hi=E.LIMITS["z"] / 1000, vel=T6_SPEED["j3_mm_s"] / 1000,
                   note="J3 = travel down from the shaft's top stop (Epson's z, 0 to 200 mm)")
    x += link_xml("epson_tool", files["epson_tool"], dark)
    x += joint_xml("J4", "revolute", "epson_shaft", "epson_tool", (0, 0, 0), lo=-2 * np.pi, hi=2 * np.pi,
                   vel=np.radians(T6_SPEED["j4_deg_s"]))
    x += "</robot>\n"
    path = os.path.join(OUT, "aurora_glovebox.urdf")
    open(path, "w").write(x)
    return path, pose, p


def check(path, pose, p):
    """Pose the URDF with yourdfpy and compare each Epson link with epson_cad.posed() (max vertex gap, mm)."""
    import yourdfpy
    u = yourdfpy.URDF.load(path, build_scene_graph=True, load_meshes=False, build_collision_scene_graph=False)
    vp = json.load(open(os.path.join(HERE, "out", "video_robot_poses.json")))
    tests = {"parked": p["parked"]}
    for k in ("video_transfer_612", "video_transfer_640"):
        if k in vp:
            tests[k] = vp[k]["pose"]
    L = E.links(hi=False)
    res = {}
    for name, q in tests.items():
        cfg = dict(J1=np.radians(q["j1"]), J2=np.radians(q["j2"]), J3=q.get("z", 0.0) / 1000, J4=np.radians(q.get("u", 0.0)))
        u.update_cfg(cfg)
        ref = E.posed(pose, q["j1"], q["j2"], q.get("z", 0.0), q.get("u", 0.0), with_unit=False)
        gaps = {}
        for link, key, off in (("epson_arm1", "arm1", 0.0), ("epson_arm2", "arm2", E.L1),
                               ("epson_shaft", "shaft", E.L1 + E.L2)):
            T = u.get_transform(link, "world")
            v = L[key].vertices - np.array([off, 0, 0])
            got = (T[:3, :3] @ (v.T / 1000.0)).T + T[:3, 3]
            gaps[link] = round(float(np.abs(got * 1000 - ref[key].vertices).max()), 4)
        res[name] = gaps
    return res


if __name__ == "__main__":
    path, pose, p = build()
    res = check(path, pose, p)
    json.dump(dict(urdf=os.path.relpath(path, HERE), max_vertex_gap_mm=res), open(os.path.join(OUT, "check.json"), "w"),
              indent=1)
    print(path, json.dumps(res))
