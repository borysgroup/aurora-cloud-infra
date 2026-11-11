"""MuJoCo holding check for the all-printed stud mount: the same model as ../analysis/mujoco_mount.py (pan and tilt
hinges held only by friction), with the printed parts' masses and the holding torques from
thread_analysis_printed.json.

    python printed/mujoco_printed.py      # writes printed/mujoco_printed.json
"""

from __future__ import annotations

import json
import pathlib
import sys
import types

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "analysis"))
import mujoco_mount as mm  # noqa: E402
import stud_mount as sm  # noqa: E402
import stud_mount_printed as spm  # noqa: E402

RHO = 1.24e-3            # g/mm^3: the threaded parts are near solid; the rest is ~85 % (as in mujoco_mount.py)
FILL = {"tilt screw": 1.0, "stud thumb nut": 1.0}
PRINTED = {"case", "back cover", "tub", "HQ retainer", "carrier", "Pi 5 retainer", "Wide nose"}
MASSES = {"zero": {"Pi Zero": 11.0, "CM3": 4.0, "ribbon": 1.0, "USB power lead": 5.0},
          "hq": dict((k, v) for k, v in mm.MASSES["hq"].items() if k != "standoffs")}

# mujoco_mount reads the mount's geometry through its module global `sm`: point it at the printed variant
mm.sm = types.SimpleNamespace(tilt_depth=spm.tilt_depth, lens_point=sm.lens_point, PAD=sm.PAD,
                              head_spec=lambda kind: (spm.head_half(kind), None))
mm.PRINTED = PRINTED


def mount_bodies(kind):
    head = spm.head_zero_parts() if kind == "zero" else spm.head_hq_parts()
    items = mm.body_mass(head, MASSES[kind])
    half = spm.head_half(kind)
    v, _, I = mm.props(spm.tilt_screw_local(kind).val())
    for sx in (-1, 1):   # the screws turn with the head when it is forced (point masses on the axis)
        items.append((v * RHO, np.array([sx * (half + 10.0), 0, 0]), np.eye(3) * 60.0))
    head_m = mm.combine(items)
    pan = spm.parts(kind)["pan"]
    yitems = []
    for name, fill in (("yoke", 0.85), ("stud thumb nut", 1.0)):
        v, c, I = mm.props(pan[name][0].val())
        yitems.append((v * RHO * fill, c, I * RHO * fill))
    return head_m, mm.combine(yitems)


def main():
    th = json.loads((HERE / "thread_analysis_printed.json").read_text())
    out = {}
    pushes = {"tilt (push across the view, in the tilt plane)": (0, 0, 1),
              "pan (push sideways, along the tilt axis)": (1, 0, 0)}
    for kind in ("zero", "hq"):
        head_m, yoke_m = mount_bodies(kind)
        stud, tilt = th["stud"], th["tilt"][kind]
        hold_tilt = min(tilt["hold_knobs_turn_Nmm_per_N"], tilt["hold_bolts_turn_Nmm_per_N"])
        g_tilt = mm.gravity_torques(head_m, kind)
        res = dict(head_mass_g=round(head_m[0] * 1000, 1), head_com_mm=[round(x * 1000, 1) for x in head_m[1]],
                   yoke_and_nut_mass_g=round(yoke_m[0] * 1000, 1), tilt_axis_depth_mm=spm.tilt_depth(kind),
                   gravity_torque_tilt_Nm=round(g_tilt, 3),
                   preload_for_gravity_N=round(g_tilt * 1000 / hold_tilt, 1),
                   knob_torque_for_gravity_Nm=round(g_tilt * 1000 / hold_tilt * tilt["K"] * 10 / 1000, 3),
                   levels={})
        levels = [(r["level"], r["Fi_N"], s["Fi_N"]) for r, s in zip(tilt["rows"], stud["rows"])]
        levels.append(("snug, after creep", tilt["rows"][0]["Fi_after_creep_N"], stud["rows"][0]["Fi_after_creep_N"]))
        for name, Fi_t, Fi_s in levels:
            T_tilt = Fi_t * hold_tilt / 1000
            T_pan = Fi_s * stud["pan_hold_Nmm_per_N"] / 1000
            lvl = dict(Fi_tilt_N=Fi_t, Fi_stud_N=Fi_s, T_hold_tilt_Nm=round(T_tilt, 3), T_hold_pan_Nm=round(T_pan, 3))
            drift = {}
            for t in (0, 45, 90):
                mv, _ = mm.run(kind, head_m, yoke_m, T_pan, T_tilt, t, T_end=1.0)
                drift[t] = round(mv["tilt_deg"] + mv["pan_deg"], 4)
            lvl["gravity_drift_deg_1s"] = drift
            bumps = {}
            for pname, vec in pushes.items():
                lo, hi = 0.0, 200.0
                for _ in range(10):
                    mid = (lo + hi) / 2
                    mv, _ = mm.run(kind, head_m, yoke_m, T_pan, T_tilt, 45, push=vec, F=mid)
                    if max(mv.values()) > 0.5:
                        hi = mid
                    else:
                        lo = mid
                mv, pk = mm.run(kind, head_m, yoke_m, T_pan, T_tilt, 45, push=vec, F=lo)
                half = spm.head_half(kind)
                P_stud = max(0.0, pk["stud_axial"]) + pk["stud_moment"] / (sm.PAD["d"] / 2000)
                P_screw = pk["tilt_axial"] + pk["tilt_moment"] / (2 * half / 1000)
                Cs, Ct = stud["C"], tilt["C"]
                bumps[pname] = dict(
                    threshold_peak_force_N=round(lo, 1),
                    stud_P_N=round(P_stud, 1), stud_separation_margin=round(Fi_s / ((1 - Cs) * P_stud), 1)
                    if P_stud > 0 else None, stud_strip_margin=round(stud["F_strip_N"] / (Fi_s + Cs * P_stud), 1),
                    screw_P_N=round(P_screw, 1), screw_load_N=round(Fi_t + Ct * P_screw, 1),
                    screw_z_break_margin=round(tilt["F_screw_z_break_N"] / (Fi_t + Ct * P_screw), 1))
            lvl["bumps_at_45deg"] = bumps
            res["levels"][name] = lvl
            print(kind, name, json.dumps(lvl)[:500], flush=True)
        out[kind] = res
    (HERE / "mujoco_printed.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
