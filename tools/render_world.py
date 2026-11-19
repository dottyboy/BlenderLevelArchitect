"""Render a world of terrain chunks: blender --factory-startup -b -P tools/render_world.py -- out.png [biome] [cols] [rows]"""
import importlib.util, math, os, sys
import bpy
from mathutils import Vector
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("gla", os.path.join(ROOT, "levelArchitect_v2.py"))
gla = importlib.util.module_from_spec(spec); spec.loader.exec_module(gla); gla.register()
args = sys.argv[sys.argv.index("--") + 1:]
out = args[0]
biome = args[1] if len(args) > 1 else "meadow"
cols = int(args[2]) if len(args) > 2 else 3
rows = int(args[3]) if len(args) > 3 else 3
sc = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
size = 160.0
root = gla.plan_world("world", biome, (cols, rows), size, 3.0, 11, scatter=0.6)
gla.plan_write_to_blend(sc, root); gla.plan_build(bpy.context, root)
span = max(cols, rows) * size
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam)
cam.data.lens = 30; cam.location = (0, -span * 0.95, span * 0.55); tgt = Vector((0, 0, 0))
cam.rotation_euler = (tgt - cam.location).to_track_quat('-Z', 'Y').to_euler(); cam.data.clip_end = 5000; sc.camera = cam
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", 'SUN')); sc.collection.objects.link(sun)
sun.rotation_euler = (math.radians(50), 0, math.radians(-40)); sun.data.energy = 3.5
sc.world = bpy.data.worlds.new("w"); sc.world.use_nodes = True
sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.68, 0.85, 1)
sc.view_settings.view_transform = 'Standard'
sc.render.resolution_x, sc.render.resolution_y = 1280, 720
sc.render.engine = 'BLENDER_EEVEE'; sc.render.filepath = out
bpy.ops.render.render(write_still=True)
