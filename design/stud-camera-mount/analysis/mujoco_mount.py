"""MuJoCo model of the stud mount: the yoke pans on the stud and the head tilts on the M4 bolts, each joint held only
by the friction torque that the thread preload produces (analysis/thread_analysis.py). Mass properties come from the
CadQuery solids (PLA at the sliced parts' effective density) plus catalogue masses for the boards, cameras and lens.

    python analysis/mujoco_mount.py        # writes analysis/mujoco_results.json

Checks, for each head and each knob-torque level (snug / firm / hard, and snug after PLA creep):
  1. gravity: worst-case gravity torque about the tilt and pan axes vs the holding torque (and a 2 s settle);
  2. glove bumps: a 50 ms half-sine push at the lens, in three directions; bisection for the peak force that moves
     the camera by 0.5 deg, and the joint reaction at that force (stud tension incl. prying, bolt axial load), which
     goes back into Shigley's joint relations (bolt load Fi + C P, separation margin Fi / ((1 - C) P)).
MuJoCo is a rigid-body solver: it gives loads and motion, not stresses; the stresses are in thread_analysis.py.
The joints' dry friction is a MuJoCo soft constraint; solimpfriction ~1 keeps it from creeping under steady load.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

import mujoco
import numpy as np
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import stud_mount as sm  # noqa: E402
import thread_analysis as ta  # noqa: E402

RHO_PLA = 1.24e-3 * 0.85        # g/mm^3: 6 walls + 40 % gyroid on these small parts ~85 % of solid
# catalogue masses (g); groups are matched by substring of the part name
MASSES = {
    "zero": {"Pi Zero": 11.0, "CM3": 4.0, "standoffs": 3.0, "ribbon": 1.0, "USB power lead": 5.0},
    "hq": {"zoom lens": 148.0, "lens screws": 0.0, "lens glass": 0.0, "HQ board": 18.0, "HQ mount": 12.0,
           "HQ connector": 0.0, "Pi 5": 46.0, "Active Cooler": 15.0, "Wide": 4.0, "standoffs": 6.0, "ribbon": 3.0},
}
PRINTED = {"case", "back cover", "camera plate", "Wide nose", "Pi carrier", "cheeks"}
STEEL_EXTRA = {"tilt": 2 * (2.4 + 0.3 + 1.0)}   # g: two M4x16 hex bolts, washers, brass inserts (on the head)


def props(shape):
    """(volume mm^3, centroid mm, inertia about centroid per unit density, mm^5)."""
    gp = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape.wrapped, gp)
    c = gp.CentreOfMass()
    m = gp.MatrixOfInertia()
    I = np.array([[m.Value(i, j) for j in (1, 2, 3)] for i in (1, 2, 3)])
    return gp.Mass(), np.array([c.X(), c.Y(), c.Z()]), I


def combine(items):
    """items: (mass g, com mm, inertia about own com g.mm^2) -> total (kg, m, kg.m^2)."""
    M = sum(m for m, _, _ in items)
    com = sum(m * c for m, c, _ in items) / M
    I = np.zeros((3, 3))
    for m, c, Ic in items:
        d = c - com
        I += Ic + m * (np.dot(d, d) * np.eye(3) - np.outer(d, d))
    return M / 1000, com / 1000, I * 1e-9


def body_mass(parts, groups):
    items = []
    by_group = {}
    for name, (wp, _) in parts.items():
        shape = wp.val() if len(wp.vals()) == 1 else wp.combine().val()
        v, c, I = props(shape)
        if name in PRINTED:
            items.append((v * RHO_PLA, c, I * RHO_PLA))
            continue
        key = next((g for g in groups if g in name), None)
        if key is None:
            continue
        by_group.setdefault(key, []).append((v, c, I))
    for key, lst in by_group.items():
        vt = sum(v for v, _, _ in lst)
        if vt <= 0 or groups[key] <= 0:
            continue
        rho = groups[key] / vt
        items += [(v * rho, c, I * rho) for v, c, I in lst]
    return items


def mount_bodies(kind):
    head = sm.head_zero_parts() if kind == "zero" else sm.head_hq_parts()
    items = body_mass(head, MASSES[kind])
    half, _ = sm.head_spec(kind)
    for sx in (-1, 1):   # knobs, bolts, washers, inserts rotate with the head (point masses on the axis)
        items.append((3.4 * 1.24 * 0.85 + STEEL_EXTRA["tilt"] / 2, np.array([sx * (half + 10.0), 0, 0]),
                      np.eye(3) * 50.0))
    head_m = combine(items)
    pan = sm.parts(kind)["pan"]
    yitems = []
    for name in ("yoke", "stud thumb nut"):
        v, c, I = props(pan[name][0].val())
        yitems.append((v * RHO_PLA, c, I * RHO_PLA))
    yitems.append((2.5 + 3.0, np.array([0, 0, -sm.PAD["t"] - 3.0]), np.eye(3) * 30.0))   # M6 nut + washer
    return head_m, combine(yitems)


def mjcf(kind, head_m, yoke_m, T_pan, T_tilt):
    depth = sm.tilt_depth(kind) / 1000
    lens = np.array(sm.lens_point(kind)) / 1000

    def inertial(mc):
        m, c, I = mc
        fi = " ".join(f"{x:.4e}" for x in (I[0, 0], I[1, 1], I[2, 2], I[0, 1], I[0, 2], I[1, 2]))
        return f'<inertial pos="{c[0]:.5f} {c[1]:.5f} {c[2]:.5f}" mass="{m:.5f}" fullinertia="{fi}"/>'

    return f"""
<mujoco model="stud_mount_{kind}">
  <option timestep="0.0005" gravity="0 0 -9.81" integrator="implicitfast"/>
  <default><joint solreffriction="0.002 1" solimpfriction="0.9999 0.9999 0.0001 0.5 2"/></default>
  <worldbody>
    <body name="yoke">
      <joint name="pan" type="hinge" axis="0 0 1" frictionloss="{T_pan:.5f}" damping="0.0005" armature="1e-6"/>
      {inertial(yoke_m)}
      <body name="head" pos="0 0 {-depth:.5f}">
        <joint name="tilt" type="hinge" axis="1 0 0" frictionloss="{T_tilt:.5f}" damping="0.0005"
               armature="1e-6"/>
        {inertial(head_m)}
        <site name="lens" pos="{lens[0]:.5f} {lens[1]:.5f} {lens[2]:.5f}"/>
      </body>
    </body>
  </worldbody>
</mujoco>"""


def reaction_at(model, data, body, point):
    """Force and moment that the parent exerts on `body` through its joint, about `point` (world), N and N.m."""
    mujoco.mj_rnePostConstraint(model, data)
    b = model.body(body).id
    tq, f = data.cfrc_int[b, :3].copy(), data.cfrc_int[b, 3:].copy()
    c = data.subtree_com[model.body_rootid[b]]
    return f, tq + np.cross(c - point, f)


def run(kind, head_m, yoke_m, T_pan, T_tilt, tilt_deg, push=None, F=0.0, dur=0.05, T_end=0.4):
    m = mujoco.MjModel.from_xml_string(mjcf(kind, head_m, yoke_m, T_pan, T_tilt))
    d = mujoco.MjData(m)
    d.qpos[:] = [0.0, math.radians(tilt_deg)]
    mujoco.mj_forward(m, d)
    q0 = d.qpos.copy()
    site = m.site("lens").id
    head = m.body("head").id
    peak = dict(stud_axial=0.0, stud_moment=0.0, tilt_axial=0.0, tilt_moment=0.0)
    depth = sm.tilt_depth(kind) / 1000
    while d.time < T_end:
        d.xfrc_applied[:] = 0
        if push is not None and d.time < dur:
            mag = F * math.sin(math.pi * d.time / dur)
            # push direction in the head frame, rotated to world
            R = d.site_xmat[site].reshape(3, 3)
            fw = R @ np.array(push) * mag
            p = d.site_xpos[site]
            torque = np.cross(p - d.xipos[head], fw)
            d.xfrc_applied[head, :3] = fw
            d.xfrc_applied[head, 3:] = torque
        mujoco.mj_step(m, d)
        if push is not None and d.time < dur + 0.01:
            fs, ms = reaction_at(m, d, "yoke", np.zeros(3))
            peak["stud_axial"] = max(peak["stud_axial"], fs[2])   # +z: the stud pulls the yoke up
            peak["stud_moment"] = max(peak["stud_moment"], math.hypot(ms[0], ms[1]))
            fh, mh = reaction_at(m, d, "head", d.xpos[head])
            Rh = d.xmat[head].reshape(3, 3)
            fl, ml = Rh.T @ fh, Rh.T @ mh
            peak["tilt_axial"] = max(peak["tilt_axial"], abs(fl[0]))
            peak["tilt_moment"] = max(peak["tilt_moment"], math.hypot(ml[1], ml[2]))
    dq = np.degrees(np.abs(d.qpos - q0))
    return dict(pan_deg=float(dq[0]), tilt_deg=float(dq[1])), peak


def gravity_torques(head_m, kind):
    """Worst gravity torque about the tilt axis over tilts 0-90 deg (N.m)."""
    m, c, _ = head_m
    worst = 0.0
    for t in range(0, 91, 5):
        a = math.radians(t)
        y = c[1] * math.cos(a) - c[2] * math.sin(a)
        worst = max(worst, abs(m * 9.81 * y))
    return worst


def main():
    th = json.loads((HERE / "thread_analysis.json").read_text())
    out = {}
    pushes = {"tilt (push across the view, in the tilt plane)": (0, 0, 1),
              "pan (push sideways, along the tilt axis)": (1, 0, 0),
              "axial (push on the lens front, back along the view)": (0, 1, 0)}
    for kind in ("zero", "hq"):
        head_m, yoke_m = mount_bodies(kind)
        stud, tilt = th["stud"], th["tilt"][kind]
        hold_tilt = min(tilt["hold_knobs_turn_Nmm_per_N"], tilt["hold_bolts_turn_Nmm_per_N"])
        g_tilt = gravity_torques(head_m, kind)
        res = dict(head_mass_g=round(head_m[0] * 1000, 1), head_com_mm=[round(x * 1000, 1) for x in head_m[1]],
                   yoke_mass_g=round(yoke_m[0] * 1000, 1), tilt_axis_depth_mm=sm.tilt_depth(kind),
                   gravity_torque_tilt_Nm=round(g_tilt, 3),
                   preload_for_gravity_N=round(g_tilt * 1000 / hold_tilt, 1),
                   knob_torque_for_gravity_Nm=round(g_tilt * 1000 / hold_tilt * tilt["K"] * 4 / 1000, 3),
                   levels={})
        levels = [(r["level"], r["Fi_N"], s["Fi_N"]) for r, s in zip(tilt["rows"], stud["rows"])]
        levels.append(("snug, after creep", tilt["rows"][0]["Fi_after_creep_N"], stud["rows"][0]["Fi_after_creep_N"]))
        for name, Fi_t, Fi_s in levels:
            T_tilt = Fi_t * hold_tilt / 1000
            T_pan = Fi_s * stud["pan_hold_Nmm_per_N"] / 1000
            lvl = dict(Fi_tilt_N=Fi_t, Fi_stud_N=Fi_s, T_hold_tilt_Nm=round(T_tilt, 3), T_hold_pan_Nm=round(T_pan, 3))
            drift = {}
            for t in (0, 45, 90):
                mv, _ = run(kind, head_m, yoke_m, T_pan, T_tilt, t, T_end=1.0)
                drift[t] = round(mv["tilt_deg"] + mv["pan_deg"], 4)
            lvl["gravity_drift_deg_1s"] = drift
            bumps = {}
            for pname, vec in pushes.items():
                lo, hi = 0.0, 200.0
                for _ in range(10):
                    mid = (lo + hi) / 2
                    mv, _ = run(kind, head_m, yoke_m, T_pan, T_tilt, 45, push=vec, F=mid)
                    if max(mv.values()) > 0.5:
                        hi = mid
                    else:
                        lo = mid
                mv, pk = run(kind, head_m, yoke_m, T_pan, T_tilt, 45, push=vec, F=lo)
                # joint loads back into Shigley: stud tension from axial pull + prying about the pad's edge,
                # bolt axial load from the head's sideways reaction (one bolt takes it), plus the head's bending
                P_stud = max(0.0, pk["stud_axial"]) + pk["stud_moment"] / (sm.PAD["d"] / 2000)
                half, _ = sm.head_spec(kind)
                P_bolt = pk["tilt_axial"] + pk["tilt_moment"] / (2 * half / 1000)
                Cs, Ct = stud["C"], tilt["C"]
                bumps[pname] = dict(
                    threshold_peak_force_N=round(lo, 1),
                    stud_P_N=round(P_stud, 1), stud_bolt_load_N=round(Fi_s + Cs * P_stud, 1),
                    stud_separation_margin=round(Fi_s / ((1 - Cs) * P_stud), 1) if P_stud > 0 else None,
                    bolt_P_N=round(P_bolt, 1), tilt_bolt_load_N=round(Fi_t + Ct * P_bolt, 1),
                    tilt_separation_margin=round(Fi_t / ((1 - Ct) * P_bolt), 1) if P_bolt > 0 else None,
                    insert_pullout_margin=round(tilt["insert_pullout_N"] / (Fi_t + Ct * P_bolt), 1))
            lvl["bumps_at_45deg"] = bumps
            res["levels"][name] = lvl
            print(kind, name, json.dumps(lvl)[:400], flush=True)
        out[kind] = res
    (HERE / "mujoco_results.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
