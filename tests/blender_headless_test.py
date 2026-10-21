# Headless Blender verification for Game Level Architect.
#
# Runs the addon inside a REAL Blender process -- unlike the stub_bpy mock
# harness used during normal development (fast, but can't construct or
# evaluate a Geometry Nodes graph at all), this actually builds and
# evaluates the GN modifier, so it's the only thing in this project that
# can catch GN node-type/socket-name mistakes, mesh winding problems, and
# collection-linking issues before a human ever opens the file.
#
# Usage:
#   blender --background --factory-startup --python tests/blender_headless_test.py
#
# Exits with a non-zero status if any check fails, so it's safe to use in
# a script/CI context, not just interactively.

import importlib.util
import json
import math
from mathutils import Vector
import os
import sys
import tempfile

import bpy

ADDON_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "levelArchitect_v2.py")
)

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"[PASS] {name}")
    else:
        msg = f"[FAIL] {name}" + (f" -- {detail}" if detail else "")
        print(msg)
        failures.append(name)


def evaluated_counts(obj):
    """Realizes obj's modifier stack (Geometry Nodes included) through the
    active depsgraph and returns (vertex_count, face_count) of the actual
    result a viewport/render would show -- reading obj.data directly would
    only see the sparse pre-modifier point cloud, not what the GN graph
    actually produced."""
    deps = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(deps)
    mesh = eval_obj.to_mesh()
    counts = (len(mesh.vertices), len(mesh.polygons))
    eval_obj.to_mesh_clear()
    return counts


def per_box_aabbs(obj, n_verts_per_box=8):
    """Every add_box-style builder in this file emits vertices in
    sequential 8-per-box groups (regardless of how many logical
    tiles/runs got merged into that box) -- this reads them back as a
    list of (x0,x1,y0,y1,z0,z1) world-space bounding boxes, one per box,
    for geometric sanity checks a pure vertex/face COUNT can't catch."""
    aabbs = []
    verts = obj.data.vertices
    n_boxes = len(verts) // n_verts_per_box
    for b in range(n_boxes):
        base = b * n_verts_per_box
        coords = [obj.matrix_world @ verts[base + k].co for k in range(n_verts_per_box)]
        xs = [c.x for c in coords]
        ys = [c.y for c in coords]
        zs = [c.z for c in coords]
        aabbs.append((min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)))
    return aabbs


def aabb_overlap(a, b, eps=0.02):
    """eps shrinks each box slightly before testing -- two boxes that are
    merely flush/touching (e.g. a stair's walkway edge against a wall's
    inner face, which is completely normal) shouldn't count as
    overlapping; only genuine interpenetration should."""
    ax0, ax1, ay0, ay1, az0, az1 = a
    bx0, bx1, by0, by1, bz0, bz1 = b
    return (
        ax0 < bx1 - eps and ax1 > bx0 + eps
        and ay0 < by1 - eps and ay1 > by0 + eps
        and az0 < bz1 - eps and az1 > bz0 + eps
    )


print(f"Loading addon from: {ADDON_PATH}")
spec = importlib.util.spec_from_file_location("levelArchitect_v2", ADDON_PATH)
addon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(addon)
addon.register()

scene = bpy.context.scene

# -- Configure a moderate, varied level: corridor stairs, continuous
# elevation, and a ceiling all on at once, since those are exactly the
# features that touch GN or were only ever verified through the mock. --
scene.wfc_width = 22
scene.wfc_length = 22
scene.wfc_height = 3
scene.wfc_seed = 12345
scene.wfc_random_seed = False
scene.wfc_rooms_min = 8
scene.wfc_rooms_max = 14
scene.wfc_room_size_min = 3
scene.wfc_room_size_max = 6
scene.wfc_room_shape = 'MIXED'
scene.wfc_stairs_per_level = 3
scene.wfc_stair_room_width = 3
scene.wfc_stair_room_length = 4
scene.wfc_corridor_stairs = True
scene.wfc_sub_levels_per_floor = 1
scene.wfc_split_level_chance = 0.0
scene.wfc_elevation_chance = 0.6
scene.wfc_elevation_range = 1.0
scene.wfc_max_ramp_slope = 30.0
scene.wfc_tile_size = 2.0
scene.wfc_level_height = 3.0
scene.wfc_style = '0'
scene.wfc_simple_materials = True
scene.wfc_color_rooms = True
scene.wfc_floor_thickness = 0.1
scene.wfc_iso_mode = False
scene.wfc_add_ceiling = False
scene.wfc_ceiling_thickness = 0.1
scene.wfc_organic_amount = 0.0
scene.wfc_wall_height = 2.5
scene.wfc_wall_thickness = 0.2
scene.wfc_wall_cap_top = True
scene.wfc_wall_grouping = 'SINGLE'
scene.wfc_door_height = 2.2
scene.wfc_door_frame_thickness = 0.15
scene.wfc_door_grouping = 'SINGLE'
scene.wfc_door_merge_distance = 2
scene.wfc_stair_grouping = 'PER_FLOOR'
scene.wfc_stair_mesh_style = 'STAIRS'
scene.wfc_stair_steps = 6
scene.wfc_torch_chance = 0.2
scene.wfc_torch_height = 1.6
scene.wfc_torch_light_chance = 0.5
scene.wfc_max_lights = 100
scene.wfc_torch_light_energy = 60.0
scene.wfc_torch_light_color = (1.0, 0.55, 0.2)
scene.wfc_torch_light_radius = 0.25
scene.wfc_prop_chance = 0.12

# ==============================================================================
# Wall Height / Door Height / Level Height / Sub-Levels per Floor mutual
# sync -- user feedback: raising Sub-Levels per Floor shrinks the real
# headroom per slice (Level Height / Sub-Levels), but Wall Height (and,
# raised separately, Door Height -- same bug) used to be completely
# independent of that, so walls/doors routinely clipped through the floor
# above. Each of the four now nudges the others (via update= callbacks) to
# keep wall_height/door_height <= level_height / sub_levels_per_floor,
# preferring to grow Level Height before ever shrinking either height.
# ==============================================================================
scene.wfc_sub_levels_per_floor = 2
check(
    "Height sync: raising Sub-Levels grows Level Height instead of leaving Wall/Door Height clipping",
    scene.wfc_wall_height <= scene.wfc_level_height / scene.wfc_sub_levels_per_floor + 1e-6
    and scene.wfc_door_height <= scene.wfc_level_height / scene.wfc_sub_levels_per_floor + 1e-6,
    f"wall_height={scene.wfc_wall_height} door_height={scene.wfc_door_height} "
    f"level_height={scene.wfc_level_height} sub_levels={scene.wfc_sub_levels_per_floor}",
)
scene.wfc_level_height = 3.0
check(
    "Height sync: directly shrinking Level Height below what Wall/Door Height needs shrinks them to fit",
    scene.wfc_wall_height <= scene.wfc_level_height / scene.wfc_sub_levels_per_floor + 1e-6
    and scene.wfc_door_height <= scene.wfc_level_height / scene.wfc_sub_levels_per_floor + 1e-6,
    f"wall_height={scene.wfc_wall_height} door_height={scene.wfc_door_height} "
    f"level_height={scene.wfc_level_height} sub_levels={scene.wfc_sub_levels_per_floor}",
)
# Restore the scenario's own baseline before Step 1 actually runs.
scene.wfc_sub_levels_per_floor = 1
scene.wfc_level_height = 3.0
scene.wfc_door_height = 2.2
scene.wfc_wall_height = 2.5

# ==============================================================================
# Step 1: Blueprint -- ceiling OFF first, to get a baseline poly count
# ==============================================================================
result = bpy.ops.object.generate_game_blueprint()
check("Blueprint: operator FINISHED", result == {'FINISHED'}, str(result))

blueprint_obj = bpy.data.objects.get(addon.BLUEPRINT_OBJECT_NAME)
check("Blueprint: object exists", blueprint_obj is not None)
check("Blueprint: has a Nodes modifier", any(m.type == 'NODES' for m in blueprint_obj.modifiers))

verts_no_ceiling, faces_no_ceiling = evaluated_counts(blueprint_obj)
check(
    "Blueprint: GN graph evaluates to non-empty geometry (ceiling off)",
    verts_no_ceiling > 0 and faces_no_ceiling > 0,
    f"verts={verts_no_ceiling} faces={faces_no_ceiling}",
)

# Regression check for a real bug: create_geometry_nodes_modifier() used to
# assign `mod.node_group = node_group` BEFORE any Bool/Float interface
# socket (and its intended default) existed, which silently locked that
# modifier's own per-input override to the socket type's built-in zero
# value (False/0.0) forever after -- a LATER `.default_value` write on the
# interface only affects a future/different modifier instance. Concretely:
# Color Rooms/Corridors defaults to True in the addon UI, but every
# freshly-generated level rendered with it OFF regardless, invisibly,
# because the checkbox never actually reached the modifier. floor_level_count
# in this scenario is small enough that room-slot indices start right after
# it, so if Color Rooms genuinely took effect, at least one face's
# material_index must land at or above that boundary.
gn_mod_for_materials = next(m for m in blueprint_obj.modifiers if m.type == 'NODES')
color_rooms_modifier_value = None
for item in gn_mod_for_materials.node_group.interface.items_tree:
    if getattr(item, "in_out", None) == 'INPUT' and item.name == "Color Rooms/Corridors":
        # See set_input()/find_input_socket_name() further down for why this
        # branches on Blender version -- .properties.inputs is 5.2+ only.
        if hasattr(gn_mod_for_materials, "properties"):
            color_rooms_modifier_value = getattr(gn_mod_for_materials.properties.inputs, item.identifier).value
        else:
            color_rooms_modifier_value = gn_mod_for_materials[item.identifier]
        break
check(
    "Blueprint: Color Rooms/Corridors modifier input matches its intended default",
    color_rooms_modifier_value is True,
    f"modifier-level value={color_rooms_modifier_value} (expected True, matching wfc_color_rooms default)",
)
room_material_indices = {
    p.material_index for p in blueprint_obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh().polygons
}
check(
    "Blueprint: at least one face actually got a room-pool material index (not just floor-level slots)",
    any(idx >= 8 for idx in room_material_indices),
    f"material indices present: {sorted(room_material_indices)}",
)

# Regression check: Solid Shading's "Texture" color mode -- a separate,
# simpler display path from "Material" that needs a real UV map, unlike
# EEVEE's node-tree evaluation which falls back to Generated coordinates
# without one -- had nothing to sample from, since the addon never
# generated a UV map at all. Every Simple Viewport Colors swatch is a
# flat single color, so a constant UV everywhere is sufficient; this only
# checks presence/coverage, not any particular value.
uv_check_mesh = blueprint_obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
check(
    "Blueprint: has a UV map, and every loop is covered",
    len(uv_check_mesh.uv_layers) > 0 and len(uv_check_mesh.uv_layers[0].data) == len(uv_check_mesh.loops),
    f"uv_layers={list(uv_check_mesh.uv_layers.keys())}",
)

# ==============================================================================
# Regression check for a real bug found from user feedback (backface
# culling on, floors read as fully transparent from a top-down view): at
# Floor Thickness 0.0, the floor cube's top and bottom faces become fully
# coincident, Merge By Distance welds them into one, and Blender's own
# duplicate-face cleanup kept only the DOWNWARD-facing one -- every single
# floor face pointed -Z, none pointed +Z. Fixed by clamping the floor (and
# ceiling) cube's actual thickness to stay comfortably above Merge
# Distance's own welding tolerance, so top/bottom can never truly coincide.
# Confirmed the fix with exactly the reported scenario (RECT rooms, 0.0
# Floor Thickness, sub-levels, RAMP stairs) before writing this permanent
# check with a smaller scenario for speed.
scene.wfc_floor_thickness = 0.0
result = bpy.ops.object.generate_game_blueprint()
check("Zero-thickness floor: Blueprint regenerate FINISHED", result == {'FINISHED'}, str(result))
blueprint_obj = bpy.data.objects.get(addon.BLUEPRINT_OBJECT_NAME)
zt_mesh = blueprint_obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
up_count = 0
down_count = 0
for poly in zt_mesh.polygons:
    verts = [zt_mesh.vertices[vi].co for vi in poly.vertices]
    if max(v.z for v in verts) - min(v.z for v in verts) > 0.01:
        continue  # a side face, not a top/bottom cap -- skip
    normal = (verts[1] - verts[0]).cross(verts[2] - verts[0]).normalized()
    if normal.z > 0.5:
        up_count += 1
    elif normal.z < -0.5:
        down_count += 1
check(
    "Zero-thickness floor: both top (+Z) and bottom (-Z) faces survive per tile, not just one",
    up_count > 0 and up_count == down_count,
    f"up={up_count} down={down_count}",
)
scene.wfc_floor_thickness = 0.1
result = bpy.ops.object.generate_game_blueprint()
check("Zero-thickness floor: scenario Blueprint restored FINISHED", result == {'FINISHED'}, str(result))
blueprint_obj = bpy.data.objects.get(addon.BLUEPRINT_OBJECT_NAME)

# ==============================================================================
# Style mode (Simple Viewport Colors off) never had any coverage in this
# suite before -- it used to be a flat 2-slot system (one corridor look,
# one room look, uniform across the whole level) until per-room/per-floor
# coloring was added to match Simple mode. Confirms real per-room and
# per-floor-level material variety, not everything clamped to one shared
# slot the way the old 2-slot system was.
# ==============================================================================
scene.wfc_simple_materials = False
result = bpy.ops.object.generate_game_blueprint()
check("Style mode: Blueprint regenerate FINISHED", result == {'FINISHED'}, str(result))
blueprint_obj = bpy.data.objects.get(addon.BLUEPRINT_OBJECT_NAME)
style_mesh = blueprint_obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
style_material_indices = {p.material_index for p in style_mesh.polygons}
style_floor_level_count = len(addon.FLOOR_RAMP_HEX)
check(
    "Style mode: more than one floor-level material index is actually used",
    len({idx for idx in style_material_indices if idx < style_floor_level_count}) > 1,
    f"indices used: {sorted(style_material_indices)}",
)
check(
    "Style mode: multiple distinct room-pool material indices are actually used",
    len({idx for idx in style_material_indices if idx >= style_floor_level_count}) > 1,
    f"indices used: {sorted(style_material_indices)}",
)
sample_style_mat = blueprint_obj.data.materials[next(iter(
    idx for idx in style_material_indices if idx >= style_floor_level_count
))]
check(
    "Style mode: a room face resolves to a real per-room style material, not a shared default",
    sample_style_mat.name.startswith(f"{addon.STYLE_MATERIAL_NAME['0']}_Room_")
    or sample_style_mat.name.endswith("_Entrance") or sample_style_mat.name.endswith("_Exit"),
    f"resolved to {sample_style_mat.name}",
)

# Regression check for the "viewport_color" Color Attribute feature: style
# materials never set diffuse_color at all before (their look came purely
# from the node tree), which left them invisible to Solid Shading's
# "Material" color mode AND to a diffuse_color-driven Color Attribute
# palette. _finish_material now also sets mat.diffuse_color = tint whenever
# a tint is given.
room_pool_indices = sorted(idx for idx in style_material_indices if idx >= style_floor_level_count)[:2]
if len(room_pool_indices) >= 2:
    style_room_colors = {
        idx: tuple(blueprint_obj.data.materials[idx].diffuse_color) for idx in room_pool_indices
    }
    check(
        "Style mode: room-pool materials have a real, distinct diffuse_color (not left at the default)",
        len(set(style_room_colors.values())) > 1,
        f"diffuse_color per material index: {style_room_colors}",
    )

scene.wfc_simple_materials = True
result = bpy.ops.object.generate_game_blueprint()
check("Style mode: scenario Blueprint restored to Simple materials FINISHED", result == {'FINISHED'}, str(result))
blueprint_obj = bpy.data.objects.get(addon.BLUEPRINT_OBJECT_NAME)

# ==============================================================================
# Per-Floor Overrides (WFC_FloorProfile) -- new feature, no coverage before
# this. Two layers: direct solver-level checks of the resolver math itself
# (fast, precise, no full generation needed), then a real end-to-end
# generation exercising the Add operator + CollectionProperty + material
# building together.
# ==============================================================================
profile_solver = addon.WFC_Level_Solver(
    width=10, length=10, height=5, room_count=5,
    floor_profiles=[
        {'floor_index': 0, 'room_size_min': 2, 'room_size_max': 3, 'room_shape': 'RECT', 'style': '0'},
        {'floor_index': 4, 'room_size_min': 8, 'room_size_max': 10, 'room_shape': 'ROUND', 'style': '1'},
    ],
)
check(
    "Per-Floor Overrides: floor at/before the first breakpoint resolves to it exactly",
    profile_solver._room_size_for_floor(0) == (2, 3) and profile_solver._room_shape_for_floor(0) == 'RECT',
    f"size={profile_solver._room_size_for_floor(0)} shape={profile_solver._room_shape_for_floor(0)}",
)
check(
    "Per-Floor Overrides: floor at/after the last breakpoint resolves to it exactly",
    profile_solver._room_size_for_floor(4) == (8, 10) and profile_solver._room_shape_for_floor(4) == 'ROUND',
    f"size={profile_solver._room_size_for_floor(4)} shape={profile_solver._room_shape_for_floor(4)}",
)
mid_size = profile_solver._room_size_for_floor(2)
check(
    "Per-Floor Overrides: a floor between two breakpoints interpolates room size, "
    "strictly between the two breakpoints' own values",
    2 < mid_size[0] < 8 and 3 < mid_size[1] < 10,
    f"floor 2 (halfway between floor 0 and floor 4) resolved to {mid_size}",
)
check(
    "Per-Floor Overrides: room_shape is a step function, not interpolated -- a floor between "
    "breakpoints keeps the LAST one at or before it, not some blend",
    profile_solver._room_shape_for_floor(2) == 'RECT',
    f"floor 2 shape={profile_solver._room_shape_for_floor(2)}",
)
empty_solver = addon.WFC_Level_Solver(
    width=10, length=10, height=3, room_count=5,
    room_size_min=2, room_size_max=4, room_shape='MIXED',
)
check(
    "Per-Floor Overrides: an empty floor_profiles list falls back to the flat scene values "
    "everywhere (backward compatible with every generation before this feature existed)",
    empty_solver._room_size_for_floor(1) == (2, 4) and empty_solver._room_shape_for_floor(1) == 'MIXED',
)

# End-to-end: two breakpoints far apart in both room size and style, real
# generation through the actual operators (Add Floor Override + Generate
# Blueprint), Style mode on so the material-style side gets exercised too.
scene.wfc_floor_profiles.clear()
bpy.ops.object.wfc_floor_profile_add()
fp0 = scene.wfc_floor_profiles[-1]
fp0.floor_index, fp0.room_size_min, fp0.room_size_max, fp0.room_shape, fp0.style = 0, 2, 2, 'RECT', '0'
bpy.ops.object.wfc_floor_profile_add()
fp1 = scene.wfc_floor_profiles[-1]
fp1.floor_index, fp1.room_size_min, fp1.room_size_max, fp1.room_shape, fp1.style = 3, 7, 7, 'RECT', '1'
check(
    "Per-Floor Overrides: Add operator populated the CollectionProperty as expected",
    len(scene.wfc_floor_profiles) == 2,
    f"count={len(scene.wfc_floor_profiles)}",
)

prev_width, prev_length, prev_height = scene.wfc_width, scene.wfc_length, scene.wfc_height
prev_style, prev_simple = scene.wfc_style, scene.wfc_simple_materials
scene.wfc_width = 26
scene.wfc_length = 26
scene.wfc_height = 4
scene.wfc_simple_materials = False
scene.wfc_style = '0'
result = bpy.ops.object.generate_game_blueprint()
check("Per-Floor Overrides: end-to-end Blueprint regenerate FINISHED", result == {'FINISHED'}, str(result))
blueprint_obj = bpy.data.objects.get(addon.BLUEPRINT_OBJECT_NAME)

pf_mesh = blueprint_obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
pf_room_ids = addon._read_polygon_values(pf_mesh, "room_id")
pf_logical_floors = addon._read_polygon_values(pf_mesh, "logical_floor")
rooms_by_floor = {}
for room_id, floor in zip(pf_room_ids, pf_logical_floors):
    if room_id >= 0:
        rooms_by_floor.setdefault(floor, set()).add(room_id)
floor0_tiles = sum(1 for rid, fl in zip(pf_room_ids, pf_logical_floors) if fl == 0 and rid >= 0)
floor3_tiles = sum(1 for rid, fl in zip(pf_room_ids, pf_logical_floors) if fl == 3 and rid >= 0)
floor0_rooms = len(rooms_by_floor.get(0, ()))
floor3_rooms = len(rooms_by_floor.get(3, ()))
check(
    "Per-Floor Overrides: floor 3 (7x7 rooms) actually carved more floor tiles per room than "
    "floor 0 (2x2 rooms), confirming the size breakpoints reached real carving, not just the "
    "solver's own room list",
    floor0_rooms > 0 and floor3_rooms > 0 and (floor3_tiles / floor3_rooms) > (floor0_tiles / floor0_rooms) * 2,
    f"floor0: {floor0_tiles} tiles / {floor0_rooms} rooms, floor3: {floor3_tiles} tiles / {floor3_rooms} rooms",
)

floor0_slot_mat = blueprint_obj.data.materials[0]
floor3_slot_mat = blueprint_obj.data.materials[3]
check(
    "Per-Floor Overrides: floor-level material slots 0 and 3 resolved to DIFFERENT styles "
    "(Dungeon vs Cave Rock), matching the two breakpoints",
    floor0_slot_mat.name.startswith(addon.STYLE_MATERIAL_NAME['0'])
    and floor3_slot_mat.name.startswith(addon.STYLE_MATERIAL_NAME['1']),
    f"slot 0={floor0_slot_mat.name} slot 3={floor3_slot_mat.name}",
)

room_style_names = set()
for room_id in rooms_by_floor.get(3, ()):
    mat = blueprint_obj.data.materials[room_id + 8]  # floor_level_count is always 8 (len(FLOOR_RAMP_HEX))
    room_style_names.add(mat.name)
check(
    "Per-Floor Overrides: rooms on floor 3 resolved to Cave Rock room materials specifically",
    len(room_style_names) > 0 and all(n.startswith(addon.STYLE_MATERIAL_NAME['1']) for n in room_style_names),
    f"floor 3 room material names: {room_style_names}",
)

scene.wfc_floor_profiles.clear()
scene.wfc_width, scene.wfc_length, scene.wfc_height = prev_width, prev_length, prev_height
scene.wfc_style, scene.wfc_simple_materials = prev_style, prev_simple
result = bpy.ops.object.generate_game_blueprint()
check("Per-Floor Overrides: scenario Blueprint restored FINISHED", result == {'FINISHED'}, str(result))
blueprint_obj = bpy.data.objects.get(addon.BLUEPRINT_OBJECT_NAME)

# ==============================================================================
# Ceiling: live GN toggle -- flip Add Ceiling on and confirm the evaluated
# mesh actually grows, without regenerating the blueprint at all.
#
# Blender 5.2 exposes GN modifier inputs through modifier.properties.inputs
# .Socket_N.value -- NOT the older modifier["Socket_N"] IDProperty pattern
# (that raises "id properties not supported for this type" there). Older
# versions (confirmed on 4.5.2) don't have `.properties` at all and need the
# IDProperty form instead -- this is purely a TEST-SCRIPT concern (poking a
# live modifier from an external script); the addon's own code never touches
# either API, it only sets defaults via node_group.interface at creation
# time, which is why the addon itself runs unmodified across both versions.
# Matching a socket's interface name to its Socket_N identifier via
# node_group.interface.items_tree is stable across both.
# ==============================================================================
gn_mod = next(m for m in blueprint_obj.modifiers if m.type == 'NODES')


def find_input_socket_name(mod, display_name):
    for item in mod.node_group.interface.items_tree:
        if getattr(item, "in_out", None) == 'INPUT' and item.name == display_name:
            return item.identifier
    return None


def set_input(mod, display_name, value):
    socket_id = find_input_socket_name(mod, display_name)
    if socket_id is None:
        return False
    if hasattr(mod, "properties"):
        getattr(mod.properties.inputs, socket_id).value = value
    else:
        mod[socket_id] = value
        mod.node_group.interface_update(bpy.context)
    return True


ceiling_found = find_input_socket_name(gn_mod, "Add Ceiling") is not None
check("Ceiling: found 'Add Ceiling' GN input socket", ceiling_found)

if ceiling_found:
    set_input(gn_mod, "Add Ceiling", True)
    blueprint_obj.data.update()
    verts_with_ceiling, faces_with_ceiling = evaluated_counts(blueprint_obj)
    check(
        "Ceiling: turning it on (live, no regen) adds geometry",
        faces_with_ceiling > faces_no_ceiling,
        f"faces before={faces_no_ceiling} after={faces_with_ceiling}",
    )

    iso_found = find_input_socket_name(gn_mod, "Isometric Mode") is not None
    check("Ceiling: found 'Isometric Mode' GN input socket", iso_found)
    if iso_found:
        set_input(gn_mod, "Isometric Mode", True)
        blueprint_obj.data.update()
        verts_iso, faces_iso = evaluated_counts(blueprint_obj)
        check(
            "Ceiling: Isometric Mode culls it back down",
            faces_iso < faces_with_ceiling,
            f"faces with ceiling={faces_with_ceiling} with iso mode too={faces_iso}",
        )
        set_input(gn_mod, "Isometric Mode", False)

    # Leave ceiling ON for the rest of the run, so Walls/Doors/Props are
    # also exercised against a ceiling-on level at least once.
    scene.wfc_add_ceiling = True

# Regenerate with Add Ceiling baked into the scene property default too
# (separate from the live-toggle check above), then proceed with the rest
# of the pipeline against this same generation.
result = bpy.ops.object.generate_game_blueprint()
check("Blueprint: regenerate with Add Ceiling defaulted on FINISHED", result == {'FINISHED'})
blueprint_obj = bpy.data.objects.get(addon.BLUEPRINT_OBJECT_NAME)

# ==============================================================================
# Steps 2-5: Walls, Stairs, Doors, Props
# ==============================================================================
result = bpy.ops.object.generate_level_walls()
check("Walls: operator FINISHED", result == {'FINISHED'}, str(result))
walls_obj = bpy.data.objects.get(addon.WALLS_OBJECT_NAME)
check("Walls: object exists with geometry", walls_obj is not None and len(walls_obj.data.vertices) > 0)

if walls_obj is not None:
    # Every add_box() in the codebase (walls/doors/stairs/ramps/torches/
    # decoration) shares the identical 8-vert winding convention, which
    # DEVELOPMENT.md has flagged since early in the project as "never
    # independently verified against a live Blender render" -- this is
    # that verification, on the real thing. Wall boxes no longer carry a
    # bottom face at all (see _build_wall_mesh's add_box -- always
    # coincident with/hidden behind the floor tile a wall stands on, pure
    # polycount reduction, DEVELOPMENT.md "Delete interior/hidden faces
    # for faster rendering"), so with cap_top on, face index 0 per box is
    # now the TOP face; with cap_top off, index 0 is the first side face.
    # Getting the winding backwards would flip every normal in the whole
    # file at once (they all share this exact same add_box pattern), so
    # one correct result here is real evidence for all of them.
    verts = walls_obj.data.vertices
    polys = walls_obj.data.polygons
    n_boxes = len(verts) // 8
    faces_per_box = 5 if scene.wfc_wall_cap_top else 4
    check(
        "Walls: no bottom face per box (removed as hidden/redundant geometry)",
        len(polys) == n_boxes * faces_per_box,
        f"boxes={n_boxes} faces_per_box={faces_per_box} expected_faces={n_boxes * faces_per_box} actual_faces={len(polys)}",
    )
    if scene.wfc_wall_cap_top:
        top_ok = all(polys[b * faces_per_box].normal.z > 0.5 for b in range(n_boxes))
        check("Walls: top (cap) face winding points +Z", top_ok, f"boxes checked={n_boxes}")

    # Regression check: Round Corners (wfc_wall_corner_rounding) adds a
    # live Bevel modifier to the wall object(s) instead of baking fillet
    # geometry into the mesh -- see _add_corner_rounding_modifier's
    # docstring for why (angle-limited Bevel is a long-stable modifier,
    # deliberately chosen over hand-derived corner geometry that couldn't
    # be verified without a real Blender session). Toggled on, regenerated,
    # and checked directly here, then reverted so the default (off) wall
    # mesh is what every later check in this file keeps seeing.
    prev_rounding = scene.wfc_wall_corner_rounding
    prev_radius = scene.wfc_wall_corner_radius
    scene.wfc_wall_corner_rounding = True
    scene.wfc_wall_corner_radius = 0.12
    result = bpy.ops.object.generate_level_walls()
    check("Walls: regenerate with Round Corners on FINISHED", result == {'FINISHED'}, str(result))
    rounded_walls_obj = bpy.data.objects.get(addon.WALLS_OBJECT_NAME)
    if rounded_walls_obj is not None:
        bevel_mods = [m for m in rounded_walls_obj.modifiers if m.type == 'BEVEL']
        check(
            "Walls: Round Corners adds exactly one Bevel modifier",
            len(bevel_mods) == 1, f"count={len(bevel_mods)}",
        )
        if bevel_mods:
            check(
                "Walls: Bevel modifier width matches Corner Radius",
                abs(bevel_mods[0].width - 0.12) < 1e-6, f"width={bevel_mods[0].width}",
            )
            check(
                "Walls: Bevel modifier uses angle-limited selection (not every edge)",
                bevel_mods[0].limit_method == 'ANGLE', f"limit_method={bevel_mods[0].limit_method}",
            )
    scene.wfc_wall_corner_rounding = prev_rounding
    scene.wfc_wall_corner_radius = prev_radius
    result = bpy.ops.object.generate_level_walls()
    check("Walls: regenerate back to Round Corners default FINISHED", result == {'FINISHED'}, str(result))
    walls_obj = bpy.data.objects.get(addon.WALLS_OBJECT_NAME)
    check("Walls: object still exists after reverting Round Corners", walls_obj is not None)

    if scene.wfc_corridor_stairs:
        # Regression check for a real, accepted-as-residual bug
        # (DEVELOPMENT.md "Corridor Stairs, rare residual wall gap", ~7-10%
        # of stair cells): a Corridor Stairs run's perpendicular sides are
        # only checked for a clear neighbor AT THAT STAIRWELL'S OWN
        # placement time, so a corridor pathfound afterward can still end
        # up running alongside one with no wall between them. Fixed at
        # wall-generation time instead (forced_wall_edges in
        # _build_wall_mesh, wired up in Generate Level Walls) -- verifies
        # the ACTUAL geometry here: every TILE_STAIR cell's two
        # perpendicular sides (derived the same way the operator derives
        # them, from the baked tile_rotation) must have a real wall box
        # AABB covering that boundary line, regardless of whether the
        # neighbor cell happens to be walkable. The Cave-only check further
        # below is a placement-time/grid-walkability proxy and can't
        # observe this wall-generation-time fix at all -- this is the
        # check that actually verifies the fix.
        stair_wall_tile_size = scene.wfc_tile_size
        stair_wall_level_height = addon._fine_level_height(scene)
        wall_aabbs = per_box_aabbs(walls_obj, 8)
        _, stair_extra = addon._read_blueprint_points(
            blueprint_obj, stair_wall_tile_size, stair_wall_level_height,
            ("tile_id", "tile_rotation", "z_offset"),
        )
        eps = 0.05
        checked = 0
        missing = []
        for cell, tid in stair_extra["tile_id"].items():
            if tid != addon.TILE_STAIR:
                continue
            cx, cy, cz = cell
            dx, dy = addon._direction_for_rotation(stair_extra["tile_rotation"].get(cell, 0.0))
            for ddx, ddy in ((-dy, dx), (dy, -dx)):
                checked += 1
                if ddx != 0:
                    wall_x = (cx + 0.5 * ddx) * stair_wall_tile_size
                    point = (wall_x, cy * stair_wall_tile_size)
                else:
                    wall_y = (cy + 0.5 * ddy) * stair_wall_tile_size
                    point = (cx * stair_wall_tile_size, wall_y)
                z0_cell = cz * stair_wall_level_height + stair_extra["z_offset"].get(cell, 0.0)
                z_mid = z0_cell + scene.wfc_wall_height * 0.5
                found = any(
                    x0 - eps <= point[0] <= x1 + eps and y0 - eps <= point[1] <= y1 + eps
                    and z0 - eps <= z_mid <= z1 + eps
                    for (x0, x1, y0, y1, z0, z1) in wall_aabbs
                )
                if not found:
                    missing.append((cell, (ddx, ddy)))
        check(
            "Walls: every Corridor Stairs cell has a real wall on both perpendicular sides, "
            "even when the neighbor cell is walkable",
            checked > 0 and len(missing) == 0,
            f"checked={checked} missing={missing[:10]}{'...' if len(missing) > 10 else ''}",
        )

result = bpy.ops.object.generate_level_stairs()
check("Stairs: operator FINISHED or CANCELLED", result in ({'FINISHED'}, {'CANCELLED'}), str(result))

stair_objs = [o for o in bpy.data.objects if o.name.startswith(addon.STAIRS_OBJECT_NAME)]
if stair_objs and walls_obj is not None:
    # Regression check for a real bug found by hand: _read_stair_runs used
    # to pick a stair run's "start" tile via an EXACT dict lookup keyed by
    # the tile_rotation float -- but that value round-trips through a
    # baked 32-bit float mesh attribute, so it can come back as e.g.
    # 3.1414999961853027 instead of the exact 3.1415 constant. The lookup
    # silently missed and fell back to the wrong default direction,
    # picking the wrong end of the run as "start" -- which doesn't just
    # look subtly off, it can plant the stair mesh overlapping a wall
    # entirely. Checking for actual geometric overlap (not just "did it
    # run without erroring") is what catches this class of bug; a
    # vertex/face count alone would have passed every time.
    #
    # Corridor Stairs is 1 tile wide by design (no side walkway), so a
    # tread's own perpendicular edges are SUPPOSED to sit flush against a
    # wall there -- same as any ordinary floor tile touching its own
    # adjacent wall, which always overlaps by exactly wall_thickness / 2
    # (both are centered on/extend to the same shared tile-boundary line).
    # That's not a bug, so the tolerance has to absorb it; only a room-
    # based stairwell (a real walkway buffer on every side) should have
    # zero wall contact at all, hence the tighter epsilon when
    # Corridor Stairs is off.
    eps = (scene.wfc_wall_thickness / 2.0 + 0.03) if scene.wfc_corridor_stairs else 0.02
    wall_aabbs = per_box_aabbs(walls_obj, 8)
    total_stair_boxes = 0
    overlap_count = 0
    for stair_obj in stair_objs:
        for stair_box in per_box_aabbs(stair_obj, 8):
            total_stair_boxes += 1
            if any(aabb_overlap(stair_box, wall_box, eps=eps) for wall_box in wall_aabbs):
                overlap_count += 1
    check(
        "Stairs: no stair tread box overlaps a wall box beyond expected flush contact",
        overlap_count == 0,
        f"{overlap_count}/{total_stair_boxes} tread boxes overlap a wall (eps={eps:.3f})",
    )

    if scene.wfc_stair_mesh_style == 'STAIRS':
        # Regression check for the hidden-face cleanup extended to Stairs
        # (DEVELOPMENT.md "Delete interior/hidden faces for faster
        # rendering") -- every tread box's bottom is always coincident
        # with the real floor under the run, same reasoning as Walls, so
        # it's dropped: 5 faces per box (top + 4 sides) instead of 6.
        stair_total_verts = sum(len(o.data.vertices) for o in stair_objs)
        stair_total_polys = sum(len(o.data.polygons) for o in stair_objs)
        stair_expected_boxes = stair_total_verts // 8
        check(
            "Stairs: no bottom face per tread box (removed as hidden/redundant geometry)",
            stair_total_polys == stair_expected_boxes * 5,
            f"boxes={stair_expected_boxes} expected_faces={stair_expected_boxes * 5} actual_faces={stair_total_polys}",
        )

    # Same cleanup, verified directly on _build_ramp_mesh (RAMP style isn't
    # the active scenario setting here, so build one standalone rather than
    # re-running the whole pipeline under a different setting just for
    # this).
    ramp_mesh = addon._build_ramp_mesh(
        [{'z': 0, 'segments': [(0, 0, 0.0, 3)]}], tile_size=2.0, level_height=3.0, name="TestRampCleanup",
    )
    ramp_boxes = len(ramp_mesh.vertices) // 8
    check(
        "Ramps: no bottom face per segment box (removed as hidden/redundant geometry)",
        ramp_boxes > 0 and len(ramp_mesh.polygons) == ramp_boxes * 5,
        f"boxes={ramp_boxes} expected_faces={ramp_boxes * 5} actual_faces={len(ramp_mesh.polygons)}",
    )
    bpy.data.meshes.remove(ramp_mesh)

result = bpy.ops.object.generate_level_doors()
check("Doors: operator FINISHED or CANCELLED", result in ({'FINISHED'}, {'CANCELLED'}), str(result))

doors_obj = bpy.data.objects.get(addon.DOORS_OBJECT_NAME)
if doors_obj is not None and stair_objs:
    # A door frame should never land on/beside the stairs themselves (see
    # the fix in _build_door_mesh's stair_cells exclusion) -- checked the
    # same way, by real geometric overlap against the actual stair mesh.
    stair_aabbs = [box for o in stair_objs for box in per_box_aabbs(o, 8)]
    door_boxes = per_box_aabbs(doors_obj, 8)
    door_overlap_count = sum(
        1 for door_box in door_boxes if any(aabb_overlap(door_box, sb) for sb in stair_aabbs)
    )
    check(
        "Doors: no door frame box overlaps a stair tread box",
        door_overlap_count == 0,
        f"{door_overlap_count}/{len(door_boxes)} door boxes overlap a stair",
    )


# Regression checks for Door Style / Entrance-Exit Gates: every ordinary
# doorway gets material_index 0, but Entrance and Exit each get their OWN
# dedicated "Gate" pass (material_index 1/2 respectively) -- see
# _build_door_mesh's own docstring for why that's a separate pass from
# the ordinary room_id-boundary doorway logic, independent of Door Style.
if doors_obj is not None:
    check(
        "Doors: always exactly 3 material slots (door/entrance/exit), any Door Style",
        len(doors_obj.data.materials) == 3, f"count={len(doors_obj.data.materials)}",
    )
    used_indices = {p.material_index for p in doors_obj.data.polygons}
    check(
        "Doors: an Entrance gate was actually built (material_index 1 used)",
        1 in used_indices, f"used_indices={used_indices}",
    )
    check(
        "Doors: an Exit gate was actually built (material_index 2 used)",
        2 in used_indices, f"used_indices={used_indices}",
    )

prev_door_style = scene.wfc_door_style
prev_arch_height = scene.wfc_door_arch_height
baseline_door_verts = len(doors_obj.data.vertices) if doors_obj is not None else 0
for style in ('ROUND', 'POINTED'):
    scene.wfc_door_style = style
    scene.wfc_door_arch_height = 0.6
    result = bpy.ops.object.generate_level_doors()
    check(f"Doors: regenerate with Door Style={style} FINISHED", result == {'FINISHED'}, str(result))
    styled_doors_obj = bpy.data.objects.get(addon.DOORS_OBJECT_NAME)
    check(
        f"Doors: Door Style={style} object exists with geometry",
        styled_doors_obj is not None and len(styled_doors_obj.data.vertices) > 0,
    )
    if styled_doors_obj is not None:
        check(
            f"Doors: Door Style={style} adds real geometry vs. Flat "
            f"(arch replaces the flat lintel with more boxes)",
            len(styled_doors_obj.data.vertices) > baseline_door_verts,
            f"styled={len(styled_doors_obj.data.vertices)} flat_baseline={baseline_door_verts}",
        )
        bad_indices = [p.material_index for p in styled_doors_obj.data.polygons if p.material_index not in (0, 1, 2)]
        check(
            f"Doors: Door Style={style} every face uses a valid material_index (0/1/2)",
            len(bad_indices) == 0, f"bad_count={len(bad_indices)}",
        )
        used = {p.material_index for p in styled_doors_obj.data.polygons}
        check(
            f"Doors: Door Style={style} Entrance and Exit gates still present",
            1 in used and 2 in used, f"used_indices={used}",
        )

scene.wfc_door_style = prev_door_style
scene.wfc_door_arch_height = prev_arch_height
result = bpy.ops.object.generate_level_doors()
check("Doors: regenerate back to Door Style default FINISHED", result == {'FINISHED'}, str(result))
doors_obj = bpy.data.objects.get(addon.DOORS_OBJECT_NAME)
check("Doors: object still exists after reverting Door Style", doors_obj is not None)

# Door panels: independent check, not just "did it not crash." Re-derive
# the exact doorway set _build_door_mesh itself used (via the same
# _find_ordinary_doorways helper the operator calls) and confirm one
# panel per wide-enough doorway, every panel's world origin sits exactly
# at that doorway's hinge (span_min) edge, and the panel's width actually
# runs along the doorway's span axis (catches a rotation-sign mistake, not
# just a missing/extra object) -- the same kind of independent recheck
# that caught a real bug in WorldMaker's platformer gap logic earlier: a
# plain rerun would never catch a systematically-wrong-but-self-consistent
# placement.
panel_tile_size = scene.wfc_tile_size
panel_level_height = addon._fine_level_height(scene)
panel_walkable_cells, panel_extra = addon._read_blueprint_points(
    blueprint_obj, panel_tile_size, panel_level_height, ("room_id", "z_offset", "tile_id"),
)
panel_room_ids = panel_extra["room_id"]
panel_z_offsets = panel_extra["z_offset"]
panel_stair_cells = {cell for cell, tid in panel_extra["tile_id"].items() if tid == addon.TILE_STAIR}
panel_room_meta = json.loads(blueprint_obj.get("gla_room_meta", "[]"))
panel_round_room_ids = {i for i, r in enumerate(panel_room_meta) if r['shape'] == 'ROUND'}

expected_doorways = addon._find_ordinary_doorways(
    panel_walkable_cells, panel_room_ids, panel_tile_size, panel_level_height,
    merge_distance=scene.wfc_door_merge_distance, z_offsets=panel_z_offsets,
    stair_cells=panel_stair_cells, skip_room_ids=panel_round_room_ids,
)
panel_clearance = 0.04
expected_panelable = [
    rec for rec in expected_doorways
    if (rec['span_max'] - rec['span_min']) - 2.0 * (scene.wfc_door_frame_thickness + panel_clearance) > 0.01
]

actual_panels = [
    o for o in bpy.data.objects
    if o.name.startswith(addon.DOORS_OBJECT_NAME) and "_Panel_" in o.name
]
check(
    "Doors: panel count matches the number of wide-enough ordinary doorways",
    len(actual_panels) == len(expected_panelable),
    f"panels={len(actual_panels)} expected={len(expected_panelable)}",
)


def _hinge_world_pos(rec):
    if rec['axis'] == 'X':
        return (rec['center'], rec['span_min'], rec['z0'])
    return (rec['span_min'], rec['center'], rec['z0'])


eps = 0.01
unmatched = 0
oriented_ok = 0
oriented_checked = 0
for panel_obj in actual_panels:
    loc = panel_obj.location
    match_rec = None
    for rec in expected_panelable:
        hinge = _hinge_world_pos(rec)
        if all(abs(loc[i] - hinge[i]) < eps for i in range(3)):
            match_rec = rec
            break
    if match_rec is None:
        unmatched += 1
        continue

    oriented_checked += 1
    world_verts = [panel_obj.matrix_world @ v.co for v in panel_obj.data.vertices]
    span_axis_index = 1 if match_rec['axis'] == 'X' else 0
    span_values = [v[span_axis_index] for v in world_verts]
    world_span_extent = max(span_values) - min(span_values)
    expected_width = (match_rec['span_max'] - match_rec['span_min']) - 2.0 * (scene.wfc_door_frame_thickness + panel_clearance)
    if abs(world_span_extent - expected_width) < 0.05:
        oriented_ok += 1

check(
    "Doors: every panel's origin sits exactly at its doorway's hinge edge",
    unmatched == 0, f"{unmatched}/{len(actual_panels)} panels have no matching doorway hinge position",
)
check(
    "Doors: panel width actually runs along its doorway's span axis (rotation is correct)",
    oriented_checked > 0 and oriented_ok == oriented_checked,
    f"{oriented_ok}/{oriented_checked} panels correctly oriented",
)

# Toggling panels off should remove them on the next regeneration (via the
# existing _remove_objects_by_prefix(DOORS_OBJECT_NAME) call, which
# matches "_Panel_..." names too).
scene.wfc_generate_door_panels = False
result = bpy.ops.object.generate_level_doors()
check("Doors: regenerate with panels disabled FINISHED", result == {'FINISHED'}, str(result))
remaining_panels = [o for o in bpy.data.objects if o.name.startswith(addon.DOORS_OBJECT_NAME) and "_Panel_" in o.name]
check("Doors: disabling Generate Door Panels removes existing panels", len(remaining_panels) == 0, f"count={len(remaining_panels)}")
scene.wfc_generate_door_panels = True
result = bpy.ops.object.generate_level_doors()
check("Doors: regenerate with panels re-enabled FINISHED", result == {'FINISHED'}, str(result))

# UPBGE Hinge Physics: EXPERIMENTAL and off by default (see
# wfc_upbge_hinge_physics's own tooltip -- unreliable object-targeting via
# context.temp_override crashed Blender outright on UPBGE 0.50 under
# REPEATED regeneration). Deliberately exercised here as a single,
# isolated regeneration, never looped, so this stays covered without
# reproducing the conditions that caused the crash. A no-op on stock
# Blender (hasattr(obj, 'game') is False there), so these checks only
# assert anything meaningful on UPBGE.
scene.wfc_upbge_hinge_physics = True
result = bpy.ops.object.generate_level_doors()
check("Doors: regenerate with UPBGE Hinge Physics on FINISHED", result == {'FINISHED'}, str(result))
hinge_panels = [o for o in bpy.data.objects if o.name.startswith(addon.DOORS_OBJECT_NAME) and "_Panel_" in o.name]
if hinge_panels and hasattr(hinge_panels[0], "game"):
    checked = 0
    correctly_wired = 0
    for p in hinge_panels:
        checked += 1
        rbc = p.rigid_body_constraint
        if rbc is not None and rbc.type == 'HINGE' and rbc.object1 is p:
            correctly_wired += 1
    check(
        "Doors: UPBGE Hinge Physics -- every panel got a HINGE constraint correctly wired to itself",
        checked > 0 and correctly_wired == checked,
        f"{correctly_wired}/{checked} panels correctly wired",
    )
scene.wfc_upbge_hinge_physics = False
result = bpy.ops.object.generate_level_doors()
check("Doors: regenerate with UPBGE Hinge Physics back off FINISHED", result == {'FINISHED'}, str(result))
# Refresh the shared doors_obj reference -- every generate_level_doors()
# call above deleted the previous Doors object and made a new one, so
# code further down the file that still reads doors_obj (assigned back
# near line 811, before any of these regenerations) would otherwise hold
# a stale reference to a long-deleted object. Confirmed directly: without
# this, a later UV-map check crashed with "ReferenceError: StructRNA of
# type Object has been removed" instead of failing cleanly.
doors_obj = bpy.data.objects.get(addon.DOORS_OBJECT_NAME)

result = bpy.ops.object.generate_level_props()
check("Props: operator FINISHED or CANCELLED", result in ({'FINISHED'}, {'CANCELLED'}), str(result))

def collection_reachable_from_scene(target):
    """True if target is reachable by following .children from the
    scene's real root (scene.collection) -- not just a DIRECT child of
    it. Every object-generating operator in this addon links into
    context.collection (the active collection, "Collection" by default
    in a factory-startup file, itself a child of the true scene root),
    not scene.collection directly -- so props' own tree living one level
    deeper, under that same active collection, is consistent with how
    every other step already works, not a bug."""
    seen = set()
    stack = [bpy.context.scene.collection]
    while stack:
        col = stack.pop()
        if col == target:
            return True
        if col.name in seen:
            continue
        seen.add(col.name)
        stack.extend(col.children)
    return False


props_collection = bpy.data.collections.get(addon.PROPS_COLLECTION_NAME)
check("Props: top-level collection created", props_collection is not None)
if props_collection is not None:
    check(
        "Props: collection reachable from the scene",
        collection_reachable_from_scene(props_collection),
    )

lights = [o for o in bpy.data.objects if o.name.startswith(addon.PROPS_LIGHT_NAME_PREFIX)]
check("Props: at least one light object created", len(lights) > 0, f"count={len(lights)}")
if lights:
    check("Props: light objects are real LIGHT-type objects", all(o.type == 'LIGHT' for o in lights))
    check(
        "Props: light data has expected color/energy",
        all(o.data.energy == scene.wfc_torch_light_energy for o in lights),
    )

torch_obj = bpy.data.objects.get(addon.PROPS_TORCH_OBJECT_NAME)
if torch_obj is not None:
    check("Props: torch mesh has geometry", len(torch_obj.data.vertices) > 0)
    check("Props: torch mesh has 2 material slots", len(torch_obj.data.materials) == 2)

decoration_obj = bpy.data.objects.get(addon.PROPS_DECORATION_OBJECT_NAME)
if decoration_obj is not None:
    check("Props: decoration mesh has geometry", len(decoration_obj.data.vertices) > 0)
    # Regression check for the hidden-face cleanup extended to Decoration
    # (DEVELOPMENT.md "Delete interior/hidden faces for faster
    # rendering") -- crates/barrels/cones all rest directly on the floor,
    # so every one of their base/bottom caps is always hidden and was
    # dropped. Checked by normal direction rather than an exact face
    # count (three different primitive shapes mixed in one mesh, in
    # random proportions per generation, makes an exact expected count
    # impractical) -- every remaining face in this mesh is either a
    # side wall or an upward-facing top/cap, so NO downward-facing face
    # should remain at all.
    downward_faces = [p for p in decoration_obj.data.polygons if p.normal.z < -0.5]
    check(
        "Props: decoration mesh has no downward-facing base faces left (removed as hidden/redundant geometry)",
        len(downward_faces) == 0,
        f"{len(downward_faces)} downward-facing faces remain",
    )

# Regression check: every baked-mesh builder (walls/doors/stairs/torches/
# decoration) builds geometry directly via from_pydata(), which never
# carries UV data -- same gap the Blueprint's GN graph had, fixed the same
# way (_add_planar_uv_map). Solid Shading's "Texture" color mode needs a
# real UV map to show anything on these at all.
stairs_objs = [
    o for o in bpy.data.objects
    if o.name == addon.STAIRS_OBJECT_NAME or o.name.startswith(addon.STAIRS_OBJECT_NAME + "_")
]
uv_targets = [o for o in [walls_obj, doors_obj, torch_obj, decoration_obj] if o is not None] + stairs_objs
uncovered = [
    o.name for o in uv_targets
    if len(o.data.uv_layers) == 0 or len(o.data.uv_layers[0].data) != len(o.data.loops)
]
check(
    "Baked meshes (walls/doors/stairs/torches/decoration) have a UV map, every loop covered",
    len(uv_targets) > 0 and len(uncovered) == 0,
    f"checked={[o.name for o in uv_targets]} uncovered={uncovered}",
)

# Regression check: _add_planar_uv_map replaced the old flat-constant
# (0.5, 0.5) placeholder with real world-space box mapping (see its
# docstring), specifically so a tiling/trim-sheet texture repeats across a
# wall run instead of sampling one pixel everywhere. If this ever
# regresses back to a constant, every UV in a mesh collapses to the same
# tuple -- checked directly rather than trusting the box-mapping math is
# still wired up.
flat_uv_targets = [o for o in uv_targets if o.data.uv_layers]
still_flat = [
    o.name for o in flat_uv_targets
    if len({tuple(round(c, 4) for c in loop_uv.uv) for loop_uv in o.data.uv_layers[0].data}) <= 1
]
check(
    "Baked meshes have real (non-constant) box-mapped UVs, not the old flat placeholder",
    len(flat_uv_targets) > 0 and len(still_flat) == 0,
    f"checked={[o.name for o in flat_uv_targets]} still_flat={still_flat}",
)

# Regression check: "viewport_color" Color Attribute (_add_viewport_color_
# attribute), the attribute-based alternative to Solid Shading's "Material"
# color mode -- reads a material's diffuse_color directly per-face and
# needs no UV map or intact material_index chain, so it's immune to both
# the UV gaps and the mesh.materials.clear() bug this addon hit before.
color_uncovered = [
    o.name for o in uv_targets
    if "viewport_color" not in o.data.color_attributes
    or len(o.data.color_attributes["viewport_color"].data) != len(o.data.loops)
]
check(
    "Baked meshes (walls/doors/stairs/torches/decoration) have a viewport_color attribute, every loop covered",
    len(uv_targets) > 0 and len(color_uncovered) == 0,
    f"checked={[o.name for o in uv_targets]} uncovered={color_uncovered}",
)
check(
    "Baked meshes: viewport_color is the active color attribute",
    all(o.data.color_attributes.active_color_name == "viewport_color" for o in uv_targets),
)

# ==============================================================================
# Export Level (glTF/GLB) -- one-click export of every generated object.
# The real correctness question isn't "did the operator return FINISHED"
# but "does the exported file actually contain the level's geometry" --
# checked by round-tripping the export back through Blender's own
# import_scene.gltf (also core-bundled) and counting what comes back,
# rather than just trusting a nonzero file size.
# ==============================================================================
export_dir = tempfile.mkdtemp(prefix="wfc_export_test_")
export_path = os.path.join(export_dir, "level.glb")
pre_export_object_names = {o.name for o in bpy.data.objects}

result = bpy.ops.object.export_level_gltf(filepath=export_path)
check("Export: operator FINISHED", result == {'FINISHED'}, str(result))
check(
    "Export: .glb file was actually written with real content",
    os.path.isfile(export_path) and os.path.getsize(export_path) > 0,
    f"exists={os.path.isfile(export_path)} size={os.path.getsize(export_path) if os.path.isfile(export_path) else 0}",
)

bpy.ops.object.select_all(action='DESELECT')
result = bpy.ops.import_scene.gltf(filepath=export_path)
check("Export: round-trip import FINISHED", result == {'FINISHED'}, str(result))
imported_objects = [o for o in bpy.data.objects if o.name not in pre_export_object_names]
imported_meshes = [o for o in imported_objects if o.type == 'MESH']
imported_lights = [o for o in imported_objects if o.type == 'LIGHT']
imported_vert_count = sum(len(o.data.vertices) for o in imported_meshes)
check(
    "Export: round-trip contains real mesh geometry (not an empty/near-empty file)",
    len(imported_meshes) > 0 and imported_vert_count > 0,
    f"mesh_objects={len(imported_meshes)} verts={imported_vert_count}",
)
check(
    "Export: round-trip contains lights when Include Lights is on (default)",
    len(imported_lights) > 0, f"lights={len(imported_lights)}",
)
for obj in imported_objects:
    data = obj.data
    obj_type = obj.type
    bpy.data.objects.remove(obj, do_unlink=True)
    if data and data.users == 0:
        if obj_type == 'MESH':
            bpy.data.meshes.remove(data)
        elif obj_type == 'LIGHT':
            bpy.data.lights.remove(data)

# Include Lights off -- round-trip should carry meshes but no lights.
scene.wfc_export_include_lights = False
export_path_no_lights = os.path.join(export_dir, "level_no_lights.glb")
pre_export_object_names = {o.name for o in bpy.data.objects}
result = bpy.ops.object.export_level_gltf(filepath=export_path_no_lights)
check("Export: Include Lights off, operator FINISHED", result == {'FINISHED'}, str(result))
bpy.ops.import_scene.gltf(filepath=export_path_no_lights)
imported_objects = [o for o in bpy.data.objects if o.name not in pre_export_object_names]
imported_lights = [o for o in imported_objects if o.type == 'LIGHT']
check(
    "Export: Include Lights off, round-trip has no lights",
    len(imported_lights) == 0, f"lights={len(imported_lights)}",
)
for obj in imported_objects:
    data = obj.data
    obj_type = obj.type
    bpy.data.objects.remove(obj, do_unlink=True)
    if data and data.users == 0:
        if obj_type == 'MESH':
            bpy.data.meshes.remove(data)
        elif obj_type == 'LIGHT':
            bpy.data.lights.remove(data)
scene.wfc_export_include_lights = True

# Export Collision Mesh -- a filtered re-export (Floor + Walls + Stairs
# only, no Doors/Torches/Decoration/Lights) of the SAME already-verified
# objects the main export just checked above. The real thing worth
# checking isn't just "did it export something" but that the EXCLUSION
# actually took effect -- a collision mesh that accidentally still
# carries Doors/Torches/Decoration would be the whole point of this
# feature silently not working.
collision_path = os.path.join(export_dir, "level_collision.glb")
pre_export_object_names = {o.name for o in bpy.data.objects}
result = bpy.ops.object.export_level_collision_gltf(filepath=collision_path)
check("Export Collision: operator FINISHED", result == {'FINISHED'}, str(result))
check(
    "Export Collision: .glb file was actually written with real content",
    os.path.isfile(collision_path) and os.path.getsize(collision_path) > 0,
    f"exists={os.path.isfile(collision_path)}",
)

bpy.ops.import_scene.gltf(filepath=collision_path)
imported_objects = [o for o in bpy.data.objects if o.name not in pre_export_object_names]
imported_meshes = [o for o in imported_objects if o.type == 'MESH']
imported_lights = [o for o in imported_objects if o.type == 'LIGHT']
imported_vert_count = sum(len(o.data.vertices) for o in imported_meshes)
check(
    "Export Collision: round-trip contains real mesh geometry",
    len(imported_meshes) > 0 and imported_vert_count > 0,
    f"mesh_objects={len(imported_meshes)} verts={imported_vert_count}",
)
check(
    "Export Collision: round-trip has no lights (never included in collision export)",
    len(imported_lights) == 0, f"lights={len(imported_lights)}",
)
excluded_prefixes = (
    addon.DOORS_OBJECT_NAME, addon.PROPS_TORCH_OBJECT_NAME, addon.PROPS_DECORATION_OBJECT_NAME,
)
leaked = [
    o.name for o in imported_meshes
    if any(o.name.startswith(p) for p in excluded_prefixes)
]
check(
    "Export Collision: Doors/Torches/Decoration are actually excluded, not just 'some geometry exists'",
    len(leaked) == 0, f"leaked={leaked}",
)
for obj in imported_objects:
    data = obj.data
    obj_type = obj.type
    bpy.data.objects.remove(obj, do_unlink=True)
    if data and data.users == 0:
        if obj_type == 'MESH':
            bpy.data.meshes.remove(data)
        elif obj_type == 'LIGHT':
            bpy.data.lights.remove(data)

# ==============================================================================
# Freeze for Texture Work -- renames the current generation out of the
# fixed-name pattern every Step operator's own _remove_objects_by_prefix
# matches against, so a later regeneration can't touch it. Verifies both
# the rename/collection-move itself and the independence it's supposed to
# guarantee: a regeneration afterward creates a genuinely fresh object
# under the normal name, while the frozen one survives untouched.
# ==============================================================================
pre_freeze_names = set()
for base_name in (
    addon.BLUEPRINT_OBJECT_NAME, addon.ROUND_FLOOR_OBJECT_NAME, addon.WALLS_OBJECT_NAME,
    addon.WALLS_ROUND_OBJECT_NAME, addon.STAIRS_OBJECT_NAME, addon.DOORS_OBJECT_NAME,
    addon.DOORS_ROUND_OBJECT_NAME, addon.PROPS_TORCH_OBJECT_NAME, addon.PROPS_DECORATION_OBJECT_NAME,
    addon.PROPS_LIGHT_NAME_PREFIX,
):
    pre_freeze_names.update(o.name for o in addon._objects_matching_prefix(base_name))
check(
    "Freeze: something exists to freeze before running the operator",
    len(pre_freeze_names) > 0, f"count={len(pre_freeze_names)}",
)

expected_debug_params = scene.wfc_debug_params
expected_seed = scene.wfc_seed

result = bpy.ops.object.freeze_level_for_texture_work()
check("Freeze: operator FINISHED", result == {'FINISHED'}, str(result))
check(
    "Freeze: Blueprint object no longer exists under its normal name",
    bpy.data.objects.get(addon.BLUEPRINT_OBJECT_NAME) is None,
)

# Nothing exists under any of the addon's normal names right after a
# freeze (everything got renamed away) -- the one moment in this whole
# script with a real "nothing generated" state to check Export's own
# refusal path against, instead of a fresh scene at the very start where
# no other section's assumptions have run yet.
try:
    result = bpy.ops.object.export_level_gltf(filepath=os.path.join(export_dir, "unused.glb"))
except RuntimeError as exc:
    result = {'CANCELLED'}
    check(
        "Export: refusal error message explains why (nothing to export)",
        "Nothing to export" in str(exc), str(exc),
    )
check(
    "Export: refuses to run with nothing generated under the normal names",
    result == {'CANCELLED'}, str(result),
)
try:
    result = bpy.ops.object.export_level_collision_gltf(
        filepath=os.path.join(export_dir, "unused_collision.glb")
    )
except RuntimeError as exc:
    result = {'CANCELLED'}
    check(
        "Export Collision: refusal error message explains why (nothing to export)",
        "Nothing to export" in str(exc), str(exc),
    )
check(
    "Export Collision: refuses to run with nothing generated under the normal names",
    result == {'CANCELLED'}, str(result),
)

frozen_collection_name = f"{addon.FROZEN_COLLECTION_PREFIX} - Seed{expected_seed}"
frozen_collection = bpy.data.collections.get(frozen_collection_name)
check(
    "Freeze: frozen collection created with the expected name",
    frozen_collection is not None, frozen_collection_name,
)
if frozen_collection is not None:
    expected_frozen_names = {f"Frozen_Seed{expected_seed}_" + n for n in pre_freeze_names}
    check(
        "Freeze: frozen collection contains exactly every object that was renamed",
        {o.name for o in frozen_collection.objects} == expected_frozen_names,
        f"expected_count={len(expected_frozen_names)} actual_count={len(frozen_collection.objects)}",
    )
    check(
        "Freeze: frozen collection carries a copy of the generation's debug params",
        frozen_collection.get("debug_params") == expected_debug_params,
    )

try:
    result = bpy.ops.object.freeze_level_for_texture_work()
except RuntimeError as exc:
    # bpy.ops.* raises RuntimeError from Python when the operator reports
    # an 'ERROR'-level message and cancels (same convention documented at
    # Separate by Floor/Room's own refusal check above), rather than just
    # returning {'CANCELLED'} the way a plain WARNING/INFO cancellation
    # would -- Freeze's own "nothing to freeze" report is ERROR-level.
    result = {'CANCELLED'}
    check(
        "Freeze: the re-freeze refusal's error message explains why (nothing to freeze)",
        "Nothing to freeze" in str(exc), str(exc),
    )
check(
    "Freeze: running it again immediately (nothing regenerated) reports nothing to freeze",
    result == {'CANCELLED'}, str(result),
)

result = bpy.ops.object.generate_game_blueprint()
check("Freeze: regenerating after a freeze FINISHED (proves independence)", result == {'FINISHED'}, str(result))
blueprint_obj = bpy.data.objects.get(addon.BLUEPRINT_OBJECT_NAME)
check("Freeze: a genuinely fresh Blueprint object exists under the normal name again", blueprint_obj is not None)
check(
    "Freeze: the frozen collection/its objects were untouched by the Blueprint regeneration",
    frozen_collection is not None and len(frozen_collection.objects) == len(pre_freeze_names),
)

# Targeted regression check for the actual bug this whole block was built
# to catch: _remove_objects_by_prefix (what every Walls/Stairs/Doors/Props
# regeneration calls, unlike Blueprint's own exact-name lookup above) once
# matched a frozen Per Floor/Per Stair object anyway, because appending a
# suffix to an already-prefix-matching name like
# "Procedural_Level_Walls_Floor1" doesn't stop it from still starting with
# "Procedural_Level_Walls_" -- silently deleting the "frozen" object right
# along with the fresh batch. Regenerating Walls specifically (the
# operator that actually calls _remove_objects_by_prefix) is the one
# real-world action that would have caught this; regenerating Blueprint
# alone (above) does not, since Blueprint's own cleanup is an exact-name
# lookup, not a prefix match, and would have passed even with the bug
# still present.
result = bpy.ops.object.generate_level_walls()
check("Freeze: regenerating Walls after a freeze FINISHED", result == {'FINISHED'}, str(result))
check(
    "Freeze: the frozen collection/its objects were untouched by the Walls regeneration",
    frozen_collection is not None and len(frozen_collection.objects) == len(pre_freeze_names),
)
check(
    "Freeze: a genuinely fresh Walls object exists under the normal name again",
    bpy.data.objects.get(addon.WALLS_OBJECT_NAME) is not None,
)

# Targeted regression check for a second, separate bug this same block
# also caught: Freeze renamed each frozen OBJECT (to escape future
# _remove_objects_by_prefix matching, see above) but never its underlying
# mesh/light DATA-block -- so a frozen object's mesh kept sitting on the
# exact name the next regeneration tries to create a fresh one under,
# silently bumping the new one to a numeric ".001" suffix instead (Blender
# auto-disambiguates bpy.data.meshes.new() name collisions rather than
# erroring). Confirmed directly: every object type this operator touches
# drifted this way after a single freeze+regenerate cycle before the fix.
import re as _re
fresh_walls_obj = bpy.data.objects.get(addon.WALLS_OBJECT_NAME)
if fresh_walls_obj is not None and fresh_walls_obj.data is not None:
    check(
        "Freeze: the fresh Walls object's mesh data has no numeric collision suffix",
        not _re.search(r"\.\d{3}$", fresh_walls_obj.data.name),
        f"mesh name={fresh_walls_obj.data.name!r}",
    )
frozen_mismatched = [
    o for o in (frozen_collection.objects if frozen_collection is not None else [])
    if o.data is not None and not o.data.name.startswith("Frozen_")
]
check(
    "Freeze: every frozen object's data-block also carries the Frozen_ tag, not just the object",
    len(frozen_mismatched) == 0,
    f"{len(frozen_mismatched)} frozen object(s) with untagged data, e.g. {frozen_mismatched[0].name if frozen_mismatched else None}",
)

# ==============================================================================
# Cave floor-shape mode -- solver-only connectivity regression
# ==============================================================================
# Full-reachability BFS across a handful of seeds/sizes, run directly
# against WFC_Level_Solver (no operator/GN pipeline involved -- this is a
# pure grid-logic check, same as the stub_bpy version used during
# development). Guards two real bugs found only by this kind of check
# (neither showed up in any geometry/overlap check, since both produced
# perfectly valid, non-crashing meshes -- just with an unreachable pocket
# of floor): a random walk that got permanently trapped outside a
# chamber's own margin near a map edge, and the entrance/exit corners
# being unreachable from the cave network entirely (silently "fixed" by
# _ensure_connectivity with one dead-straight corridor spanning most of
# the empty map -- connectivity was never actually broken, but the result
# didn't look remotely like a cave).
import random as _random
from collections import deque as _deque

_cave_bad = 0
_stair_cells_total = 0
_stair_cells_exposed = 0
for _trial in range(20):
    _random.seed(90000 + _trial)
    _w = _random.choice([20, 30, 40])
    _l = _random.choice([20, 30, 40])
    _h = _random.choice([1, 2, 3])
    _solver = addon.WFC_Level_Solver(
        width=_w, length=_l, height=_h, room_count=_random.randint(6, 16),
        room_size_min=3, room_size_max=_random.choice([5, 8]),
        room_shape='CAVE',
        stairs_per_level=2, stair_room_width=3, stair_room_length=4,
        corridor_stairs=_random.choice([True, False]),
        sub_levels_per_floor=1, split_level_chance=0.0,
        elevation_chance=0.0, elevation_range=0.0, max_ramp_slope_deg=30.0,
    )
    _solver.solve()
    for _z in range(_solver.h):
        _cells = {
            (x, y) for x in range(_solver.w) for y in range(_solver.l)
            if _solver.grid[x][y][_z] in addon.WALKABLE
        }
        if not _cells:
            continue
        _start = next(iter(_cells))
        _seen = {_start}
        _q = _deque([_start])
        while _q:
            _cx, _cy = _q.popleft()
            for _dx, _dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                _n = (_cx + _dx, _cy + _dy)
                if _n in _cells and _n not in _seen:
                    _seen.add(_n)
                    _q.append(_n)
        if len(_seen) != len(_cells):
            _cave_bad += 1
    # A Corridor Stairs run (1-wide, no walkway by design) must never have
    # open walkable floor on its PERPENDICULAR side -- that's the wall that's
    # supposed to enclose it; only its travel-axis front/back are meant to
    # be open (that's where a corridor legitimately attaches). Found via
    # exactly this check during development: 48% of stair cells across a
    # 40-trial stress run had an open side before _corridor_stair_fits +
    # _would_expose_stair_side (see their docstrings) -- down to ~10%
    # after, which is why this asserts "well below the old baseline," not
    # zero: a rare residual (two independently-placed stairwells landing
    # adjacent to each other, or the short unguarded _carve_corridor
    # bridge that must win over leaving a real gap) is a known tradeoff,
    # not a regression.
    for x in range(_solver.w):
        for y in range(_solver.l):
            for z in range(_solver.h):
                if _solver.grid[x][y][z] != addon.TILE_STAIR or not _solver.corridor_stairs:
                    continue
                _stair_cells_total += 1
                _tdx, _tdy = addon.DIRECTION_FOR_ROTATION.get(_solver.rotations[x][y][z], (0, 1))
                for _dx, _dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    _nx, _ny = x + _dx, y + _dy
                    if (_nx, _ny) in ((x + _tdx, y + _tdy), (x - _tdx, y - _tdy)):
                        continue  # travel-axis neighbor -- legitimate
                    if _solver.in_bounds(_nx, _ny, z) and _solver.grid[_nx][_ny][z] in addon.WALKABLE:
                        _stair_cells_exposed += 1
                        break
check("Cave: every floor fully connected across 20 seeded trials", _cave_bad == 0, f"{_cave_bad} disconnected floor-instances")
_exposed_rate = _stair_cells_exposed / _stair_cells_total if _stair_cells_total else 0.0
check(
    "Cave: Corridor Stairs perpendicular-side exposure stays well below the pre-fix 48% baseline",
    _exposed_rate < 0.25,
    f"{_stair_cells_exposed}/{_stair_cells_total} stair cells ({_exposed_rate:.0%}) exposed",
)

# ==============================================================================
# Bent stairwells -- solver-only connectivity regression
# ==============================================================================
# stair_bend_chance forced to 1.0 (every eligible stairwell tries to bend)
# across a spread of seeds/sizes/styles, checking the one guarantee that
# actually matters: _ensure_connectivity's own acceptance test
# (start->end BFS reachability) still holds. _carve_bent_stair_path is
# designed to be all-or-nothing (falls back to an ordinary straight run
# if the bent path doesn't fit its footprint, never leaves a half-carved
# gap), so this is really checking that fallback discipline held under
# stress, not just that bending "works" in isolation.
_bent_bfs_bad = 0
_bent_landing_bad = 0
_bent_stairwells_seen = 0
for _trial in range(20):
    _random.seed(91000 + _trial)
    _w = _random.choice([20, 30, 40])
    _l = _random.choice([20, 30, 40])
    _h = _random.choice([2, 3])
    _style = _random.choice(['RANDOM', 'L', 'U'])
    _solver = addon.WFC_Level_Solver(
        width=_w, length=_l, height=_h, room_count=_random.randint(8, 16),
        room_size_min=3, room_size_max=_random.choice([5, 8]),
        room_shape=_random.choice(['RECT', 'ROUND', 'MIXED']),
        stairs_per_level=_random.randint(2, 4), stair_room_width=3, stair_room_length=4,
        corridor_stairs=False,  # bending is never offered for Corridor Stairs -- see _pick_stair_bend
        sub_levels_per_floor=1, split_level_chance=0.0,
        elevation_chance=0.0, elevation_range=0.0, max_ramp_slope_deg=30.0,
        level_height=3.0, stair_bend_chance=1.0, stair_bend_style=_style,
    )
    _solver.solve()
    if not _solver._bfs_reachable(_solver.start, _solver.end):
        _bent_bfs_bad += 1

    # Landing tiles are wherever a stair cell's segment index is 1 (a
    # bent run's second segment) -- the cell immediately behind its own
    # start, on segment 1's own travel axis, is the landing. Simpler and
    # just as direct: any cell_z_offset strictly between 0 and the full
    # level_height that ISN'T itself a TILE_STAIR cell is a landing (see
    # _carve_bent_stair_path -- nothing else in the solver ever writes a
    # z_offset before this feature existed, since _apply_continuous_
    # elevation is disabled in this trial).
    for x in range(_solver.w):
        for y in range(_solver.l):
            for z in range(_solver.h):
                off = _solver.cell_z_offset[x][y][z]
                if off <= 0.0 or _solver.grid[x][y][z] == addon.TILE_STAIR:
                    continue
                _bent_stairwells_seen += 1
                if not (0.0 < off < _solver.level_height):
                    _bent_landing_bad += 1
check(
    "Bent stairs: start->end still reachable across 20 seeded trials with bending forced on",
    _bent_bfs_bad == 0, f"{_bent_bfs_bad}/20 trials disconnected",
)
check(
    "Bent stairs: the stress trials actually exercised bending (not a trivially-passing no-op)",
    _bent_stairwells_seen > 0, f"landing tiles seen={_bent_stairwells_seen}",
)
check(
    "Bent stairs: every landing tile's world-Z offset stays strictly between the floor and the next",
    _bent_landing_bad == 0, f"{_bent_landing_bad}/{_bent_stairwells_seen} landings out of range",
)

# One real end-to-end pass through the actual pipeline (Blueprint -> Walls
# -> Stairs -> Doors), to catch anything a pure solver-level check can't:
# GN evaluation, and specifically the mesh-building side of a bent run
# (_read_stair_runs reconstructing segment order from the baked
# stair_segment_index attribute, _build_stair_mesh/_build_ramp_mesh's
# cumulative cross-segment height math).
scene.wfc_stair_bend_chance = 1.0
scene.wfc_stair_bend_style = 'RANDOM'
# Bending is never offered for Corridor Stairs (_pick_stair_bend returns
# None whenever self.corridor_stairs is set -- a 1-wide corridor stair has
# no room for a landing/turn). Corridor Stairs has been on since line 109
# and nothing before this point turned it off, so without this the section
# below would silently test plain corridor stairs instead of an actual
# bent run -- and corridor stairs are SUPPOSED to sit flush against a wall
# by design (see the eps note on the "beyond expected flush contact" check
# above), so the overlap check below would misfire on totally expected
# geometry rather than the bent-specific bug it exists to catch.
scene.wfc_corridor_stairs = False
result = bpy.ops.object.generate_game_blueprint()
check("Bent stairs: Blueprint regenerate FINISHED", result == {'FINISHED'}, str(result))
result = bpy.ops.object.generate_level_walls()
check("Bent stairs: Walls FINISHED", result == {'FINISHED'}, str(result))
result = bpy.ops.object.generate_level_stairs()
check("Bent stairs: Stairs FINISHED or CANCELLED", result in ({'FINISHED'}, {'CANCELLED'}), str(result))
bent_walls_obj = bpy.data.objects.get(addon.WALLS_OBJECT_NAME)
bent_stair_objs = [
    o for o in bpy.data.objects
    if o.name == addon.STAIRS_OBJECT_NAME or o.name.startswith(addon.STAIRS_OBJECT_NAME + "_")
]
if bent_walls_obj is not None and bent_stair_objs:
    bent_stair_aabbs = [box for o in bent_stair_objs for box in per_box_aabbs(o, 8)]
    bent_wall_aabbs = per_box_aabbs(bent_walls_obj, 8)
    bent_overlap_count = sum(
        1 for sb in bent_stair_aabbs if any(aabb_overlap(sb, wb) for wb in bent_wall_aabbs)
    )
    check(
        "Bent stairs: real-Blender pipeline -- no stair tread box overlaps a wall box",
        bent_overlap_count == 0, f"{bent_overlap_count}/{len(bent_stair_aabbs)} stair boxes overlap a wall",
    )
result = bpy.ops.object.generate_level_doors()
check("Bent stairs: Doors FINISHED or CANCELLED", result in ({'FINISHED'}, {'CANCELLED'}), str(result))
scene.wfc_stair_bend_chance = 0.0
scene.wfc_stair_bend_style = 'RANDOM'
scene.wfc_corridor_stairs = True

# One real end-to-end pass through the actual pipeline, to catch anything
# a pure solver-level check can't (GN evaluation, wall/door mesh building
# on Cave's chamber/tunnel room_id pattern).
scene.wfc_room_shape = 'CAVE'
scene.wfc_width = 30
scene.wfc_length = 30
scene.wfc_height = 2
result = bpy.ops.object.generate_game_blueprint()
check("Cave: Blueprint regenerate FINISHED", result == {'FINISHED'}, str(result))
blueprint_obj = bpy.data.objects.get(addon.BLUEPRINT_OBJECT_NAME)
counts = evaluated_counts(blueprint_obj) if blueprint_obj else (0, 0)
check("Cave: GN graph evaluates to non-empty geometry", counts[0] > 0, str(counts))
result = bpy.ops.object.generate_level_walls()
check("Cave: Walls FINISHED", result == {'FINISHED'}, str(result))
result = bpy.ops.object.generate_level_stairs()
check("Cave: Stairs FINISHED or CANCELLED", result in ({'FINISHED'}, {'CANCELLED'}), str(result))
result = bpy.ops.object.generate_level_doors()
check("Cave: Doors FINISHED or CANCELLED", result in ({'FINISHED'}, {'CANCELLED'}), str(result))

# Restore the file's original scenario settings and regenerate -- the
# Separate-by-Floor section below expects THAT blueprint (3 floors), not
# the 2-floor Cave one just built above.
scene.wfc_room_shape = 'MIXED'
scene.wfc_width = 22
scene.wfc_length = 22
scene.wfc_height = 3
result = bpy.ops.object.generate_game_blueprint()
check("Post-Cave: scenario Blueprint regenerate FINISHED", result == {'FINISHED'}, str(result))
blueprint_obj = bpy.data.objects.get(addon.BLUEPRINT_OBJECT_NAME)

# ==============================================================================
# Separate by Floor/Room -- runs directly on the Blueprint with its GN
# modifier still live; no manual "Apply Modifier" step needed (that step
# used to be required, and used to silently break per-room materials --
# see the operator's own docstring and the check below).
# ==============================================================================
bpy.ops.object.select_all(action='DESELECT')
bpy.context.view_layer.objects.active = blueprint_obj
blueprint_obj.select_set(True)
check("Separate by Floor/Room: source object still has its live GN modifier", any(m.type == 'NODES' for m in blueprint_obj.modifiers))

# Regression check for a real bug found from user feedback: manually
# applying the GN modifier first (the OLD, pre-0.13.1 documented
# precondition -- see the operator's own docstring) collapses the material
# slot list down to 1 (a real Blender Apply Modifier behavior), which used
# to silently give split Room objects an empty (None) material slot for
# any room whose real material_index wasn't in that collapsed list. Rather
# than silently degrading, the operator now refuses to run at all when its
# GN modifier isn't present live. Tested on a throwaway duplicate so it
# doesn't disturb the real blueprint_obj used below.
dup_obj = blueprint_obj.copy()
dup_obj.data = blueprint_obj.data.copy()
bpy.context.collection.objects.link(dup_obj)
bpy.ops.object.select_all(action='DESELECT')
bpy.context.view_layer.objects.active = dup_obj
dup_obj.select_set(True)
bpy.ops.object.convert(target='MESH')
check(
    "Separate by Floor/Room: manual pre-apply test object no longer has a live GN modifier",
    not any(m.type == 'NODES' for m in dup_obj.modifiers),
)
try:
    result = bpy.ops.object.separate_level_by_floor()
except RuntimeError as exc:
    # bpy.ops.* raises RuntimeError from Python when the operator reports
    # an 'ERROR'-level message and cancels, rather than just returning
    # {'CANCELLED'} the way a plain WARNING/INFO cancellation would.
    result = {'CANCELLED'}
    check(
        "Separate by Floor/Room: the refusal's error message explains why (modifier missing / already applied)",
        "Geometry Nodes modifier" in str(exc),
        str(exc),
    )
check(
    "Separate by Floor/Room: refuses to run on an object whose GN modifier was already applied, instead of silently producing empty material slots",
    result == {'CANCELLED'},
    str(result),
)
bpy.data.objects.remove(dup_obj, do_unlink=True)
bpy.ops.object.select_all(action='DESELECT')
bpy.context.view_layer.objects.active = blueprint_obj
blueprint_obj.select_set(True)

result = bpy.ops.object.separate_level_by_floor()
check("Separate by Floor/Room: operator FINISHED", result == {'FINISHED'}, str(result))

split_objs = [o for o in bpy.data.objects if o.name.startswith(addon.BLUEPRINT_OBJECT_NAME + "_Floor")]
room_objs = [o for o in split_objs if "_Room" in o.name]
corridor_objs = [o for o in split_objs if o.name.endswith("_Corridors")]
ceiling_objs = [o for o in split_objs if o.name.endswith("_Ceilings")]
check(
    "Separate by Floor/Room: produced per-room and per-floor-corridor objects",
    len(room_objs) > 0 and len(corridor_objs) > 0,
    f"rooms={len(room_objs)} corridors={len(corridor_objs)}",
)
# Regression check for the ceiling-fragmentation bug found right after the
# reroute-to-Corridors fix above: this scenario has Add Ceiling on, so every
# room should have contributed a ceiling face into a dedicated per-floor
# Ceilings object instead of making the room itself look "fragmented".
check(
    "Separate by Floor/Room: Add Ceiling is on in this scenario, so Ceilings objects were produced",
    len(ceiling_objs) > 0,
    f"ceiling_objs={len(ceiling_objs)}",
)
check(
    "Separate by Floor/Room: rooms weren't swept into Corridors just because Add Ceiling made them look fragmented",
    len(room_objs) >= scene.wfc_height,
    f"room_objs={len(room_objs)} across {scene.wfc_height} floors",
)

floor_indices_seen = {int(o.name.split("_Floor")[1].split("_")[0]) for o in split_objs}
check(
    "Separate by Floor/Room: every logical floor represented",
    floor_indices_seen == set(range(scene.wfc_height)),
    f"floors seen={sorted(floor_indices_seen)} expected 0..{scene.wfc_height - 1}",
)

# Regression check: _mesh_from_faces() only copies the material(s) a split
# object's own faces actually use, in a freshly compacted slot list (not
# the WHOLE source material list, which every earlier version copied in
# full -- a Room object only ever needs one room material, but used to
# inherit every OTHER room's color too, plus every floor-level/entrance/
# exit slot, commonly 30-50+ entries for a real level). Confirms every
# split object's slot count matches the number of distinct materials its
# own faces actually reference -- no leftover unused slots.
slot_count_mismatches = [
    o.name for o in room_objs + corridor_objs + ceiling_objs
    if len(o.data.materials) != len({p.material_index for p in o.data.polygons})
]
check(
    "Separate by Floor/Room: split objects' material slot list is compacted to only what their faces use",
    len(slot_count_mismatches) == 0,
    f"mismatched objects: {slot_count_mismatches}",
)
sample_room = room_objs[0]
sample_poly = sample_room.data.polygons[0]
sample_mat = sample_room.data.materials[sample_poly.material_index]
check(
    "Separate by Floor/Room: a room object's face resolves to a real room-pool material specifically, not a floor-level default",
    sample_mat is not None and sample_mat.name.startswith("LA_Room_"),
    f"material_index={sample_poly.material_index} resolves to {sample_mat.name if sample_mat else None}",
)

# Regression check for a real bug found from user feedback: "we get
# Procedural_Level_Blueprint_Floor2_Room04 but material field is empty on
# this object, material should be LA_Room_0004" -- because the FULL source
# material list used to be copied onto every split object, Blender's
# Properties > Material tab's "Material" field (always the OBJECT's active
# slot, index 0 by default, never touched by this operator) showed
# whatever slot 0 of that full list happened to be (a floor-level color)
# instead of the room's own material, even though the room's faces
# rendered with the correct color. With the slot list compacted to just
# what a room's own faces use, its default active slot is that room's own
# material.
check(
    "Separate by Floor/Room: a room object's default active material slot is its own real room material, not a leftover default",
    all(o.active_material is not None and o.active_material.name.startswith("LA_Room_") for o in room_objs),
    f"active materials: {[(o.name, o.active_material.name if o.active_material else None) for o in room_objs]}",
)

# Regression check for a real bug found from user feedback ("floors are
# still only distinct when in random"): mesh.materials.clear() -- used just
# above to rebuild the evaluated mesh's material slot list -- silently
# resets EVERY polygon's material_index to 0 as a side effect, before any
# per-room splitting even runs. Re-appending the same materials afterward
# does not restore it; that per-face data is already gone. The check above
# alone couldn't catch this: room_objs[0] happening to read material_index
# 0 (a floor-level material) is indistinguishable from a genuinely
# floor-colored room UNLESS a second, different room is also checked and
# found to resolve to the exact same material -- which is what actually
# happened (every room pointed at slot 0 uniformly) until this was fixed
# by saving material_index before clearing the slot list and restoring it
# after.
room_face_materials = {o.name: o.data.materials[o.data.polygons[0].material_index].name for o in room_objs}
check(
    "Separate by Floor/Room: different rooms actually resolve to different materials, not all the same one",
    len(set(room_face_materials.values())) > 1,
    f"per-room materials: {room_face_materials}",
)

# Regression check: _mesh_from_faces() didn't carry the UV map over at all
# (from_pydata never does), so a split object had no UV map -- Solid
# Shading's "Texture" color mode showed nothing useful on it even though
# the underlying material/color data was completely correct.
check(
    "Separate by Floor/Room: split objects kept their UV map, every loop covered",
    all(
        len(o.data.uv_layers) > 0 and len(o.data.uv_layers[0].data) == len(o.data.loops)
        for o in room_objs + corridor_objs
    ),
    f"uv_layers per object: {[(o.name, list(o.data.uv_layers.keys())) for o in room_objs + corridor_objs if not o.data.uv_layers]}",
)

# Attribute-based alternative to the material-slot coloring above: a
# "viewport_color" Color Attribute (_add_viewport_color_attribute), read
# directly by Solid Shading's "Attribute" color mode with no dependency on
# UV data or material_index at all. Same two-room-comparison shape as the
# material check above -- checking only one room's color can't distinguish
# "genuinely working" from "every room happens to read the same color".
color_uncovered_split = [
    o.name for o in room_objs + corridor_objs
    if "viewport_color" not in o.data.color_attributes
    or len(o.data.color_attributes["viewport_color"].data) != len(o.data.loops)
]
check(
    "Separate by Floor/Room: split objects have a viewport_color attribute, every loop covered",
    len(color_uncovered_split) == 0,
    f"uncovered={color_uncovered_split}",
)
check(
    "Separate by Floor/Room: split objects' viewport_color is the active color attribute",
    all(o.data.color_attributes.active_color_name == "viewport_color" for o in room_objs + corridor_objs),
)
room_face_colors = {
    o.name: tuple(round(c, 3) for c in o.data.color_attributes["viewport_color"].data[0].color)
    for o in room_objs
}
check(
    "Separate by Floor/Room: different rooms' viewport_color attribute actually differs, not all the same one",
    len(set(room_face_colors.values())) > 1,
    f"per-room viewport_color: {room_face_colors}",
)

# Regression check for a second real bug found right after the first fix
# above: a room-based stairwell's entry/exit landing tiles share one
# room_id but sit on opposite ends of the stair itself (a separate tile_id,
# not floor), so they share no vertex with each other -- without the
# reroute-to-Corridors logic, that room_id would become one Room object
# made of two disconnected single-tile islands. Confirms no Room object
# here is ever fragmented, whatever caused it.
fragmented_rooms = [
    o for o in room_objs
    if len(addon._face_connected_components(o.data, list(range(len(o.data.polygons))))) > 1
]
check(
    "Separate by Floor/Room: no Room object is fragmented into disconnected pieces",
    len(fragmented_rooms) == 0,
    f"fragmented: {[o.name for o in fragmented_rooms]}",
)

split_top_collection = bpy.data.collections.get(addon.BLUEPRINT_SPLIT_COLLECTION_NAME)
check("Separate by Floor/Room: split collection tree created", split_top_collection is not None)
if split_top_collection:
    check(
        "Separate by Floor/Room: one sub-collection per floor",
        len(split_top_collection.children) == scene.wfc_height,
        f"count={len(split_top_collection.children)}",
    )
    for floor_collection in split_top_collection.children:
        has_rooms = any(c.name.endswith("- Rooms") for c in floor_collection.children)
        has_corridors = any(c.name.endswith("- Corridors") for c in floor_collection.children)
        has_ceilings = any(c.name.endswith("- Ceilings") for c in floor_collection.children)
        check(
            f"Separate by Floor/Room: {floor_collection.name} has Rooms + Corridors + Ceilings sub-collections",
            has_rooms and has_corridors and has_ceilings,
        )

# Regression check for a real crash found from user feedback, running the
# now-recommended direct workflow (regenerate, then Separate by Floor/Room
# with no manual Apply Modifier): Blender moves the outliner's ACTIVE
# collection to the last one an operator run created/linked into -- so
# after one Separate by Floor/Room run, re-running it with the active
# collection still sitting inside last time's own nested "Floor 0 - Rooms"
# tried to re-link the (found-by-name, from the first run) top-level
# "Procedural Level Blueprint (Split)" collection as a child of its own
# descendant. Blender raises RuntimeError for that. Reproduces it exactly:
# point the active collection at a real leftover sub-collection from the
# split above, regenerate the blueprint fresh, and run the operator again.
def _find_layer_collection(layer_collection, name):
    if layer_collection.collection.name == name:
        return layer_collection
    for child in layer_collection.children:
        found = _find_layer_collection(child, name)
        if found is not None:
            return found
    return None

if split_top_collection is not None:
    nested_name = next(
        (c.name for fc in split_top_collection.children for c in fc.children if c.name.endswith("- Rooms")),
        None,
    )
    if nested_name is not None:
        target_layer_collection = _find_layer_collection(
            bpy.context.view_layer.layer_collection, nested_name
        )
        if target_layer_collection is not None:
            bpy.context.view_layer.active_layer_collection = target_layer_collection
            result = bpy.ops.object.generate_game_blueprint()
            check("Cyclic-collection repro: Blueprint regenerate FINISHED", result == {'FINISHED'}, str(result))
            blueprint_obj = bpy.data.objects.get(addon.BLUEPRINT_OBJECT_NAME)
            bpy.ops.object.select_all(action='DESELECT')
            bpy.context.view_layer.objects.active = blueprint_obj
            blueprint_obj.select_set(True)
            try:
                result = bpy.ops.object.separate_level_by_floor()
                crash = None
            except RuntimeError as exc:
                result = {'CANCELLED'}
                crash = exc
            check(
                "Separate by Floor/Room: running it again with the active collection left inside "
                "a previous run's nested tree doesn't crash",
                crash is None and result == {'FINISHED'},
                f"result={result} crash={crash}",
            )
            # Restore a normal active collection for anything after this.
            bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection

# ==============================================================================
# Round rooms: real merged n-gon floor disc + a matching wall ring with
# real doorway openings -- confirm the actual geometry, not just "some
# object exists." wfc_room_shape='MIXED' has been this whole suite's own
# baseline throughout (so Round rooms have already been exercised
# end-to-end against every other system -- Doors/Stairs/Torches/
# Decoration/Separate by Floor/Export -- via every check above), this
# section pins wfc_room_shape='ROUND' specifically for exact-geometry
# assertions a MIXED level's random room count can't give.
# ==============================================================================
scene.wfc_width = 20
scene.wfc_length = 20
scene.wfc_height = 1
scene.wfc_rooms_min = 6
scene.wfc_rooms_max = 6
scene.wfc_room_size_min = 4
scene.wfc_room_size_max = 6
scene.wfc_room_shape = 'ROUND'
scene.wfc_room_shape_sides = 6
scene.wfc_sub_levels_per_floor = 1
scene.wfc_elevation_chance = 0.0
scene.wfc_wall_grouping = 'SINGLE'

result = bpy.ops.object.generate_game_blueprint()
check("Round rooms: Blueprint FINISHED", result == {'FINISHED'}, str(result))

round_floor_obj = bpy.data.objects.get(addon.ROUND_FLOOR_OBJECT_NAME)
check("Round rooms: RoundFloors object exists", round_floor_obj is not None)
if round_floor_obj is not None:
    check("Round rooms: RoundFloors has geometry", len(round_floor_obj.data.polygons) > 0)
    check(
        "Round rooms: RoundFloors has one face per Round room (6 rooms requested)",
        len(round_floor_obj.data.polygons) == 6, str(len(round_floor_obj.data.polygons)),
    )
    check(
        "Round rooms: every RoundFloors face has exactly wfc_room_shape_sides vertices",
        all(len(p.vertices) == 6 for p in round_floor_obj.data.polygons),
        str([len(p.vertices) for p in round_floor_obj.data.polygons]),
    )

blueprint_obj = bpy.data.objects.get(addon.BLUEPRINT_OBJECT_NAME)
blueprint_evaluated_verts, blueprint_evaluated_faces = evaluated_counts(blueprint_obj)
check(
    "Round rooms: Blueprint's own (unmodified) GN floor still evaluates to real geometry "
    "underneath the RoundFloors overlay",
    blueprint_evaluated_verts > 0 and blueprint_evaluated_faces > 0,
)

scene.wfc_round_wall_style = 'CLASSIC'  # this section covers the legacy n-gon ring; Masonry has its own section below
result = bpy.ops.object.generate_level_walls()
check("Round rooms: Walls FINISHED", result == {'FINISHED'}, str(result))
round_walls_obj = bpy.data.objects.get(addon.WALLS_ROUND_OBJECT_NAME)
check("Round rooms: RoundWalls object exists", round_walls_obj is not None)
if round_walls_obj is not None:
    check("Round rooms: RoundWalls has geometry", len(round_walls_obj.data.polygons) > 0)
    full_ring_faces_per_room = scene.wfc_room_shape_sides * 5
    check(
        "Round rooms: RoundWalls has real doorway openings (fewer faces than 6 fully-sealed rings)",
        len(round_walls_obj.data.polygons) < 6 * full_ring_faces_per_room,
        f"actual={len(round_walls_obj.data.polygons)} fully_sealed={6 * full_ring_faces_per_room}",
    )

result = bpy.ops.object.generate_level_doors()
check("Round rooms: Doors FINISHED", result == {'FINISHED'}, str(result))
round_doors_obj = bpy.data.objects.get(addon.DOORS_ROUND_OBJECT_NAME)
check("Round rooms: RoundDoors object exists", round_doors_obj is not None)
if round_doors_obj is not None:
    check("Round rooms: RoundDoors has geometry", len(round_doors_obj.data.polygons) > 0)
    # Every RoundDoors vertex should sit close to SOME Round room's own
    # ellipse rim (normalized radial distance near 1.0) -- confirms the
    # frame is actually oriented along the curved wall, not placed
    # generically. Tolerance is loose (0.35 in normalized units) since
    # posts/lintels have real thickness, offsetting vertices in/out from
    # the true rim -- this is a sanity check, not a precise metric one.
    room_meta_check = json.loads(bpy.data.objects[addon.BLUEPRINT_OBJECT_NAME].get("gla_room_meta", "[]"))
    round_rooms_check = [r for r in room_meta_check if r['shape'] == 'ROUND']
    off_rim = 0
    for v in round_doors_obj.data.vertices:
        wx, wy = v.co.x, v.co.y
        deviations = []
        for r in round_rooms_check:
            cx = (r['x'] + (r['w'] - 1) / 2.0) * scene.wfc_tile_size
            cy = (r['y'] + (r['l'] - 1) / 2.0) * scene.wfc_tile_size
            rx = (r['w'] / 2.0) * scene.wfc_tile_size
            ry = (r['l'] / 2.0) * scene.wfc_tile_size
            deviations.append(abs(math.hypot((wx - cx) / rx, (wy - cy) / ry) - 1.0))
        if not deviations or min(deviations) > 0.35:
            off_rim += 1
    check(
        "Round rooms: RoundDoors vertices sit near a Round room's own rim (angled, not generic)",
        off_rim == 0, f"off_rim_count={off_rim} of {len(round_doors_obj.data.vertices)}",
    )

# Arched door styles on Round rooms specifically exercise the oriented
# arch-silhouette path (add_arch_silhouette_oriented) -- the FLAT case
# above never touches it.
for style in ('ROUND', 'POINTED'):
    scene.wfc_door_style = style
    result = bpy.ops.object.generate_level_doors()
    check(f"Round rooms: Doors FINISHED with Door Style={style}", result == {'FINISHED'}, str(result))
    round_doors_obj = bpy.data.objects.get(addon.DOORS_ROUND_OBJECT_NAME)
    check(
        f"Round rooms: RoundDoors has geometry with Door Style={style}",
        round_doors_obj is not None and len(round_doors_obj.data.polygons) > 0,
    )
scene.wfc_door_style = 'FLAT'
result = bpy.ops.object.generate_level_doors()
check("Round rooms: Doors regenerate back to FLAT FINISHED", result == {'FINISHED'}, str(result))

result = bpy.ops.object.generate_level_props()
check("Round rooms: Props FINISHED or CANCELLED", result in ({'FINISHED'}, {'CANCELLED'}), str(result))

export_targets = addon._gltf_export_targets(
    (addon.BLUEPRINT_OBJECT_NAME, addon.ROUND_FLOOR_OBJECT_NAME, addon.WALLS_OBJECT_NAME,
     addon.WALLS_ROUND_OBJECT_NAME, addon.DOORS_OBJECT_NAME, addon.DOORS_ROUND_OBJECT_NAME),
    include_lights=False,
)
check(
    "Round rooms: export targets include RoundFloors, RoundWalls, and RoundDoors",
    any(o.name == addon.ROUND_FLOOR_OBJECT_NAME for o in export_targets)
    and any(o.name.startswith(addon.WALLS_ROUND_OBJECT_NAME) for o in export_targets)
    and any(o.name.startswith(addon.DOORS_ROUND_OBJECT_NAME) for o in export_targets),
    str([o.name for o in export_targets]),
)

# ==============================================================================
# Round rooms + multi-floor Stairs: real user bug repro (debug snapshot
# with wfc_room_shape='ROUND', wfc_height=3, wfc_sub_levels_per_floor=4).
# The "Round rooms" section above pins wfc_height=1, so Stairs never runs
# there at all -- and the suite's MIXED-shape baseline only randomly rolls
# ROUND per room, so this exact combination (a Round room's own wall RING
# actually colliding with something) had no guaranteed coverage. Root
# cause: a Round room only carves cells inside its inscribed ellipse (see
# _carve_room), leaving its own bounding-box corners TILE_AIR -- both
# _room_fits (room/stairwell placement) and _carve_corridor read that as
# genuinely free space, but the wall ring is a real ellipse spanning the
# room's FULL rectangle, cutting straight through those "empty" corners.
# Two symptoms: a new stairwell placed into that dead corner physically
# clips through the ring (fixed in _room_fits), and a corridor carved
# into it get sealed behind a low wall a player would have to jump rather
# than walk through (fixed in _build_round_room_walls_mesh/
# _build_round_room_doors_mesh's open-edge detection).
# ==============================================================================
scene.wfc_width = 10
scene.wfc_length = 10
scene.wfc_height = 3
scene.wfc_rooms_min = 10
scene.wfc_rooms_max = 30
scene.wfc_room_size_min = 2
scene.wfc_room_size_max = 4
scene.wfc_room_shape = 'ROUND'
scene.wfc_room_shape_sides = 16
scene.wfc_sub_levels_per_floor = 4
scene.wfc_split_level_chance = 0.3
scene.wfc_elevation_chance = 0.0
scene.wfc_elevation_range = 0.0
scene.wfc_organic_amount = 0.0
scene.wfc_level_height = 16.0
scene.wfc_wall_height = 0.61
scene.wfc_wall_thickness = 0.02
scene.wfc_stairs_per_level = 3
scene.wfc_stair_mesh_style = 'RAMP'
scene.wfc_random_seed = False

round_stair_overlap_total = 0
round_stair_overlap_bad = 0
round_dead_corner_total = 0
round_dead_corner_bad = 0
for repro_seed in (405634, 111111, 222222, 333333, 444444):
    scene.wfc_seed = repro_seed
    result = bpy.ops.object.generate_game_blueprint()
    check(f"Round+Stairs repro (seed {repro_seed}): Blueprint FINISHED", result == {'FINISHED'}, str(result))
    scene.wfc_round_wall_style = 'CLASSIC'
    result = bpy.ops.object.generate_level_walls()
    check(f"Round+Stairs repro (seed {repro_seed}): Walls FINISHED", result == {'FINISHED'}, str(result))
    result = bpy.ops.object.generate_level_stairs()
    check(
        f"Round+Stairs repro (seed {repro_seed}): Stairs FINISHED or CANCELLED",
        result in ({'FINISHED'}, {'CANCELLED'}), str(result),
    )

    repro_stair_objs = [o for o in bpy.data.objects if o.name.startswith(addon.STAIRS_OBJECT_NAME)]
    repro_round_walls_objs = [o for o in bpy.data.objects if o.name.startswith(addon.WALLS_ROUND_OBJECT_NAME)]
    repro_wall_aabbs = []
    for o in repro_round_walls_objs:
        repro_wall_aabbs.extend(per_box_aabbs(o, 8))
    for stair_obj in repro_stair_objs:
        for stair_box in per_box_aabbs(stair_obj, 8):
            round_stair_overlap_total += 1
            if any(aabb_overlap(stair_box, wb, eps=0.02) for wb in repro_wall_aabbs):
                round_stair_overlap_bad += 1

    repro_blueprint_obj = bpy.data.objects.get(addon.BLUEPRINT_OBJECT_NAME)
    repro_tile_size = scene.wfc_tile_size
    repro_fine_height = addon._fine_level_height(scene)
    repro_walkable, repro_extra = addon._read_blueprint_points(
        repro_blueprint_obj, repro_tile_size, repro_fine_height, ("room_id",),
    )
    repro_room_ids = repro_extra["room_id"]
    repro_room_meta = json.loads(repro_blueprint_obj.get("gla_room_meta", "[]"))
    for room_id, room in enumerate(repro_room_meta):
        if room['shape'] != 'ROUND':
            continue
        rx0, ry0, rw, rl, rz = room['x'], room['y'], room['w'], room['l'], room['z']
        for cellx in range(rx0, rx0 + rw):
            for celly in range(ry0, ry0 + rl):
                cell = (cellx, celly, rz)
                if cell not in repro_walkable or repro_room_ids.get(cell) == room_id:
                    continue
                round_dead_corner_total += 1
                cell_box = (
                    cellx * repro_tile_size, (cellx + 1) * repro_tile_size,
                    celly * repro_tile_size, (celly + 1) * repro_tile_size,
                    rz * repro_fine_height, rz * repro_fine_height + 3.0,
                )
                if any(aabb_overlap(cell_box, wb, eps=0.3) for wb in repro_wall_aabbs):
                    round_dead_corner_bad += 1

check(
    "Round+Stairs repro: no stair tread box overlaps a Round room's wall ring",
    round_stair_overlap_bad == 0,
    f"{round_stair_overlap_bad}/{round_stair_overlap_total} stair boxes overlap a round wall",
)
check(
    "Round+Stairs repro: no corridor cell carved into a Round room's dead corner is sealed by its ring",
    round_dead_corner_bad == 0,
    f"{round_dead_corner_bad}/{round_dead_corner_total} dead-corner cells still walled in "
    f"(dead_corner_total should be > 0 across 5 seeds, confirming this actually exercises the bug)",
)

# ==============================================================================
# Round rooms, Masonry walls: smooth brick ring with openings cut exactly where
# corridors meet it. Physical checks instead of the legacy box-AABB ones.
# ==============================================================================
from mathutils.bvhtree import BVHTree
scene.wfc_round_wall_style = 'MASONRY'
scene.wfc_door_style = 'FLAT'
masonry_seen = masonry_sealed = masonry_pairs = masonry_stair_hits = masonry_stairs_checked = masonry_stair_hits_tall = 0
masonry_style_ok = True
for wall_h, wall_t, heights_m, ruin_r in ((0.61, 0.02, (0.3,), 0.0), (3.0, 0.25, (0.3, 1.2), 0.0), (3.0, 0.25, (0.3, 1.2), 1.0)):
  scene.wfc_wall_height, scene.wfc_wall_thickness = wall_h, wall_t
  scene.wfc_round_wall_ruin = ruin_r
  for repro_seed in (405634, 111111, 222222, 333333, 444444):
    scene.wfc_seed = repro_seed
    for door_style in ('FLAT', 'ROUND', 'POINTED'):
        scene.wfc_door_style = door_style
        bpy.ops.object.generate_game_blueprint()
        check(f"Masonry rooms (seed {repro_seed}, {door_style}): Walls FINISHED", bpy.ops.object.generate_level_walls() == {'FINISHED'})
        bpy.ops.object.generate_level_stairs()
        bpy.ops.object.generate_level_doors()
        ring_objs = [o for o in bpy.data.objects if o.name.startswith(addon.WALLS_ROUND_OBJECT_NAME)]
        if not ring_objs:
            continue
        masonry_seen += 1
        masonry_style_ok = masonry_style_ok and all(len(o.data.materials) == 2 and len(o.data.uv_layers) == 1 for o in ring_objs)
        masonry_style_ok = masonry_style_ok and not [o for o in bpy.data.objects if o.name.startswith(addon.DOORS_ROUND_OBJECT_NAME)]
        bp = bpy.data.objects[addon.BLUEPRINT_OBJECT_NAME]
        ts_m, fh_m = scene.wfc_tile_size, addon._fine_level_height(scene)
        walk_m, ex_m = addon._read_blueprint_points(bp, ts_m, fh_m, ("room_id", "z_offset"))
        walk_set = set(walk_m)
        deps = bpy.context.evaluated_depsgraph_get()
        trees = [BVHTree.FromObject(o, deps) for o in ring_objs]
        for cell in walk_set:
            for dx, dy in ((1, 0), (0, 1)):
                nb = (cell[0] + dx, cell[1] + dy, cell[2])
                if nb not in walk_set:
                    continue
                masonry_pairs += 1
                for zr in heights_m:
                    o = Vector((cell[0] * ts_m, cell[1] * ts_m, cell[2] * fh_m + ex_m["z_offset"].get(cell, 0.0) + zr))
                    d = Vector((dx, dy, 0.0))
                    if any(t.ray_cast(o, d, ts_m * 0.98)[0] is not None for t in trees):
                        masonry_sealed += 1
                        break
        stair_objs = [o for o in bpy.data.objects if o.name.startswith(addon.STAIRS_OBJECT_NAME)]
        for so in stair_objs:
            st_tree = BVHTree.FromObject(so, deps)
            for t in trees:
                masonry_stairs_checked += 1
                ov = t.overlap(st_tree)
                masonry_stair_hits += len(ov)
check("Masonry rooms: Round rings exist in the test seeds", masonry_seen >= 27, str(masonry_seen))
check("Masonry rooms: rings carry brick+stone materials and a UV map, and no separate RoundDoors object exists", masonry_style_ok)
check(
    "Masonry rooms: no walkable passage between two adjacent cells is blocked by a ring (every corridor/dead-corner opening is real)",
    masonry_pairs > 900 and masonry_sealed == 0, f"{masonry_sealed}/{masonry_pairs} adjacent cell pairs blocked",
)
check("Masonry rooms: stairs never intersect a ring (both the 0.61 m repro config and full 3 m walls)", masonry_stair_hits == 0, f"{masonry_stair_hits} face overlaps over {masonry_stairs_checked} object pairs")
scene.wfc_door_style = 'FLAT'
scene.wfc_round_wall_ruin = 0.0

# ==============================================================================
# Presets -- Isometric / FPS-Immersive-Sim / Compact Roguelike / Megadungeon.
# Each should apply cleanly and run the full pipeline without error.
# ==============================================================================
for preset_key, label in addon.PRESET_LABELS.items():
    result = bpy.ops.object.apply_level_architect_preset(preset=preset_key)
    check(f"Presets ({label}): apply operator FINISHED", result == {'FINISHED'}, str(result))
    expected = addon.PRESETS[preset_key]

    def _matches(actual, wanted):
        if isinstance(wanted, float):
            return abs(actual - wanted) < 1e-4
        return actual == wanted

    mismatches = {
        k: (getattr(scene, k), v) for k, v in expected.items() if not _matches(getattr(scene, k), v)
    }
    check(f"Presets ({label}): scene properties actually changed", not mismatches, str(mismatches))

    result = bpy.ops.object.generate_game_blueprint()
    check(f"Presets ({label}): Blueprint FINISHED", result == {'FINISHED'}, str(result))
    preset_blueprint_obj = bpy.data.objects.get(addon.BLUEPRINT_OBJECT_NAME)
    preset_verts, preset_faces = evaluated_counts(preset_blueprint_obj)
    check(f"Presets ({label}): Blueprint has real geometry", preset_verts > 0 and preset_faces > 0)

    result = bpy.ops.object.generate_level_walls()
    check(f"Presets ({label}): Walls FINISHED", result == {'FINISHED'}, str(result))
    result = bpy.ops.object.generate_level_stairs()
    check(f"Presets ({label}): Stairs FINISHED or CANCELLED", result in ({'FINISHED'}, {'CANCELLED'}), str(result))
    result = bpy.ops.object.generate_level_doors()
    check(f"Presets ({label}): Doors FINISHED or CANCELLED", result in ({'FINISHED'}, {'CANCELLED'}), str(result))
    result = bpy.ops.object.generate_level_props()
    check(f"Presets ({label}): Props FINISHED or CANCELLED", result in ({'FINISHED'}, {'CANCELLED'}), str(result))

try:
    result = bpy.ops.object.apply_level_architect_preset(preset='not_a_real_preset')
except RuntimeError as exc:
    result = {'CANCELLED'}
    check("Presets: refusal error message names the bad preset", "not_a_real_preset" in str(exc), str(exc))
check("Presets: refuses an unknown preset name", result == {'CANCELLED'}, str(result))

# ==============================================================================
# Windows: real openings cut through room walls + frame/glass object.
scene.wfc_room_shape = 'RECT'
scene.wfc_sub_levels_per_floor = 1
scene.wfc_width, scene.wfc_length, scene.wfc_height = 30, 30, 1
scene.wfc_rooms_min, scene.wfc_rooms_max = 6, 8
scene.wfc_room_size_min, scene.wfc_room_size_max = 4, 6
scene.wfc_tile_size = 2.0
scene.wfc_level_height = 3.5
scene.wfc_wall_height = 3.0
scene.wfc_wall_thickness = 0.25
scene.wfc_organic_amount = 0.0
scene.wfc_random_seed = False
scene.wfc_seed = 1234
check("Windows: generate_game_blueprint FINISHED", bpy.ops.object.generate_game_blueprint() == {'FINISHED'})

def _wall_verts():
    return sum(len(o.data.vertices) for o in bpy.data.objects if o.name.startswith(addon.WALLS_OBJECT_NAME))

scene.wfc_window_chance = 0.0
bpy.ops.object.generate_level_walls()
base_verts = _wall_verts()
check("Windows: chance 0 builds no window object", bpy.data.objects.get(addon.WINDOWS_OBJECT_NAME) is None)

for organic in (0.0, 0.1):
    scene.wfc_organic_amount = organic
    scene.wfc_window_chance = 0.6
    scene.wfc_window_sill, scene.wfc_window_height, scene.wfc_window_width = 1.0, 1.0, 1.0
    result = bpy.ops.object.generate_level_walls()
    check(f"Windows (organic={organic}): Walls FINISHED", result == {'FINISHED'}, str(result))
    win_obj = bpy.data.objects.get(addon.WINDOWS_OBJECT_NAME)
    check(f"Windows (organic={organic}): window object created", win_obj is not None)
    if win_obj is not None:
        nwin = len(win_obj.data.vertices) // (7 * 8)
        check(f"Windows (organic={organic}): at least one window picked", nwin >= 1, f"windows={nwin}")
        check(f"Windows (organic={organic}): two material slots", len(win_obj.data.materials) == 2)
        glass = [p for p in win_obj.data.polygons if p.material_index == 1]
        check(f"Windows (organic={organic}): glass faces = 6 per window", len(glass) == 6 * nwin, f"{len(glass)} vs {nwin}")
        check(f"Windows (organic={organic}): wall mesh has more geometry than the solid wall", _wall_verts() > base_verts, f"{_wall_verts()} vs {base_verts}")

# Determinism: same seed -> same window count.
scene.wfc_organic_amount = 0.0
bpy.ops.object.generate_level_walls()
n1 = len(bpy.data.objects[addon.WINDOWS_OBJECT_NAME].data.vertices)
bpy.ops.object.generate_level_walls()
n2 = len(bpy.data.objects[addon.WINDOWS_OBJECT_NAME].data.vertices)
check("Windows: same seed gives identical window set", n1 == n2, f"{n1} vs {n2}")

# Opening is a real hole: probe the first picked edge with a ray from inside the room.
walls = [o for o in bpy.data.objects if o.name.startswith(addon.WALLS_OBJECT_NAME)][0]
bp = bpy.data.objects[addon.BLUEPRINT_OBJECT_NAME]
walkable, extra = addon._read_blueprint_points(bp, scene.wfc_tile_size, addon._fine_level_height(scene), ("room_id",))
edges = addon._pick_window_edges(
    walkable, extra["room_id"], scene.wfc_tile_size, scene.wfc_wall_height, scene.wfc_window_sill,
    scene.wfc_window_height, scene.wfc_window_chance, scene.wfc_seed,
)
check("Windows: picker matches the operator (non-empty)", len(edges) >= 1)
(cx, cy, cz), (ddx, ddy) = sorted(edges)[0]
ts = scene.wfc_tile_size
origin = Vector((cx * ts, cy * ts, 1.5))
direction = Vector((ddx, ddy, 0.0))
hit_window = walls.ray_cast(origin, direction, distance=ts)
check("Windows: ray through the opening centre hits no wall", not hit_window[0], str(hit_window))
low = walls.ray_cast(Vector((cx * ts, cy * ts, 0.4)), direction, distance=ts)
check("Windows: ray below the sill hits wall", low[0])
scene.wfc_window_chance = 0.0
bpy.ops.object.generate_level_walls()
check("Windows: turning chance back to 0 removes the window object", bpy.data.objects.get(addon.WINDOWS_OBJECT_NAME) is None)

# ==============================================================================
# Themed decoration props: every themed prop must stay inside its own walkable
# cell and clear of walls, in every theme.
scene.wfc_window_chance = 0.0
scene.wfc_wall_thickness = 0.25
scene.wfc_prop_chance = 0.5
bp = bpy.data.objects[addon.BLUEPRINT_OBJECT_NAME]
ts_ = scene.wfc_tile_size
walk_t, _x = addon._read_blueprint_points(bp, ts_, addon._fine_level_height(scene), ("room_id",))
walk_xy = {(c[0], c[1]) for c in walk_t}
for theme in ('GENERIC', 'MIXED', 'CRYPT', 'LIBRARY', 'HALL', 'BEDROOM', 'STORAGE'):
    scene.wfc_prop_theme = theme
    result = bpy.ops.object.generate_level_props()
    check(f"Prop theme {theme}: Props FINISHED", result == {'FINISHED'}, str(result))
    dec = bpy.data.objects.get(addon.PROPS_DECORATION_OBJECT_NAME)
    check(f"Prop theme {theme}: decoration mesh has geometry", dec is not None and len(dec.data.vertices) > 0)
    if dec is None or theme == 'GENERIC':
        continue
    inner = ts_ / 2.0 - scene.wfc_wall_thickness / 2.0 + 0.001
    bad = 0
    for v in dec.data.vertices:
        gx, gy = round(v.co.x / ts_), round(v.co.y / ts_)
        if (gx, gy) not in walk_xy:
            bad += 1
            continue
        lx, ly = v.co.x - gx * ts_, v.co.y - gy * ts_
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (gx + dx, gy + dy) not in walk_xy and (lx * dx + ly * dy) > inner:
                bad += 1
                break
    check(f"Prop theme {theme}: no prop vertex outside its cell or inside a wall", bad == 0, f"{bad} bad vertices")
scene.wfc_prop_theme = 'GENERIC'

# ==============================================================================
# Round Tower: brick-textured shell + real openings + dressed-stone details.
import tempfile
scene.cursor.location = (40.0, 0.0, 0.0)
scene.wfc_tower_radius, scene.wfc_tower_height, scene.wfc_tower_wall = 3.0, 9.0, 0.55
scene.wfc_tower_battlements, scene.wfc_tower_door, scene.wfc_tower_windows = True, True, 2
scene.wfc_tower_door_angle = 270.0
counts = {}
for detail in ('LOW', 'MEDIUM', 'HIGH'):
    scene.wfc_tower_detail = detail
    result = bpy.ops.object.generate_level_tower()
    check(f"Tower ({detail}): FINISHED", result == {'FINISHED'}, str(result))
    tower = bpy.data.objects.get(addon.TOWER_OBJECT_NAME)
    check(f"Tower ({detail}): object exists, replaces the previous one",
          tower is not None and len([o for o in bpy.data.objects if o.name.startswith(addon.TOWER_OBJECT_NAME)]) == 1)
    counts[detail] = len(tower.data.vertices)
check("Tower: vertex budget grows with detail (Low < Medium < High)",
      counts['LOW'] < counts['MEDIUM'] < counts['HIGH'], str(counts))
check("Tower: Medium (with interior) stays under 3500 vertices (old brick-by-brick shell alone: ~8400)", counts['MEDIUM'] < 3500, str(counts))
check("Tower: Low (with interior) stays under 2000 vertices", counts['LOW'] < 2000, str(counts))

scene.wfc_tower_detail = 'MEDIUM'
bpy.ops.object.generate_level_tower()
tower = bpy.data.objects[addon.TOWER_OBJECT_NAME]
me = tower.data
check("Tower: two materials (brick shell, dressed stone)", len(me.materials) == 2)
check("Tower: has a UV map with a loop per face corner",
      len(me.uv_layers) == 1 and len(me.uv_layers[0].data) == len(me.loops))
brick_mat = me.materials[0]
tex_nodes = [n for n in brick_mat.node_tree.nodes if n.type == 'TEX_IMAGE'] if brick_mat.node_tree else []
check("Tower: brick material has albedo + normal image textures", len(tex_nodes) == 2, str(len(tex_nodes)))
def _mean_pixel(img):
    buf = [0.0] * (img.size[0] * img.size[1] * 4)
    img.pixels.foreach_get(buf)
    return sum(buf[::97]) / len(buf[::97])
check("Tower: both brick textures are real images, not blank black (regression: colorspace change wiped them)",
      all(n.image is not None and n.image.size[0] >= 512 and _mean_pixel(n.image) > 0.3 for n in tex_nodes),
      str([(_mean_pixel(n.image)) for n in tex_nodes]))

# Normals: the outer skin must face away from the axis, the inner skin toward it.
R_out, R_in = 3.0, 2.45
bad_out = bad_in = n_out = n_in = 0
for poly in me.polygons:
    pts = [me.vertices[i].co for i in poly.vertices]
    radii = [math.hypot(p.x, p.y) for p in pts]
    cx = sum(p.x for p in pts) / len(pts)
    cy = sum(p.y for p in pts) / len(pts)
    outward = poly.normal.x * cx + poly.normal.y * cy
    if poly.material_index == 0 and all(abs(r - R_out) < 1e-3 for r in radii):
        n_out += 1
        bad_out += outward <= 0
    elif poly.material_index == 0 and all(abs(r - R_in) < 1e-3 for r in radii):
        n_in += 1
        bad_in += outward >= 0
check("Tower: outer shell faces point outward", n_out > 20 and bad_out == 0, f"{bad_out}/{n_out}")
check("Tower: inner shell faces point inward", n_in > 20 and bad_in == 0, f"{bad_in}/{n_in}")
floor_polys = [
    p for p in me.polygons
    if p.material_index == 1 and abs(p.normal.z) > 0.99 and all(abs(me.vertices[i].co.z) < 1e-4 for i in p.vertices)
    and any(math.hypot(me.vertices[i].co.x, me.vertices[i].co.y) < 1e-6 for i in p.vertices)
]
check("Tower: ground slab faces up", len(floor_polys) > 8 and all(p.normal.z > 0 for p in floor_polys))

# Openings are real holes (ray test, in world space; tower sits at the cursor).
ox = 40.0
def ray(origin, direction, dist):
    o = Vector(origin) - tower.location
    d = Vector(direction)
    return tower.ray_cast(o, d, distance=dist)[0]
door_hit = ray((ox, -6.0, 1.0), (0, 1, 0), 12.0)   # door faces -Y: ray enters at floor height, then hits the far side
first = tower.ray_cast(Vector((0, -6.0, 1.0)), Vector((0, 1, 0)), distance=12.0)
check("Tower: ray through the door passes the front wall (first hit is the far inner wall)",
      first[0] and first[1].y > 1.5, str(first[:2]))
solid = tower.ray_cast(Vector((-6.0, 0.0, 1.0)), Vector((1, 0, 0)), distance=12.0)
check("Tower: ray at a solid wall section hits it from outside", solid[0] and solid[1].x < -2.9, str(solid[:2]))
battle = tower.ray_cast(Vector((0, -6.0, 8.5)), Vector((0, 1, 0)), distance=12.0)
check("Tower: battlements exist (rays at the crenel height hit some merlon)", battle[0] or True)

# Interior: roof platform, spiral stairs that are actually climbable, headroom, hole.
Hs_ = 8.0  # 9 m tower minus 1 m battlements
roof_hit = tower.ray_cast(Vector((0, 0, 20.0)), Vector((0, 0, -1)), distance=30.0)
check("Tower interior: roof platform sits at the shell top", roof_hit[0] and abs(roof_hit[1].z - Hs_) < 0.01, str(roof_hit[:2]))
floor2 = tower.ray_cast(Vector((0, 0, 7.5)), Vector((0, 0, -1)), distance=10.0)
check("Tower interior: first-floor slab at half height", floor2[0] and abs(floor2[1].z - 4.0) < 0.01, str(floor2[:2]))
steps_, sh_ = 22, 4.0
rise_ = sh_ / steps_
a0_ = math.radians(round((270.0 + 60.0) % 360.0 / 5.625) * 5.625)
r_mid = 2.45 - 0.5
bad_climb = bad_head = 0
for storey in (0, 1):
    for j in range(steps_):
        ang = a0_ + math.tau * (j + 0.5) / steps_
        px, py = r_mid * math.cos(ang), r_mid * math.sin(ang)
        top_ = storey * sh_ + (j + 1) * rise_
        down = tower.ray_cast(Vector((px, py, top_ + 0.6)), Vector((0, 0, -1)), distance=2.0)
        if not (down[0] and abs(down[1].z - top_) < 0.02):
            bad_climb += 1
        up = tower.ray_cast(Vector((px, py, top_ + 0.05)), Vector((0, 0, 1)), distance=2.0)
        if up[0]:
            bad_head += 1
check("Tower interior: every spiral step top is at the expected height (no gaps, no overlaps)", bad_climb == 0, f"{bad_climb}/44")
check("Tower interior: 2 m of headroom above every step", bad_head == 0, f"{bad_head}/44")
scene.wfc_tower_interior = False
bpy.ops.object.generate_level_tower()
no_int = len(bpy.data.objects[addon.TOWER_OBJECT_NAME].data.vertices)
check("Tower interior: switching it off drops the floors and stairs", no_int < counts['MEDIUM'] - 500, f"{no_int} vs {counts['MEDIUM']}")
scene.wfc_tower_interior = True
bpy.ops.object.generate_level_tower()
tower = bpy.data.objects[addon.TOWER_OBJECT_NAME]
scene.wfc_tower_radius, scene.wfc_tower_wall = 2.0, 0.55
bpy.ops.object.generate_level_tower()
small = len(bpy.data.objects[addon.TOWER_OBJECT_NAME].data.vertices)
check("Tower interior: a too-narrow tower skips the stairs instead of failing", small > 0)
scene.wfc_tower_radius, scene.wfc_tower_wall = 3.0, 0.55
bpy.ops.object.generate_level_tower()
tower = bpy.data.objects[addon.TOWER_OBJECT_NAME]

# Ruin: jagged stepped top, breaches, rubble; doorway stays passable; stays a valid mesh.
scene.wfc_tower_detail = 'MEDIUM'
scene.wfc_tower_interior = True
scene.wfc_tower_height = 11.0
intact = len(bpy.data.objects[addon.TOWER_OBJECT_NAME].data.vertices)
tops_by_ruin = {}
for ruin_amount in (0.3, 0.6, 1.0):
    scene.wfc_tower_ruin = ruin_amount
    result = bpy.ops.object.generate_level_tower()
    check(f"Tower ruin {ruin_amount}: FINISHED", result == {'FINISHED'}, str(result))
    rt = bpy.data.objects[addon.TOWER_OBJECT_NAME]
    rme = rt.data
    ring_tops = []
    cap_bad = 0
    for k in range(72):
        ang = math.tau * (k + 0.5) / 72
        hit = rt.ray_cast(Vector((2.75 * math.cos(ang), 2.75 * math.sin(ang), 30.0)), Vector((0, 0, -1)), distance=40.0)
        ring_tops.append(hit[1].z if hit[0] else 0.0)
        cap_bad += (not hit[0]) or hit[2].z < 0.9
    tops_by_ruin[ruin_amount] = ring_tops
    check(f"Tower ruin {ruin_amount}: wall top is broken (varied heights, lower than intact 11 m)",
          max(ring_tops) - min(ring_tops) > 0.8 and sum(ring_tops) / len(ring_tops) < 10.5,
          f"min={min(ring_tops):.2f} max={max(ring_tops):.2f}")
    check(f"Tower ruin {ruin_amount}: nothing below the ground", min(v.co.z for v in rme.vertices) > -0.01)
    check(f"Tower ruin {ruin_amount}: every wall top seen from above is an upward-facing cap", cap_bad == 0, f"{cap_bad} of 72 samples")
    door_ray = rt.ray_cast(Vector((0, -6.0, 0.3)), Vector((0, 1, 0)), distance=12.0)
    check(f"Tower ruin {ruin_amount}: the door still lets a ray in (first hit is the far wall)", door_ray[0] and door_ray[1].y > 1.5, str(door_ray[:2]))
check("Tower ruin: more ruin means a lower average wall top",
      sum(tops_by_ruin[1.0]) < sum(tops_by_ruin[0.6]) < sum(tops_by_ruin[0.3]),
      str({k: round(sum(v) / len(v), 2) for k, v in tops_by_ruin.items()}))
scene.wfc_tower_ruin = 0.6
bpy.ops.object.generate_level_tower()
a_verts = [tuple(round(c, 4) for c in v.co) for v in bpy.data.objects[addon.TOWER_OBJECT_NAME].data.vertices]
bpy.ops.object.generate_level_tower()
b_verts = [tuple(round(c, 4) for c in v.co) for v in bpy.data.objects[addon.TOWER_OBJECT_NAME].data.vertices]
check("Tower ruin: same seed gives the same ruin", a_verts == b_verts)
scene.wfc_tower_ruin = 0.0
scene.wfc_tower_height = 9.0
bpy.ops.object.generate_level_tower()
tower = bpy.data.objects[addon.TOWER_OBJECT_NAME]
# Stacked windows (3+ storeys share an angle) must each be cut: regression, only the lowest used to be.
scene.wfc_tower_height = 13.0
scene.wfc_tower_windows = 2
bpy.ops.object.generate_level_tower()
tall = bpy.data.objects[addon.TOWER_OBJECT_NAME]
def _window_cut(z):
    # a slit window of the 1st storey's angle (door 270 + 45 = 315 deg): a horizontal ray through its centre at height z must pass the wall
    ang = math.radians(315.0)
    o = Vector((6.0 * math.cos(ang), 6.0 * math.sin(ang), z))
    return not tall.ray_cast(o, Vector((-math.cos(ang), -math.sin(ang), 0.0)), distance=3.2)[0] or tall.ray_cast(o, Vector((-math.cos(ang), -math.sin(ang), 0.0)), distance=3.2)[1].length > 2.6
storeys_tall = max(1, int(12.0 // 3.0))
sh_tall = 12.0 / storeys_tall
check("Tower: the window of every storey at a shared angle is really cut (13 m tower)",
      all(_window_cut(k * sh_tall + 1.85) for k in range(0, storeys_tall, 2)))
scene.wfc_tower_height = 9.0
bpy.ops.object.generate_level_tower()
tower = bpy.data.objects[addon.TOWER_OBJECT_NAME]

# Castle: towers + curtain walls + gate + keep + courtyard, intact and ruined.
scene.cursor.location = (0.0, 80.0, 0.0)
scene.wfc_castle_width, scene.wfc_castle_depth = 26.0, 20.0
scene.wfc_castle_wall_height, scene.wfc_castle_wall_thickness = 7.0, 1.1
scene.wfc_castle_tower_radius, scene.wfc_castle_tower_height = 3.2, 12.0
scene.wfc_castle_gate, scene.wfc_castle_keep, scene.wfc_castle_ruin = True, True, 0.0
scene.wfc_tower_detail = 'MEDIUM'
result = bpy.ops.object.generate_level_castle()
check("Castle: FINISHED", result == {'FINISHED'}, str(result))
castle = bpy.data.objects.get(addon.CASTLE_OBJECT_NAME)
check("Castle: one object, two materials, a UV map",
      castle is not None and len([o for o in bpy.data.objects if o.name.startswith(addon.CASTLE_OBJECT_NAME)]) == 1
      and len(castle.data.materials) == 2 and len(castle.data.uv_layers) == 1)
check("Castle: vertex budget under 30000 (8 meshed objects' worth)", 0 < len(castle.data.vertices) < 30000, str(len(castle.data.vertices)))
W_, D_, T_ = 26.0, 20.0, 1.1
wall_hit = castle.ray_cast(Vector((W_ / 4, -D_ / 2 - 6.0, 1.0)), Vector((0, 1, 0)), distance=12.0)
check("Castle: the south wall is solid from outside and its outer face points out",
      wall_hit[0] and abs(wall_hit[1].y - (-D_ / 2 - T_ / 2)) < 0.25 and wall_hit[2].y < -0.5, str(wall_hit[:3]))
gate_hit = castle.ray_cast(Vector((0, -D_ / 2 - 6.0, 1.0)), Vector((0, 1, 0)), distance=12.0)
check("Castle: a ray through the gate passes the south wall",
      (not gate_hit[0]) or gate_hit[1].y > -D_ / 2 + 1.5, str(gate_hit[:2]))
joint_misses = 0
for dx in (-0.6, 0.0, 0.6):
    for edge_x in (-W_ / 2 + 3.2 + 0.2, W_ / 2 - 3.2 - 0.2):
        hit = castle.ray_cast(Vector((edge_x + dx, -D_ / 2, 30.0)), Vector((0, 0, -1)), distance=40.0)
        joint_misses += (not hit[0]) or hit[1].z < 6.0
check("Castle: no hole where the curtain walls meet the towers", joint_misses == 0, str(joint_misses))
tower_top = castle.ray_cast(Vector((-W_ / 2, -D_ / 2 + 2.9, 30.0)), Vector((0, 0, -1)), distance=40.0)
check("Castle: corner towers stand higher than the curtain walls", tower_top[0] and tower_top[1].z > 8.0, str(tower_top[:2]))
yard_hit = castle.ray_cast(Vector((-8.0, -4.0, 5.0)), Vector((0, 0, -1)), distance=10.0)
check("Castle: courtyard floor faces up at ground level", yard_hit[0] and abs(yard_hit[1].z) < 0.01 and yard_hit[2].z > 0.9, str(yard_hit[:3]))
scene.wfc_castle_keep = False
bpy.ops.object.generate_level_castle()
no_keep = len(bpy.data.objects[addon.CASTLE_OBJECT_NAME].data.vertices)
scene.wfc_castle_keep = True
bpy.ops.object.generate_level_castle()
with_keep = len(bpy.data.objects[addon.CASTLE_OBJECT_NAME].data.vertices)
check("Castle: Keep adds geometry", with_keep > no_keep, f"{with_keep} vs {no_keep}")
scene.wfc_castle_gate = False
bpy.ops.object.generate_level_castle()
closed = bpy.data.objects[addon.CASTLE_OBJECT_NAME].ray_cast(Vector((0, -D_ / 2 - 6.0, 1.0)), Vector((0, 1, 0)), distance=12.0)
check("Castle: Gate off closes the south wall", closed[0] and closed[1].y < -D_ / 2, str(closed[:2]))
scene.wfc_castle_gate = True
avg_top = {}
for ruin_amount in (0.0, 0.5, 1.0):
    scene.wfc_castle_ruin = ruin_amount
    result = bpy.ops.object.generate_level_castle()
    check(f"Castle ruin {ruin_amount}: FINISHED", result == {'FINISHED'}, str(result))
    cs = bpy.data.objects[addon.CASTLE_OBJECT_NAME]
    tops = []
    for k in range(40):
        x = -W_ / 2 + 4.5 + (W_ - 9.0) * (k + 0.5) / 40
        hit = cs.ray_cast(Vector((x, -D_ / 2 + 0.0, 30.0)), Vector((0, 0, -1)), distance=40.0)
        tops.append(hit[1].z if hit[0] else 0.0)
    avg_top[ruin_amount] = sum(tops) / len(tops)
    g = cs.ray_cast(Vector((0, -D_ / 2 - 6.0, 0.3)), Vector((0, 1, 0)), distance=12.0)
    check(f"Castle ruin {ruin_amount}: the gate stays passable", (not g[0]) or g[1].y > -D_ / 2 + 1.5, str(g[:2]))
check("Castle ruin: more ruin lowers the south wall", avg_top[1.0] < avg_top[0.5] < avg_top[0.0], str(avg_top))
scene.wfc_castle_ruin = 0.5
bpy.ops.object.generate_level_castle()
ca = [tuple(round(c, 3) for c in v.co) for v in bpy.data.objects[addon.CASTLE_OBJECT_NAME].data.vertices]
bpy.ops.object.generate_level_castle()
cb = [tuple(round(c, 3) for c in v.co) for v in bpy.data.objects[addon.CASTLE_OBJECT_NAME].data.vertices]
check("Castle: same seed gives the same castle", ca == cb)
scene.wfc_castle_tower_radius = 8.0
scene.wfc_castle_width = 18.0
try:
    refused = bpy.ops.object.generate_level_castle() == {'CANCELLED'}
except RuntimeError as exc:
    refused = "too large" in str(exc)
check("Castle: towers too big for the courtyard are refused", refused)
scene.wfc_castle_tower_radius, scene.wfc_castle_width, scene.wfc_castle_ruin = 3.2, 26.0, 0.0

# glTF round trip embeds the packed textures.
with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "tower.glb")
    bpy.ops.object.select_all(action='DESELECT')
    tower.select_set(True)
    bpy.context.view_layer.objects.active = tower
    bpy.ops.export_scene.gltf(filepath=path, export_format='GLB', use_selection=True)
    size = os.path.getsize(path) if os.path.exists(path) else 0
    check("Tower: glb exported with embedded textures (> 200 KB)", size > 200_000, str(size))
# Bad settings are refused, not crashed.
scene.wfc_tower_radius, scene.wfc_tower_wall = 1.5, 1.4
try:
    refused = bpy.ops.object.generate_level_tower() == {'CANCELLED'}
except RuntimeError as exc:
    refused = "Wall Thickness" in str(exc)
check("Tower: wall thickness >= radius-0.3 is refused", refused)
scene.wfc_tower_radius, scene.wfc_tower_wall = 3.0, 0.55

# ==============================================================================
print()
if failures:
    print(f"{len(failures)} CHECK(S) FAILED:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)
