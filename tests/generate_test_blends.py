# Generates one .blend file per scenario in SCENARIOS, each running the
# full pipeline (Blueprint -> Walls -> Stairs -> Doors -> Props) against
# the SAME fixed seed, so the option being showcased is the only thing
# that differs between files -- not random layout variance too.
#
# Filenames are deliberately generic (test_01.blend, test_02.blend, ...)
# rather than settings-encoded -- with this many toggles a descriptive
# filename would be unreadable. testfiles.txt (written alongside them)
# is the actual index: which file has which settings.
#
# Usage (one scenario per Blender process, invoked by generate_test_blends.sh):
#   blender --background --factory-startup --python tests/generate_test_blends.py -- <scenario_index>
#
# Run all scenarios: ./generate_test_blends.sh [path-to-blender]

import importlib.util
import os
import sys

import bpy

ADDON_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "levelArchitect_v2.py")
)
OUTPUT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "test_blends")
)
TESTFILES_TXT = os.path.join(OUTPUT_DIR, "testfiles.txt")

FIXED_SEED = 424242

# Applied before every scenario's own overrides -- a representative,
# moderate-size level with every option at its shipped default.
BASELINE = dict(
    wfc_width=24, wfc_length=24, wfc_height=3,
    wfc_seed=FIXED_SEED, wfc_random_seed=False,
    wfc_rooms_min=8, wfc_rooms_max=14,
    wfc_room_size_min=3, wfc_room_size_max=6,
    wfc_room_shape='RECT',
    wfc_stairs_per_level=3, wfc_stair_room_width=3, wfc_stair_room_length=4,
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

# (filename, one-line description, {property: value} overrides on top of BASELINE)
SCENARIOS = [
    (
        "test_01.blend",
        "Baseline -- every option at its shipped default (RECT rooms, room-based stepped "
        "stairs, no elevation, no ceiling, Simple Viewport Colors on).",
        {},
    ),
    (
        "test_02.blend",
        "Room Shape = ROUND.",
        dict(wfc_room_shape='ROUND'),
    ),
    (
        "test_03.blend",
        "Room Shape = MIXED (random RECT/ROUND per room).",
        dict(wfc_room_shape='MIXED'),
    ),
    (
        "test_04.blend",
        "Corridor Stairs ON -- stairs are a flush 1-wide strip in the corridor network "
        "instead of a buffered stairwell room.",
        dict(wfc_corridor_stairs=True),
    ),
    (
        "test_05.blend",
        "Stair Mesh Style = RAMP instead of stepped stairs.",
        dict(wfc_stair_mesh_style='RAMP'),
    ),
    (
        "test_06.blend",
        "Continuous Room Elevation ON (Elevation Chance 0.6, Range 1.0m) -- eligible rooms "
        "get a smooth height offset with a sloped connecting ramp corridor.",
        dict(wfc_elevation_chance=0.6, wfc_elevation_range=1.0),
    ),
    (
        "test_07.blend",
        "Add Ceiling ON -- every room gets a ceiling slab (FPS-style, no open top).",
        dict(wfc_add_ceiling=True),
    ),
    (
        "test_08.blend",
        "Add Ceiling ON + Isometric Mode ON -- shows the ceiling being culled back off for "
        "a dollhouse-style top-down view.",
        dict(wfc_add_ceiling=True, wfc_iso_mode=True),
    ),
    (
        "test_09.blend",
        "Organic Irregularity = 0.15m -- cosmetic jitter on wall height/thickness, stair "
        "tread width, ramp edge waviness. NOTE: this also disables the wall run-merging "
        "polycount optimization (only active when Organic Irregularity is exactly 0), so "
        "wall object here has one box per tile-edge again, same as pre-optimization builds.",
        dict(wfc_organic_amount=0.15),
    ),
    (
        "test_10.blend",
        "Sub-Levels per Floor = 2, Split-Level Chance = 0.4 -- some rooms sit raised/lowered "
        "within their own logical floor, connected via the normal stairwell system.",
        dict(wfc_sub_levels_per_floor=2, wfc_split_level_chance=0.4),
    ),
    (
        "test_11.blend",
        "Kitchen sink -- MIXED rooms + Corridor Stairs + Continuous Elevation + Add Ceiling "
        "+ Organic Irregularity + Sub-Levels, all on together.",
        dict(
            wfc_room_shape='MIXED', wfc_corridor_stairs=True,
            wfc_elevation_chance=0.5, wfc_elevation_range=0.8,
            wfc_add_ceiling=True, wfc_organic_amount=0.1,
            wfc_sub_levels_per_floor=2, wfc_split_level_chance=0.3,
        ),
    ),
    (
        "test_12.blend",
        "Style materials (Simple Viewport Colors OFF) -- procedural Dungeon style material "
        "set instead of the flat per-room texture palette.",
        dict(wfc_simple_materials=False),
    ),
    (
        "test_13.blend",
        "Room Shape = CAVE -- every floor becomes one organic connected network of winding "
        "tunnels and round chambers instead of discrete rooms joined by straight corridors. "
        "Paired with Corridor Stairs (flush 1-wide stair strip fits the tunnel look).",
        dict(wfc_room_shape='CAVE', wfc_corridor_stairs=True),
    ),
    (
        "test_14.blend",
        "Style materials = Cave Rock (style '1') + Room Shape = CAVE -- per-room/per-floor "
        "tinted-procedural coloring (new this session) on the style the organic look actually "
        "matches, instead of the flat per-room texture palette.",
        dict(wfc_simple_materials=False, wfc_style='1', wfc_room_shape='CAVE'),
    ),
    (
        "test_15.blend",
        "Style materials = Open Area (style '2'), plain RECT rooms -- third and last style "
        "variant, same per-room/per-floor coloring as test_14 and test_12's Dungeon style.",
        dict(wfc_simple_materials=False, wfc_style='2'),
    ),
    (
        "test_16.blend",
        "Floor Thickness = 0.0 -- the zero-thickness degenerate case fixed this session (floor "
        "cube's top/bottom faces used to collapse and lose their correct winding; now clamped "
        "to stay outside Merge Distance's welding tolerance while still reading as flat).",
        dict(wfc_floor_thickness=0.0),
    ),
    (
        "test_17.blend",
        "Room Shape = CAVE + Add Ceiling ON -- the trickiest combination for the Ceilings-"
        "bucket-separation fix (a Cave chamber's ceiling patch is just as disconnected from "
        "its floor patch as an ordinary room's), shown together on purpose.",
        dict(wfc_room_shape='CAVE', wfc_add_ceiling=True),
    ),
    (
        "test_18.blend",
        "Sub-Levels per Floor = 3 with Wall/Door Height left at their normal defaults -- Level "
        "Height grows automatically (new this session) so nothing clips into the slice above; "
        "compare the saved wfc_level_height in this file's Debug Params against test_01's.",
        dict(wfc_sub_levels_per_floor=3, wfc_split_level_chance=0.5),
    ),
    (
        "test_19.blend",
        "Same as test_11's kitchen-sink combo, but with Separate by Floor/Room also run "
        "afterward -- saved file shows the actual split Rooms/Corridors/Ceilings collection "
        "tree per floor instead of one combined Blueprint object.",
        dict(
            wfc_room_shape='MIXED', wfc_corridor_stairs=True,
            wfc_elevation_chance=0.5, wfc_elevation_range=0.8,
            wfc_add_ceiling=True, wfc_organic_amount=0.1,
            wfc_sub_levels_per_floor=2, wfc_split_level_chance=0.3,
            _run_separate=True,
        ),
    ),
    (
        "test_20.blend",
        "Stress/showcase scale -- much bigger map and room count than the other scenarios, "
        "MIXED rooms, Corridor Stairs, for eyeballing density and performance at a larger size.",
        dict(
            wfc_width=44, wfc_length=44, wfc_height=4,
            wfc_rooms_min=20, wfc_rooms_max=30,
            wfc_room_shape='MIXED', wfc_corridor_stairs=True, wfc_stairs_per_level=4,
        ),
    ),
]


def apply_settings(scene, overrides):
    # Keys starting with "_" are scenario-runner directives (e.g.
    # _run_separate), not real wfc_* scene properties -- applied by main()
    # itself, never passed to setattr.
    settings = dict(BASELINE)
    settings.update({k: v for k, v in overrides.items() if not k.startswith("_")})
    for key, value in settings.items():
        setattr(scene, key, value)


def run_pipeline(run_separate, addon):
    result = bpy.ops.object.generate_game_blueprint()
    if result != {'FINISHED'}:
        return f"Blueprint FAILED: {result}"
    bpy.ops.object.generate_level_walls()
    bpy.ops.object.generate_level_stairs()
    bpy.ops.object.generate_level_doors()
    bpy.ops.object.generate_level_props()
    if run_separate:
        blueprint_obj = bpy.data.objects.get(addon.BLUEPRINT_OBJECT_NAME)
        bpy.ops.object.select_all(action='DESELECT')
        bpy.context.view_layer.objects.active = blueprint_obj
        blueprint_obj.select_set(True)
        result = bpy.ops.object.separate_level_by_floor()
        if result != {'FINISHED'}:
            return f"Separate by Floor/Room FAILED: {result}"
    return None


def main():
    argv = sys.argv
    if "--" not in argv:
        print("Usage: blender --background --python generate_test_blends.py -- <scenario_index>")
        sys.exit(1)
    scenario_index = int(argv[argv.index("--") + 1])
    filename, description, overrides = SCENARIOS[scenario_index]

    print(f"Loading addon from: {ADDON_PATH}")
    spec = importlib.util.spec_from_file_location("levelArchitect_v2", ADDON_PATH)
    addon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(addon)
    addon.register()

    scene = bpy.context.scene
    apply_settings(scene, overrides)

    error = run_pipeline(overrides.get("_run_separate", False), addon)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, filename)
    bpy.ops.wm.save_as_mainfile(filepath=out_path)

    status = "OK" if error is None else error
    with open(TESTFILES_TXT, "a") as f:
        f.write(f"{filename}\t[{status}]\t{description}\n")

    print(f"Saved {out_path} -- {status}")


main()
