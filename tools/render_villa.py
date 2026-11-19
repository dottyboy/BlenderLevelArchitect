"""Render docs/img/villa.png: a generated villa (U-shaped plan).

    blender --factory-startup -b -P tools/render_villa.py
"""
import importlib.util, math, os
import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("gla", os.path.join(ROOT, "levelArchitect_v2.py"))
gla = importlib.util.module_from_spec(spec); spec.loader.exec_module(gla); gla.register()
sc = bpy.context.scene
node = gla.plan_node("villa", "building", "mansion", params={"plan": "random", "plan_shape": "U", "plan_seed": 7, "floors": 2, "wing": 36.0})
gla.plan_write_to_blend(sc, node)
gla.plan_build(bpy.context, node)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam)
cam.data.lens = 28; cam.location = (48, -98, 64); tgt = Vector((0, 4, 3))
cam.rotation_euler = (tgt - cam.location).to_track_quat('-Z', 'Y').to_euler(); cam.data.clip_end = 600; sc.camera = cam
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", 'SUN')); sc.collection.objects.link(sun)
sun.rotation_euler = (math.radians(50), 0, math.radians(-35)); sun.data.energy = 3.0
sc.world = bpy.data.worlds.new("w"); sc.world.use_nodes = True
sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.62, 0.72, 0.85, 1)
sc.render.resolution_x, sc.render.resolution_y = 1280, 800
sc.render.engine = 'BLENDER_EEVEE'
sc.render.filepath = os.path.join(ROOT, "docs", "img", "villa.png")
bpy.ops.render.render(write_still=True)
