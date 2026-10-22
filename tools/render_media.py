"""Renders the stills and animation frames used by README.md / docs/ (run inside Blender, background mode):

    blender --background --factory-startup --python tools/render_media.py -- <job> <out_dir> [quality]

Jobs: castle_still, castle_turntable, ruin_slider, tint_cycle, tower_trio, tower_cutaway, hall_cutaway,
      level_still, round_rooms_still, seeds_gallery
quality: draft (default, 16 samples) or final (64 samples).
The frames land as PNGs; tools/make_gif.sh turns a frame folder into a GIF with ffmpeg.
"""
import importlib.util
import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("la", os.path.join(ROOT, "levelArchitect_v2.py"))
la = importlib.util.module_from_spec(spec)
spec.loader.exec_module(la)
la.register()
sc = bpy.context.scene
args = sys.argv[sys.argv.index("--") + 1:]
JOB, OUT = args[0], args[1]
QUALITY = args[2] if len(args) > 2 else "draft"
os.makedirs(OUT, exist_ok=True)


def clear_scene():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)


def setup_render(w, h):
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = 64 if QUALITY == "final" else 16
    sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = 'PNG'


def world_and_sun(sky=(0.55, 0.62, 0.74), sun=4.2, ground=(0.17, 0.21, 0.12), ground_size=200):
    sc.world = bpy.data.worlds.new("w")
    sc.world.use_nodes = True
    sc.world.node_tree.nodes['Background'].inputs[0].default_value = (*sky, 1)
    light = bpy.data.lights.new("sun", 'SUN')
    light.energy = sun
    lo = bpy.data.objects.new("sun", light)
    sc.collection.objects.link(lo)
    lo.rotation_euler = (math.radians(52), math.radians(8), math.radians(-35))
    if ground:
        bpy.ops.mesh.primitive_plane_add(size=ground_size, location=(0, 0, -0.03))
        g = bpy.context.object
        m = bpy.data.materials.new("g")
        m.use_nodes = True
        m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (*ground, 1)
        m.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 1.0
        g.data.materials.append(m)


def camera(loc, target, lens=32):
    cam = bpy.data.cameras.new("c")
    cam.lens = lens
    co = bpy.data.objects.new("c", cam)
    sc.collection.objects.link(co)
    co.location = loc
    co.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat('-Z', 'Y').to_euler()
    sc.camera = co
    return co


def orbit(center, radius, height, angle):
    return (center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle), height)


def render(name):
    sc.render.filepath = os.path.join(OUT, name + ".png")
    bpy.ops.render.render(write_still=True)


def make_castle(ruin=0.0, color='PLAIN', seed=3, loc=(0, 0, 0)):
    sc.wfc_seed = seed
    sc.wfc_castle_ruin = ruin
    sc.wfc_castle_brick_color = color
    sc.cursor.location = loc
    bpy.ops.object.generate_level_castle()


def make_tower(ruin=0.0, color='PLAIN', loc=(0, 0, 0), height=11.0, windows=2, props=False, lights=False):
    sc.wfc_seed = 4
    sc.wfc_tower_ruin = ruin
    sc.wfc_tower_brick_color = color
    sc.wfc_tower_height = height
    sc.wfc_tower_windows = windows
    sc.wfc_tower_props = props
    sc.wfc_tower_lights = lights
    sc.cursor.location = loc
    bpy.ops.object.generate_level_tower()
    obj = bpy.data.objects[la.TOWER_OBJECT_NAME]
    obj.name = "T_%d" % len([o for o in bpy.data.objects if o.name.startswith("T_")])
    return obj


def bisect(obj, plane_co, plane_no):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=plane_co, plane_no=plane_no, clear_inner=True)
    bm.to_mesh(obj.data)
    bm.free()


def level(seed, shape='MIXED', rooms=(6, 8), size=(16, 16), props='MIXED', windows=0.3):
    for k, v in dict(
        wfc_width=size[0], wfc_length=size[1], wfc_height=1, wfc_rooms_min=rooms[0], wfc_rooms_max=rooms[1],
        wfc_room_size_min=3, wfc_room_size_max=6, wfc_room_shape=shape, wfc_sub_levels_per_floor=1,
        wfc_level_height=4.0, wfc_tile_size=2.0, wfc_wall_height=3.0, wfc_wall_thickness=0.3, wfc_door_style='ROUND',
        wfc_door_height=2.3, wfc_torch_chance=0.35, wfc_prop_chance=0.22, wfc_prop_theme=props, wfc_random_seed=False,
        wfc_seed=seed, wfc_iso_mode=False, wfc_add_ceiling=False, wfc_window_chance=windows, wfc_window_sill=1.1,
        wfc_wall_style='MASONRY', wfc_round_wall_style='MASONRY', wfc_masonry_room_colors=True,
    ).items():
        setattr(sc, k, v)
    for op in (bpy.ops.object.generate_game_blueprint, bpy.ops.object.generate_level_walls,
               bpy.ops.object.generate_level_doors, bpy.ops.object.generate_level_props):
        op()


# ------------------------------------------------------------------ jobs
if JOB in ("castle_still", "castle_turntable", "ruin_slider", "tint_cycle"):
    setup_render(1280, 720) if JOB == "castle_still" else setup_render(640, 360)
    clear_scene()
    if JOB == "castle_still":
        make_castle(0.0, 'MIXED')
        world_and_sun()
        camera((20, -40, 22), (0, 0, 4))
        render("castle_intact")
        for o in list(bpy.data.objects):
            if o.name.startswith(la.CASTLE_OBJECT_NAME) or o.name.startswith(la.HALL_PROPS_OBJECT_NAME):
                bpy.data.objects.remove(o, do_unlink=True)
        make_castle(0.6, 'PLAIN', seed=5)
        render("castle_ruin")
    elif JOB == "castle_turntable":
        make_castle(0.0, 'MIXED')
        world_and_sun()
        cam = camera((0, 0, 0), (0, 0, 4))
        n = 48
        for i in range(n):
            cam.location = orbit((0, 0), 46, 23, math.radians(-90 + 360 * i / n))
            cam.rotation_euler = (Vector((0, 0, 4)) - cam.location).to_track_quat('-Z', 'Y').to_euler()
            render("f%03d" % i)
    elif JOB == "ruin_slider":
        world_and_sun(ground_size=60)
        camera((9, -15, 8), (0, 0, 4.5), lens=38)
        steps = [i / 10.0 for i in range(11)]
        for i, r in enumerate(steps + steps[-2:0:-1]):
            for o in list(bpy.data.objects):
                if o.name.startswith("T_") or o.name.startswith("Procedural_Level"):
                    bpy.data.objects.remove(o, do_unlink=True)
            make_tower(r, 'PLAIN', props=False, lights=False)
            render("f%03d" % i)
    else:  # tint_cycle
        world_and_sun(ground_size=60)
        camera((9, -15, 8), (0, 0, 4.5), lens=38)
        for i, c in enumerate(['PLAIN', 'OCHRE', 'SLATE', 'MOSS', 'ROSE', 'UMBER', 'SAND']):
            for o in list(bpy.data.objects):
                if o.name.startswith("T_") or o.name.startswith("Procedural_Level"):
                    bpy.data.objects.remove(o, do_unlink=True)
            make_tower(0.0, c)
            render("f%03d" % i)
elif JOB == "tower_trio":
    setup_render(1280, 720)
    clear_scene()
    world_and_sun()
    for i, r in enumerate((0.3, 0.6, 1.0)):
        make_tower(r, ('OCHRE', 'PLAIN', 'SLATE')[i], loc=((i - 1) * 10.5, 0, 0))
    camera((0, -30, 10), (0, 0, 4.8), lens=34)
    render("tower_ruins")
elif JOB == "tower_cutaway":
    setup_render(1000, 1000)
    clear_scene()
    world_and_sun(ground_size=80)
    t = make_tower(0.0, 'PLAIN', height=13.0, windows=2, props=True, lights=False)
    bisect(t, (0, 0, 0), (0, 1, 0))
    camera((5, -17, 9), (0, 0, 6.0), lens=32)
    render("tower_interior")
elif JOB == "hall_cutaway":
    setup_render(1280, 720)
    clear_scene()
    sc.wfc_castle_hall_props = True
    make_castle(0.0, 'PLAIN')
    world_and_sun()
    c = bpy.data.objects[la.CASTLE_OBJECT_NAME]
    bisect(c, (0, 2.4, 0), (0, 1, 0))     # keep removed south of its centre line: the hall is open to the camera
    camera((6, -12, 11), (0, 2.4, 1.6), lens=30)
    render("keep_hall")
elif JOB in ("level_still", "round_rooms_still"):
    setup_render(1280, 720)
    clear_scene()
    if JOB == "level_still":
        level(11, 'MIXED', (7, 9), (18, 18), 'MIXED', 0.35)
        mid = sc.wfc_tile_size * sc.wfc_width / 2
        world_and_sun(ground=None)
        camera((mid, mid - 26, 30), (mid, mid - 2, 0), lens=34)
        render("generated_level")
    else:
        level(5, 'ROUND', (4, 5), (14, 14), 'LIBRARY', 0.0)
        mid = sc.wfc_tile_size * sc.wfc_width / 2
        world_and_sun(ground=None)
        camera((mid, mid - 15, 17), (mid, mid, 0), lens=32)
        render("round_rooms")
elif JOB == "seeds_gallery":
    setup_render(640, 400)
    clear_scene()
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.display.shading.light = 'STUDIO'
    sc.display.shading.color_type = 'MATERIAL'
    for i, seed in enumerate((3, 5, 7, 11, 14, 21, 33, 44)):
        for o in list(bpy.data.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        level(seed, 'MIXED', (6, 8), (16, 16), 'MIXED', 0.3)
        mid = sc.wfc_tile_size * sc.wfc_width / 2
        camera((mid, mid - 24, 36), (mid, mid, 0), lens=34)
        render("f%03d" % i)
else:
    raise SystemExit("unknown job " + JOB)
