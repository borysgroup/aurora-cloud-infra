"""Flattens Bambu Studio's system presets (machine, process, filament) so the command-line slicer can load them.

The CLI reads a preset JSON as-is and does not follow its "inherits" chain, so a system preset such as
"0.20mm Standard @BBL H2D" has to be merged with all of its parents first, as the GUI does when it exports a preset.
"""

from __future__ import annotations

import json
from pathlib import Path


def find_preset(profiles: Path, kind: str, name: str) -> Path:
    """The JSON file of system preset `name` (kind: machine, process or filament) under resources/profiles/BBL."""
    p = profiles / kind / f"{name}.json"
    if p.exists():
        return p
    for q in (profiles / kind).rglob("*.json"):           # a few presets live in sub-folders or under another file name
        try:
            if json.loads(q.read_text()).get("name") == name:
                return q
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    raise FileNotFoundError(f"{kind} preset {name!r} not found under {profiles}")


def flatten(profiles: Path, kind: str, name: str) -> dict:
    """The preset with every inherited key filled in; `inherits` removed."""
    chain = []
    cur = name
    while cur:
        d = json.loads(find_preset(profiles, kind, cur).read_text())
        chain.append(d)
        cur = d.get("inherits", "")
    out: dict = {}
    for d in reversed(chain):
        out.update(d)
    out.pop("inherits", None)
    out["name"] = name
    out["from"] = "system"
    return out


def user_preset(profiles: Path, kind: str, parent: str, name: str, overrides: dict) -> dict:
    """A user preset `name` derived from system preset `parent` with `overrides` applied (vector options are filled to
    the parent's length, one value per extruder or variant)."""
    out = flatten(profiles, kind, parent)
    for k, v in overrides.items():
        if isinstance(out.get(k), list) and not isinstance(v, list):
            out[k] = [str(v)] * len(out[k])
        else:
            out[k] = v
    out.update({"name": name, "from": "User", "inherits": parent})
    return out
