"""Holding checks for the nylon-kit stud mount, with the all-printed mount's models and this mount's geometry and
masses.

    python kit/holding_kit.py     # prints a summary, writes kit/holding_kit.json

  stud    unchanged: the all-printed thumb nut on the same pad (../printed/thread_analysis_printed.py)
  tilt    the all-printed M10 x 1.25 joint without a cover's ear in the grip. The arm bears straight on the boss face,
          which is as wide as the ear was (18 / 20 mm), so the holding torque per newton of preload is unchanged; the
          shorter grip only moves the joint constant.
  nylon   M2 / M2.5 nylon screws into nylon nuts and standoffs: tensile and torsional strength of the screw, the most
          torque a screwdriver can put on before the shank yields (combined tension and thread torque, Shigley Eq.
          8-26 terms), half of that as the tightening limit (NBK's rule for plastic screws), the preload it gives,
          thread stripping in the nut or standoff (FED-STD-H28 areas), the nut punching through the PLA over its
          slot, and the HQ Camera's four screws under the zoom lens's moment.
  mujoco  gravity drift and bump thresholds (../analysis/mujoco_mount.py's friction-hinge model) with these heads.
Nothing here was measured. Nylon is PA66 at 23 C / 50 % RH from typical datasheet values (it is stronger dry, weaker
wet or warm); PLA and friction values are the all-printed analysis's assumptions.
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

NYLON = dict(sigma_u=60.0,      # MPa, PA66 tensile strength at 23 C / 50 % RH (about 80 dry as moulded)
             tau_u=36.0,        # MPa, shear strength, taken as 0.6 x tensile
             rho=1.14e-3,       # g/mm^3
             f_thread=0.20,     # nylon on nylon threads, dry
             f_collar=0.25,     # nylon head or nut on PLA
             relax=0.5)         # preload left after long-term stress relaxation (assumed)
DRIVE_FRACTION = 0.5            # tighten to half the torque that yields the shank (NBK: 50 % of torsional strength)
TAU_PLA_PUNCH = tpa.ASSUME["tau_interlayer"]   # MPa, PLA around a nut pulled through its slot's roof (conservative)


def _over_front_nut(L):
    """PLA between an M2 nut in a front-face pocket and the camera board above it (the screw comes from the board's
    back, L long): plate + shoulder - the pocket's depth."""
    return (L - sk.PAST - sk.HW["M2"]["nut_m"]) - sm.CM3["pcb_t"]


# joints: (size, what, engaged length in the nut or standoff mm, PLA over the nut mm or None, head/nut bearing on PLA)
JOINTS = [("M2", "CM3: M2 x 6 into nuts in the case's front face", 1.6, _over_front_nut(6), "nut"),
          ("M2.5", "Pi Zero: M2.5 x 12 from the front into F-F standoffs", 2.5, None, "head"),
          ("M2.5", "Pi Zero back cover: M2.5 x 6 into the same standoffs", 3.0, None, "head"),
          ("M2.5", "HQ Camera: M2.5 x 12 from the tub's front, nuts on the board", 2.0, None, "head"),
          ("M2.5", "Pi 5: M2.5 x 6 into nuts in the carrier posts' slots", 2.0, sk.HK["pi_roof"], "nut"),
          ("M2.5", "carrier: M2.5 x 8 into nuts in the cheeks' slots", 2.0, sk.HK["carrier_roof"], "nut"),
          ("M2.5", "Wide nose: M2.5 x 8 into nuts in the nose's slots", 2.0, sk.HK["nose_roof"], "nut"),
          ("M2", "Wide: M2 x 8 into nuts in the nose's front face", 1.6, _over_front_nut(8), "nut")]


def ring_area(D, d):
    return math.pi / 4 * (D * D - d * d)


def nylon_screw(size):
    """Strength of one nylon screw and the preload at the tightening limit."""
    th, s = ta.THREADS[size], sk.HW[size]
    N = NYLON
    tr, _, tc = ta.torque_terms(th, N["f_thread"], N["f_collar"], (s["head_d"] + s["clear"]) / 2)
    K = (tr + tc) / th["d"]
    Zp = math.pi * th["d3"] ** 3 / 16
    F_t = N["sigma_u"] * th["At"]
    T_twist = N["tau_u"] * Zp / 1000                      # pure torsion at the root, N.m
    # shank yields when sqrt(sigma^2 + 3 tau^2) = sigma_u, sigma = Fi / At, tau = Fi tr / Zp
    Fi_y = N["sigma_u"] / math.sqrt((1 / th["At"]) ** 2 + 3 * (tr / Zp) ** 2)
    T_yield = Fi_y * K * th["d"] / 1000
    T_drive = DRIVE_FRACTION * T_yield
    Fi = T_drive * 1000 / (K * th["d"])
    return dict(size=size, At_mm2=th["At"], d3_mm=th["d3"], K=round(K, 3), F_tensile_N=round(F_t),
                T_twist_off_pure_torsion_Nm=round(T_twist, 3), T_shank_yield_Nm=round(T_yield, 3),
                T_tighten_max_Nm=round(T_drive, 3), Fi_at_T_tighten_N=round(Fi, 1),
                Fi_after_relaxation_N=round(Fi * N["relax"], 1))


def joints():
    out = []
    scr = {size: nylon_screw(size) for size in sk.HW}
    for size, what, Le, roof, bearing in JOINTS:
        th, s, n = ta.THREADS[size], sk.HW[size], scr[size]
        A_int, A_ext = tpa.strip_area(th["d"], th["d2"], th["D1"], th["d2"], th["p"], Le)
        F_strip = min(A_int, A_ext) * NYLON["tau_u"]
        row = dict(size=size, joint=what, engaged_mm=round(Le, 2), F_strip_N=round(F_strip),
                   strip_margin_at_T_tighten=round(F_strip / n["Fi_at_T_tighten_N"], 1))
        if bearing == "head":
            row["head_on_PLA_MPa"] = round(n["Fi_at_T_tighten_N"] / ring_area(s["head_d"], s["clear"]), 1)
        else:
            row["nut_on_PLA_MPa"] = round(n["Fi_at_T_tighten_N"] / ring_area(s["nut_af"] * 1.05, s["clear"]), 1)
        if roof is not None:
            perim = 6 * s["nut_af"] / math.sqrt(3)
            F_punch = perim * roof * TAU_PLA_PUNCH
            row.update(PLA_over_nut_mm=round(roof, 2), F_punch_through_N=round(F_punch),
                       punch_vs_screw_tensile=round(F_punch / n["F_tensile_N"], 1))
        out.append(row)
    return scr, out


def hq_camera_screws(scr, g_shock=10.0):
    """The HQ Camera's four M2.5 screws hold the board, its mount and the zoom lens: tension in the two upper screws
    at tilt 0 (lens horizontal) from the lens's overhang, statically and under a g_shock bump."""
    m = (mm.MASSES["hq"]["zoom lens"] + mm.MASSES["hq"]["HQ mount"] + mm.MASSES["hq"]["HQ board"]) / 1000
    lens = sm.LENS_ZOOM["profile"]
    overhang = (sm.HQ_CS_SEAT + 0.5 * lens[-1][1]) / 1000   # board face to the lens's mid-length, m
    M = m * 9.81 * overhang
    P = M / (sm.HQ_PITCH / 1000) / 2
    n = scr["M2.5"]
    Fi, Fr = n["Fi_at_T_tighten_N"], n["Fi_after_relaxation_N"]
    return dict(mass_g=round(m * 1000), overhang_mm=round(overhang * 1000, 1), moment_Nm=round(M, 3),
                tension_per_upper_screw_N=round(P, 2), tension_at_shock_N=round(P * g_shock, 1), shock_g=g_shock,
                separation_margin_static_relaxed=round(Fr / P, 1),
                separation_margin_at_shock=round(Fi / (P * g_shock), 1),
                separation_margin_at_shock_relaxed=round(Fr / (P * g_shock), 1),
                tensile_margin_at_shock=round(n["F_tensile_N"] / (Fi + P * g_shock), 1))


# ------------------------------------------------------------------------------------------ MuJoCo
def masses(kind, head):
    """Mass groups for mm.body_mass, matched by substring, first match wins: the kit hardware (nylon, by volume) comes
    before the boards so "M2.5 screws, Pi 5" doesn't fall into "Pi 5"."""
    out = {}
    for name, (wp, mat) in head.items():
        if mat == "nylon":
            shape = wp.val() if len(wp.vals()) == 1 else wp.combine().val()
            out[name] = mm.props(shape)[0] * NYLON["rho"]
    if kind == "zero":
        out.update({"Pi Zero": 11.0, "CM3": 4.0, "ribbon": 1.0, "USB power lead": 5.0})
    else:
        out.update((k, v) for k, v in mm.MASSES["hq"].items() if k != "standoffs")
    return out


mm.sm = types.SimpleNamespace(tilt_depth=sk.tilt_depth, lens_point=sk.lens_point, PAD=sm.PAD,
                              head_spec=lambda kind: (sk.head_half(kind), None))
mm.PRINTED = {"case", "back cover", "tub", "carrier", "Wide nose"}


def mount_bodies(kind):
    head = sk.head_zero_parts() if kind == "zero" else sk.head_hq_parts()
    groups = masses(kind, head)
    items = mm.body_mass(head, groups)
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
    hw_g = sum(m for k, m in groups.items() if k.startswith(("M2 ", "M2.5 ")))
    return head_m, mm.combine(yitems), hw_g


def mujoco_checks(th):
    out = {}
    pushes = {"tilt (push across the view, in the tilt plane)": (0, 0, 1),
              "pan (push sideways, along the tilt axis)": (1, 0, 0)}
    for kind in ("zero", "hq"):
        head_m, yoke_m, hw_g = mount_bodies(kind)
        stud, tilt = th["stud"], th["tilt"][kind]
        hold_tilt = min(tilt["hold_knobs_turn_Nmm_per_N"], tilt["hold_bolts_turn_Nmm_per_N"])
        g_tilt = mm.gravity_torques(head_m, kind)
        res = dict(head_mass_g=round(head_m[0] * 1000, 1), nylon_hardware_on_head_g=round(hw_g, 2),
                   head_com_mm=[round(x * 1000, 1) for x in head_m[1]],
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
    scr, jt = joints()
    res = dict(assumptions=dict(nylon=NYLON, drive_fraction=DRIVE_FRACTION, tau_pla_punch_MPa=TAU_PLA_PUNCH,
                                printed=tpa.ASSUME),
               hand_torque_Nm=tpa.HAND, bom=sk.bom(), thread=th, nylon_screws=scr, joints=jt,
               hq_camera_screws=hq_camera_screws(scr), mujoco=mujoco_checks(th))
    (HERE / "holding_kit.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(dict(nylon_screws=scr, joints=jt, hq_camera_screws=res["hq_camera_screws"],
                          tilt={k: {q: v[q] for q in ("C", "hold_knobs_turn_Nmm_per_N", "hold_bolts_turn_Nmm_per_N")}
                                for k, v in th["tilt"].items()}), indent=1))


if __name__ == "__main__":
    main()
