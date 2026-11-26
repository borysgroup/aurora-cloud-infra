"""Teknic ClearPath CPM NEMA 23 integrated servo (the pin-fin unit with the QR label on the exfoliator),
from Teknic's own STEP.

Teknic publishes the CAD without a login at https://teknic.com/files/downloads/CPM-231x.zip (66 MB:
STEP, IGES, Parasolid and eDrawings for the keyed "-Q" and "-LS" shafts, the 231x stack length). The
dimensional drawing is https://teknic.com/files/downloads/23xx%20CPM%20Dimensional%20Drawing.pdf:
59.1 mm square flange, ø38.10 mm pilot, 4 x ø5.2 mm holes on a 66.67 mm circle, ø9.53 x 20.57 mm keyed
shaft. The stack length (231x) is an assumption: the stills don't show the motor's length.

    python clearpath_cad.py      # download once, mesh into ~/.cache/aurora-teknic-cpm23/cpm23.stl

The STEP and the mesh are fetched at build time and not redistributed here.
"""
import io
import os
import urllib.request
import zipfile

import numpy as np
import trimesh

URL = "https://teknic.com/files/downloads/CPM-231x.zip"
CACHE = os.environ.get("TEKNIC_CAD_CACHE", os.path.expanduser("~/.cache/aurora-teknic-cpm23"))


def fetch(cache=CACHE, faces=60000):
    os.makedirs(cache, exist_ok=True)
    stl = os.path.join(cache, "cpm23.stl")
    if os.path.exists(stl):
        return stl
    step = os.path.join(cache, "cpm231x_q.step")
    if not os.path.exists(step):
        zf = os.path.join(cache, "CPM-231x.zip")
        if not os.path.exists(zf):
            urllib.request.urlretrieve(URL, zf)
        z = zipfile.ZipFile(zf)
        name = next(n for n in z.namelist() if n.endswith("-Q.STEP"))
        open(step, "wb").write(z.read(name))
    import gmsh
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.occ.importShapes(step)
    gmsh.model.occ.synchronize()
    for k, v in (("Mesh.MeshSizeMin", 0.3), ("Mesh.MeshSizeMax", 6.0), ("Mesh.MeshSizeFromCurvature", 12),
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
    if len(m.faces) > faces:
        m = m.simplify_quadric_decimation(face_count=faces)
    m.export(stl)
    return stl


def mesh(cache=CACHE):
    return trimesh.load(fetch(cache))


if __name__ == "__main__":
    m = mesh()
    print(len(m.faces), np.round(m.bounds, 2).tolist(), np.round(m.extents, 2).tolist())
