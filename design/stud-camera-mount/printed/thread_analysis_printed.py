"""Printed threads of the all-printed stud mount, checked with Shigley's Ch. 8 relations, as in
../analysis/thread_analysis.py (same helpers, same hand torques), with PLA in place of the steel and brass.

    python printed/thread_analysis_printed.py     # prints a summary, writes printed/thread_analysis_printed.json

Joints
  stud   steel M6 stud (6g) -> printed PLA thumb nut, M6 x 1 internal thread (0.20 mm radial allowance), whose top
         face clamps the PLA yoke pad against the ceiling (no washer)
  tilt   printed PLA thumb screw, M10 x 1.25 (0.15 mm allowance), knob face on the PLA yoke arm, through the cover's
         ear, into a printed M10 x 1.25 thread in the PLA boss (0.15 mm allowance), 10 mm engaged; one each side

What changes with printed threads
  * friction: PLA on steel and PLA on PLA threads, f ~ 0.3 instead of 0.15, so a given hand torque gives about half
    the preload (torque coefficient K ~ 0.4 to 0.5 instead of 0.2)
  * strength: the threads strip in the PLA, and the tilt screw (printed upright) carries its tension across its
    layers, which is the weak direction of a print
  * the thread engagement is shallower because of the allowances
Nothing here was measured: friction, interlayer strengths and creep are assumptions in ASSUME.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "analysis"))
import stud_mount as sm  # noqa: E402
import stud_mount_printed as spm  # noqa: E402
import thread_analysis as ta  # noqa: E402

ASSUME = dict(
    f_thread_pla_steel=0.30,   # PLA nut on a steel stud, dry (reported 0.25-0.4)
    f_thread_pla_pla=0.30,     # PLA on PLA threads, dry
    mu_pla_pla=0.30,           # knob face on the pad / arm, arm on the ear
    mu_pla_steel=0.30,         # pad on the stainless ceiling
    E_pla=3500.0,              # MPa (compression, near solid: 6 walls / 100 % infill on the threaded parts)
    E_creep_ratio=0.6,         # 1000 h creep modulus / E (as in thread_analysis.py)
    tau_interlayer=15.0,       # MPa: shear strength across layer bonds (bulk PLA ~35-40 MPa in-plane)
    sigma_z=20.0,              # MPa: tension across layers, printed upright (in-plane ~50-60 MPa)
    Kt_root=2.2,               # stress concentration at the first engaged thread root (brittle in z: applied)
    Sp_A2_70=450.0,
)
HAND = ta.HAND                 # same assumed glove torques: stud 0.3 / 0.8 / 1.5, tilt 0.15 / 0.4 / 0.8 N.m

M6 = ta.THREADS["M6"]
M10F = dict(d=10.0, p=1.25, d2=9.188, d3=8.466, D1=8.647, At=61.2)   # M10 x 1.25 (ISO 724)


def strip_area(d_ext_major, E_int, D_int_minor, E_ext, p, Le):
    """Shigley / FED-STD-H28 stripping shear areas: (internal thread at the external major diameter, external
    thread at the internal minor diameter)."""
    A_int = math.pi * Le * d_ext_major * (0.5 + 0.57735 * (d_ext_major - E_int) / p)
    A_ext = math.pi * Le * D_int_minor * (0.5 + 0.57735 * (E_ext - D_int_minor) / p)
    return A_int, A_ext


def stud_joint(Le=None):
    A = ASSUME
    t = spm.STUD_THREAD
    c = t["allowance"]
    Le = Le if Le is not None else spm.KNOB["h"] - t["entry_chamfer"]       # stud through the whole nut
    # collar: the nut's top face on the pad, an annulus from the countersink to the pad's 24 mm bar / 46 mm disc
    # (the knob is 34 mm; flutes take ~15 % of the rim)
    ro, ri = 0.5 * 31.0, 0.5 * (t["d"] + 2 * c + 2 * t["entry_chamfer"])
    dc = 2 * ta.r_eff(ro, ri)
    tr, tl, tc = ta.torque_terms(M6, A["f_thread_pla_steel"], A["mu_pla_pla"], dc)
    K = (tr + tc) / M6["d"]
    # stripping: PLA internal thread (pitch diameter grown by 2c) against the stud's minimum major diameter
    E_int = M6["d2"] + 2 * c
    D1_int = M6["D1"] + 2 * c
    A_int, A_ext = strip_area(M6["d_min6g"], E_int, D1_int, M6["d2_min6g"], M6["p"], Le)
    F_strip = A_int * A["tau_interlayer"]
    # stiffness: steel stud through the pad's 8 mm; members: PLA pad (two frustums from the nut face)
    grip = sm.PAD["t"]
    kb = M6["At"] * 200000.0 / grip
    km = ta.frustum_k(A["E_pla"], M6["d"], 2 * ri + 2.0, grip)
    C = kb / (kb + km)
    relax = (1 / kb + 1 / km) / (1 / kb + 1 / (km * A["E_creep_ratio"]))
    T_pan_per_N = A["mu_pla_steel"] * ta.r_eff(sm.PAD["d"] / 2, sm.STUD["weld_d"] / 2)
    knob_drag = A["mu_pla_pla"] * dc / 2
    rows = []
    for name, T in HAND["stud"].items():
        Fi = T * 1000 / (K * M6["d"])
        rows.append(dict(level=name, T_Nm=T, Fi_N=round(Fi), n_strip_PLA_nut=round(F_strip / Fi, 1),
                         stud_stress_MPa=round(Fi / M6["At"], 1),
                         nut_face_on_pad_MPa=round(Fi / (math.pi * (ro ** 2 - ri ** 2) * 0.85), 2),
                         T_pan_hold_Nm=round(Fi * T_pan_per_N / 1000, 2), Fi_after_creep_N=round(Fi * relax)))
    # shortest engagement that keeps a safety factor of 3 on stripping at "hard"
    Fi_hard = HAND["stud"]["hard"] * 1000 / (K * M6["d"])
    Le_min = 3 * Fi_hard / (A["tau_interlayer"] * A_int / Le)
    return dict(thread="M6x1, PLA nut on the steel stud", allowance_mm=c, engaged_mm=round(Le, 1), K=round(K, 3),
                thread_raise_Nmm_per_N=round(tr, 2), thread_loosen_Nmm_per_N=round(tl, 2),
                collar_Nmm_per_N=round(tc, 2), strip_area_mm2=round(A_int, 1), F_strip_N=round(F_strip),
                C=round(C, 3), preload_left_after_creep=round(relax, 2),
                pan_hold_Nmm_per_N=round(T_pan_per_N, 2), knob_face_drag_Nmm_per_N=round(knob_drag, 2),
                min_engagement_SF3_hard_mm=round(Le_min, 1),
                min_stud_proud_mm=round(sm.PAD["t"] + t["entry_chamfer"] + Le_min, 1), rows=rows)


def tilt_joint(kind):
    A = ASSUME
    t = spm.TILT_THREAD
    ce, ci = t["ext_allowance"], t["int_allowance"]
    Le = spm.TSCREW["engage"] - t["entry_chamfer"]
    # collar: knob face (24 mm, 8 flutes) on the arm's 22 mm end disc, around its clearance hole
    ro, ri = 0.5 * min(spm.TSCREW["knob_d"] - 2.0, 22.0), spm.ARM_HOLE / 2
    dc = 2 * ta.r_eff(ro, ri)
    th = dict(M10F)
    tr, tl, tc = ta.torque_terms(th, A["f_thread_pla_pla"], A["mu_pla_pla"], dc)
    K = (tr + tc) / M10F["d"]
    d_maj_ext = M10F["d"] - 2 * ce
    d_min_ext = M10F["d3"] - 2 * ce
    E_ext = M10F["d2"] - 2 * ce
    E_int = M10F["d2"] + 2 * ci
    D1_int = M10F["D1"] + 2 * ci
    A_int, A_ext = strip_area(d_maj_ext, E_int, D1_int, E_ext, M10F["p"], Le)
    F_strip_boss = A_int * A["tau_interlayer"]
    F_strip_screw = A_ext * A["tau_interlayer"]
    A_root = math.pi / 4 * d_min_ext ** 2
    # stiffness: PLA screw over the grip (arm + ear + gap closed); members: arm and ear, PLA
    grip = spm.ARM_T + spm.ears(kind)
    kb = A_root * A["E_pla"] / grip
    km = ta.series(ta.frustum_k(A["E_pla"], M10F["d"], 2 * ro * 0.8, grip / 2),
                   ta.frustum_k(A["E_pla"], M10F["d"], 2 * ro * 0.8, grip / 2))
    C = kb / (kb + km)
    relax = (1 / kb + 1 / km) / (1 / (kb * A["E_creep_ratio"]) + 1 / (km * A["E_creep_ratio"]))
    # holding torque about the tilt axis per newton of preload per side (two sides), as in thread_analysis.py:
    # (a) the knobs turn with the head: the arm slips on both faces; (b) the knobs stick, the screws turn in the bosses
    half_face = 0.5 * min(2 * (spm.ZP if kind == "zero" else spm.HP)["ear_r"], 22.0)
    r_ear = ta.r_eff(half_face, spm.ARM_HOLE / 2)
    r_knob = ta.r_eff(ro, ri)
    hold_a = 2 * A["mu_pla_pla"] * (r_ear + r_knob)
    hold_b = 2 * A["mu_pla_pla"] * r_ear + tl + tr
    # arm bending as the 0.5 mm gap closes: cantilever from the yoke's bar, 5 mm thick, ~22 mm wide
    L = spm.tilt_depth(kind) - sm.PAD["t"]
    I = 22.0 * spm.ARM_T ** 3 / 12
    F_arm = 3 * A["E_pla"] * I * spm.ARM_GAP / L ** 3
    s_arm = F_arm * L * (spm.ARM_T / 2) / I
    rows = []
    for name, T in HAND["tilt"].items():
        Fi = T * 1000 / (K * M10F["d"])
        T_th = Fi * tr
        sig = Fi / A_root
        tau = 16 * T_th / (math.pi * d_min_ext ** 3)
        vm = math.hypot(sig, math.sqrt(3) * tau)
        rows.append(dict(level=name, T_Nm=T, Fi_N=round(Fi), screw_vm_MPa=round(vm, 1),
                         n_screw_z_tension=round(A["sigma_z"] / (A["Kt_root"] * vm), 1),
                         n_strip_boss=round(F_strip_boss / Fi, 1), n_strip_screw=round(F_strip_screw / Fi, 1),
                         knob_on_arm_MPa=round(Fi / (math.pi * (ro ** 2 - ri ** 2)), 2),
                         T_tilt_hold_Nm=round(Fi * min(hold_a, hold_b) / 1000, 2),
                         Fi_after_creep_N=round(Fi * relax)))
    return dict(kind=kind, thread="M10x1.25, PLA screw in a PLA boss", allowances_mm=(ce, ci), engaged_mm=Le,
                K=round(K, 3), thread_raise_Nmm_per_N=round(tr, 2), thread_loosen_Nmm_per_N=round(tl, 2),
                collar_Nmm_per_N=round(tc, 2), strip_area_boss_mm2=round(A_int, 1),
                strip_area_screw_mm2=round(A_ext, 1), F_strip_boss_N=round(F_strip_boss),
                F_strip_screw_N=round(F_strip_screw), screw_root_area_mm2=round(A_root, 1),
                F_screw_z_break_N=round(A["sigma_z"] / A["Kt_root"] * A_root), C=round(C, 3),
                preload_left_after_creep=round(relax, 2), hold_knobs_turn_Nmm_per_N=round(hold_a, 2),
                hold_bolts_turn_Nmm_per_N=round(hold_b, 2), knob_face_drag_Nmm_per_N=round(
                    A["mu_pla_pla"] * r_knob, 2), arm_gap_closing_force_N=round(F_arm, 1),
                arm_root_bending_MPa=round(s_arm, 1), rows=rows)


def main():
    res = dict(assumptions=ASSUME, hand_torque_Nm=HAND, stud=stud_joint(),
               tilt={k: tilt_joint(k) for k in ("zero", "hq")})
    (HERE / "thread_analysis_printed.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "assumptions"}, indent=1))


if __name__ == "__main__":
    main()
