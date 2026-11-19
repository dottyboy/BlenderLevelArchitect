"""Render a tile map as a 3D level: blender --factory-startup -b -P tools/render_tilemap.py -- <map.png> <out.png> [tile] [tile_m]"""
import importlib.util, math, os, sys
import bpy
from mathutils import Vector
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("gla", os.path.join(ROOT, "levelArchitect_v2.py"))
gla = importlib.util.module_from_spec(spec); spec.loader.exec_module(gla); gla.register()
args = sys.argv[sys.argv.index("--") + 1:]
img, out = args[0], args[1]
tile = int(args[2]) if len(args) > 2 else 16
tm = float(args[3]) if len(args) > 3 else 1.0
sc = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)                                  # the default cube, camera and light
extra = {}
ts = os.environ.get("TILESET")
if ts:
    extra["tileset"] = {"image": ts, "json": os.path.splitext(ts)[0] + ".json"}
root = gla.plan_from_tilemap_picture(img, "tilemap", tile, tm, **extra)
gla.plan_write_to_blend(sc, root); gla.plan_build(bpy.context, root)
w, d = gla.tilemap_size(root["params"])
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam)
cam.data.lens = 38
cam.location = (w * 0.08, -d * 0.82, max(w, d) * 0.62); tgt = Vector((0, 0, 0))
cam.rotation_euler = (tgt - cam.location).to_track_quat('-Z', 'Y').to_euler(); cam.data.clip_end = 5000; sc.camera = cam
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", 'SUN')); sc.collection.objects.link(sun)
sun.rotation_euler = (math.radians(55), 0, math.radians(-40)); sun.data.energy = 3.0
sc.world = bpy.data.worlds.new("w"); sc.world.use_nodes = True
sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.68, 0.85, 1)
sc.render.resolution_x, sc.render.resolution_y = 1280, 800
sc.view_settings.view_transform = 'Standard'
sc.render.engine = 'BLENDER_EEVEE'; sc.render.filepath = out
bpy.ops.render.render(write_still=True)
