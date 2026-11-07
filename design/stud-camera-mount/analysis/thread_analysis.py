"""Threaded joints of the stud camera mount, checked with Shigley's Ch. 8 relations (Shigley's Mechanical Engineering
Design, 10th/11th ed.): torque-preload (Eq. 8-26/8-27), joint stiffness and joint constant (Eqs. 8-17, 8-20/8-22,
8-24), thread stripping areas (as in Machinery's Handbook / FED-STD-H28 for 6g/6H fits), plus bearing, insert
pull-out and holding torque for the printed (PLA) members.

    python analysis/thread_analysis.py          # prints the tables, writes analysis/thread_analysis.json

Joints
  stud   M6 welded ceiling stud -> M6 nut (in the thumb nut) -> ISO 7093 washer -> PLA yoke pad -> ceiling
  tilt   M4 x 16 hex bolt (in the tilt knob) -> ISO 7089 washer -> PLA knob -> PLA yoke arm -> PLA boss with an
         M4 x 8.1 brass heat-set insert (two per mount, one each side)
  small  M2.5 screws into standoffs (Pi Zero, Pi 5, HQ Camera) and M2 screws + nuts (Camera Module 3), through PLA

All inputs that are assumptions (friction, PLA properties, hand torque) are in ASSUME; nothing here was measured.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import stud_mount as sm  # noqa: E402

# ISO 724 basic profile + ISO 965 6g/6H limits (mm)
THREADS = {
    "M6": dict(d=6.0, p=1.0, d2=5.350, d3=4.773, D1=4.917, At=20.1, d_min6g=5.794, D2_max6H=5.500, d2_min6g=5.212,
               D1_max6H=5.153),
    "M4": dict(d=4.0, p=0.7, d2=3.545, d3=3.141, D1=3.242, At=8.78, d_min6g=3.838, D2_max6H=3.663, d2_min6g=3.433,
               D1_max6H=3.422),
    "M2.5": dict(d=2.5, p=0.45, d2=2.208, d3=1.948, D1=2.013, At=3.39),
    "M2": dict(d=2.0, p=0.4, d2=1.740, d3=1.509, D1=1.567, At=2.07),
}

ASSUME = dict(
    f_thread=0.15,          # steel/steel and steel/brass threads, dry, plated (Shigley Table 8-15 -> K ~ 0.2)
    f_collar_steel=0.15,    # nut or bolt head on a steel washer
    mu_pla_steel=0.30,      # PLA pad on the stainless ceiling (static, dry); low end of reported 0.3-0.5
    mu_pla_pla=0.30,        # PLA knob / arm / boss faces
    E_pla=3500.0,           # MPa, printed PLA, compression (bulk ~3.5 GPa; 6 walls + 40 % gyroid is lower)
    E_steel=200000.0,
    tau_pla=15.0,           # MPa, effective shear strength of printed PLA around a heat-set insert's knurl
                            # (bulk PLA ~35-40 MPa; layer bonds and the re-melted zone knock it down)
    sigma_bearing_pla=40.0, # MPa, short-term compressive (bearing) limit for printed PLA
    sigma_creep_pla=15.0,   # MPa, sustained bearing stress above which PLA creeps noticeably at room temperature
    E_creep_ratio=0.6,      # long-term (1000 h) creep modulus / E for PLA at ~10 MPa, 20-30 C (assumed)
    tau_brass=200.0,        # MPa, CuZn39Pb3 insert (Rm ~360-430 MPa, shear ~0.55 Rm)
    tau_steel_8_8=480.0,    # MPa, 0.6 x 800 MPa
    Sp_A2_70=450.0,         # MPa, proof strength of A2-70 stainless (stud assumed 304 / A2)
    Sp_8_8=580.0,           # MPa, class 8.8 proof strength (M4 bolt)
)

# hand torque on the printed knobs through glovebox gloves (assumed; not measured)
HAND = {"stud": dict(snug=0.3, firm=0.8, hard=1.5),      # 34 mm thumb nut
        "tilt": dict(snug=0.15, firm=0.4, hard=0.8)}     # 24 mm tilt knob


def ring_area(do, di):
    return math.pi / 4 * (do * do - di * di)


def r_eff(ro, ri):
    """Friction radius of a uniformly loaded annulus."""
    return 2.0 / 3.0 * (ro ** 3 - ri ** 3) / (ro ** 2 - ri ** 2)


def torque_terms(th, f, fc, dc):
    """Shigley Eq. 8-26 per newton of preload (N.mm/N): thread (raising), thread (lowering), collar."""
    dm, l, sec = th["d2"], th["p"], 1 / math.cos(math.radians(30))
    raise_ = dm / 2 * (l + math.pi * f * dm * sec) / (math.pi * dm - f * l * sec)
    lower = dm / 2 * (math.pi * f * dm * sec - l) / (math.pi * dm + f * l * sec)
    collar = fc * dc / 2
    return raise_, lower, collar


def frustum_k(E, d, D, t):
    """Shigley Eq. 8-20: stiffness of one conical frustum (30 deg half-angle) of thickness t, bearing diameter D."""
    num = 0.5774 * math.pi * E * d
    den = math.log((1.155 * t + D - d) * (D + d) / ((1.155 * t + D + d) * (D - d)))
    return num / den


def series(*k):
    return 1.0 / sum(1.0 / x for x in k)


def strip_area_internal(th, Le):
    """Shear area of an internal thread (nut, insert) at the external thread's minimum major diameter."""
    return math.pi * Le * th["d_min6g"] * (0.5 + 0.57735 * (th["d_min6g"] - th["D2_max6H"]) / th["p"])


def strip_area_external(th, Le):
    """Shear area of an external thread (bolt, stud) at the internal thread's maximum minor diameter."""
    return math.pi * Le * th["D1_max6H"] * (0.5 + 0.57735 * (th["d2_min6g"] - th["D1_max6H"]) / th["p"])


def stud_joint():
    A, th = ASSUME, THREADS["M6"]
    pad_t, w_t, w_d = sm.PAD["t"], sm.STUD["washer_t"], sm.STUD["washer_d"]
    dw_nut = 8.9                                                     # ISO 4032 M6 bearing face, min
    tr, tl, tc = torque_terms(th, A["f_thread"], A["f_collar_steel"], (dw_nut + 6.4) / 2)
    K = (tr + tc) / th["d"]
    # stiffness: stud (welded, threaded through the grip) vs washer + PLA pad, frustums from the nut's face
    grip = pad_t + w_t
    kb = th["At"] * A["E_steel"] / grip
    k_w = frustum_k(A["E_steel"], th["d"], dw_nut, w_t)
    k_pad = frustum_k(A["E_pla"], th["d"], dw_nut + 2 * w_t * math.tan(math.radians(30)), pad_t)
    km = series(k_w, k_pad)
    C = kb / (kb + km)
    km_creep = series(k_w, k_pad * A["E_creep_ratio"])
    relax = (1 / kb + 1 / km) / (1 / kb + 1 / km_creep)               # F(t)/F0 when the PLA creeps
    # bearing: washer on the pad, pad on the ceiling (outside the weld-bead recess)
    A_washer = ring_area(w_d, sm.STUD["clear"])
    A_ceiling = ring_area(sm.PAD["d"], sm.STUD["weld_d"])
    # holding torque about the stud (pan): pad on the ceiling only (the washer face may turn with the nut)
    T_pan_per_N = A["mu_pla_steel"] * r_eff(sm.PAD["d"] / 2, sm.STUD["weld_d"] / 2)
    # does a forced pan drag the nut? friction torque on the washer face vs the nut's break-away torques
    T_washer_face = A["mu_pla_steel"] * r_eff(w_d / 2, sm.STUD["clear"] / 2)
    # thread engagement: nut fully on the stud; stripping areas
    Le = sm.STUD["nut_t"]
    As_nut, As_stud = strip_area_internal(th, Le), strip_area_external(th, Le)
    min_stud = pad_t + w_t + 3 * th["p"] + 1.0                        # 3 full threads + chamfer
    rows = []
    for name, T in HAND["stud"].items():
        Fi = T * 1000 / (K * th["d"])
        T_th = Fi * tr
        sig = Fi / th["At"]
        tau = 16 * T_th / (math.pi * th["d3"] ** 3)
        vm = math.hypot(sig, math.sqrt(3) * tau)
        rows.append(dict(level=name, T_Nm=T, Fi_N=round(Fi), stud_vm_MPa=round(vm, 1),
                         n_stud_proof=round(A["Sp_A2_70"] / vm, 1),
                         n_strip_nut=round(As_nut * A["tau_steel_8_8"] / Fi, 1),
                         n_strip_stud=round(As_stud * 0.6 * 700 / Fi, 1),
                         washer_on_pad_MPa=round(Fi / A_washer, 1), pad_on_ceiling_MPa=round(Fi / A_ceiling, 2),
                         T_pan_hold_Nm=round(Fi * T_pan_per_N / 1000, 2),
                         Fi_after_creep_N=round(Fi * relax)))
    return dict(thread="M6x1", K=round(K, 3), kb_kN_mm=round(kb / 1000, 1), km_kN_mm=round(km / 1000, 1),
                C=round(C, 3), preload_left_after_creep=round(relax, 2), grip_mm=grip,
                min_stud_length_mm=round(min_stud, 1),
                pan_hold_Nmm_per_N=round(T_pan_per_N, 2),
                nut_breakaway_loosen_Nmm_per_N=round(tl + tc, 2), nut_tighten_Nmm_per_N=round(tr + tc, 2),
                washer_face_drag_Nmm_per_N=round(T_washer_face, 2),
                strip_area_nut_mm2=round(As_nut, 1), strip_area_stud_mm2=round(As_stud, 1), rows=rows)


def tilt_joint(kind):
    A, th, t = ASSUME, THREADS["M4"], sm.TILT
    half, _ = sm.head_spec(kind)
    boss_d = (sm.ZERO if kind == "zero" else sm.HQ)["boss_d"]
    dw_head = 5.88                                                   # ISO 4017 M4 bearing face, min
    tr, tl, tc = torque_terms(th, A["f_thread"], A["f_collar_steel"], (dw_head + 4.3) / 2)
    K = (tr + tc) / th["d"]
    knob_under = t["knob_h"] - t["head_h"] - 0.2 - t["washer_t"] - 0.1   # PLA under the washer
    grip = t["washer_t"] + knob_under + sm.ARM_T                     # gap to the boss closed when tight
    engage = t["bolt_l"] - grip
    kb = th["At"] * A["E_steel"] / grip                              # ISO 4017: threaded to the head
    # members: washer, then PLA (knob + arm + boss down to the insert); tapped-hole grip l' = h + d/2 (Shigley)
    lp = knob_under + sm.ARM_T + th["d"] / 2
    k_w = frustum_k(A["E_steel"], th["d"], dw_head, t["washer_t"])
    D_pla = dw_head + 2 * t["washer_t"] * math.tan(math.radians(30))
    k_pla = series(frustum_k(A["E_pla"], th["d"], D_pla, lp / 2),
                   frustum_k(A["E_pla"], th["d"], D_pla, lp / 2))     # two frustums meeting at mid-grip
    km = series(k_w, k_pla)
    C = kb / (kb + km)
    relax = (1 / kb + 1 / km) / (1 / kb + 1 / series(k_w, k_pla * A["E_creep_ratio"]))
    A_washer = ring_area(t["washer_d"], t["clear"])
    A_head = ring_area(dw_head, t["clear"])
    A_knob_arm = ring_area(20.0, t["clear"])                         # knob face on the arm's 20 mm end
    A_arm_boss = ring_area(min(20.0, boss_d), t["insert_d"])
    A_pull = math.pi * t["insert_d"] * t["insert_l"]
    F_pull = A["tau_pla"] * A_pull
    T_torqueout = A["tau_pla"] * A_pull * t["insert_d"] / 2 / 1000
    As_ins = strip_area_internal(th, engage)
    As_bolt = strip_area_external(th, engage)
    # holding torque of the head about the tilt axis, two sides, per newton of preload per side:
    #   (a) knobs turn with the head: both faces of each arm slip
    #   (b) knobs stick to the arms and the bolts turn in the inserts (one loosens, one tightens)
    r_boss = r_eff(min(10.0, boss_d / 2), t["clear"] / 2)
    r_knob = r_eff(10.0, t["clear"] / 2)
    hold_a = 2 * A["mu_pla_pla"] * (r_boss + r_knob)
    hold_b = 2 * A["mu_pla_pla"] * r_boss + tl + tr
    rows = []
    for name, T in HAND["tilt"].items():
        Fi = T * 1000 / (K * th["d"])
        T_th = Fi * tr
        sig = Fi / th["At"]
        tau = 16 * T_th / (math.pi * th["d3"] ** 3)
        vm = math.hypot(sig, math.sqrt(3) * tau)
        rows.append(dict(level=name, T_Nm=T, Fi_N=round(Fi), bolt_vm_MPa=round(vm, 1),
                         n_bolt_proof=round(A["Sp_8_8"] / vm, 1),
                         n_strip_insert=round(As_ins * A["tau_brass"] / Fi, 1),
                         n_strip_bolt=round(As_bolt * A["tau_steel_8_8"] / Fi, 1),
                         n_insert_pullout=round(F_pull / Fi, 1),
                         n_insert_torqueout=round(T_torqueout / (T_th / 1000), 1),
                         washer_on_knob_MPa=round(Fi / A_washer, 1),
                         head_on_PLA_no_washer_MPa=round(Fi / A_head, 1),
                         knob_on_arm_MPa=round(Fi / A_knob_arm, 1), arm_on_boss_MPa=round(Fi / A_arm_boss, 1),
                         T_tilt_hold_Nm=round(Fi * min(hold_a, hold_b) / 1000, 2),
                         Fi_after_creep_N=round(Fi * relax)))
    return dict(kind=kind, thread="M4x0.7", K=round(K, 3), grip_mm=round(grip, 1), engagement_mm=round(engage, 1),
                insert_hole_depth_mm=t["hole"], kb_kN_mm=round(kb / 1000, 1), km_kN_mm=round(km / 1000, 1),
                C=round(C, 3), preload_left_after_creep=round(relax, 2),
                insert_pullout_N=round(F_pull), insert_torqueout_Nm=round(T_torqueout, 2),
                hold_knobs_turn_Nmm_per_N=round(hold_a, 2), hold_bolts_turn_Nmm_per_N=round(hold_b, 2),
                bolt_loosen_Nmm_per_N=round(tl, 3), knob_face_drag_Nmm_per_N=round(A["mu_pla_pla"] * r_knob, 2),
                strip_area_insert_mm2=round(As_ins, 1), strip_area_bolt_mm2=round(As_bolt, 1), rows=rows)


def small_screws():
    A = ASSUME
    out = []
    for th_name, T, dk, clear, what in (("M2.5", 0.10, 5.0, 2.7, "Pi / HQ standoff screws, pan head"),
                                        ("M2", 0.05, 3.8, 2.2, "Camera Module 3 screws, into M2 nuts")):
        th = THREADS[th_name]
        tr, tl, tc = torque_terms(th, A["f_thread"], 0.25, (dk + clear) / 2)
        K = (tr + tc) / th["d"]
        Fi = T * 1000 / (K * th["d"])
        out.append(dict(thread=th_name, use=what, T_Nm=T, K=round(K, 3), Fi_N=round(Fi),
                        head_on_PLA_MPa=round(Fi / ring_area(dk, clear), 1), screw_MPa=round(Fi / th["At"], 1)))
    return out


def nut_pocket_press_fit():
    """Lame thick-wall interference (Shigley Eq. 3-57) for the M6 nut in the thumb nut's hex pocket, treated as a
    round bore at the flats: a steel plug in a PLA hub, outer radius to the flute roots."""
    A = ASSUME
    R = sm.STUD["nut_af"] / 2
    ro = sm.KNOB["d"] / 2 - 3.0 + 1.2                     # flute root
    nu_o, nu_i, Eo, Ei = 0.36, 0.30, A["E_pla"], A["E_steel"]
    g = (ro ** 2 + R ** 2) / (ro ** 2 - R ** 2)
    rows = []
    for delta_d in (0.0, 0.05, 0.10, 0.15, 0.20):          # diametral interference, mm
        dr = delta_d / 2
        p = dr / (R * ((g + nu_o) / Eo + (1 - nu_i) / Ei))
        rows.append(dict(diametral_interference_mm=delta_d, pressure_MPa=round(p, 1),
                         hoop_at_bore_MPa=round(p * g, 1), hoop_x_Kt2_at_corners_MPa=round(2 * p * g, 1)))
    return dict(nominal_clearance_mm=round(sm.KNOB["hex_af"] - sm.STUD["nut_af"], 2), rows=rows)


def main():
    res = dict(assumptions=ASSUME, hand_torque_Nm=HAND, stud=stud_joint(),
               tilt={k: tilt_joint(k) for k in ("zero", "hq")}, small_screws=small_screws(),
               nut_pocket=nut_pocket_press_fit())
    (HERE / "thread_analysis.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "assumptions"}, indent=1))


if __name__ == "__main__":
    main()
