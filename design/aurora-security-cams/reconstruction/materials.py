"""Physically based materials for the reconstruction (glTF metallic-roughness), one per finish.

Base colours are the median sRGB of each finish in the 2026-11-19 18:22 UTC frames (camera white
balance), except where a finish only shows as a highlight (glass, ground steel). `aniso` and `brushed`
are read by blender_render.py (glTF has no anisotropy in the core spec); other viewers ignore them.
"""
import numpy as np
import trimesh

M = {
    # glovebox shell
    "stainless_deck": dict(color="#b5b0a3", metallic=1.0, roughness=0.30, aniso=0.55, brushed=True),
    "stainless_wall": dict(color="#bdb39c", metallic=1.0, roughness=0.26, aniso=0.5, brushed=True),
    "stainless_frame": dict(color="#b9b5aa", metallic=1.0, roughness=0.35, aniso=0.4, brushed=True),
    "stainless_door": dict(color="#c4c4b8", metallic=1.0, roughness=0.22, aniso=0.7, brushed=True),
    "window": dict(color="#e9f1f1", metallic=0.0, roughness=0.03, transmission=1.0, ior=1.49, alpha=0.12),
    "glove_port": dict(color="#9aa0a2", metallic=1.0, roughness=0.3),
    # aluminium and steel
    "alu_blasted": dict(color="#cfd4d3", metallic=1.0, roughness=0.48),
    "alu_machined": dict(color="#d7dcdb", metallic=1.0, roughness=0.22, aniso=0.45, brushed=True),
    "steel_ground": dict(color="#c8ccce", metallic=1.0, roughness=0.18),
    "steel_post": dict(color="#c6cacc", metallic=1.0, roughness=0.15),
    "black_oxide": dict(color="#2b2c2e", metallic=0.4, roughness=0.45),
    "black_anodised": dict(color="#34363a", metallic=0.2, roughness=0.42),
    "hole_floor": dict(color="#0b0b0c", metallic=0.0, roughness=0.9),
    # plastics and paint
    "black_plastic": dict(color="#1e1c1a", metallic=0.0, roughness=0.55),
    "black_rubber": dict(color="#151515", metallic=0.0, roughness=0.8),
    "grey_pvc": dict(color="#8f8c88", metallic=0.0, roughness=0.6),
    "epson_paint": dict(color="#d4dad5", metallic=0.0, roughness=0.38),
    "epson_grey": dict(color="#aeb4b2", metallic=0.0, roughness=0.45),
    "epson_print": dict(color="#1d2f73", metallic=0.0, roughness=0.5),
    "olympus_paint": dict(color="#d2d8d2", metallic=0.0, roughness=0.4),
    "red_plastic": dict(color="#b3150d", metallic=0.0, roughness=0.42),
    "yellow_pla": dict(color="#e6d200", metallic=0.0, roughness=0.5),
    "yellow_abs": dict(color="#f0c800", metallic=0.0, roughness=0.4),
    "tape_white": dict(color="#e4ebec", metallic=0.0, roughness=0.55),
    "tape_blue": dict(color="#6a90cf", metallic=0.0, roughness=0.5),
    "tray_white": dict(color="#dfe3e2", metallic=0.0, roughness=0.55),
    "chip": dict(color="#2c1832", metallic=0.0, roughness=0.3),
    "label_paper": dict(color="#ecece6", metallic=0.0, roughness=0.7),
    "green_anod": dict(color="#2f9a4a", metallic=0.6, roughness=0.35),
    "lens_glass": dict(color="#20262a", metallic=0.0, roughness=0.02),
    "copper": dict(color="#c87a4a", metallic=1.0, roughness=0.35),
    "wire_red": dict(color="#c02020", metallic=0.0, roughness=0.5),
    "wire_blue": dict(color="#2050c0", metallic=0.0, roughness=0.5),
    "wire_green": dict(color="#20a040", metallic=0.0, roughness=0.5),
    "wire_black": dict(color="#101010", metallic=0.0, roughness=0.5),
    "tube_blue": dict(color="#2a62c4", metallic=0.0, roughness=0.25, transmission=0.3),
    "tube_green": dict(color="#3fae7a", metallic=0.0, roughness=0.18, transmission=0.35),
    "blue_anod": dict(color="#1f3f9a", metallic=0.5, roughness=0.35),
    "cable_blue": dict(color="#2a5fc0", metallic=0.0, roughness=0.45),
    "cable_grey": dict(color="#a9aaa6", metallic=0.0, roughness=0.55),
    "cable_black": dict(color="#151515", metallic=0.0, roughness=0.5),
    "wire_red_cable": dict(color="#b8231c", metallic=0.0, roughness=0.45),
    "decal": dict(color="#ffffff", metallic=0.0, roughness=0.6),
    "paint": dict(color="#888888", metallic=0.0, roughness=0.5),
}

# the flat colours scene.py used before materials existed, mapped to a finish
BY_COLOUR = {"#b5b0a3": "stainless_deck", "#bdb39c": "stainless_wall", "#8f8c88": "grey_pvc",
             "#34363a": "black_anodised", "#1e1c1a": "black_plastic", "#d3d8d6": "alu_blasted",
             "#d4dad5": "epson_paint", "#aeb4b2": "epson_grey", "#202020": "black_rubber",
             "#b3150d": "red_plastic", "#e4ebec": "tape_white", "#6a90cf": "tape_blue", "#e6d200": "yellow_pla",
             "#2a62c4": "tube_blue", "#d2d8d2": "olympus_paint", "#c9cfd0": "tray_white", "#3a1f3f": "chip",
             "#c6cacc": "steel_post", "#9ea4a8": "steel_ground", "#c9cdd0": "steel_ground",
             "#0e0e0f": "hole_floor", "#151515": "black_rubber"}


def rgba(hexcol, alpha=1.0, linear=True):
    """Hex sRGB to an RGBA list; glTF's baseColorFactor is linear, so convert unless linear=False."""
    h = hexcol.lstrip("#")
    c = np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])
    if linear:
        c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return [float(x) for x in c] + [float(alpha)]


def for_colour(hexcol):
    return BY_COLOUR.get(hexcol.lower())


_cache = {}


def pbr(key, color=None, image=None):
    """trimesh PBRMaterial for a finish (shared between parts with the same finish and colour)."""
    spec = M[key]
    col = color or spec["color"]
    ck = (key, col, id(image) if image is not None else None)
    if ck not in _cache:
        alpha = spec.get("alpha", 1.0)
        _cache[ck] = trimesh.visual.material.PBRMaterial(
            name=key if color is None or color.lower() == spec["color"] else f"{key}{col.lower()}",
            baseColorFactor=rgba(col, alpha) if image is None else [1.0, 1.0, 1.0, 1.0],
            metallicFactor=spec["metallic"], roughnessFactor=spec["roughness"], baseColorTexture=image,
            alphaMode="BLEND" if alpha < 1 else ("MASK" if image is not None and image.mode == "RGBA" else None),
            alphaCutoff=0.5 if image is not None and image.mode == "RGBA" and alpha >= 1 else None,
            doubleSided=alpha < 1)
    return _cache[ck]


def smooth(mesh, angle_deg=32.0):
    """Split vertices at edges sharper than angle_deg so exported normals are smooth only across curves."""
    try:
        return trimesh.graph.smooth_shade(mesh, angle=np.radians(angle_deg))
    except Exception:
        return mesh
