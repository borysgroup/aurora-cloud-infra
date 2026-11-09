"""Holding checks for the kit-screw stud mount, with the all-printed mount's models and this mount's geometry and
masses.

    python kit/holding_kit.py     # prints a summary, writes kit/holding_kit.json

  stud    unchanged: the all-printed thumb nut on the same pad (../printed/thread_analysis_printed.py)
  tilt    the all-printed M10 x 1.25 joint without a cover's ear in the grip. The arm bears straight on the boss face,
          which is as wide as the ear was (18 / 20 mm), so the holding torque per newton of preload is unchanged; the
          shorter grip only moves the joint constant.
  screws  M2 / M2.5 pan-head screws forming their thread in printed pilot holes: preload at a light screwdriver
          torque (Shigley Eq. 8-27 terms, as ../analysis/thread_analysis.py), stripping of the formed PLA thread
          (FED-STD-H28 area at the screw's major diameter, interlayer shear), and the HQ Camera's four screws under
          the zoom lens's moment.
  mujoco  gravity drift and bump thresholds (../analysis/mujoco_mount.py's friction-hinge model) with these heads.
Nothing here was measured: friction, interlayer strength and creep are the all-printed analysis's assumptions.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
import types

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "printed"))
sys.path.insert(0, str(HERE.parent / "analysis"))
import mujoco_mount as mm  # noqa: E402
import stud_mount as sm  # noqa: E402
import stud_mount_kit as sk  # noqa: E402
import stud_mount_printed as spm  # noqa: E402
import thread_analysis as ta  # noqa: E402
import thread_analysis_printed as tpa  # noqa: E402

# the all-printed tilt-joint model reads the grip and the arm length from stud_mount_printed: give it this mount's
spm.ears = lambda kind: 0.0
spm.tilt_depth = sk.tilt_depth

STEEL_G = {"M2.5": 0.35, "M2": 0.20}          # g per pan-head x 6 screw
DRIVE = {"M2.5": 0.10, "M2": 0.05}            # N.m, snug with a small screwdriver (as thread_analysis.small_screws)
ENGAGED = {"M2.5": [("Pi Zero 2 W (1.0 mm board)", 6.0 - 1.0), ("Pi 5 (1.6 mm board)", 6.0 - 1.6),
                    ("HQ Camera (1.4 mm board)", 6.0 - 1.4), ("covers, carrier, nose (1.5-2.5 mm under the head)",
                                                            6.0 - 2.5)],
           "M2": [("Camera Module 3 / Wide (1.12 mm board)", 6.0 - 1.12)]}


def kit_screws():
    A = tpa.ASSUME
    out = []
    for size, rows in ENGAGED.items():
        th = ta.THREADS[size]
        s = sk.SCREW[size]
        tr, tl, tc = ta.torque_terms(th, A["f_thread_pla_steel"], A["mu_pla_steel"], (s["head_d"] + s["clear"]) / 2)
        K = (tr + tc) / th["d"]
        Fi = DRIVE[size] * 1000 / (K * th["d"])
        for use, Le in rows:
            A_int, _ = tpa.strip_area(th["d"], th["d2"], s["pilot"], th["d2"], th["p"], Le)
            F_strip = A_int * A["tau_interlayer"]
            out.append(dict(screw=f"{size} x 6", use=use, pilot_mm=s["pilot"], engaged_mm=round(Le, 2), K=round(K, 3),
                            T_snug_Nm=DRIVE[size], Fi_snug_N=round(Fi), strip_area_mm2=round(A_int, 1),
                            F_strip_N=round(F_strip), strip_margin_at_snug=round(F_strip / Fi, 1),
                            T_strip_Nm=round(F_strip * K * th["d"] / 1000, 2)))
    return out


def hq_camera_screws(Fi, F_strip, g_shock=10.0):
    """The HQ Camera's four M2.5 screws hold the board, its mount and the zoom lens: tension in the two upper screws
    at tilt 0 (lens horizontal) from the lens's overhang, statically and under a g_shock bump."""
    m = (mm.MASSES["hq"]["zoom lens"] + mm.MASSES["hq"]["HQ mount"] + mm.MASSES["hq"]["HQ board"]) / 1000
    lens = sm.LENS_ZOOM["profile"]
    overhang = (sm.HQ_CS_SEAT + 0.5 * lens[-1][1]) / 1000   # board face to the lens's mid-length, m
    M = m * 9.81 * overhang
    P = M / (sm.HQ_PITCH / 1000) / 2
    return dict(mass_g=round(m * 1000), overhang_mm=round(overhang * 1000, 1), moment_Nm=round(M, 3),
                tension_per_upper_screw_N=round(P, 2), tension_at_shock_N=round(P * g_shock, 1), shock_g=g_shock,
                separation_margin_at_shock=round(Fi / (P * g_shock), 1),
                strip_margin_at_shock=round(F_strip / (Fi + P * g_shock), 1))


# ------------------------------------------------------------------------------------------ MuJoCo
MASSES = {"zero": {"Pi Zero": 11.0, "CM3": 4.0, "ribbon": 1.0, "USB power lead": 5.0,
                   "M2.5 screws": 8 * STEEL_G["M2.5"], "M2 screws": 4 * STEEL_G["M2"]},
          "hq": dict([(k, v) for k, v in mm.MASSES["hq"].items() if k != "standoffs"]
                     + [("M2.5 screws", 15 * STEEL_G["M2.5"]), ("M2 screws", 4 * STEEL_G["M2"])])}


def lens_point(kind):
    if kind == "zero":
        h = sk.ZK
        return (h["lens_x"], h["plate_t"] + h["cm3_gap"] - sm.CM3["lens_h"] + 0.9 - h["axis_y"], h["lens_z"])
    return sm.lens_point("hq")


mm.sm = types.SimpleNamespace(tilt_depth=sk.tilt_depth, lens_point=lens_point, PAD=sm.PAD,
                              head_spec=lambda kind: (sk.head_half(kind), None))
mm.PRINTED = {"case", "back cover", "tub", "carrier", "Wide nose"}


def mount_bodies(kind):
    head = sk.head_zero_parts() if kind == "zero" else sk.head_hq_parts()
    items = mm.body_mass(head, MASSES[kind])
    half = sk.head_half(kind)
    v, _, _ = mm.props(sk.tilt_screw_local().val())
    for sx in (-1, 1):
        items.append((v * 1.24e-3, np.array([sx * (half + 10.0), 0, 0]), np.eye(3) * 60.0))
    head_m = mm.combine(items)
    pan = sk.parts(kind)["pan"]
    yitems = []
    for name, fill in (("yoke", 0.85), ("stud thumb nut", 1.0)):
        v, c, I = mm.props(pan[name][0].val())
        yitems.append((v * 1.24e-3 * fill, c, I * 1.24e-3 * fill))
    return head_m, mm.combine(yitems)


def mujoco_checks(th):
    out = {}
    pushes = {"tilt (push across the view, in the tilt plane)": (0, 0, 1),
              "pan (push sideways, along the tilt axis)": (1, 0, 0)}
    for kind in ("zero", "hq"):
        head_m, yoke_m = mount_bodies(kind)
        stud, tilt = th["stud"], th["tilt"][kind]
        hold_tilt = min(tilt["hold_knobs_turn_Nmm_per_N"], tilt["hold_bolts_turn_Nmm_per_N"])
        g_tilt = mm.gravity_torques(head_m, kind)
        res = dict(head_mass_g=round(head_m[0] * 1000, 1), head_com_mm=[round(x * 1000, 1) for x in head_m[1]],
                   yoke_and_nut_mass_g=round(yoke_m[0] * 1000, 1), tilt_axis_depth_mm=sk.tilt_depth(kind),
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
                half = sk.head_half(kind)
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
            print(kind, name, json.dumps(lvl)[:400], flush=True)
        out[kind] = res
    return out


def main():
    th = dict(stud=tpa.stud_joint(), tilt={k: tpa.tilt_joint(k) for k in ("zero", "hq")})
    screws = kit_screws()
    hq = next(r for r in screws if r["use"].startswith("HQ"))
    res = dict(assumptions=tpa.ASSUME, hand_torque_Nm=tpa.HAND, screw_drive_torque_Nm=DRIVE, bom=sk.bom(),
               thread=th, kit_screws=screws, hq_camera_screws=hq_camera_screws(hq["Fi_snug_N"], hq["F_strip_N"]),
               mujoco=mujoco_checks(th))
    (HERE / "holding_kit.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(dict(kit_screws=screws, hq_camera_screws=res["hq_camera_screws"],
                          tilt={k: {q: v[q] for q in ("C", "hold_knobs_turn_Nmm_per_N", "hold_bolts_turn_Nmm_per_N")}
                                for k, v in th["tilt"].items()}), indent=1))


if __name__ == "__main__":
    main()
