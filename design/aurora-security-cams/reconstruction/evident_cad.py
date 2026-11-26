"""Evident (Olympus) BX3 microscope modules from Evident's own CAD: the BX3-URA reflected-light
illuminator, the U-DP dual port and the U-TLU tube lens unit.

Evident publishes these as "appearance model only" STEP files, one per ZIP, without a login (its OEM
downloads page, https://evidentscientific.com/en/downloads/oem):

    https://adobeassets.evidentscientific.com/content/dam/mis/3d-objectives/BX3-URA.zip
    https://adobeassets.evidentscientific.com/content/dam/mis/3d-objectives/U-DP.zip
    https://adobeassets.evidentscientific.com/content/dam/mis/3d-objectives/U-TLU.zip

`fetch()` downloads them once into a cache directory and meshes each with gmsh. The files are not
redistributed here (the exported glTF and STL hold a tessellation, as they do for Epson's and Teknic's
CAD).

Frames (read off the STEP files): all three are in mm with the optical axis vertical (z). The BX3-URA's
axis is at x = y = 0, its body spans z = 75.9 to 164.7 mm, the filter drum reaches 149 mm towards -y and
the lamp end 261 mm towards +y. The U-DP's axis is at x = y = 0 (z = 0 to 63 mm); the U-TLU's at
x = y = 70 mm (z = 0 to 63.6 mm). A thin 122 x 100 x 3 mm plate in the BX3-URA file, 250 mm from the axis
below the body, is not part of the module and is left out.

    python evident_cad.py      # download, mesh and print each module's bounds
"""
import io
import os
import urllib.request
import zipfile

import numpy as np
import trimesh

BASE = "https://adobeassets.evidentscientific.com/content/dam/mis/3d-objectives/"
MODULES = ("BX3-URA", "U-DP", "U-TLU")
CACHE = os.environ.get("EVIDENT_CAD_CACHE", os.path.expanduser("~/.cache/aurora-evident-bx3"))
AXIS = {"BX3-URA": (0.0, 0.0), "U-DP": (0.0, 0.0), "U-TLU": (70.0, 70.0)}
URA_BODY_Z = (75.9, 164.7)
FACES = {"BX3-URA": 120000, "U-DP": 30000, "U-TLU": 15000}


def fetch(cache=CACHE):
    """Download and mesh each module into cache/<module>.stl (STEP frame, mm). Returns the cache path."""
    os.makedirs(cache, exist_ok=True)
    for mod in MODULES:
        stl = os.path.join(cache, f"{mod}.stl")
        if os.path.exists(stl):
            continue
        step = os.path.join(cache, f"{mod}.stp")
        if not os.path.exists(step):
            data = urllib.request.urlopen(BASE + f"{mod}.zip", timeout=120).read()
            z = zipfile.ZipFile(io.BytesIO(data))
            name = next(n for n in z.namelist() if n.lower().endswith((".stp", ".step")))
            open(step, "wb").write(z.read(name))
        _mesh(step, stl, FACES[mod], drop_far=(mod == "BX3-URA"))
    return cache


def _mesh(step, stl, faces, drop_far=False):
    import gmsh
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.occ.importShapes(step)
    gmsh.model.occ.synchronize()
    if drop_far:
        for d, t in gmsh.model.getEntities(3):
            b = gmsh.model.getBoundingBox(d, t)
            if b[5] < 0.0:                       # the stray plate below the BX3-URA
                gmsh.model.removeEntities([(d, t)], recursive=True)
    for k, v in (("Mesh.MeshSizeMin", 0.3), ("Mesh.MeshSizeMax", 6.0), ("Mesh.MeshSizeFromCurvature", 16),
                 ("Mesh.Algorithm", 6)):
        gmsh.option.setNumber(k, v)
    gmsh.model.mesh.generate(2)
    nt, nc, _ = gmsh.model.mesh.getNodes()
    tags = np.asarray(nt, np.int64)
    lut = np.zeros(tags.max() + 1, np.int64)
    lut[tags] = np.arange(len(tags))
    V = np.asarray(nc).reshape(-1, 3)
    F = []
    for typ, conn in zip(*gmsh.model.mesh.getElements(2)[::2]):
        if typ == 2:
            F.append(lut[np.asarray(conn, np.int64).reshape(-1, 3)])
    gmsh.finalize()
    m = trimesh.Trimesh(V, np.vstack(F), process=True)
    m.merge_vertices()
    m.remove_unreferenced_vertices()
    if len(m.faces) > faces:
        m = m.simplify_quadric_decimation(face_count=faces)
    m.export(stl)


def meshes(cache=CACHE):
    fetch(cache)
    return {mod: trimesh.load(os.path.join(cache, f"{mod}.stl")) for mod in MODULES}


YAW = {"BX3-URA": 180.0, "U-DP": 270.0, "U-TLU": 0.0}


def stack(ox, oy, z_mount, yaw=None):
    """The three modules stacked on the optical axis at (ox, oy): the BX3-URA's body underside at z_mount,
    the U-DP on its top, the U-TLU on the U-DP. yaw (degrees about the axis, per module): the BX3-URA at
    180 puts its filter drum towards +y and the lamp end towards -y; the U-DP at 270 matches its outline in
    Overhead 1 best of the four quarter turns. Returns ({module: mesh}, top z)."""
    M = meshes()
    yaw = dict(YAW, **(yaw or {}))
    out = {}
    z = z_mount
    for mod in MODULES:
        R = trimesh.transformations.rotation_matrix(np.radians(yaw[mod]), (0, 0, 1))
        m = M[mod].copy()
        ax = AXIS[mod]
        z0 = URA_BODY_Z[0] if mod == "BX3-URA" else m.bounds[0][2]
        m.apply_translation((-ax[0], -ax[1], -z0))
        m.apply_transform(R)
        m.apply_translation((ox, oy, z))
        out[mod] = m
        z = z + ((URA_BODY_Z[1] - URA_BODY_Z[0]) if mod == "BX3-URA" else (M[mod].bounds[1][2] - M[mod].bounds[0][2]))
    return out, z


if __name__ == "__main__":
    for k, m in meshes().items():
        print(k, len(m.faces), np.round(m.bounds, 1).tolist())
