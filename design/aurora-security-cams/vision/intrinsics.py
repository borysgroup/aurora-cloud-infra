"""Expected (published) and estimated intrinsics of the Amcrest IP5M-T1179EW-AI-V3 at 1920x1080.

Published (Amcrest spec sheet, 2025-10-30, = Dahua IPC-HDW2541T-S (S2)): 1/2.7" CMOS, 2.8 mm F1.6 M12 lens,
FOV H 111 / V 58 / D 132 deg, top main-stream mode 2960x1668 (16:9). Pixel pitch is not published.

Estimated: division-model distortion from plumb lines (plumbline.py, both cameras, principal point at the
frame centre); focal length from the registration with f free (register_chamber.py; weak, few landmarks).

    python intrinsics.py [--plumb out/plumb.json] [--reg out/registration.json]
"""
import argparse
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lensmodel import NORM, opencv_coeffs, opencv_rational  # noqa: E402

W, H = 1920, 1080
C = ((W - 1) / 2, (H - 1) / 2)
F_MM = 2.8
FOV = dict(h=111.0, v=58.0, d=132.0)
TOP_MODE = (2960, 1668)


def published():
    s = W / TOP_MODE[0]          # 1080p as the whole 2960x1668 area scaled (0.6486; 1080/1668 = 0.6475)
    out = dict(source="Amcrest IP5M-T1179EW-AI-V3 spec sheet (2025-10-30) and Dahua IPC-HDW2541T-S (S2) datasheet",
               sensor='1/2.7" progressive CMOS (part and pixel pitch not published)', lens="2.8 mm, F1.6, M12, fixed",
               fov_deg=FOV, top_main_stream=TOP_MODE,
               readout_assumption=("1080p is the full 2960x1668 active area scaled by 0.6486 (same 16:9 aspect, "
                                   "and the frame shows the full ~111 deg width, so not a crop)"),
               principal_point_px=list(C), cases={})
    for name, pitch_um in (("pitch 2.0 um (typical 1/2.7-inch 5 MP 16:9 sensors)", 2.0),
                           ("pitch from a 6.6 mm (1/2.7-inch) diagonal over 2960x1668", 6.6e3 / math.hypot(*TOP_MODE))):
        f_full = F_MM / (pitch_um * 1e-3)
        out["cases"][name] = dict(pitch_um=round(pitch_um, 3), f_px_full_mode=round(f_full, 1),
                                  f_px_1080p=round(f_full * s, 1))
    f_alt = F_MM / 2.0e-3 * W / 2688
    out["cases"]["alternative: 1080p scaled from the 2688x1520 mode (a crop), pitch 2.0 um"] = dict(f_px_1080p=round(f_alt, 1))
    out["cases"]["alternative: 1080p a 1:1 crop, pitch 2.0 um"] = dict(f_px_1080p=round(F_MM / 2.0e-3, 1))
    half = dict(h=W / 2, v=H / 2, d=math.hypot(W, H) / 2)
    out["f_from_fov_pinhole_px"] = {k: round(half[k] / math.tan(math.radians(v / 2)), 1) for k, v in FOV.items()}
    out["f_from_fov_equidistant_px"] = {k: round(half[k] / math.radians(v / 2), 1) for k, v in FOV.items()}
    out["note"] = ("FOV figures of a wide lens include its barrel distortion, so the pinhole reading of them "
                   "(f = half-size / tan(half-angle)) is far below f from focal length / pixel pitch; the published "
                   "H/V/D are also mutually inconsistent (no single mapping fits all three).")
    return out


def fov_from(f, lam):
    l1, l2 = lam
    def ru(rd):
        r = rd / NORM
        return rd / (1 + l1 * r ** 2 + l2 * r ** 4)
    half = dict(h=W / 2, v=H / 2, d=math.hypot(W, H) / 2)
    return {k: round(2 * math.degrees(math.atan(ru(v) / f)), 1) for k, v in half.items()}


def f_matching_fov(lam):
    l1, l2 = lam
    half = dict(h=W / 2, v=H / 2, d=math.hypot(W, H) / 2)
    out = {}
    for k, v in half.items():
        r = v / NORM
        out[k] = round(v / (1 + l1 * r ** 2 + l2 * r ** 4) / math.tan(math.radians(FOV[k] / 2)), 1)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--plumb", default=os.path.join(HERE, "out", "plumb.json"))
    ap.add_argument("--reg", default=os.path.join(HERE, "out", "registration.json"))
    ap.add_argument("--f-adopt", type=float, default=1070.0)
    ap.add_argument("--f-adopt-sd", type=float, default=45.0)
    ap.add_argument("--out", default=os.path.join(HERE, "out", "intrinsics.json"))
    ap.add_argument("--calib", default="/tmp/aurora-vision/calib")
    a = ap.parse_args()
    pl = json.load(open(a.plumb))
    lam = pl["joint"]["two_param"]
    est = dict(
        principal_point_px=list(C), principal_point_note="assumed at the frame centre (not estimated)",
        distortion=dict(model="division, p_u - c = (p_d - c) / (1 + l1 r^2 + l2 r^4), r = |p_d - c| / 1000 px",
                        joint_two_param=dict(l1=lam[0], l2=lam[1], rms_px=pl["joint"]["two_param_rms_px"],
                                             n_lines=pl["joint"]["n_lines"]),
                        per_camera_two_param={k: dict(l1=pl[k]["two_param"][0][0], l2=pl[k]["two_param"][0][1],
                                                      rms_px=pl[k]["two_param"][1]) for k in ("cam0", "cam1")},
                        per_camera_one_param={k: dict(l1=pl[k]["lam"], se=pl[k]["lam_se_jackknife"],
                                                      rms_px=pl[k]["rms_px"], rms_px_uncorrected=pl[k]["rms_px_lam0"])
                                              for k in ("cam0", "cam1")},
                        lines_used={k: list(pl[k]["lines"]) for k in ("cam0", "cam1")},
                        lines_rejected={k: list(pl[k]["rejected"]) for k in ("cam0", "cam1")}),
        f_matching_published_fov_with_this_distortion=f_matching_fov(lam),
    )
    if os.path.exists(a.reg):
        reg = json.load(open(a.reg))
        est["f_from_registration_f_free"] = {k: dict(f=v["free_f"]["f"], sd=(v["free_f"]["param_sd"] or [None] * 7)[6],
                                                     camera_centre=v["free_f"]["camera_centre"])
                                             for k, v in reg["cameras"].items()}
        est["f_from_registration_note"] = ("poorly constrained: 3-4 model landmarks with +/-20-35 mm uncertainty per "
                                           "camera, so f trades off against camera distance; not adopted")
    r_max = math.hypot(*C) + 2
    d5, e5 = opencv_coeffs(lam, a.f_adopt, r_max)
    d8, e8 = opencv_rational(lam, a.f_adopt, r_max)
    est["f_from_chip_tray_homography"] = dict(
        method=("chip tray as a planar target: grid-to-image homographies from out/chip_tray.json, pocket centres "
                "undistorted with the division model above, homography refit, f from the orthogonality constraint "
                "with the principal point at the centre (independent of pocket pitch); computed by "
                "tray_focal.py"),
        cam0=dict(f=1062, p16_p84=[1015, 1111]), cam1=dict(f=1089, p16_p84=[998, 1199]),
        equal_norm_constraint=dict(cam0=1100, cam1=986), combined=dict(f=1070, sd=45))
    adopted = dict(f_px=a.f_adopt, f_sd_px=a.f_adopt_sd, cx=C[0], cy=C[1], division=lam,
                   K=[[a.f_adopt, 0, C[0]], [0, a.f_adopt, C[1]], [0, 0, 1]],
                   dist_opencv_rational=d8.tolist(), dist_opencv_rational_max_err_px=e8,
                   dist_opencv_5=d5.tolist(), dist_opencv_5_max_err_px=e5,
                   fov_deg_implied=fov_from(a.f_adopt, lam),
                   why=("f = 1070 +/- 45 px from the images: the chip-tray homographies (1062 and 1089 px) and lower "
                        "registration residuals than at 950 px (cam0 6.5 vs 7.6 px, cam1 0.8 vs 1.4 px on points; ducts "
                        "20/4.6/5.8 vs 26/8.2/5.5 px). It is 13-18 % above the sensor-based 908-935 px, which fits a "
                        "1080p stream scaled from a central ~2560x1440 window rather than the whole 2960x1668 area "
                        "(not confirmed by any published source); with the measured distortion it gives the published "
                        "58 deg vertical FOV exactly"))
    out = dict(image_size=[W, H], published=published(), estimated=est, adopted=adopted)
    json.dump(out, open(a.out, "w"), indent=1)
    os.makedirs(a.calib, exist_ok=True)
    json.dump(out, open(os.path.join(a.calib, "intrinsics.json"), "w"), indent=1)
    print(json.dumps(dict(published=out["published"]["cases"], fov_pinhole=out["published"]["f_from_fov_pinhole_px"],
                          f_match=est["f_matching_published_fov_with_this_distortion"], adopted_fov=adopted["fov_deg_implied"],
                          e8=e8, e5=e5), indent=1))
