# Generates ONE .blend file containing several Cave-mode levels laid out
# side by side (translated apart along X), instead of one file per
# scenario like generate_test_blends.py -- lets you open a single file and
# scroll across every Cave variation at once instead of switching between
# files.
#
# Running the full pipeline more than once in the same session is normally
# unsafe for this: Walls/Stairs/Doors/Props each call
# _remove_objects_by_prefix() at the START of their own operator, matching
# by EXACT name or "name_" prefix -- so scenario 2's Walls step would
# delete scenario 1's walls outright (same object name) the moment it ran,
# and Props' torch/light/decoration collections are looked up and REUSED
# by exact name too, mixing every scenario's props into one shared
# collection. Fixed here by renaming (never leaving the exact base name
# behind) and repositioning EVERY object/collection a scenario created
# immediately after that scenario finishes, before the next one starts --
# by the time scenario 2 runs, nothing in the scene still matches the
# names its own cleanup logic looks for.
#
# Usage: blender --background --factory-startup --python tests/generate_cave_gallery.py

import importlib.util
import os

import bpy

ADDON_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "levelArchitect_v2.py")
)
OUTPUT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "test_blends")
)
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "test_cave_gallery.blend")

FIXED_SEED = 424242
GAP_METERS = 8.0  # empty space between one scenario's footprint and the next

CAVE_BASELINE = dict(
    wfc_width=24, wfc_length=24, wfc_height=2,
    wfc_seed=FIXED_SEED, wfc_random_seed=False,
    wfc_rooms_min=8, wfc_rooms_max=14,
    wfc_room_size_min=3, wfc_room_size_max=6,
    wfc_room_shape='CAVE',
    wfc_stairs_per_level=2, wfc_stair_room_width=3, wfc_stair_room_length=4,
    wfc_corridor_stairs=False,
    wfc_sub_levels_per_floor=1, wfc_split_level_chance=0.0,
    wfc_elevation_chance=0.0, wfc_elevation_range=0.0, wfc_max_ramp_slope=30.0,
    wfc_tile_size=2.0, wfc_level_height=3.0,
    wfc_style='0', wfc_simple_materials=True, wfc_color_rooms=True,
    wfc_floor_thickness=0.1, wfc_iso_mode=False,
    wfc_add_ceiling=False, wfc_ceiling_thickness=0.1,
    wfc_organic_amount=0.0,
    wfc_wall_height=2.5, wfc_wall_thickness=0.2, wfc_wall_cap_top=True,
    wfc_wall_grouping='SINGLE',
    wfc_door_height=2.2, wfc_door_frame_thickness=0.15,
    wfc_door_grouping='SINGLE', wfc_door_merge_distance=2,
    wfc_stair_grouping='PER_FLOOR', wfc_stair_mesh_style='STAIRS', wfc_stair_steps=6,
    wfc_torch_chance=0.2, wfc_torch_height=1.6,
    wfc_torch_light_chance=0.5, wfc_max_lights=100,
    wfc_torch_light_energy=60.0, wfc_torch_light_color=(1.0, 0.55, 0.2),
    wfc_torch_light_radius=0.25, wfc_prop_chance=0.12,
)

# (label, {property: value} overrides on top of CAVE_BASELINE) -- label
# becomes both the object-name prefix and this scenario's own collection
# name, so it doubles as the in-file legend.
CAVE_SCENARIOS = [
    ("01_Baseline", {}),
    ("02_CorridorStairs", dict(wfc_corridor_stairs=True)),
    ("03_AddCeiling", dict(wfc_add_ceiling=True)),
    ("04_StyleDungeon", dict(wfc_simple_materials=False, wfc_style='0')),
    ("05_StyleCaveRock", dict(wfc_simple_materials=False, wfc_style='1')),
    ("06_StyleOpenArea", dict(wfc_simple_materials=False, wfc_style='2')),
    ("07_Elevation", dict(wfc_elevation_chance=0.6, wfc_elevation_range=1.0)),
    ("08_DifferentSeed", dict(wfc_seed=987654)),
    ("09_LargerMap", dict(wfc_width=36, wfc_length=36, wfc_rooms_min=14, wfc_rooms_max=20)),
    (
        "10_KitchenSink",
        dict(
            wfc_corridor_stairs=True, wfc_add_ceiling=True,
            wfc_simple_materials=False, wfc_style='1',
            wfc_elevation_chance=0.4, wfc_elevation_range=1.0,
        ),
    ),
]


def apply_settings(scene, overrides):
    settings = dict(CAVE_BASELINE)
    settings.update(overrides)
    for key, value in settings.items():
        setattr(scene, key, value)


def run_pipeline():
    result = bpy.ops.object.generate_game_blueprint()
    if result != {'FINISHED'}:
        return f"Blueprint FAILED: {result}"
    bpy.ops.object.generate_level_walls()
    bpy.ops.object.generate_level_stairs()
    bpy.ops.object.generate_level_doors()
    bpy.ops.object.generate_level_props()
    return None


def isolate_and_place(label, x_offset):
    """Renames every object/collection this scenario just created (so the
    NEXT scenario's own regeneration cleanup can't match and delete them),
    and shifts every new object sideways by x_offset so this scenario's
    level sits in its own strip of the map instead of overlapping the
    previous one at the origin. Returns the object count for the log."""
    moved = 0
    for obj in bpy.data.objects:
        if not obj.name.startswith(f"{label}__"):
            continue
        obj.location.x += x_offset
        moved += 1
    return moved


def main():
    print(f"Loading addon from: {ADDON_PATH}")
    spec = importlib.util.spec_from_file_location("levelArchitect_v2", ADDON_PATH)
    addon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(addon)
    addon.register()

    scene = bpy.context.scene
    x_offset = 0.0
    summary = []

    for label, overrides in CAVE_SCENARIOS:
        pre_objects = set(bpy.data.objects.keys())
        pre_collections = set(bpy.data.collections.keys())

        apply_settings(scene, overrides)
        error = run_pipeline()

        for name in set(bpy.data.objects.keys()) - pre_objects:
            bpy.data.objects[name].name = f"{label}__{name}"
        for name in set(bpy.data.collections.keys()) - pre_collections:
            bpy.data.collections[name].name = f"{label} - {name}"

        moved = isolate_and_place(label, x_offset)

        status = "OK" if error is None else error
        summary.append(f"{label}\t[{status}]\t{moved} objects at x={x_offset:.1f}m")
        print(f"{label}: {status}, moved {moved} objects to x={x_offset:.1f}m")

        footprint_x = scene.wfc_width * scene.wfc_tile_size
        x_offset += footprint_x + GAP_METERS

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=OUTPUT_PATH)

    summary_path = os.path.join(OUTPUT_DIR, "cave_gallery_index.txt")
    with open(summary_path, "w") as f:
        f.write("# test_cave_gallery.blend -- Cave-mode scenarios laid out side by side along X\n")
        f.write("# label\t[status]\tnotes\n")
        f.write("\n".join(summary) + "\n")

    print(f"Saved {OUTPUT_PATH}")
    print(f"Index written to {summary_path}")


main()
