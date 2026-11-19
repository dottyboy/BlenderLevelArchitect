"""Generate a world and build it in Blender, then render it:
    blender --factory-startup -b -P tools/render_worldgen.py -- out.png [size=2000] [res=4] [seed=7] [skin=""|ink] [view=aerial|ground]"""
import importlib.util, math, os, sys
import bpy
from mathutils import Vector
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("gla", os.path.join(ROOT, "levelArchitect_v2.py"))
gla = importlib.util.module_from_spec(spec); spec.loader.exec_module(gla); gla.register()
args = sys.argv[sys.argv.index("--") + 1:]
out = args[0]
size = float(args[1]) if len(args) > 1 else 2000.0
res = float(args[2]) if len(args) > 2 else 4.0
seed = int(args[3]) if len(args) > 3 else 7
skin = args[4] if len(args) > 4 and args[4] != "none" else ""
view = args[5] if len(args) > 5 else "aerial"
sc = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
w = gla.generate_world(size, res, seed)
built = gla.world_build(bpy.context, w, 64, monuments=True, skin=skin)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam)
if view == "ground":                                              # a road-level view of the first monument
    p = w["monuments"][0]
    cam.location = (p["x"] - 90.0, p["y"] - 150.0, p["z"] + 30.0); tgt = Vector((p["x"], p["y"], p["z"] + 6.0)); cam.data.lens = 28
else:
    cam.location = (0.0, -size * 0.95, size * 0.75); tgt = Vector((0.0, size * 0.05, 0.0)); cam.data.lens = 28
cam.rotation_euler = (tgt - cam.location).to_track_quat('-Z', 'Y').to_euler(); cam.data.clip_end = 20000; sc.camera = cam
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", 'SUN')); sc.collection.objects.link(sun)
sun.rotation_euler = (math.radians(48), 0, math.radians(-35)); sun.data.energy = 3.2
sc.world = bpy.data.worlds.new("w"); sc.world.use_nodes = True
sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.62, 0.74, 0.88, 1) if skin != "ink" else (0.8, 0.81, 0.85, 1)
sc.view_settings.view_transform = 'Standard'
sc.render.resolution_x, sc.render.resolution_y = 1280, 720
sc.render.engine = 'BLENDER_EEVEE'; sc.render.filepath = out
bpy.ops.render.render(write_still=True)
