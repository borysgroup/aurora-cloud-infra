#!/usr/bin/env python3
"""Headless Bambu Studio slicing for a Bambu Lab H2D (0.4 mm nozzle, Bambu PLA Basic).

Setup (once per runner):  bash install_bambu_studio.sh
Slice a plate:            python slice_h2d.py slice plates/proof_all_parts.json
Re-flatten profiles:      python slice_h2d.py resolve   (after a Bambu Studio upgrade)

``slice`` arranges the parts on one plate (``--arrange 1``, never auto-orients
unless ``--auto-orient`` is given), slices with the flattened H2D presets plus
the strength overrides, and writes into the output directory:

  <name>.gcode.3mf     sliced project (send to the printer / open in Bambu Studio)
  <name>.summary.json  versions, profiles, overrides with evidence, time, filament
  <name>.slicer.log    full Bambu Studio CLI log

It exits non-zero if the CLI fails, reports any slicing warning (floating
regions, floating cantilever, ...), parts end up outside the plate or on a
second plate, or an override/nozzle choice is not found in the embedded config.

Plate spec (JSON; paths relative to the spec file; all keys but "parts" optional):

  {"name": "camera_mount",
   "parts": [{"stl": "../stl/yoke_hq.stl", "copies": 2}, "../stl/tilt_knob.stl"],
   "overrides": {"wall_loops": 6},          # applied after the strength defaults
   "supports": false, "nozzle": "left", "process": "0.20mm Standard @BBL H2D",
   "bed_type": "Textured PEI Plate", "outdir": "out"}

Command-line options (--stl, --set, --supports, --nozzle, ...) take precedence
over the spec. Overrides use Bambu Studio's config keys (``--set key=value``); a
single value for a per-extruder/variant key is repeated to the preset's length.

``resolve`` flattens the vendor system presets (``inherits`` chain + ``include``
templates) into stand-alone JSON under ``profiles/``: the CLI's
``--load-settings``/``--load-filaments`` read only the keys present in the given
file, so the raw vendor JSONs would silently fall back to built-in defaults.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROFILE_DIR = HERE / "profiles"
DEFAULT_APP_DIR = Path(os.environ.get("BAMBU_STUDIO_APP", "/tmp/bambu/app"))
DEFAULT_OUT_DIR = HERE / "out"

MACHINE = "Bambu Lab H2D 0.4 nozzle"
PROCESSES = ("0.20mm Standard @BBL H2D", "0.20mm Balanced Strength @BBL H2D")
DEFAULT_PROCESS = PROCESSES[0]
FILAMENT = "Bambu PLA Basic @BBL H2D"
PRINTER_MODEL_ID = "O1D"  # Bambu Lab H2D

# Robust-part settings (user request). Speeds/temperatures stay at vendor values.
STRENGTH_OVERRIDES = {
    "layer_height": "0.2",
    "wall_loops": "6",
    "top_shell_layers": "6",
    "bottom_shell_layers": "5",
    "sparse_infill_density": "40%",
    "sparse_infill_pattern": "gyroid",
}

# H2D logical extruder ids as used by filament_map (1-based). The CLI source
# documents id 1 as the left extruder; physical_extruder_map (machine preset)
# maps it to the firmware's extruder index, which resources/printers/O1D.json
# names (0 = right, 1 = left).
NOZZLES = {"left": 1, "right": 2}
DEFAULT_NOZZLE = "left"  # what the CLI's own "Auto For Flush" picks for one filament

# [error]-level CLI log lines that are expected on a successful headless slice.
BENIGN_LOG_ERRORS = [
    r"Invalid T command \(T(1001|65535|65279)\)",   # H2D start/end gcode special T codes
    r"ZFiller: encounter idx from clip",
    r"the parent path .* is not there, create it",
    r"glfw_callback|glfwInit return error|Unable to init glew|init opengl failed",  # no thumbnails headless
]
WARNING_RE = re.compile(r"found (?:NON_CRITICAL )?slicing warnings: (.*?)(?:, no_check=\d+)?\s*$")

# Keys that describe a preset file rather than a setting. They are taken from
# the leaf preset only (Bambu Studio's PresetBundle does the same); filament_id
# is the exception and is inherited when the leaf lacks it.
LEAF_ONLY_KEYS = {"name", "from", "instantiation", "setting_id", "description",
                  "type", "url", "version"}
LINK_KEYS = {"inherits", "include"}


class SliceError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Profile flattening
# --------------------------------------------------------------------------
class VendorProfiles:
    """Index of one vendor's presets (``resources/profiles/<vendor>``)."""

    def __init__(self, vendor_dir: Path):
        self.vendor_dir = vendor_dir
        index = json.loads((vendor_dir.parent / f"{vendor_dir.name}.json").read_text())
        self.vendor_version = index.get("version", "")
        self.paths: dict[str, Path] = {}
        for key in ("machine_model_list", "machine_list", "process_list", "filament_list"):
            for entry in index.get(key, []):
                self.paths.setdefault(entry["name"], vendor_dir / entry["sub_path"])
        self._cache: dict[str, tuple[dict, list[str]]] = {}

    def raw(self, name: str) -> dict:
        if name not in self.paths:
            raise KeyError(f"preset {name!r} is not listed in {self.vendor_dir.name}.json")
        return json.loads(self.paths[name].read_text())

    @staticmethod
    def _includes(own: dict) -> list[str]:
        inc = own.get("include") or []
        return [inc] if isinstance(inc, str) else list(inc)

    def resolve(self, name: str) -> tuple[dict, list[str]]:
        """Return (flattened settings, source preset names in merge order).

        Precedence mirrors PresetBundle::load_vendor_configs_from_json:
        own keys > include templates (in listed order) > inherits chain.
        """
        if name in self._cache:
            return self._cache[name]
        own = self.raw(name)
        merged: dict = {}
        sources: list[str] = []
        if own.get("inherits"):
            base, base_sources = self.resolve(own["inherits"])
            merged.update({k: v for k, v in base.items() if k not in LEAF_ONLY_KEYS})
            sources += base_sources
        for inc in self._includes(own):
            inc_cfg, inc_sources = self.resolve(inc)
            merged.update({k: v for k, v in inc_cfg.items()
                           if k not in LEAF_ONLY_KEYS and k != "filament_id"})
            sources += inc_sources
        merged.update({k: v for k, v in own.items() if k not in LINK_KEYS})
        sources.append(name)
        self._cache[name] = (merged, sources)
        return merged, sources

    def include_overrides(self, name: str) -> list[str]:
        """Keys where an include template replaces a different inherited value.
        The GUI applies only include keys that differ from the built-in default,
        so these are the only keys where flattening could in principle diverge
        from the GUI; listed in the manifest for audit."""
        own = self.raw(name)
        chain = self.resolve(own["inherits"])[0] if own.get("inherits") else {}
        out = []
        for inc in self._includes(own):
            for k, v in self.resolve(inc)[0].items():
                if (k not in LEAF_ONLY_KEYS and k not in LINK_KEYS and k != "filament_id"
                        and k in chain and chain[k] != v and k not in own):
                    out.append(f"{inc}: {k}")
        return out


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def flattened_preset(vp: VendorProfiles, name: str) -> tuple[dict, list[str]]:
    cfg, sources = vp.resolve(name)
    out = {"type": cfg["type"], "name": name, "from": "system", "instantiation": "true"}
    for k in ("setting_id", "filament_id", "description"):
        if k in cfg:
            out[k] = cfg[k]
    for k in sorted(cfg):
        if k not in out and k not in LINK_KEYS:
            out[k] = cfg[k]
    return out, sources


def cmd_resolve(args: argparse.Namespace) -> int:
    app = Path(args.app).resolve()
    vendor_dir = app / "resources" / "profiles" / "BBL"
    vp = VendorProfiles(vendor_dir)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {"bambu_studio_version": bambu_version(app), "bbl_profile_version": vp.vendor_version,
                "generated_by": "slice_h2d.py resolve", "presets": {}}
    for name in (MACHINE, *PROCESSES, FILAMENT):
        flat, sources = flattened_preset(vp, name)
        dest = PROFILE_DIR / f"{name}.json"
        dest.write_text(json.dumps(flat, indent=4, ensure_ascii=False) + "\n")
        manifest["presets"][name] = {
            "file": dest.name, "type": flat["type"], "keys": len(flat), "sha256": sha256(dest),
            "merged_from": [{"name": s, "file": str(vp.paths[s].relative_to(vendor_dir.parent)),
                             "sha256": sha256(vp.paths[s])} for s in sources],
            "include_overrides_inherited_value": vp.include_overrides(name),
        }
        print(f"wrote profiles/{dest.name} ({len(flat)} keys from {len(sources)} vendor files)")
    (PROFILE_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return 0


# --------------------------------------------------------------------------
# Bambu Studio invocation helpers
# --------------------------------------------------------------------------
def bambu_binary(app: Path) -> Path:
    exe = app / "bin" / "bambu-studio"
    if not exe.is_file():
        raise SliceError(f"Bambu Studio not found at {exe}; run install_bambu_studio.sh "
                         "or pass --app / set BAMBU_STUDIO_APP")
    return exe


def bambu_env(app: Path) -> dict:
    env = dict(os.environ)
    # Same as the AppImage's AppRun.
    env["LD_LIBRARY_PATH"] = str(app / "bin") + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    env["LC_ALL"] = "C"
    return env


def bambu_version(app: Path) -> str:
    # The CLI drops a result.json into its working directory, even for --help.
    with tempfile.TemporaryDirectory() as scratch:
        out = subprocess.run([str(bambu_binary(app)), "--help"], env=bambu_env(app), cwd=scratch,
                             capture_output=True, text=True, timeout=120).stdout
    m = re.match(r"BambuStudio-([\d.]+):", out.strip())
    return m.group(1) if m else "unknown"


def cli_value(v) -> str:
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (list, tuple)):
        return ",".join(cli_value(x) for x in v)
    return str(v)


# --------------------------------------------------------------------------
# Output parsing and verification
# --------------------------------------------------------------------------
def _norm(v: str) -> str:
    v = v.strip().strip('"')
    try:
        return f"{float(v[:-1]):g}%" if v.endswith("%") else f"{float(v):g}"
    except ValueError:
        return v


def _items(v) -> list[str]:
    if isinstance(v, list):
        return [_norm(str(x)) for x in v]
    return [_norm(x) for x in re.split(r"[,;]", str(v))]


def value_matches(expected: str, actual, resolved: bool = False) -> bool:
    """Compare a requested value with the output. ``resolved`` marks the gcode
    config block, where per-variant vectors (e.g. 7 speed entries for the H2D's
    nozzle variants) are already reduced to one entry per extruder."""
    if actual is None:
        return False
    exp, act = _items(expected), _items(actual)
    if len(set(exp)) == 1:  # one value requested: every entry must equal it
        return bool(act) and all(a == exp[0] for a in act)
    if resolved:
        return bool(act) and all(a in exp for a in act)
    return exp == act


def expand_to_profile_shape(key: str, value: str, profile_cfgs: list[dict]) -> str:
    """A single value for a key that the presets store as a per-extruder/variant
    vector is repeated to the preset's length, so the project config saved in
    the 3MF keeps the vendor layout (the CLI would otherwise store a 1-entry
    vector next to 7-entry variant lists)."""
    if "," in value or ";" in value:
        return value
    for cfg in profile_cfgs:
        base = cfg.get(key)
        if isinstance(base, list) and len(base) > 1:
            return ",".join([value] * len(base))
    return value


def gcode_config_block(gcode: str) -> dict[str, str]:
    start, end = gcode.find("; CONFIG_BLOCK_START"), gcode.find("; CONFIG_BLOCK_END")
    cfg = {}
    for line in gcode[start:end].splitlines()[1:]:
        if line.startswith("; ") and " = " in line:
            k, v = line[2:].split(" = ", 1)
            cfg[k.strip()] = v
    return cfg


def gcode_header(gcode: str) -> dict:
    head = gcode[: gcode.find("; HEADER_BLOCK_END")]
    out = {}
    m = re.search(r"model printing time: ([^;\n]+); total estimated time: ([^\n]+)", head)
    if m:
        out["model_printing_time"], out["total_estimated_time"] = m.group(1).strip(), m.group(2).strip()
    for key, pat in (("total_layers", r"total layer number: (\d+)"),
                     ("filament_length_mm", r"total filament length \[mm\] : ([\d.]+)"),
                     ("filament_weight_g", r"total filament weight \[g\] : ([\d.]+)"),
                     ("max_z_height_mm", r"max_z_height: ([\d.]+)")):
        mm = re.search(pat, head)
        if mm:
            out[key] = float(mm.group(1)) if "." in mm.group(1) else int(mm.group(1))
    m = re.search(r"; BambuStudio ([\d.]+)", head)
    if m:
        out["bambu_studio_version"] = m.group(1)
    return out


def parse_slice_info(xml: str) -> dict:
    plates = re.findall(r"<plate>(.*?)</plate>", xml, re.S)
    info = {"plate_count": len(plates),
            "client_version": (re.findall(r'X-BBL-Client-Version" value="([^"]*)"', xml) or [""])[0]}
    if not plates:
        return info
    p = plates[0]
    info["metadata"] = dict(re.findall(r'<metadata key="([^"]+)" value="([^"]*)"', p))
    info["objects"] = re.findall(r'<object [^>]*name="([^"]*)" skipped="false"', p)
    info["filaments"] = [dict(re.findall(r'(\w+)="([^"]*)"', f)) for f in re.findall(r"<filament [^>]*/>", p)]
    info["nozzles"] = [dict(re.findall(r'(\w+)="([^"]*)"', f)) for f in re.findall(r"<nozzle [^>]*/>", p)]
    info["warnings"] = [dict(re.findall(r'(\w+)\s*="([^"]*)"', w)) for w in re.findall(r"<warning [^>]*/>", p)]
    return info


def fmt_duration(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}h {s % 3600 // 60:02d}m {s % 60:02d}s"


# --------------------------------------------------------------------------
# slice
# --------------------------------------------------------------------------
def load_plate(args: argparse.Namespace) -> dict:
    spec: dict = {}
    base = Path.cwd()
    if args.plate:
        path = Path(args.plate).resolve()
        spec = json.loads(path.read_text())
        base = path.parent
        spec.setdefault("name", path.stem)
    parts = []
    for p in spec.get("parts", []):
        p = {"stl": p} if isinstance(p, str) else dict(p)
        parts.append({"stl": (base / p["stl"]).resolve(), "copies": int(p.get("copies", 1))})
    for s in args.stl or []:
        m = re.match(r"^(.*?)(?::(\d+))?$", s)
        parts.append({"stl": Path(m.group(1)).resolve(), "copies": int(m.group(2) or 1)})
    if not parts:
        raise SliceError("no parts: give a plate spec and/or --stl PATH[:COPIES]")
    for p in parts:
        if not p["stl"].is_file():
            raise SliceError(f"STL not found: {p['stl']}")
        if not 1 <= p["copies"] <= 512:
            raise SliceError(f"copies must be 1..512 ({p['stl'].name})")
    name = args.name or spec.get("name") or "plate"
    if not re.fullmatch(r"[\w.+-]+", name):
        raise SliceError(f"plate name {name!r} must be a simple file name")
    outdir = Path(args.outdir).resolve() if args.outdir else (
        (base / spec["outdir"]).resolve() if spec.get("outdir") else DEFAULT_OUT_DIR)
    return {"name": name, "parts": parts, "spec": spec, "outdir": outdir}


def cmd_slice(args: argparse.Namespace) -> int:
    try:
        return _slice(args)
    except SliceError as e:
        sys.stdout.flush()
        print(f"\nSLICE FAILED: {e}", file=sys.stderr)
        return 1


def _slice(args: argparse.Namespace) -> int:
    plate = load_plate(args)
    spec = plate["spec"]
    app = Path(args.app).resolve()
    exe = bambu_binary(app)

    process = args.process or spec.get("process") or DEFAULT_PROCESS
    nozzle = args.nozzle or spec.get("nozzle") or DEFAULT_NOZZLE
    if nozzle not in NOZZLES:
        raise SliceError(f"nozzle must be one of {sorted(NOZZLES)}")
    supports = args.supports if args.supports is not None else bool(spec.get("supports", False))
    bed_type = args.bed_type or spec.get("bed_type") or "Textured PEI Plate"

    profiles = {"machine": MACHINE, "process": process, "filament": FILAMENT}
    files = {k: PROFILE_DIR / f"{v}.json" for k, v in profiles.items()}
    for k, f in files.items():
        if not f.is_file():
            raise SliceError(f"{k} profile {f.name} missing; run `python slice_h2d.py resolve`")
    manifest = json.loads((PROFILE_DIR / "manifest.json").read_text())
    version = bambu_version(app)
    if manifest.get("bambu_studio_version") != version:
        raise SliceError(f"profiles were flattened from Bambu Studio {manifest.get('bambu_studio_version')} "
                         f"but {version} is installed; run `python slice_h2d.py resolve`")
    cfgs = {k: json.loads(f.read_text()) for k, f in files.items()}
    machine_cfg = cfgs["machine"]

    # Settings passed on the command line (highest priority in the CLI).
    overrides: dict[str, str] = {} if args.no_strength else dict(STRENGTH_OVERRIDES)
    overrides.update({k: cli_value(v) for k, v in (spec.get("overrides") or {}).items()})
    for kv in args.set or []:
        if "=" not in kv:
            raise SliceError(f"--set expects KEY=VALUE, got {kv!r}")
        k, v = kv.split("=", 1)
        overrides[k.strip().replace("-", "_")] = v.strip()
    requested = dict(overrides)
    overrides = {k: expand_to_profile_shape(k, v, [cfgs["process"], cfgs["machine"], cfgs["filament"]])
                 for k, v in overrides.items()}
    logical = NOZZLES[nozzle]
    fixed = {  # always pinned so results do not depend on CLI defaults
        "curr_bed_type": bed_type,
        "nozzle_volume_type": "Standard,Standard",
        "filament_map_mode": "Manual",
        "filament_map": str(logical),
        "enable_support": "1" if supports else "0",
    }
    clash = sorted(set(fixed) & set(overrides))
    if clash:
        raise SliceError(f"use the dedicated options instead of overriding {clash}")
    settings = {**overrides, **fixed}

    outdir = plate["outdir"]
    outdir.mkdir(parents=True, exist_ok=True)
    name = plate["name"]
    out_3mf, out_log, out_summary = (outdir / f"{name}.gcode.3mf", outdir / f"{name}.slicer.log",
                                     outdir / f"{name}.summary.json")
    for f in (out_3mf, out_log, out_summary):
        f.unlink(missing_ok=True)

    work = Path(tempfile.mkdtemp(prefix=f"bambu-{name}-"))
    try:
        cmd = [str(exe), "--debug", "3", "--datadir", str(work / "datadir"),
               "--load-settings", f"{files['machine']};{files['process']}",
               "--load-filaments", str(files["filament"]),
               "--clone-objects", ",".join(str(p["copies"]) for p in plate["parts"])]
        cmd += [f"--{k.replace('_', '-')}={v}" for k, v in settings.items()]
        cmd += ["--arrange", "1", "--orient", "1" if args.auto_orient else "0", "--slice", "0",
                "--outputdir", str(work / "out"), "--export-3mf", out_3mf.name]
        cmd += [str(p["stl"]) for p in plate["parts"]]
        print("$ " + shlex.join(cmd), flush=True)
        try:
            proc = subprocess.run(cmd, env=bambu_env(app), cwd=work, capture_output=True, text=True,
                                  timeout=args.timeout)
        except subprocess.TimeoutExpired:
            raise SliceError(f"Bambu Studio did not finish within {args.timeout} s (--timeout)") from None
        log = proc.stdout + proc.stderr
        out_log.write_text(log)
        produced = work / "out" / out_3mf.name
        if produced.is_file():
            shutil.move(produced, out_3mf)
        result_path = work / "out" / "result.json"
        cli_result = json.loads(result_path.read_text()) if result_path.is_file() else {}
    finally:
        shutil.rmtree(work, ignore_errors=True)

    failures: list[str] = []
    if proc.returncode != 0 or cli_result.get("return_code", 0) != 0:
        cli_msgs = [l.strip() for l in log.splitlines()
                    if re.match(r"(Invalid |Need values|Params in command line error)", l) or "[fatal]" in l
                    or ("[error]" in l and not any(re.search(b, l) for b in BENIGN_LOG_ERRORS))]
        failures.append(f"Bambu Studio exited {proc.returncode} "
                        f"(return_code {cli_result.get('return_code')}: {cli_result.get('error_string')})"
                        + "".join(f"\n      {m[:300]}" for m in cli_msgs[-5:]))

    warnings = []
    for line in log.splitlines():
        m = WARNING_RE.search(line)
        if m and m.group(1) not in warnings:
            warnings.append(m.group(1))
    for p in cli_result.get("sliced_plates", []):
        if p.get("warning_message") and p["warning_message"] not in warnings:
            warnings.append(p["warning_message"])
    allowed = [re.compile(a) for a in (args.allow_warning or [])]
    blocking = [w for w in warnings if not any(a.search(w) for a in allowed)]
    failures += [f"slicer warning: {w}" for w in blocking]
    log_errors = [l.split("]", 3)[-1].strip() for l in log.splitlines()
                  if "[error]" in l and not any(re.search(b, l) for b in BENIGN_LOG_ERRORS)]

    summary: dict = {
        "plate": name,
        "status": None,
        "bambu_studio_version": version,
        "bbl_profile_version": manifest.get("bbl_profile_version"),
        "profiles": {k: {"name": profiles[k], "file": str(files[k].relative_to(HERE)),
                         "sha256": sha256(files[k])} for k in profiles},
        "bed_type": bed_type,
        "supports": supports,
        "auto_orient": bool(args.auto_orient),
        "parts": [{"stl": os.path.relpath(p["stl"], HERE), "copies": p["copies"],
                   "sha256": sha256(p["stl"])} for p in plate["parts"]],
        "command": cmd,
        "command_line": shlex.join(cmd),
        "warnings": warnings,
        "allowed_warning_patterns": [a.pattern for a in allowed],
        "unexpected_log_errors": log_errors,
    }

    if out_3mf.is_file():
        with zipfile.ZipFile(out_3mf) as z:
            names = z.namelist()
            sinfo = parse_slice_info(z.read("Metadata/slice_info.config").decode())
            project = json.loads(z.read("Metadata/project_settings.config"))
            gcode_files = sorted(n for n in names if re.fullmatch(r"Metadata/plate_\d+\.gcode", n))
            gcode = z.read(gcode_files[0]).decode(errors="replace") if gcode_files else ""
        gcfg, header = gcode_config_block(gcode), gcode_header(gcode)
        meta = sinfo.get("metadata", {})

        # Overrides: requested value vs. the 3MF project config and the gcode config block.
        checks = {}
        for k, v in settings.items():
            ok_p, ok_g = value_matches(v, project.get(k)), value_matches(v, gcfg.get(k), resolved=True)
            checks[k] = {"requested": requested.get(k, v), "passed": v,
                         "project_settings.config": project.get(k),
                         "gcode_config_block": gcfg.get(k), "ok": ok_p and ok_g}
            if not (ok_p and ok_g):
                failures.append(f"override {k}={v} not in output (project={project.get(k)!r}, gcode={gcfg.get(k)!r})")
        summary["settings"] = checks

        # Nozzle: filament_map in slice_info + firmware extruder index in the start gcode.
        phys_map = [int(x) for x in machine_cfg.get("physical_extruder_map", ["0", "1"])]
        phys_expected = phys_map[logical - 1]
        names_by_phys = {}
        dev = app / "resources" / "printers" / f"{PRINTER_MODEL_ID}.json"
        if dev.is_file():
            for idx, d in next(iter(json.loads(dev.read_text()).values())).get("tool_head_display_names", {}).items():
                names_by_phys[int(idx)] = d["nozzle"][0]
        m = re.search(r"^M104 S\d+ T(\d+) ; rise temp in advance", gcode, re.M)
        phys_seen = int(m.group(1)) if m else None
        summary["nozzle"] = {
            "requested": nozzle,
            "filament_map (logical, 1=left 2=right)": logical,
            "slice_info filament_maps": meta.get("filament_maps"),
            "slice_info nozzle": sinfo.get("nozzles"),
            "physical_extruder_map": phys_map,
            "firmware_extruder_expected": phys_expected,
            "firmware_extruder_in_start_gcode": phys_seen,
            "firmware_extruder_name": names_by_phys.get(phys_expected),
        }
        if meta.get("filament_maps") != str(logical):
            failures.append(f"slice_info filament_maps={meta.get('filament_maps')!r}, expected {logical}")
        if phys_seen is not None and phys_seen != phys_expected:
            failures.append(f"start gcode heats T{phys_seen}, expected T{phys_expected} ({nozzle})")

        expected_objects = sum(p["copies"] for p in plate["parts"])
        if sinfo.get("plate_count") != 1 or len(gcode_files) != 1:
            failures.append(f"arrange used {sinfo.get('plate_count')} plates; parts do not fit on one H2D plate")
        if len(sinfo.get("objects", [])) != expected_objects:
            failures.append(f"{len(sinfo.get('objects', []))} objects on plate 1, expected {expected_objects}")
        if meta.get("outside") != "false":
            failures.append(f"slice_info reports objects outside the plate (outside={meta.get('outside')!r})")
        if meta.get("printer_model_id") != PRINTER_MODEL_ID:
            failures.append(f"printer_model_id={meta.get('printer_model_id')!r}, expected {PRINTER_MODEL_ID} "
                            "(machine_full/Bambu Lab H2D.json missing? see install_bambu_studio.sh)")
        for w in sinfo.get("warnings", []):
            failures.append(f"slice_info warning: {w}")

        fil = sinfo.get("filaments") or [{}]
        cli_plate = (cli_result.get("sliced_plates") or [{}])[0]
        summary["results"] = {
            "print_time_s": int(meta.get("prediction", 0)),
            "print_time": fmt_duration(float(meta.get("prediction", 0))),
            "model_printing_time": header.get("model_printing_time"),
            "filament_g": float(meta.get("weight", 0)),
            "filament_m": round(sum(float(f.get("used_m", 0)) for f in fil), 2),
            "filament_used": fil,
            "total_layers": header.get("total_layers"),
            "max_z_height_mm": header.get("max_z_height_mm"),
            "support_used": meta.get("support_used"),
            "printer_model_id": meta.get("printer_model_id"),
            "objects": [{"name": o.get("name"), "bbox": o.get("bbox")} for o in cli_plate.get("objects", [])],
            "feature_type_times_s": {k: round(v) for k, v in (cli_plate.get("feature_type_times") or {}).items()},
            "thumbnail_in_3mf": any(n.startswith("Metadata/plate_1") and n.endswith(".png") for n in names),
            "gcode_header": header,
        }
        summary["outputs"] = {"gcode_3mf": str(out_3mf), "sha256": sha256(out_3mf),
                              "size_bytes": out_3mf.stat().st_size, "log": str(out_log)}
    else:
        failures.append("no .gcode.3mf produced")

    summary["status"] = "failed" if failures else "ok"
    summary["failures"] = failures
    out_summary.write_text(json.dumps(summary, indent=2) + "\n")

    res = summary.get("results", {})
    print(f"\nplate {name}: {summary['status'].upper()}")
    if res:
        print(f"  time {res['print_time']} ({res['print_time_s']} s, model {res['model_printing_time']}), "
              f"filament {res['filament_g']} g / {res['filament_m']} m, layers {res['total_layers']}")
        print(f"  nozzle {nozzle} (filament_map={logical}, firmware T{summary['nozzle']['firmware_extruder_in_start_gcode']}), "
              f"bed {bed_type}, supports {'on' if supports else 'off'}, process {process}")
    for w in warnings:
        print(f"  {'allowed ' if w not in blocking else ''}warning: {w}")
    for e in log_errors:
        print(f"  note: unexpected [error] log line: {e}")
    print(f"  summary {out_summary}", flush=True)
    if failures:
        print("\nSLICE FAILED:\n  - " + "\n  - ".join(failures), file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("resolve", help="flatten vendor presets into profiles/")
    r.add_argument("--app", default=str(DEFAULT_APP_DIR), help="extracted AppImage root (default %(default)s)")
    r.set_defaults(func=cmd_resolve)

    s = sub.add_parser("slice", help="arrange and slice one plate",
                       description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s.add_argument("plate", nargs="?", help="plate spec JSON")
    s.add_argument("--stl", action="append", metavar="PATH[:COPIES]", help="add a part (repeatable)")
    s.add_argument("--name", help="output base name (default: spec name or file stem)")
    s.add_argument("--set", action="append", metavar="KEY=VALUE",
                   help="Bambu Studio config override, e.g. wall_loops=4 (repeatable; wins over spec)")
    s.add_argument("--no-strength", action="store_true", help="do not apply the built-in strength overrides")
    sup = s.add_mutually_exclusive_group()
    sup.add_argument("--supports", dest="supports", action="store_true", default=None, help="enable supports")
    sup.add_argument("--no-supports", dest="supports", action="store_false", help="disable supports (default)")
    s.add_argument("--nozzle", choices=sorted(NOZZLES), help=f"H2D nozzle for the PLA (default {DEFAULT_NOZZLE})")
    s.add_argument("--process", choices=PROCESSES, help=f"base process preset (default {DEFAULT_PROCESS})")
    s.add_argument("--bed-type", help="curr_bed_type (default Textured PEI Plate)")
    s.add_argument("--auto-orient", action="store_true",
                   help="let Bambu Studio re-orient parts (tests only; final STLs come pre-oriented)")
    s.add_argument("--allow-warning", action="append", metavar="REGEX",
                   help="do not fail on slicer warnings matching REGEX (repeatable)")
    s.add_argument("--outdir", help=f"output directory (default {DEFAULT_OUT_DIR.relative_to(HERE)}/)")
    s.add_argument("--app", default=str(DEFAULT_APP_DIR), help="extracted AppImage root (default %(default)s)")
    s.add_argument("--timeout", type=int, default=1800, help="CLI timeout in seconds")
    s.set_defaults(func=cmd_slice)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
