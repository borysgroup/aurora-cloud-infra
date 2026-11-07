"""Exports the stud mount's printed parts in their print orientation and slices them for a Bambu Lab H2D (0.4 mm
nozzles) in Bambu PLA Basic with Bambu Studio's command-line slicer.

    xvfb-run -a python print/slice_h2d.py --bambu /path/to/squashfs-root     # from design/stud-camera-mount

`--bambu` is an extracted Bambu Studio AppImage (`BambuStudio_*.AppImage --appimage-extract`); tested with
v02.09.01.70. Writes print/stl/*.stl (one per part, print orientation), print/<plate>.gcode.3mf (sliced projects
that Bambu Studio opens and the H2D prints) and print/slice_summary.json (time and filament per plate).

The process is Bambu's "0.20mm Standard @BBL H2D" with 100 % infill, four walls and no support (the parts are
oriented so none is needed) on the Textured PEI plate. Solid parts are stiff around the crush-rib pockets, and they
carry little trapped air into the glovebox through the antechamber.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cadquery as cq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import bambu_profiles as bp  # noqa: E402
import stud_mount as sm  # noqa: E402

MACHINE = "Bambu Lab H2D 0.4 nozzle"
PROCESS = "0.20mm Standard @BBL H2D"
FILAMENT = "Bambu PLA Basic @BBL H2D"
PROCESS_OVERRIDES = {
    "sparse_infill_density": "100%",
    "sparse_infill_pattern": "zig-zag",       # rectilinear; at 100 % it prints as solid infill
    "wall_loops": "4",
    "top_shell_layers": "5",
    "bottom_shell_layers": "4",
    "enable_support": "0",
    "enable_prime_tower": "0",                # one filament
    "precise_outer_wall": "1",
    "seam_position": "aligned",
    "curr_bed_type": "Textured PEI Plate",
}
# Plates: two Pi Zero mounts (cameras 1 and 2), the HQ mount (camera 4), and a test of the two crush-rib pockets to
# print first and try with the actual M6 nut and M4 bolt before the rest.
PLATES = {
    "test_fit_pockets": {"stud_thumb_nut": 1, "tilt_knob": 1},
    "zero_mounts_x2": {"yoke_zero": 2, "head_zero_case": 2, "head_zero_back_cover": 2, "stud_thumb_nut": 2,
                       "tilt_knob": 4},
    "hq_mount": {"yoke_hq": 1, "head_hq_frame": 1, "head_hq_pi_carrier": 1, "head_hq_wide_nose": 1,
                 "stud_thumb_nut": 1, "tilt_knob": 2},
}


def export_stls(out: Path) -> dict:
    """Writes every printed part (print orientation) to out/<name>.stl; returns {name: path}. Fine tessellation so
    the 0.3 mm crush ribs survive."""
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    for group in sm.PRINTED.values():
        for name, make in group.items():
            p = out / f"{name}.stl"
            cq.exporters.export(make(), str(p), tolerance=0.01, angularTolerance=0.1)
            paths[name] = p
    return paths


def presets(profiles: Path, tmp: Path) -> tuple[Path, Path, Path]:
    """Flattened machine, process (with PROCESS_OVERRIDES) and filament presets as JSON files in tmp."""
    m = bp.flatten(profiles, "machine", MACHINE)
    p = bp.user_preset(profiles, "process", PROCESS, "0.20mm Standard @BBL H2D - stud mount (100% infill)",
                       PROCESS_OVERRIDES)
    f = bp.flatten(profiles, "filament", FILAMENT)
    files = []
    for name, d in (("machine", m), ("process", p), ("filament", f)):
        q = tmp / f"{name}.json"
        q.write_text(json.dumps(d, indent=1))
        files.append(q)
    return tuple(files)


def ensure_model_id(profiles: Path):
    """The CLI writes the printer's model id (which the printer checks) only if it finds the printer model's JSON in
    machine_full/, which the AppImage doesn't ship; copy it there from machine/."""
    src = profiles / "machine" / "Bambu Lab H2D.json"
    dst = profiles / "machine_full" / "Bambu Lab H2D.json"
    if src.exists() and not dst.exists():
        dst.parent.mkdir(exist_ok=True)
        shutil.copy(src, dst)


def slice_plate(app: Path, name: str, items: dict, stls: dict, cfg: tuple, out: Path) -> dict:
    """Arranges `items` {part: copies} on one plate and slices it; returns Bambu's result.json for the plate."""
    machine, process, filament = cfg
    files = [str(stls[part]) for part, n in items.items() for _ in range(n)]
    with tempfile.TemporaryDirectory() as d:
        cmd = [str(app), "--slice", "0", "--arrange", "1", "--orient", "0", "--ensure-on-bed",
               "--load-settings", f"{machine};{process}", "--load-filaments", str(filament),
               "--export-3mf", f"{name}.gcode.3mf", "--outputdir", d, *files]    # the 3MF path is relative to d
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        res = json.loads((Path(d) / "result.json").read_text())
        if res.get("return_code", -1) != 0:
            raise RuntimeError(f"{name}: {res.get('error_string')}\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
        shutil.move(str(Path(d) / f"{name}.gcode.3mf"), out / f"{name}.gcode.3mf")
    return res


def summary(name: str, items: dict, res: dict) -> dict:
    plate = res["sliced_plates"][0]
    grams = sum(f.get("total_used_g", 0.0) for f in plate.get("filaments", []))
    secs = plate.get("total_predication", plate.get("total_prediction", 0.0))
    return {"plate": name, "parts": items, "time_h": round(secs / 3600.0, 2), "filament_g": round(grams, 1),
            "warnings": plate.get("warning_message", plate.get("warnings", [])), "layer_height": res["layer_height"],
            "sparse_infill_density": res["sparse_infill_density"], "wall_loops": res["wall_loops"],
            "raw": {k: v for k, v in plate.items() if k not in ("feature_type_times",)}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bambu", type=Path, required=True, help="extracted Bambu Studio AppImage (squashfs-root)")
    ap.add_argument("--plates", nargs="*", default=list(PLATES))
    args = ap.parse_args()
    app = args.bambu / "AppRun"
    profiles = args.bambu / "resources" / "profiles" / "BBL"
    ensure_model_id(profiles)
    stls = export_stls(HERE / "stl")
    out = []
    with tempfile.TemporaryDirectory() as d:
        cfg = presets(profiles, Path(d))
        shutil.copy(cfg[1], HERE / "process_stud_mount.json")
        for name in args.plates:
            res = slice_plate(app, name, PLATES[name], stls, cfg, HERE)
            s = summary(name, PLATES[name], res)
            print(f"{name}: {s['time_h']} h, {s['filament_g']} g")
            out.append(s)
    (HERE / "slice_summary.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
