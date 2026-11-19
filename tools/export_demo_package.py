"""Builds the demo tile map (docs/examples/tilemap_demo.png with its tileset) and exports its game package into the Godot demo project:

    blender --factory-startup -b -P tools/export_demo_package.py
"""
import importlib.util, os
import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("gla", os.path.join(ROOT, "levelArchitect_v2.py"))
gla = importlib.util.module_from_spec(spec); spec.loader.exec_module(gla); gla.register()
sc = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
ex = os.path.join(ROOT, "docs", "examples")
root = gla.plan_from_tilemap_picture(os.path.join(ex, "tilemap_demo.png"), "demo", 16, 1.0,
                                     tileset={"image": os.path.join(ex, "tileset_demo.png"), "json": os.path.join(ex, "tileset_demo.json")})
gla.plan_write_to_blend(sc, root); gla.plan_build(bpy.context, root)
bpy.context.view_layer.objects.active = next(o for o in bpy.data.objects if "gla_tilemap" in o.keys())
out = os.path.join(ROOT, "examples", "godot_tilemap_demo", "level", "demo.glb")
print("EXPORT", bpy.ops.object.export_tilemap_package(filepath=out))
