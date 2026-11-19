"""Render docs/img/house_open.png from docs/examples/house_floorplan.png.

    blender --factory-startup -b -P tools/render_house.py
"""
import importlib.util, json, math, os, sys
import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("gla", os.path.join(ROOT, "levelArchitect_v2.py"))
gla = importlib.util.module_from_spec(spec); spec.loader.exec_module(gla); gla.register()
PIC = os.path.join(ROOT, "docs", "examples", "house_floorplan.png")


def render(roof, cam_loc, tgt, name):
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    sc = bpy.context.scene
    root = gla.plan_from_floorplan_picture(PIC, "house", None, 13.0, (), (2.7,))
    root["params"]["roof"] = roof
    gla.plan_write_to_blend(sc, root)
    gla.plan_build(bpy.context, root)
    obj = [o for o in bpy.data.objects if "gla_walk_layout" in o.keys()][0]
    print("WALK", gla.floor_plan_walk_check(json.loads(obj["gla_walk_layout"])))
    bpy.ops.mesh.primitive_plane_add(size=120, location=(0, 0, -0.21))
    gm = bpy.data.materials.new("grass"); gm.diffuse_color = (0.30, 0.45, 0.22, 1); bpy.context.object.data.materials.append(gm)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam)
    cam.data.lens = 30; cam.location = cam_loc
    cam.rotation_euler = (tgt - cam.location).to_track_quat('-Z', 'Y').to_euler(); cam.data.clip_end = 500; sc.camera = cam
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", 'SUN')); sc.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(50), 0, math.radians(-35)); sun.data.energy = 3.0
    sc.world = bpy.data.worlds.new("w"); sc.world.use_nodes = True
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.62, 0.72, 0.85, 1)
    sc.render.resolution_x, sc.render.resolution_y = 1280, 800
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.filepath = os.path.join(ROOT, "docs", "img", name)
    bpy.ops.render.render(write_still=True)


render(False, Vector((3.5, -10.5, 14.5)), Vector((0, 0.4, 0.5)), "house_open.png")
