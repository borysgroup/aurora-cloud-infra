"""Export the simplified Aurora chamber (STEP, STL, parts.json), render it, and print its numbers.

    python design/aurora-chamber/export_chamber.py            # cad/ + chamber_overview.png
    python design/aurora-chamber/export_chamber.py --params   # every number, source and uncertainty (markdown)
    python design/aurora-chamber/export_chamber.py --report   # robot envelope and stud clearances

Needs cadquery, pyvista and numpy; run the render under xvfb-run on a headless machine.
Set AURORA_CHAMBER_SCALE / AURORA_CHAMBER_RISER_MM to try other tape readings.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import aurora_chamber as ac  # noqa: E402


def report():
    print(f"interior {ac.GB_W:.0f} x {ac.GB_D:.0f} x {ac.GB_H:.0f} mm (SCALE {ac.SCALE}); Epson {ac.EPSON_MODEL}, "
          f"J1 at ({ac.robot.SCARA_XY[0]:.0f}, {ac.robot.SCARA_XY[1]:.0f}); riser {ac.RISER_RANGE[0]:.0f} to "
          f"{ac.RISER_RANGE[1]:.0f} mm, drawn at {ac.RISER_H:.0f}")
    print("riser  arm2 top  shaft top  under ceiling  duct arch  (radii: shaft 619, arm 2 658.5, arch 365)")
    for r in sorted(set(ac.RISER_RANGE) | {ac.RISER_H}):
        e = ac.envelope(r)
        print(f"{r:5.0f}  {e['arm2_top']:8.1f}  {e['shaft_top']:9.1f}  {ac.GB_H - e['shaft_top']:13.1f}  {e['arch_top']:9.1f}")
    tray = ac.TRAY_C
    print(f"tray (plate top) {np.hypot(*(tray[:2] - ac.robot.SCARA_XY)):.0f} mm from J1")
    for name, st in ac.CEILING_STUDS.items():
        p = np.array([[st["xy"][0], st["xy"][1], ac.GB_H - ac.CEILING_STUD_LEN]])
        g = ac.robot_clearance(p)
        print(f"  {name} ({st['xy'][0]:.0f}, {st['xy'][1]:.0f}) {st['state']:6s}: stud tip {g['gap']:6.0f} mm from "
              f"the swept volume ({g['band']}), {np.hypot(*(np.array(st['xy']) - ac.robot.SCARA_XY)):.0f} from J1")


def render(cad_dir, out_png, size=(1600, 1000)):
    import pyvista as pv
    pv.OFF_SCREEN = True
    p = pv.Plotter(off_screen=True, window_size=size, lighting="none")
    p.set_background("#f8fafc", top="#d9e2ec")
    c = (ac.GB_W / 2, ac.GB_D / 2, 300)
    p.add_light(pv.Light(position=(950, -2600, 2600), focal_point=c, intensity=0.85))
    p.add_light(pv.Light(position=(-1800, 1800, 2200), focal_point=c, intensity=0.35))
    p.add_light(pv.Light(position=(3600, 1200, 1500), focal_point=c, intensity=0.30))
    p.add_light(pv.Light(light_type="headlight", intensity=0.25))
    style = {"chamber_shell": dict(color="#c9ced3", opacity=0.22), "windows": dict(color="#bfe3ff", opacity=0.10),
             "window_frames": dict(color="#9aa1a8", opacity=0.55), "flange_studs": dict(color="#6b7280"),
             "ceiling_studs": dict(color="#16b364"), "antechamber_doors": dict(color="#aab2ba"),
             "exfoliator": dict(color="#3b4048"), "substrate_plate": dict(color="#f5f5f5"),
             "chip_tray": dict(color="#9aa3ad"), "robot_shelf": dict(color="#26282b"),
             "epson_t6_parked": dict(color="#eceef0"), "epson_duct": dict(color="#1d1f22"),
             "epson_swept_volume": dict(color="#7c3aed", opacity=0.13), "ceiling_items": dict(color="#f2f2f2")}
    for name, st in style.items():
        m = pv.read(str(Path(cad_dir) / "stl" / f"{name}.stl"))
        p.add_mesh(m, specular=0.3, **st)
    for name, s in ac.CEILING_STUDS.items():
        p.add_point_labels([(s["xy"][0], s["xy"][1], ac.GB_H + 40)], [name], font_size=16, bold=True,
                           text_color="white", shape_color="#166534", shape="rounded_rect", show_points=False,
                           always_visible=True, margin=3)
    labels = [((ac.robot.SCARA_XY[0], ac.robot.SCARA_XY[1], 880.0), f"Epson {ac.EPSON_MODEL} (riser {ac.RISER_H:.0f})"),
              ((ac.TRAY_C[0], ac.TRAY_C[1], ac.TRAY_C[2] + 60), "substrate plate + tray"),
              ((ac.TIP_C[0], ac.TIP_C[1] - 120, ac.TIP_C[2] + 120), "exfoliator"),
              ((0.0, ac.ANTE_DOOR_C[1], ac.ANTE_DOOR_C[2] + 230), "antechamber door")]
    p.add_point_labels([q for q, _ in labels], [t for _, t in labels], font_size=15, text_color="#1f2937",
                       shape_color="white", shape_opacity=0.85, show_points=False, always_visible=True, margin=4)
    p.add_text(f"Aurora chamber model: {ac.GB_W:.0f} x {ac.GB_D:.0f} x {ac.GB_H:.0f} mm interior (SCALE {ac.SCALE:g}). "
               "Purple: the Epson's swept volume over a 150-180 mm riser.", position=(18, 14), font_size=11,
               color="#334155")
    az, el, dist = np.radians(-32), np.radians(30), 3600.0
    cc = np.array([ac.GB_W / 2, ac.GB_D / 2, 260.0])
    p.camera_position = [tuple(cc + dist * np.array([np.sin(az) * np.cos(el), -np.cos(az) * np.cos(el), np.sin(el)])),
                         tuple(cc), (0, 0, 1)]
    p.enable_anti_aliasing("ssaa")
    p.screenshot(str(out_png))
    p.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", action="store_true", help="print the parameter table and stop")
    ap.add_argument("--report", action="store_true", help="print the envelope and stud clearances and stop")
    ap.add_argument("--no-render", action="store_true")
    args = ap.parse_args()
    if args.params:
        print(ac.params_table())
        return
    report()
    if args.report:
        return
    from aurora_chamber import cad
    _, meta = cad.export(HERE / "cad")
    for name, m in meta["parts"].items():
        print(f"  {name:20s} bounds {m['bounds_mm']}  {m['volume_cm3']} cm3")
    if not args.no_render:
        render(HERE / "cad", HERE / "chamber_overview.png")


if __name__ == "__main__":
    main()
