"""Render a village on a terrain in the ink-on-paper style: blender --factory-startup -b -P tools/render_ink_style.py -- out.png [style]"""
import importlib.util, math, os, sys
import bpy
from mathutils import Vector
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("gla", os.path.join(ROOT, "levelArchitect_v2.py"))
gla = importlib.util.module_from_spec(spec); spec.loader.exec_module(gla); gla.register()
args = sys.argv[sys.argv.index("--") + 1:]
out, style = args[0], (args[1] if len(args) > 1 else "ink")
sc = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
row = gla.plan_node("row", "compound", "yard", footprint=[[-34, -16], [34, -16], [34, 16], [-34, 16]], params={"fence": "auto", "fence_height": 1.6},
                    anchors=[{"id": "gate", "kind": "gate", "pos": [0, -16, 0], "dir": 270, "width": 4}], children=[
    gla.plan_node("house", "building", "house", transform={"x": -24, "y": 0, "z": 0, "rot": 0}),
    gla.plan_node("house2", "building", "house", transform={"x": -12, "y": 0, "z": 0, "rot": 0}, params={"floors": 2}),
    gla.plan_node("chapel", "building", "chapel", transform={"x": 2, "y": 0, "z": 0, "rot": 0}),
    gla.plan_node("stable", "building", "stable", transform={"x": 18, "y": 0, "z": 0, "rot": 0}),
    gla.plan_node("well", "building", "well", transform={"x": 28, "y": -6, "z": 0, "rot": 0}),
    gla.plan_node("tree", "building", "tree", transform={"x": 30, "y": 8, "z": 0, "rot": 0}),
    gla.plan_node("tower", "building", "tower", transform={"x": -30, "y": 10, "z": 0, "rot": 0}, params={"props": False, "lights": False, "interior": False, "height": 8.0})])
land = gla.plan_node("land", "terrain", "terrain", style=style, params={"biome": "meadow", "width": 200.0, "depth": 200.0, "scatter": 1.0}, children=[row])
land["paper"] = os.environ.get("PAPER", "white")
gla.plan_write_to_blend(sc, land); gla.plan_build(bpy.context, land)
if os.environ.get("BLOCKOUT"):
    print("BLOCKOUT", gla.ink_blockout(sc, os.environ.get("PAPER", "white")))
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam)
cam.data.lens = 34; cam.location = (6, -62, 30); tgt = Vector((4, 0, 2))
cam.rotation_euler = (tgt - cam.location).to_track_quat('-Z', 'Y').to_euler(); cam.data.clip_end = 2000; sc.camera = cam
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", 'SUN')); sc.collection.objects.link(sun)
sun.rotation_euler = (math.radians(55), 0, math.radians(-40)); sun.data.energy = 1.7
sc.world = bpy.data.worlds.new("w"); sc.world.use_nodes = True
sc.world.node_tree.nodes["Background"].inputs[0].default_value = tuple(c * 0.9 for c in gla.INK_PAPERS[os.environ.get("PAPER", "white")]) + (1,) if style == "ink" else (0.55, 0.68, 0.85, 1)
sc.world.node_tree.nodes["Background"].inputs[1].default_value = 0.8
sc.view_settings.view_transform = 'Standard'
sc.render.resolution_x, sc.render.resolution_y = 1280, 720
sc.render.engine = 'BLENDER_EEVEE'; sc.render.filepath = out
bpy.ops.render.render(write_still=True)
