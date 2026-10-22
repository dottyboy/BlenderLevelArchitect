"""Renders the stills and animation frames used by README.md / docs/ (run inside Blender, background mode):

    blender --background --factory-startup --python tools/render_media.py -- <job> <out_dir> [quality]

Jobs: castle_still, castle_turntable, ruin_slider, tint_cycle, tower_trio, tower_cutaway, hall_cutaway,
      level_still, round_rooms_still, seeds_gallery, houses_still, grounds_still, fortress_still, fortress_turntable, block_still, farm_still,
      styles_still, hutforms_still, organic_still, roundtown_still, mixed_still, hutcluster_still, biomes_still, townland_still
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
elif JOB in ("houses_still", "grounds_still", "fortress_still", "fortress_turntable", "block_still", "farm_still"):
    setup_render(1280, 720) if JOB.endswith("_still") else setup_render(640, 360)
    clear_scene()
    world_and_sun()
    sc.cursor.location = (0, 0, 0)
    if JOB == "houses_still":
        row = la.plan_node("row", "compound", "yard", footprint=[[-40, -20], [40, -20], [40, 20], [-40, 20]], children=[
            la.plan_node("house", "building", "house", transform={"x": -22, "y": 0, "z": 0, "rot": 0}, params={"brick_color": "OCHRE"}),
            la.plan_node("house2", "building", "house", transform={"x": -9, "y": 0, "z": 0, "rot": 0},
                         params={"floors": 2, "depth": 6.0, "brick_color": "MIXED"}),
            la.plan_node("chapel", "building", "chapel", transform={"x": 3, "y": 0, "z": 0, "rot": 0}, params={"brick_color": "SLATE"}),
            la.plan_node("stable", "building", "stable", transform={"x": 20, "y": 0, "z": 0, "rot": 0}),
            la.plan_node("ruin", "building", "house", transform={"x": 33, "y": 0, "z": 0, "rot": 0}, params={"ruin": 0.6}),
        ])
        la.plan_write_to_blend(sc, row)
        la.plan_build(bpy.context, row)
        camera((8, -58, 22), (8, 0, 2.0), lens=34)
        render("houses")
    else:
        plan = la.plan_new_example(sc, {"grounds_still": 'GROUNDS', "block_still": 'BLOCK', "farm_still": 'FARM'}.get(JOB, 'FORTRESS'), set())
        la.plan_write_to_blend(sc, plan)
        la.plan_build(bpy.context, plan)
        if JOB == "block_still":
            camera((0, -75, 70), (0, 0, 0), lens=32)
            render("block")
        elif JOB == "farm_still":
            camera((0, -44, 26), (0, 0, 0), lens=32)
            render("farm")
        elif JOB == "grounds_still":
            camera((10, -85, 55), (6, 0, 0), lens=30)
            render("grounds")
        elif JOB == "fortress_still":
            camera((8, -62, 42), (4, 0, 0), lens=30)
            render("fortress")
        else:
            cam = camera((0, 0, 0), (0, 0, 3))
            n = 36
            for i in range(n):
                cam.location = orbit((0, 0), 62, 38, math.radians(-90 + 360 * i / n))
                cam.rotation_euler = (Vector((0, 0, 3)) - cam.location).to_track_quat('-Z', 'Y').to_euler()
                render("f%03d" % i)
elif JOB in ("styles_still", "hutforms_still", "organic_still", "roundtown_still", "mixed_still", "hutcluster_still"):
    clear_scene()
    sc.cursor.location = (0, 0, 0)
    if JOB == "styles_still":
        setup_render(960, 540)
        for style in ([os.environ["STYLE_ONLY"]] if os.environ.get("STYLE_ONLY") else la.PLAN_STYLES):
            clear_scene()
            world_and_sun()
            row = la.plan_node("row", "compound", "yard", style=style, footprint=[[-34, -16], [34, -16], [34, 16], [-34, 16]],
                               params={"fence": "auto", "fence_height": 1.6},
                               anchors=[{"id": "gate", "kind": "gate", "pos": [0, -16, 0], "dir": 270, "width": 4}], children=[
                la.plan_node("house", "building", "house", transform={"x": -24, "y": 0, "z": 0, "rot": 0}),
                la.plan_node("house2", "building", "house", transform={"x": -12, "y": 0, "z": 0, "rot": 0}, params={"floors": 2}),
                la.plan_node("chapel", "building", "chapel", transform={"x": 2, "y": 0, "z": 0, "rot": 0}),
                la.plan_node("stable", "building", "stable", transform={"x": 18, "y": 0, "z": 0, "rot": 0}),
                la.plan_node("well", "building", "well", transform={"x": 28, "y": -6, "z": 0, "rot": 0}),
                la.plan_node("tree", "building", "tree", transform={"x": 30, "y": 8, "z": 0, "rot": 0}),
                la.plan_node("tower", "building", "tower", transform={"x": -30, "y": 10, "z": 0, "rot": 0},
                             params={"props": False, "lights": False, "interior": False, "height": 8.0})])
            la.plan_write_to_blend(sc, row)
            la.plan_build(bpy.context, row)
            camera((4, -52, 20), (4, 0, 2.5), lens=34)
            render(style)
    elif JOB == "hutforms_still":
        setup_render(1280, 640)
        world_and_sun()
        specs = [("earth", "DOME", {}), ("aircrete", "DOME", {"stilts": 1.0}), ("earthbag", "TUNNEL", {}), ("straw", "AFRAME", {}),
                 ("timber", "SILO", {"levels": 3, "width": 5.0, "depth": 5.0}), ("branch", "BOX", {"levels": 2}),
                 ("timber", "BOX", {"stilts": 1.4}), ("earth", "BOX", {"levels": 3, "basement": 1})]
        kids = [la.plan_node("h%d" % i, "building", "hut", transform={"x": -42 + i * 12, "y": 0, "z": 0, "rot": 0},
                             params={"construction": c, "form": f, **extra}) for i, (c, f, extra) in enumerate(specs)]
        row = la.plan_node("row", "compound", "yard", footprint=[[-50, -10], [50, -10], [50, 10], [-50, 10]], children=kids)
        la.plan_write_to_blend(sc, row)
        la.plan_build(bpy.context, row)
        camera((0, -88, 24), (0, 0, 3.0), lens=34)
        render("hutforms")
    elif JOB == "hutcluster_still":
        setup_render(1280, 720)
        world_and_sun()
        plan = la.plan_new_example(sc, 'HUTS', set())
        la.plan_write_to_blend(sc, plan)
        la.plan_build(bpy.context, plan)
        camera((0, -34, 22), (0, 2, 2.0), lens=34)
        render("hutcluster")
    else:
        setup_render(1280, 720)
        world_and_sun()
        kind, shape, style, cam = {"organic_still": ('BLOCK', 'ORGANIC', None, ((0, -90, 80), (0, 0, 0))),
                                   "roundtown_still": ('STREET', 'ROUND', 'chinese', ((0, -85, 75), (0, 0, 0))),
                                   "mixed_still": ('STREET', 'REGULAR', 'mixed', ((0, -60, 36), (0, 0, 0)))}[JOB]
        plan = la.plan_new_example(sc, kind, set())
        la.plan_apply_shape(plan, shape)
        if style:
            plan["style"] = style
        la.plan_write_to_blend(sc, plan)
        la.plan_build(bpy.context, plan)
        camera(cam[0], cam[1], lens=32)
        render(JOB.replace("_still", ""))
elif JOB == "biomes_still":
    setup_render(960, 540)
    for biome in ([os.environ["BIOME_ONLY"]] if os.environ.get("BIOME_ONLY") else la.PLAN_BIOMES):
        clear_scene()
        world_and_sun(ground=None)
        sc.wfc_plan_biome = biome
        plan = la.plan_new_example(sc, 'TERRAIN', set())
        plan["children"][2]["transform"]["z"] = 4.0          # the watchtower on its own height
        if biome == "mountain":
            plan["params"]["amplitude"] = 16.0
        la.plan_build(bpy.context, plan)
        camera((-15, -165, 62), (0, -30, 0), lens=30)
        render("biome_" + biome)
elif JOB == "townland_still":
    setup_render(1280, 720)
    clear_scene()
    world_and_sun(ground=None)
    town = la.plan_new_example(sc, 'TOWN', set())
    land = la.plan_node("land", "terrain", "terrain", params={"biome": "meadow", "width": 320.0, "depth": 320.0}, children=[town])
    la.plan_build(bpy.context, land)
    camera((0, -215, 125), (0, 0, 0), lens=30)
    render("townland")
else:
    raise SystemExit("unknown job " + JOB)
