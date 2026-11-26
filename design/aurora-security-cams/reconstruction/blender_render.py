"""Physically based renders of out/glovebox.glb with Blender's Cycles path tracer (CPU, no GPU needed).

    blender -b --factory-startup -P blender_render.py -- out/glovebox.glb out/blender [views...] \\
        [--samples N] [--scale S]

Views: cam0 and cam1 render a pinhole canvas twice the frame's size (times S, default 0.5) through each
calibrated camera; build_reconstruction.py applies the lens distortion afterwards so the result lines up
with the camera's frame. open_side, far_end, epson, gantry and top render from outside or inside the box,
with the ceiling and the open-side window hidden for the outside views.

The glTF carries each finish as a metallic-roughness material; this script adds what glTF can't: glass
for the windows, a brushed grain for the stainless and machined aluminium, and the room's lighting (a
uniform light-grey room plus two ceiling panels outside the box, as the deck's reflections in Overhead 2
suggest). Written for Blender 4.2 LTS.
"""
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
opts = dict(samples=32, scale=0.5)
pos = []
i = 0
while i < len(argv):
    if argv[i].startswith("--"):
        opts[argv[i][2:]] = float(argv[i + 1])
        i += 2
    else:
        pos.append(argv[i])
        i += 1
GLB, OUT = pos[0], pos[1]
VIEWS = pos[2:] or ["cam0", "cam1", "open_side", "far_end", "epson", "gantry", "top"]
HERE = os.path.dirname(os.path.abspath(__file__))
CAL = json.load(open(os.path.join(HERE, "..", "vision", "out", "cameras.json")))
W, H = 1920, 1080
MM = 0.001

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
# glTF is y-up and the importer turns it z-up; the file holds the chamber frame (z-up, mm) as-is, so undo
# that turn and scale mm to m
fix = Matrix.Scale(MM, 4) @ Matrix.Rotation(math.radians(-90), 4, "X")
for ob in bpy.context.scene.objects:
    if ob.parent is None:
        ob.matrix_world = fix @ ob.matrix_world

BRUSHED = ("stainless_deck", "stainless_wall", "stainless_frame", "stainless_door", "alu_machined")


def principled(mat):
    if not mat.use_nodes:
        return None
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def brushed(mat, bsdf, along="X", scale=900.0, rough=None):
    nt = mat.node_tree
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (2.0, scale, 2.0) if along == "X" else (scale, 2.0, 2.0)
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 3.0
    nz.inputs["Detail"].default_value = 6.0
    cr = nt.nodes.new("ShaderNodeMapRange")
    r0 = bsdf.inputs["Roughness"].default_value if rough is None else rough
    cr.inputs["To Min"].default_value = max(0.05, r0 - 0.12)
    cr.inputs["To Max"].default_value = min(1.0, r0 + 0.12)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], nz.inputs["Vector"])
    nt.links.new(nz.outputs["Fac"], cr.inputs["Value"])
    nt.links.new(cr.outputs["Result"], bsdf.inputs["Roughness"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.04
    nt.links.new(nz.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


for mat in bpy.data.materials:
    b = principled(mat)
    if b is None:
        continue
    name = mat.name.split(".")[0]
    if name.startswith("window"):
        b.inputs["Base Color"].default_value = (0.95, 0.97, 0.97, 1)
        b.inputs["Alpha"].default_value = 1.0
        b.inputs["Transmission Weight"].default_value = 1.0
        b.inputs["Roughness"].default_value = 0.02
        b.inputs["IOR"].default_value = 1.49
    elif name.startswith("tube_blue"):
        b.inputs["Transmission Weight"].default_value = 0.35
    elif name.startswith("lens_glass"):
        b.inputs["Specular IOR Level"].default_value = 1.0
        b.inputs["Coat Weight"].default_value = 1.0
    if any(name.startswith(k) for k in BRUSHED):
        brushed(mat, b)
    if name.startswith(("epson_paint", "olympus_paint", "yellow", "red_plastic", "black_plastic")):
        b.inputs["Coat Weight"].default_value = 0.15
        b.inputs["Coat Roughness"].default_value = 0.3
    if name.startswith("photo"):
        # photo texture (phototexture.py): where the photo covers a surface it already holds the light the
        # camera saw, so most of that colour is emitted as-is and only a share is lit again by the scene;
        # where no camera saw the surface, the part's own finish (metallic-roughness texture) is lit as
        # usual. The photo coverage rides in the metallic-roughness texture's red channel.
        nt = mat.node_tree
        out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
        base_tex = next((l.from_node for l in nt.links if l.to_socket == b.inputs["Base Color"]
                         and l.from_node.type == "TEX_IMAGE"), None)
        sep = next((n for n in nt.nodes if n.type == "SEPARATE_COLOR"), None)
        if base_tex is not None and out is not None:
            em = nt.nodes.new("ShaderNodeEmission")
            nt.links.new(base_tex.outputs["Color"], em.inputs["Color"])
            em.inputs["Strength"].default_value = 1.0
            fac = nt.nodes.new("ShaderNodeMath")
            fac.operation = "MULTIPLY"
            fac.inputs[1].default_value = float(opts.get("photo_emit", 0.7))
            if sep is not None:
                nt.links.new(sep.outputs["Red"], fac.inputs[0])
            else:
                fac.inputs[0].default_value = 1.0
            mix = nt.nodes.new("ShaderNodeMixShader")
            nt.links.new(fac.outputs["Value"], mix.inputs["Fac"])
            nt.links.new(b.outputs["BSDF"], mix.inputs[1])
            nt.links.new(em.outputs["Emission"], mix.inputs[2])
            nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])

# ---- room lighting --------------------------------------------------------------------------------------
scn = bpy.context.scene
world = bpy.data.worlds.new("room")
scn.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs["Color"].default_value = (0.80, 0.78, 0.74, 1)
bg.inputs["Strength"].default_value = float(opts.get("room", 0.55))
for k, (x, y, z, rx) in enumerate(((0.6, -0.9, 2.2, -25.0), (0.6, 2.0, 2.2, 25.0))):
    ld = bpy.data.lights.new(f"ceiling panel {k}", "AREA")
    ld.shape = "RECTANGLE"
    ld.size, ld.size_y = 1.2, 0.6
    ld.energy = float(opts.get("panel_w", 220.0))
    ld.color = (1.0, 0.97, 0.92)
    lo = bpy.data.objects.new(f"ceiling panel {k}", ld)
    lo.location = (x, y, z)
    lo.rotation_euler = (math.radians(rx), 0, 0)
    scn.collection.objects.link(lo)

# light that reaches the interior through the ceiling's fittings and the sloped windows, as one soft
# panel just under the ceiling (the frames show the deck and the robot's top lit from above)
ld = bpy.data.lights.new("interior fill", "AREA")
ld.shape = "RECTANGLE"
ld.size, ld.size_y = 1.0, 0.8
ld.energy = float(opts.get("fill_w", 20.0))
ld.color = (1.0, 0.98, 0.95)
lo = bpy.data.objects.new("interior fill", ld)
lo.location = (0.62, 0.56, 0.775)
scn.collection.objects.link(lo)

scn.render.engine = "CYCLES"
scn.cycles.device = "CPU"
scn.cycles.samples = int(opts["samples"])
scn.cycles.use_adaptive_sampling = True
scn.cycles.adaptive_threshold = 0.04
scn.cycles.use_denoising = True
scn.cycles.denoiser = "OPENIMAGEDENOISE"
scn.cycles.max_bounces = 5
scn.cycles.diffuse_bounces = 2
scn.cycles.glossy_bounces = 3
scn.cycles.transmission_bounces = 4
scn.cycles.sample_clamp_indirect = 4.0
scn.cycles.caustics_reflective = False
scn.cycles.caustics_refractive = False
scn.render.threads_mode = "AUTO"
scn.view_settings.view_transform = "Standard"
scn.view_settings.look = "None"
scn.view_settings.exposure = float(opts.get("exposure", 0.0))
scn.render.image_settings.file_format = "PNG"
scn.render.film_transparent = False

cam_data = bpy.data.cameras.new("cam")
cam_ob = bpy.data.objects.new("cam", cam_data)
scn.collection.objects.link(cam_ob)
scn.camera = cam_ob

HIDE_OUTSIDE = ("ceiling", "open side")
# robot parts by the link that carries them (object names start with these), for posing the robot
ROBOT_GROUPS = dict(arm1=("Epson arm1", "Epson cable"),
                    arm2=("Epson arm2", "EPSON wordmarks, arm 2", "black unit on arm 2", "end effector: shaft collar",
                          "Epson tubing"),
                    shaft=("Epson shaft", "end effector: body", "end effector: tubing", "end effector: parallel",
                           "end effector: finger"))


def set_hidden(names):
    for ob in scn.objects:
        if ob.type == "MESH":
            ob.hide_render = any(k in ob.name for k in names)


def look_at(pos, target, up=(0, 0, 1)):
    p, t = Vector(pos) * MM, Vector(target) * MM
    f = (t - p).normalized()
    r = f.cross(Vector(up)).normalized()
    u = r.cross(f)
    M = Matrix((r, u, -f)).transposed().to_4x4()
    M.translation = p
    return M


def render(path, M, lens_mm=None, fov_deg=None, res=(1920, 1080), hide=(), exposure=0.0):
    set_hidden(hide)
    scn.view_settings.exposure = float(opts.get("exposure", 0.0)) + exposure
    cam_ob.matrix_world = M
    cam_data.sensor_fit = "HORIZONTAL"
    cam_data.sensor_width = 36.0
    cam_data.clip_start, cam_data.clip_end = 0.02, 20.0
    if lens_mm:
        cam_data.lens = lens_mm
    else:
        cam_data.angle = math.radians(fov_deg)
    scn.render.resolution_x, scn.render.resolution_y = res
    scn.render.resolution_percentage = 100
    scn.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print("wrote", path, flush=True)


os.makedirs(OUT, exist_ok=True)
s = float(opts["scale"])
for v in VIEWS:
    if v in ("cam0", "cam1"):
        c = CAL["cameras"][v]
        R = [Vector(row) for row in c["R"]]
        t = Vector(c["t"])
        centre = -(Matrix(c["R"]).transposed() @ t)
        M = Matrix((R[0], -R[1], -R[2])).transposed().to_4x4()
        M.translation = centre * MM
        cw, ch = int(round(2 * W * s)), int(round(2 * H * s))
        render(os.path.join(OUT, f"{v}_pinhole.png"), M, lens_mm=CAL["f_px"] * 36.0 / (2 * W), res=(cw, ch),
               hide=(f"Amcrest camera {v}",), exposure=float(opts.get("cam_exposure", 0.3)))
    elif v == "open_side":
        render(os.path.join(OUT, "open_side.png"), look_at((560, -1350, 1250), (640, 560, 230)), fov_deg=40,
               res=(1600, 1000), hide=HIDE_OUTSIDE)
    elif v == "far_end":
        render(os.path.join(OUT, "far_end.png"), look_at((2350, 300, 1150), (620, 560, 230)), fov_deg=38,
               res=(1600, 1000), hide=HIDE_OUTSIDE + ("far-end",))
    elif v == "epson":
        render(os.path.join(OUT, "epson.png"), look_at((470, 250, 700), (1000, 640, 300)), fov_deg=58,
               res=(1600, 1000), hide=("ceiling",), exposure=-1.0)
    elif v == "gantry":
        render(os.path.join(OUT, "gantry.png"), look_at((900, 150, 620), (470, 430, 230)), fov_deg=58,
               res=(1600, 1000), hide=("ceiling",), exposure=-0.8)
    elif v == "top":
        render(os.path.join(OUT, "top.png"), look_at((600, 560, 3000), (600, 560, 0), up=(1, 0, 0)), fov_deg=30,
               res=(1600, 1600), hide=HIDE_OUTSIDE + ("far side",), exposure=-1.2)
    elif v.startswith("video_"):
        # a frame of the AURORA video, registered by video_register.py: pinhole at the shot's focal
        # length on a canvas 1.25 x the frame; build_reconstruction.py applies the radial term. The
        # robot is moved to its pose in that frame (out/video_robot_poses.json) and back afterwards.
        _, shot, kf = v.split("_")
        vc = json.load(open(os.path.join(HERE, "out", "video_cameras.json")))["shots"][shot]
        fr = vc["frames"][kf]
        R = [Vector(row) for row in fr["R"]]
        M = Matrix((R[0], -R[1], -R[2])).transposed().to_4x4()
        M.translation = Vector(fr["centre"]) * MM
        cw, ch = int(round(1.25 * W * s)), int(round(1.25 * H * s))
        saved = {}
        rp = os.path.join(HERE, "out", "video_robot_poses.json")
        deltas = json.load(open(rp)).get(v, {}).get("deltas", {}) if os.path.exists(rp) else {}
        S = Matrix.Scale(MM, 4)
        for g, D in deltas.items():
            Dm = S @ Matrix(D) @ S.inverted()
            for ob in scn.objects:
                base = ob.name.split(" ", 1)[1] if ob.name[:3].isdigit() else ob.name   # nodes are "NNN name"
                if ob.type == "MESH" and any(base.startswith(k) for k in ROBOT_GROUPS[g]):
                    saved[ob.name] = ob.matrix_world.copy()
                    ob.matrix_world = Dm @ ob.matrix_world
        render(os.path.join(OUT, f"{v}_pinhole.png"), M, lens_mm=vc["f_px"] * 36.0 / (1.25 * W), res=(cw, ch),
               hide=("open side",), exposure=float(opts.get("video_exposure", 0.0)))
        for name, mw in saved.items():
            scn.objects[name].matrix_world = mw
