"""Render one terrain biome: blender --factory-startup -b -P tools/render_terrain.py -- <biome> <out.png> [aerial]"""
import importlib.util, math, os, sys
import bpy
from mathutils import Vector
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("gla", os.path.join(ROOT, "levelArchitect_v2.py"))
gla = importlib.util.module_from_spec(spec); spec.loader.exec_module(gla); gla.register()
args = sys.argv[sys.argv.index("--") + 1:]
biome, out = args[0], args[1]
sc = bpy.context.scene
node = gla.plan_node("land", "terrain", "terrain", params={"biome": biome, "width": 240.0, "depth": 240.0, "scatter": 1.0})
gla.plan_write_to_blend(sc, node); gla.plan_build(bpy.context, node)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam)
cam.data.lens = 30
cam.location, tgt = ((0, -190, 120), Vector((0, 10, 0))) if "aerial" in args else ((10, -20, 5.5), Vector((10, 5, 1.5))) if "close" in args else ((0, -150, 45), Vector((0, 10, 0)))
cam.rotation_euler = (tgt - cam.location).to_track_quat('-Z', 'Y').to_euler(); cam.data.clip_end = 2000; sc.camera = cam
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", 'SUN')); sc.collection.objects.link(sun)
sun.rotation_euler = (math.radians(55), 0, math.radians(-40)); sun.data.energy = 3.5
sc.world = bpy.data.worlds.new("w"); sc.world.use_nodes = True
sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.68, 0.85, 1)
sc.render.resolution_x, sc.render.resolution_y = 1280, 720
sc.render.engine = 'BLENDER_EEVEE'; sc.render.filepath = out
bpy.ops.render.render(write_still=True)
