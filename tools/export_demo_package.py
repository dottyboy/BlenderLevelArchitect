"""Builds a demo tile map and exports its game package into the Godot demo project:

    blender --factory-startup -b -P tools/export_demo_package.py            # the colour demo (docs/examples/tilemap_demo.png) -> level/demo.glb + .json
    blender --factory-startup -b -P tools/export_demo_package.py -- ink     # the ink dungeon (docs/examples/ink_map.png) -> level/ink.glb + .json
"""
import importlib.util, os, sys
import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("gla", os.path.join(ROOT, "levelArchitect_v2.py"))
gla = importlib.util.module_from_spec(spec); spec.loader.exec_module(gla); gla.register()
sc = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
ex = os.path.join(ROOT, "docs", "examples")
which = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else "demo"
if which == "ink":
    pic, sheet, js = "ink_map.png", "ink_tileset.png", "ink_tileset.json"
else:
    pic, sheet, js = "tilemap_demo.png", "tileset_demo.png", "tileset_demo.json"
root = gla.plan_from_tilemap_picture(os.path.join(ex, pic), which, 16, 1.0, tileset={"image": os.path.join(ex, sheet), "json": os.path.join(ex, js)})
gla.plan_write_to_blend(sc, root); gla.plan_build(bpy.context, root)
bpy.context.view_layer.objects.active = next(o for o in bpy.data.objects if "gla_tilemap" in o.keys())
out = os.path.join(ROOT, "examples", "godot_tilemap_demo", "level", which + ".glb")
print("EXPORT", bpy.ops.object.export_tilemap_package(filepath=out))
