# Game Level Architect -- procedural game level generator for Blender
# Copyright (C) 2026 Ivica Sršan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import re
import math
import os
import random
from collections import deque

import bpy
from bpy.props import (
    BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty,
    IntProperty, StringProperty,
)
from bpy_extras.io_utils import ExportHelper

bl_info = {
    "name": "Game Level Architect",
    "author": "Ivica Sršan",
    "version": (0, 42, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > Level Architect Tab",
    "description": "Procedural game level generator using Python WFC and automatic Geometry Nodes meshing.",
    "category": "3D View",
    "warning": "Early testing release -- feedback welcome",
    "license": "GPL-3.0-or-later",
}

# ==============================================================================
# 0. SHARED CONSTANTS
# ==============================================================================
# Tile IDs baked into the "tile_id" point attribute and consumed by the GN graph.
TILE_AIR = 0
TILE_FLOOR = 1
TILE_WALL = 2  # reserved: walls are now a derived silhouette (see section 2b), not a solver tile
TILE_STAIR = 3
TILE_ENTRANCE = 4
TILE_EXIT = 5

WALKABLE = {TILE_FLOOR, TILE_STAIR, TILE_ENTRANCE, TILE_EXIT}

# Object names, shared between the blueprint operator and the wall operator
# (the latter reads the former's mesh data directly).
BLUEPRINT_OBJECT_NAME = "Procedural_Level_Blueprint"
ROUND_FLOOR_OBJECT_NAME = "Procedural_Level_RoundFloors"
WALLS_OBJECT_NAME = "Procedural_Level_Walls"
WALLS_ROUND_OBJECT_NAME = "Procedural_Level_RoundWalls"
WINDOWS_OBJECT_NAME = "Procedural_Level_Windows"
STAIRS_OBJECT_NAME = "Procedural_Level_Stairs"
DOORS_OBJECT_NAME = "Procedural_Level_Doors"
DOORS_ROUND_OBJECT_NAME = "Procedural_Level_RoundDoors"
# Panels are named f"{DOORS_OBJECT_NAME}_Panel_{i:03d}" (see
# _build_door_panels), which _remove_objects_by_prefix(DOORS_OBJECT_NAME)
# already cleans up on regeneration -- it matches base_name + "_...".
DOOR_PANELS_COLLECTION_NAME = "Procedural Level Door Panels"
PROPS_TORCH_OBJECT_NAME = "Procedural_Level_Torches"
PROPS_DECORATION_OBJECT_NAME = "Procedural_Level_Decoration"
PROPS_LIGHT_NAME_PREFIX = "Procedural_Level_Light"
PROPS_COLLECTION_NAME = "Procedural Level Props"
PROPS_TORCH_COLLECTION_NAME = "Procedural Level Props - Torches"
PROPS_LIGHT_COLLECTION_NAME = "Procedural Level Props - Lights"
PROPS_DECORATION_COLLECTION_NAME = "Procedural Level Props - Decoration"
BLUEPRINT_SPLIT_COLLECTION_NAME = "Procedural Level Blueprint (Split)"
# Prefix for the collection OBJECT_OT_FreezeForTextureWork creates each time
# it runs (one new collection per freeze, named f"{FROZEN_COLLECTION_PREFIX}
# - Seed{n}", disambiguated with a trailing " (2)" etc. on a name collision).
FROZEN_COLLECTION_PREFIX = "Frozen"

# The four cardinal horizontal neighbor offsets, used for corridor/BFS moves.
HORIZONTAL_NEIGHBORS = [
    (-1, 0),
    (1, 0),
    (0, -1),
    (0, 1),
]

# Which tile_rotation value makes a stair's ascent (local +Y, per
# _build_stair_mesh) exit toward a given cardinal direction -- the spec's
# four allowed rotation values (0/90/180/270 deg).
STAIR_EXIT_ROTATION = {
    (0, 1): 0.0,
    (-1, 0): 1.5708,
    (0, -1): 3.1415,
    (1, 0): 4.7123,
}
DIRECTION_FOR_ROTATION = {rotation: direction for direction, rotation in STAIR_EXIT_ROTATION.items()}


def _direction_for_rotation(rot, tolerance=0.01):
    """Same lookup as DIRECTION_FOR_ROTATION[rot], but tolerant of the
    value having round-tripped through a baked FLOAT mesh attribute --
    Blender stores those as 32-bit floats, so a rotation written as one
    of the exact Python float64 constants above (e.g. 3.1415) can read
    back as something like 3.1414999961853027. A plain dict lookup
    requires exact equality and silently misses that, falling through to
    the default (0, 1) -- which is exactly wrong, not just imprecise,
    since it picks a real (just different) direction rather than failing
    loudly. This finds the nearest of the 4 known rotations instead, and
    only gives up (returning the (0, 1) default) if nothing is within
    tolerance, i.e. the value is truly unrecognized rather than just
    float32-rounded. Only needed where rotation is ever read back OUT of
    a mesh attribute (_read_stair_runs) -- solver-internal call sites
    pass the exact float64 constant directly and can use
    DIRECTION_FOR_ROTATION's plain dict lookup safely."""
    closest = min(DIRECTION_FOR_ROTATION, key=lambda r: abs(r - rot))
    if abs(closest - rot) > tolerance:
        return (0, 1)
    return DIRECTION_FOR_ROTATION[closest]

# The smallest stairwell room that can still have a 1-tile walkable buffer
# on every side of the stair -- 1 tile of climb-axis buffer before AND
# after the shortest meaningful climb (2 tiles), plus 1 tile of walkway on
# both sides of the (always 1-tile-wide) stair column. Anything smaller
# forces the stair to touch the room's boundary wall directly, which is
# exactly what caused stairs to visibly clip through walls / open into
# thin air -- so this is the floor for every stairwell placement attempt,
# including the last-resort fallback before giving up on a proper room
# entirely (see _find_stair_footprint's callers).
MIN_STAIR_ROOM_WIDTH = 3
MIN_STAIR_ROOM_LENGTH = 4

# The smallest room that still gets a buffer at all -- 1 tile of buffer
# before and after a single-tile climb (1 + 1 + 1 = 3). Tried only after
# MIN_STAIR_ROOM_WIDTH x MIN_STAIR_ROOM_LENGTH fails to fit anywhere, as a
# last attempt at a walled, walkable-around stairwell before falling all
# the way back to a bare single tile with no room reserved around it at
# all -- which is what let stairs land in the middle of an ordinary 1-tile
# corridor with nowhere to walk around them.
FALLBACK_STAIR_ROOM_LENGTH = 3

# Width of a "corridor stair" (see WFC_Level_Solver.corridor_stairs) -- no
# separate walkway beside the climb, so it reserves only the single column
# it actually climbs through, same as an ordinary 1-tile-wide corridor.
# _carve_stair_room already degrades correctly at width 1 (walk_perp_idx
# and stair_perp_idx collapse to the same index, and the ceiling opening
# shrinks from 2 tiles to 1), so this is a placement-search choice, not a
# separate code path.
CORRIDOR_STAIR_WIDTH = 1

# Minimum room footprint a BENT stairwell (see WFC_Level_Solver.
# stair_bend_chance / _carve_bent_stair_path) is attempted against --
# needs more room along the climb axis than a straight run (two climb
# segments plus a landing tile, not one), and more room across it for a
# 'U' turn's second lane (see BENT_STAIR_LANE_OFFSET). Larger than the
# plain MIN_STAIR_ROOM_WIDTH/LENGTH on purpose: _carve_bent_stair_path
# already bounds-checks every cell it would carve and falls back to an
# ordinary straight run if the bent path doesn't fit, so these are a
# search-time head start toward footprints likely to actually succeed,
# not a hard requirement enforced anywhere else.
MIN_BENT_STAIR_ROOM_WIDTH = 5
MIN_BENT_STAIR_ROOM_LENGTH = 5

# How many tiles apart a 'U' turn's two parallel lanes sit -- reversing
# straight back from the landing would walk directly through the first
# segment's own already-carved tiles, so the second segment starts offset
# sideways by this many tiles instead, the real "dog-leg" shape.
BENT_STAIR_LANE_OFFSET = 2


def _set_prop(node, prop_name, value):
    """Best-effort setattr for node properties whose enum identifiers can drift
    between Blender versions (this addon targets an unreleased 5.2 API surface).
    Failing softly here means one renamed enum doesn't crash the whole generator."""
    try:
        setattr(node, prop_name, value)
    except (AttributeError, TypeError) as exc:
        print(f"[Level Architect] Could not set {node.bl_idname}.{prop_name} = {value!r}: {exc}")


def _set_input(node, socket_name, value):
    try:
        node.inputs[socket_name].default_value = value
    except (KeyError, TypeError, ValueError) as exc:
        print(f"[Level Architect] Could not set input '{socket_name}' on {node.bl_idname}: {exc}")


def _fine_level_height(scene):
    """The physical height (meters) of ONE sub-level slice, vs.
    wfc_level_height (the height of one whole logical floor). Split levels
    subdivide a floor into wfc_sub_levels_per_floor internal Z-slices, each
    this tall -- every place that positions/measures geometry along Z
    (vertex export, wall/stair mesh building, the GN modifier's Isometric
    Mode culling) uses THIS value, never wfc_level_height directly, so a
    sub_levels_per_floor of 1 (the default) reproduces the original
    single-slice-per-floor behavior exactly."""
    return scene.wfc_level_height / max(1, scene.wfc_sub_levels_per_floor)


# ==============================================================================
# 1. CORE LOGIC ENGINE (CONSTRAINT-BASED WFC-STYLE SOLVER)
# ==============================================================================
# NOTE: this is a lightweight, WFC-inspired room/corridor/stair generator with
# explicit adjacency rules and a BFS connectivity guarantee -- not a general
# wave-function-collapse solver over arbitrary tile sets. That is the right
# scope for a game-level blueprint tool: it is fast, deterministic-per-seed,
# and every rule below is one you can reason about and tune by hand.
#
# Generation pipeline (per solve() call):
#   1. Scatter non-overlapping room rectangles across the full grid, spread
#      roughly evenly across every Z level so every story has content.
#   2. Connect same-level rooms with a minimum-spanning-tree of corridors --
#      MST rather than nearest-neighbor-only guarantees every room on a level
#      is reachable from every other room on that level with no extra loops.
#   3. Connect consecutive levels with a stair between their nearest rooms.
#   4. Wire the fixed Entrance/Exit corners into their level's room network.
#   5. Extrude walls around every exposed floor/corridor edge.
#   6. BFS-verify Entrance->Exit reachability; carve a direct repair corridor
#      in the rare case scatter placement left a level under-connected.
#
# Adjacency constraints enforced:
#   - A Stair tile at (x, y, z) MUST have a Floor-like tile at (x, y, z+1)
#     directly above it (the stair's exit vector is always straight up).
#   - A Stair tile itself is walkable, so it also needs a Floor-like or Stair
#     neighbor horizontally to be reachable in the first place.
#   - Any Air cell horizontally adjacent to a Floor/Entrance/Exit/Stair cell
#     becomes a Wall, oriented to face the walkable cell it borders.
#   - Entrance and Exit must be connected by a walkable path (BFS-verified);
#     if generation leaves them isolated, a corridor is carved as a repair
#     pass so no locked/unreachable rooms ever ship.
class WFC_Level_Solver:
    def __init__(
        self, width, length, height, room_count,
        room_size_min=2, room_size_max=4, stairs_per_level=3,
        tile_size=4.0, level_height=4.0, room_shape='RECT',
        stair_room_width=3, stair_room_length=4, corridor_stairs=False,
        sub_levels_per_floor=1, split_level_chance=0.3,
        elevation_chance=0.0, elevation_range=0.0, max_ramp_slope_deg=30.0,
        floor_profiles=None, stair_bend_chance=0.0, stair_bend_style='RANDOM',
    ):
        self.w = width
        self.l = length
        # self.h is the FINE Z resolution the rest of the solver works in --
        # every corridor/stair/BFS/connectivity method below already treats
        # "z" as an opaque grid index with no assumption about what it
        # represents, so subdividing each logical floor into
        # sub_levels_per_floor internal slices needed almost no other
        # change here: _rooms_per_level and _scatter_rooms are the only two
        # methods that need to know the difference between a LOGICAL floor
        # (self.height_logical, what stairs_per_level/room distribution/the
        # user's Height field mean) and a fine slice (self.h). Everything
        # else -- corridor MST, inter-slice stairs, BFS reachability, the
        # repair pass -- just sees more Z values to iterate and connects
        # them exactly as it always did, whether a given transition is a
        # split-level step within one floor or a jump to the next floor.
        self.height_logical = height
        self.sub_levels = max(1, sub_levels_per_floor)
        self.split_level_chance = max(0.0, min(1.0, split_level_chance))
        self.h = height * self.sub_levels
        self.target_rooms = room_count
        self.room_size_min = room_size_min
        self.room_size_max = room_size_max
        self.stairs_per_level = stairs_per_level
        self.room_shape = room_shape  # 'RECT', 'ROUND', or 'MIXED' (per-room random choice)
        # Per-floor override breakpoints (see WFC_FloorProfile) -- a list
        # of dicts with 'floor_index'/'room_size_min'/'room_size_max'/
        # 'room_shape' keys, empty by default. Only ever consulted by
        # _room_size_for_floor/_room_shape_for_floor, both of which fall
        # straight back to the flat self.room_size_min/max/room_shape
        # above when this is empty -- so passing nothing here is byte-
        # identical to how every version of this class behaved before
        # this feature existed. Ignored entirely when self.room_shape is
        # 'CAVE' (see _scatter_rooms's early return) -- mixing Cave and
        # non-Cave floors in one generation is a separate, larger,
        # already-tracked limitation, not something this feature attempts.
        self.floor_profiles = floor_profiles or []

        # Every stair now lives inside its own fully enclosed stairwell room
        # of this footprint, reserved identically on the level it starts on
        # AND the level above -- see _carve_stair_room. That guarantees a
        # clean rectangular wall silhouette on both floors (no more organic
        # growth from a room's center with a 1-tile side buffer, which is
        # what produced jagged/incomplete walls around stairs before).
        self.stair_room_width = max(MIN_STAIR_ROOM_WIDTH, stair_room_width)
        self.stair_room_length = max(MIN_STAIR_ROOM_LENGTH, stair_room_length)
        # Corridor Stairs (opt-in, default off): the same _find_stair_footprint
        # / _carve_stair_room machinery, but searching for a flush 1-wide
        # strip (CORRIDOR_STAIR_WIDTH, margin=0) instead of a buffered
        # room -- see _stair_footprint_chain. Much cheaper on space, so it
        # should also mean far fewer bufferless-emergency-fallback stairs
        # in dense layouts; the trade is no walkway beside the climb, since
        # there's no room to put one in.
        self.corridor_stairs = corridor_stairs

        # Bent stairwells (opt-in, default off -- 0.0 is byte-identical to
        # every stairwell staying a single straight run, as before this
        # feature existed): each normal (non-repair, non-Corridor-Stairs)
        # stairwell independently rolls stair_bend_chance to bend through
        # one landing into two straight segments instead of one straight
        # run -- see _carve_bent_stair_path. 'L' turns the second segment
        # 90 degrees (chosen left/right at random each time), 'U' reverses
        # it 180 degrees (a "dog-leg", offset into a second parallel lane
        # so it doesn't walk back through its own first segment), 'RANDOM'
        # picks L or U per stairwell. Only ever attempted on room-based
        # stairwells (Corridor Stairs' 1-wide footprint has no room for a
        # second lane or a landing) and only from normal placement, never
        # from _ensure_connectivity's own repair pass, which stays on the
        # simplest, most reliable path since its whole job is guaranteeing
        # connectivity exists at all. Falls back to an ordinary straight
        # run automatically if the bent path doesn't fit the footprint
        # (_carve_bent_stair_path returning None) -- carving SOME valid
        # stair here is mandatory, bending is only ever a bonus.
        self.stair_bend_chance = max(0.0, min(1.0, stair_bend_chance))
        self.stair_bend_style = stair_bend_style

        # Continuous room elevation (see DEVELOPMENT.md "Middle-ground
        # sketch"): purely a rendering-layer feature on top of the
        # unchanged discrete grid -- elevation_chance/elevation_range
        # default to 0, which is byte-identical to no elevation at all.
        # See _apply_continuous_elevation for the actual logic.
        self.elevation_chance = max(0.0, min(1.0, elevation_chance))
        self.elevation_range = max(0.0, elevation_range)
        self.max_ramp_slope_deg = max(1.0, min(89.0, max_ramp_slope_deg))
        self.tile_size = tile_size
        # Previously accepted but never stored -- every OTHER world-Z
        # computation happens later, at mesh-build time, outside the
        # solver, so nothing needed it before. A bent stairwell's landing
        # needs to bake its own proportional mid-climb height directly
        # into cell_z_offset (below) at SOLVE time instead, the same way
        # every other z_offset value already is, so Walls/Doors pick it up
        # automatically with no changes of their own -- that needs the
        # real meters value here.
        self.level_height = level_height

        self.grid = [[[TILE_AIR for _ in range(self.h)] for _ in range(self.l)] for _ in range(self.w)]
        self.rotations = [[[0.0 for _ in range(self.h)] for _ in range(self.l)] for _ in range(self.w)]
        # World-Z offset (meters) added on top of z * level_height when
        # rendering a cell -- 0.0 everywhere except cells an elevated room
        # and its single connecting ramp corridor claim (see
        # _apply_continuous_elevation). The solver's own reasoning
        # (connectivity, room-fit, corridor carving, stairs) never reads
        # this -- it's applied once, after solving, purely for the meshes
        # that get built from the final grid.
        self.cell_z_offset = [[[0.0 for _ in range(self.h)] for _ in range(self.l)] for _ in range(self.w)]
        # Index into self.rooms for a floor cell that's part of a scattered
        # room, -1 for corridor/stairwell/entrance/exit floor -- lets the GN
        # graph give each room its own material slot.
        self.room_id = [[[-1 for _ in range(self.h)] for _ in range(self.l)] for _ in range(self.w)]
        # Identifies which multi-tile staircase a stair cell belongs to (-1
        # for non-stair cells), so the stairs operator can group them back
        # into one continuous run instead of building len(run) separate
        # single-tile staircases.
        self.stair_run_id = [[[-1 for _ in range(self.h)] for _ in range(self.l)] for _ in range(self.w)]
        self._next_stair_run_id = 0
        # Which straight segment of its (possibly bent) run a stair cell
        # belongs to -- 0 for every cell of an ordinary straight run (the
        # only value that ever existed before bent stairwells), 0/1 for a
        # bent run's first/second segment respectively. _read_stair_runs
        # uses this to split a stair_run_id group back into ORDERED
        # segments directly, rather than trying to infer segment order
        # from geometry after the fact.
        self.stair_segment_index = [[[0 for _ in range(self.h)] for _ in range(self.l)] for _ in range(self.w)]
        # (x, y, z) cells that are a stairwell's ceiling opening -- the floor
        # renderer skips these so climbing a stair doesn't dead-end into a
        # solid slab.
        self.floor_openings = set()
        self.rooms = []  # each: {'x','y','z','w','l','cx','cy'}
        self.room_shapes = {}  # room_index -> 'RECT'/'ROUND', what _carve_room actually carved
        self.room_cells = {}  # room_index -> [(x, y), ...] actually-carved cells (RECT: the
                               # whole box; ROUND: only cells inside the inscribed ellipse)
        # Rooms grouped by z, built once at the end of _scatter_rooms() --
        # every later pass needs "rooms on level z" repeatedly, so this
        # trades one grouping pass for the O(h) re-filter-of-self.rooms every
        # caller used to do.
        self._rooms_by_level = {}

        self.start = (1, 1, 0)
        end_z = self.h - 1 if self.h > 1 else 0
        self.end = (self.w - 2, self.l - 2, end_z)

    def in_bounds(self, x, y, z):
        return 0 <= x < self.w and 0 <= y < self.l and 0 <= z < self.h

    def solve(self):
        sx, sy, sz = self.start
        ex, ey, ez = self.end

        self._scatter_rooms()
        self._connect_rooms_per_level()
        self._connect_levels_with_stairs()
        self._wire_entrance_and_exit()
        self._ensure_connectivity()
        self._apply_continuous_elevation()

        # Entrance/Exit markers always win over anything a pass wrote at that
        # cell -- including a room_id, since it's no longer room floor.
        self.grid[sx][sy][sz] = TILE_ENTRANCE
        self.grid[ex][ey][ez] = TILE_EXIT
        self.room_id[sx][sy][sz] = -1
        self.room_id[ex][ey][ez] = -1

    # -- room scattering -------------------------------------------------------
    def _rooms_per_level(self):
        """Distribute room count across every LOGICAL floor (not fine
        Z-slice -- a floor subdivided into split levels still counts as
        ONE floor here), with at least one room per floor so the entrance
        floor and the exit floor are both guaranteed to have a room to
        connect into."""
        counts = [1] * self.height_logical
        leftover = self.target_rooms - self.height_logical
        i = 0
        while leftover > 0:
            counts[i % self.height_logical] += 1
            leftover -= 1
            i += 1
        return counts

    def _room_fits(self, x, y, rw, rl, z, margin=1):
        """A room fits if its footprint plus a 1-cell buffer (so rooms never
        touch and always get a wall between them) is entirely empty and in
        bounds.

        A Round room only carves cells inside its inscribed ellipse (see
        _carve_room), so its own bounding-box corners are never marked
        TILE_FLOOR and read as plain empty TILE_AIR above -- but its wall
        RING (_build_round_room_walls_mesh) is still a real ellipse spanning
        the room's FULL rectangle, cutting diagonally straight through those
        "empty" corners. Without this second check, a new room or stairwell
        could get placed into that dead corner (the grid genuinely has no
        floor there) and later physically collide with the round wall ring
        once it's built -- confirmed via a real user repro (stairs clipping
        into a Round room's wall). So this also rejects any candidate whose
        footprint overlaps an existing ROUND room's full reserved rectangle
        at the same z, not just its actually-carved cells."""
        for xi in range(x - margin, x + rw + margin):
            for yi in range(y - margin, y + rl + margin):
                if not self.in_bounds(xi, yi, z):
                    return False
                if self.grid[xi][yi][z] != TILE_AIR:
                    return False
        for room_index, room in enumerate(self.rooms):
            if room['z'] != z or self.room_shapes.get(room_index) != 'ROUND':
                continue
            rx0, ry0 = room['x'], room['y']
            rx1, ry1 = rx0 + room['w'], ry0 + room['l']
            if x < rx1 and x + rw > rx0 and y < ry1 and y + rl > ry0:
                return False
        return True

    def _room_size_for_floor(self, logical_floor):
        """(min, max) room size for this logical floor, from
        self.floor_profiles -- linearly interpolated between the two
        nearest breakpoints (rounded to the nearest int), clamped to the
        nearest end's value outside the breakpoints' own range. Falls back
        to the flat self.room_size_min/max when floor_profiles is empty."""
        if not self.floor_profiles:
            return self.room_size_min, self.room_size_max
        points = sorted(self.floor_profiles, key=lambda p: p['floor_index'])
        if logical_floor <= points[0]['floor_index']:
            p = points[0]
            return p['room_size_min'], p['room_size_max']
        if logical_floor >= points[-1]['floor_index']:
            p = points[-1]
            return p['room_size_min'], p['room_size_max']
        for a, b in zip(points, points[1:]):
            if a['floor_index'] <= logical_floor <= b['floor_index']:
                span = b['floor_index'] - a['floor_index']
                t = (logical_floor - a['floor_index']) / span if span > 0 else 0.0
                size_min = round(a['room_size_min'] + (b['room_size_min'] - a['room_size_min']) * t)
                size_max = round(a['room_size_max'] + (b['room_size_max'] - a['room_size_max']) * t)
                return size_min, max(size_max, size_min)
        return self.room_size_min, self.room_size_max  # unreachable, keeps this defensive

    def _room_shape_for_floor(self, logical_floor):
        """Step function (shape isn't numeric, so no interpolation): the
        LAST floor_profiles breakpoint at or before this logical floor
        wins. Falls back to self.room_shape before the first breakpoint or
        when floor_profiles is empty."""
        if not self.floor_profiles:
            return self.room_shape
        chosen = self.room_shape
        for p in sorted(self.floor_profiles, key=lambda p: p['floor_index']):
            if p['floor_index'] <= logical_floor:
                chosen = p['room_shape']
            else:
                break
        return chosen

    def _pick_room_shape(self, logical_floor):
        shape = self._room_shape_for_floor(logical_floor)
        if shape == 'MIXED':
            return 'ROUND' if random.random() < 0.5 else 'RECT'
        return shape

    def _carve_room(self, x, y, rw, rl, z, room_index, shape):
        """Carves one room's floor footprint. 'RECT' fills the whole
        x..x+rw, y..y+rl bounding box (unchanged behavior). 'ROUND' only
        fills cells inside an ellipse inscribed in that same box -- the
        usual voxel/tile-grid approximation of a circular room. Rooms
        smaller than 3 tiles on either side fall back to RECT regardless of
        the requested shape, since the ellipse test would leave too few
        cells to read as a room (or none at all for a 2x2).

        The ellipse is deliberately tightened (<= 0.8, not the mathematical
        circle's <= 1.0) rather than exactly inscribed: at the room sizes
        this generator actually produces (roughly 3-6 tiles), a true
        inscribed circle only ever clips the 4 extreme corner tiles no
        matter how big the room gets within that range -- practically
        indistinguishable from a plain rectangle at a glance, which is why
        'Round' rooms weren't reading as round at all. At 0.8 even a
        minimum-size 3x3 room carves into a visible plus/diamond, and it
        scales up into a proper stepped octagon by 6x6.

        _room_fits still reserves the FULL bounding box (plus margin) for a
        round room, same as a rect one -- simpler than ellipse-aware overlap
        checks, at the cost of leaving the box's unused corners as
        permanently-empty Air rather than lettings another room claim them.

        At extreme aspect ratios (e.g. very wide, short boxes) the ellipse
        threshold can leave a lone corner tile inside the 0.8 cutoff while
        every tile between it and the main blob falls outside it -- one
        room_index ends up carved as two disconnected pieces (confirmed:
        the stray piece is always a single tile, never a larger chunk).
        Only the LARGEST 4-connected group is kept below, so a room is
        always one contiguous blob by construction -- the rare stray tile
        is dropped rather than kept as a disconnected "part of the room" a
        player could never actually notice as connected to anything."""
        if shape == 'ROUND' and rw >= 3 and rl >= 3:
            cx = x + (rw - 1) / 2.0
            cy = y + (rl - 1) / 2.0
            rx = rw / 2.0
            ry = rl / 2.0
            cells = [
                (xi, yi)
                for xi in range(x, x + rw)
                for yi in range(y, y + rl)
                if ((xi - cx) / rx) ** 2 + ((yi - cy) / ry) ** 2 <= 0.8
            ]
            cells = self._largest_connected_group(cells)
            self.room_shapes[room_index] = 'ROUND'
        else:
            cells = [(xi, yi) for xi in range(x, x + rw) for yi in range(y, y + rl)]
            self.room_shapes[room_index] = 'RECT'

        self.room_cells[room_index] = cells
        for xi, yi in cells:
            self.grid[xi][yi][z] = TILE_FLOOR
            self.room_id[xi][yi][z] = room_index

    @staticmethod
    def _largest_connected_group(cells):
        """Keeps only the largest 4-connected group within `cells`, dropping
        any smaller disconnected piece(s). Used so a carved room is always
        one contiguous blob, never the main shape plus a stray isolated
        tile floating in the same bounding box."""
        cell_set = set(cells)
        seen = set()
        best = []
        for start in cells:
            if start in seen:
                continue
            component = []
            stack = [start]
            seen.add(start)
            while stack:
                cx, cy = stack.pop()
                component.append((cx, cy))
                for dx, dy in HORIZONTAL_NEIGHBORS:
                    neighbor = (cx + dx, cy + dy)
                    if neighbor in cell_set and neighbor not in seen:
                        seen.add(neighbor)
                        stack.append(neighbor)
            if len(component) > len(best):
                best = component
        return best

    def _pick_fine_z_for_floor(self, logical_floor):
        """Most rooms sit at their floor's base slice; split_level_chance of
        the time (when sub_levels > 1), a room instead rolls one of the
        floor's OTHER internal slices -- still the same logical floor for
        room-count distribution/stairs-per-level/labeling purposes, just
        physically raised or lowered. Connecting it to the rest of the
        floor needs no new machinery: it's just another fine-Z transition,
        handled the same way as a between-floor one by
        _connect_levels_with_stairs."""
        base = logical_floor * self.sub_levels
        if self.sub_levels <= 1 or random.random() > self.split_level_chance:
            return base
        return base + random.randint(0, self.sub_levels - 1)

    def _carve_cave_tunnel(self, start_x, start_y, z, target=None):
        """One 'drunkard's walk' leg of a Cave floor's network: wanders from
        (start_x, start_y) -- always an already-carved chamber's center --
        carving a 1-tile-wide tunnel (room_id -1, exactly like an ordinary
        corridor cell) as it goes. Returns the final (x, y), where the
        caller carves the next chamber.

        With target=None (the common case), direction has a bias toward
        continuing the same way so the path reads as winding tunnels rather
        than pure noise, and the step count is a fixed random range
        unrelated to distance from anywhere in particular.

        With target=(tx, ty) -- used for the one chamber that must actually
        reach the level's exit corner (see _carve_cave_floors) -- direction
        instead has a bias toward whichever axis closes the most distance
        to the target, and the step budget is sized off the actual Manhattan
        distance plus slack, so the walk reliably gets there while still
        wiggling en route instead of a dead-straight line covering that
        entire distance -- a straight corridor spanning most of the map is
        exactly the un-organic look this mode exists to avoid.

        Bounded by a fixed 1-tile margin -- NOT the next chamber's own
        (much larger) half-size. Using the chamber's margin here looks
        appealing (the chamber would never need reclamping afterward) but
        backfires: (start_x, start_y) is only guaranteed to satisfy some
        EARLIER, usually smaller chamber's margin, and if it already sits
        inside the new, bigger excluded zone near an edge, every step
        toward the interior is rejected by the very same test that was
        supposed to let it out, permanently trapping the walk at its
        (out-of-bounds-for-this-chamber) start. _carve_cave_floors clamps
        the chamber placement itself afterward instead.

        Only ever writes cells that are still TILE_AIR, so wandering back
        over an earlier tunnel or chamber just merges into it -- a real cave
        network is allowed to loop back on itself -- instead of stomping
        whatever room_id was already there."""
        x, y = start_x, start_y
        directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        direction = random.choice(directions)
        if target is not None:
            tx, ty = target
            # Generous slack, not just enough for a beeline: every step the
            # walk spends rejecting a stair-side-exposing move (see the
            # bounds check below) is a step that makes no progress at all,
            # and dense Cave floors reject fairly often -- too little slack
            # here means the walk frequently runs out before actually
            # reaching the target, leaving the short unguarded
            # _carve_corridor bridge in _carve_cave_floors/
            # _connect_room_to_point to close the last stretch (which,
            # unlike this walk, has no way to route AROUND a stair's side).
            steps = abs(tx - start_x) + abs(ty - start_y) + random.randint(self.room_size_max, self.room_size_max * 4)
        else:
            steps = random.randint(self.room_size_max, max(self.room_size_max + 1, (self.w + self.l) // 3))
        for _ in range(steps):
            if target is not None and random.random() < 0.6:
                dx, dy = tx - x, ty - y
                if dx == 0 and dy == 0:
                    direction = random.choice(directions)
                elif abs(dx) > abs(dy):
                    direction = (1 if dx > 0 else -1, 0)
                else:
                    direction = (0, 1 if dy > 0 else -1)
            elif random.random() > 0.75:
                direction = random.choice(directions)
            nx, ny = x + direction[0], y + direction[1]
            if not (1 <= nx < self.w - 1 and 1 <= ny < self.l - 1) \
               or (self.grid[nx][ny][z] == TILE_AIR and self._would_expose_stair_side(nx, ny, z)):
                direction = random.choice(directions)
                continue
            x, y = nx, ny
            if self.grid[x][y][z] == TILE_AIR:
                self.grid[x][y][z] = TILE_FLOOR
                self.room_id[x][y][z] = -1
            if target is not None and (x, y) == target:
                # Stop the instant a targeted walk arrives -- the step
                # budget above is sized with slack specifically so the walk
                # doesn't beeline there, but that same slack means it can
                # still have steps left AFTER arriving. Left unchecked, that
                # remaining budget keeps wandering (with its bias now
                # pointing at zero distance, so effectively random) right
                # around the thing it just reached -- for a stairwell
                # that's the wall enclosing it, so a stray extra tunnel
                # cell landing against its side punches an unintended gap
                # in what should be a fully sealed room, wall-optional-only
                # at its one real entry.
                break
        return x, y

    def _carve_cave_floors(self):
        """Cave floor-shape mode: replaces room-scatter + the MST corridor
        pass with one organic connected network per logical floor. A
        handful of 'drunkard's walks' (_carve_cave_tunnel) wander the grid
        carving tunnel; every walk after the first starts from an
        already-placed chamber's center, so the whole network is connected
        by construction -- no separate corridor-connection pass needed (see
        the CAVE early-return in _connect_rooms_per_level).

        Each walk ends by carving a round chamber -- reusing _carve_room's
        existing ROUND ellipse carve verbatim -- that gets a real room_id,
        just like a scattered room. That's what makes every downstream
        system (walls, doors, stairs, entrance/exit wiring, elevation) keep
        working completely unmodified: a door appears wherever a chamber
        meets a tunnel (room_id differs either side of the boundary),
        never between two tunnel cells (room_id -1 on both sides) -- the
        exact same rule that already governs a normal room/corridor
        boundary today. Chamber count per floor reuses _rooms_per_level's
        existing distribution and chamber size reuses room_size_min/max,
        so this needs no new user-facing settings at all.

        Ignores sub_levels_per_floor/split_level_chance -- every cave floor
        sits at its logical floor's base fine-Z slice. Split-level cave
        floors are a possible future refinement, not attempted here.

        The entrance/exit corners ((1, 1) and (w-2, l-2), fixed regardless
        of room_shape -- see __init__) are anchored explicitly rather than
        left to chance: a purely random walk covering only a modest
        fraction of the map routinely misses one or both corners entirely,
        and _ensure_connectivity's last-resort repair for that closes the
        gap with one dead-straight corridor spanning the whole empty map --
        exactly the kind of feature this mode exists to avoid. Chamber 0
        starts AT the entrance directly (free -- nothing to bridge from
        yet). The exit instead gets a target-biased walk (see
        _carve_cave_tunnel) from the last chamber placed before it, so it
        still reads as an organic tunnel that happens to end at the exit,
        not a straight beeline to it."""
        counts = self._rooms_per_level()
        sx, sy, sz = self.start
        ex, ey, ez = self.end
        for logical_floor in range(self.height_logical):
            z = logical_floor * self.sub_levels
            floor_rooms = []
            for i in range(counts[logical_floor]):
                rw = random.randint(self.room_size_min, self.room_size_max)
                rl = random.randint(self.room_size_min, self.room_size_max)
                margin_x = 1 + rw // 2
                margin_y = 1 + rl // 2
                is_last = i == counts[logical_floor] - 1
                connect_from = None  # tunnel's real endpoint, if it ends up != the final chamber center
                if i == 0 and z == sz:
                    cx = max(margin_x, min(self.w - 1 - margin_x, sx))
                    cy = max(margin_y, min(self.l - 1 - margin_y, sy))
                elif i == 0:
                    cx = random.randint(margin_x, max(margin_x, self.w - 1 - margin_x))
                    cy = random.randint(margin_y, max(margin_y, self.l - 1 - margin_y))
                else:
                    target = (ex, ey) if (is_last and z == ez) else None
                    if target is not None:
                        # Walk from whichever existing chamber is actually
                        # closest to the exit -- keeps the biased walk's
                        # distance (and so how much of it reads as
                        # "beelining") as short as the network allows,
                        # rather than risking a long directed walk from an
                        # arbitrary far-away chamber.
                        start_room = min(floor_rooms, key=lambda r: abs(r['cx'] - ex) + abs(r['cy'] - ey))
                    else:
                        start_room = random.choice(floor_rooms)
                    cx, cy = self._carve_cave_tunnel(start_room['cx'], start_room['cy'], z, target=target)
                    connect_from = (cx, cy)

                # Clamping the box in bounds can shift its center away from
                # (cx, cy) -- the tunnel's raw endpoint -- near a map edge.
                # A short corridor from the pre-clamp point closes that gap;
                # skipped whenever nothing actually moved (every cell on
                # that straight-line path would already be Floor).
                x = max(1, min(self.w - 1 - rw, cx - rw // 2))
                y = max(1, min(self.l - 1 - rl, cy - rl // 2))
                final_cx, final_cy = x + rw // 2, y + rl // 2
                if connect_from is not None and connect_from != (final_cx, final_cy):
                    self._carve_corridor(connect_from[0], connect_from[1], final_cx, final_cy, z)

                room_index = len(self.rooms)
                self._carve_room(x, y, rw, rl, z, room_index, 'ROUND')
                room = {
                    'x': x, 'y': y, 'z': z, 'w': rw, 'l': rl,
                    'cx': x + rw // 2, 'cy': y + rl // 2,
                }
                self.rooms.append(room)
                floor_rooms.append(room)

            for room in floor_rooms:
                self._rooms_by_level.setdefault(z, []).append(room)

        self._scattered_room_count = len(self.rooms)

    def _scatter_rooms(self):
        if self.room_shape == 'CAVE':
            self._carve_cave_floors()
            return

        counts = self._rooms_per_level()
        for logical_floor in range(self.height_logical):
            placed = 0
            attempts = 0
            max_attempts = counts[logical_floor] * 40
            size_min, size_max = self._room_size_for_floor(logical_floor)
            while placed < counts[logical_floor] and attempts < max_attempts:
                attempts += 1
                z = self._pick_fine_z_for_floor(logical_floor)
                rw = random.randint(size_min, size_max)
                rl = random.randint(size_min, size_max)
                x = random.randint(1, max(1, self.w - 1 - rw))
                y = random.randint(1, max(1, self.l - 1 - rl))

                if not self._room_fits(x, y, rw, rl, z):
                    continue

                room_index = len(self.rooms)
                self._carve_room(x, y, rw, rl, z, room_index, self._pick_room_shape(logical_floor))

                self.rooms.append({
                    'x': x, 'y': y, 'z': z, 'w': rw, 'l': rl,
                    'cx': x + rw // 2, 'cy': y + rl // 2,
                })
                placed += 1

        for room in self.rooms:
            self._rooms_by_level.setdefault(room['z'], []).append(room)

        # Snapshot here, before any stairwell room gets appended to
        # self.rooms (_carve_stair_room does that later, always at a
        # higher index) -- _apply_continuous_elevation only ever considers
        # self.rooms[:self._scattered_room_count] as elevation candidates,
        # since a stairwell room's geometry (floor_openings, the stair
        # mesh itself) assumes a flat floor.
        self._scattered_room_count = len(self.rooms)

    # -- corridor connections ---------------------------------------------------
    @staticmethod
    def _manhattan(a, b):
        return abs(a['cx'] - b['cx']) + abs(a['cy'] - b['cy'])

    def _mst_pairs(self, rooms):
        """Prim's algorithm over room centers, O(n^2) via the standard
        incrementally-tracked nearest-tree-distance per remaining room,
        rather than rescanning every in-tree x remaining pair from scratch
        each step (which is O(n^3) overall). Matters once a big map pushes
        room counts into the hundreds. An MST (rather than just chaining
        rooms in placement order) guarantees every room on the level is
        reachable and keeps total corridor length low."""
        n = len(rooms)
        if n < 2:
            return []
        in_tree = [False] * n
        in_tree[0] = True
        nearest_dist = [self._manhattan(rooms[0], rooms[i]) for i in range(n)]
        nearest_tree_idx = [0] * n
        pairs = []
        for _ in range(n - 1):
            best_j, best_dist = None, None
            for j in range(n):
                if not in_tree[j] and (best_dist is None or nearest_dist[j] < best_dist):
                    best_dist, best_j = nearest_dist[j], j
            in_tree[best_j] = True
            pairs.append((rooms[nearest_tree_idx[best_j]], rooms[best_j]))
            for j in range(n):
                if in_tree[j]:
                    continue
                d = self._manhattan(rooms[best_j], rooms[j])
                if d < nearest_dist[j]:
                    nearest_dist[j] = d
                    nearest_tree_idx[j] = best_j
        return pairs

    def _connect_rooms_per_level(self):
        if self.room_shape == 'CAVE':
            # Cave floors are already fully connected by construction --
            # every chamber was carved at the end of a tunnel walked from an
            # earlier chamber (see _carve_cave_floors). Running the ordinary
            # MST corridor pass on top would draw extra straight-line
            # corridors ignoring those organic tunnels entirely.
            return
        for z in range(self.h):
            level_rooms = self._rooms_by_level.get(z, [])
            for a, b in self._mst_pairs(level_rooms):
                self._carve_corridor(a['cx'], a['cy'], b['cx'], b['cy'], z)

    def _corridor_stair_fits(self, x, y, fw, fl, z):
        """Fits-check for a Corridor Stairs footprint (CORRIDOR_STAIR_WIDTH
        1 on whichever axis is perpendicular to travel) -- used instead of
        _room_fits's uniform margin. The footprint can sit flush (no
        buffer) against existing floor at its two TRAVEL-axis ends, since
        that's exactly where the connecting corridor is meant to attach --
        margin=0 is deliberate there. But its PERPENDICULAR sides must stay
        clear: unlike a room-based stairwell (which reserves a real
        walkway alongside the stair), a 1-wide corridor stair has no side
        buffer at all, so an existing walkable cell directly beside a
        tread/landing would let a player step onto the stairs from the
        side with no wall there to stop them. A uniform margin=0
        _room_fits check (the only option before this) allowed exactly
        that -- rare on RECT/ROUND floors (corridors are sparse, so a
        stairwell searching nearby empty space rarely lands beside one),
        but routine on Cave floors (chambers are densely surrounded by
        their own tunnels): 48% of stair cells across a 40-trial stress
        test had an open perpendicular side before this fix, 0% after."""
        for xi in range(x, x + fw):
            for yi in range(y, y + fl):
                if not self.in_bounds(xi, yi, z) or self.grid[xi][yi][z] != TILE_AIR:
                    return False
        if fw == 1:
            for yi in range(y, y + fl):
                for xi in (x - 1, x + 1):
                    if self.in_bounds(xi, yi, z) and self.grid[xi][yi][z] in WALKABLE:
                        return False
        else:
            for xi in range(x, x + fw):
                for yi in (y - 1, y + 1):
                    if self.in_bounds(xi, yi, z) and self.grid[xi][yi][z] in WALKABLE:
                        return False
        return True

    def _find_stair_footprint(
        self, z, width, length, center_x=None, center_y=None, margin=1, corridor_mode=False,
    ):
        """Searches for an empty width x length rectangle that is free
        (with `margin` of buffer) on BOTH level z and level z+1 -- a
        stairwell reserves the identical footprint on the level it starts on
        and the level above, so both must be clear or the two floors would
        collide with whatever else is already there. Tries all 4 cardinal
        orientations (which axis the climb runs along). If center_x/center_y
        is given, candidate positions are tried nearest-first so the
        stairwell lands close to the room it's meant to serve; otherwise
        positions are sampled at random across the whole level.

        corridor_mode swaps the fits-check to _corridor_stair_fits (see
        there) instead of the plain uniform-margin _room_fits -- margin is
        ignored in that case (_corridor_stair_fits doesn't take one).

        Returns (x, y, footprint_w, footprint_l, rotation) or None if no
        orientation/position combination fits anywhere."""
        orientations = list(STAIR_EXIT_ROTATION.items())
        random.shuffle(orientations)

        if center_x is not None:
            max_radius = max(self.w, self.l)
            candidates = []
            for radius in range(max_radius):
                ring = [
                    (center_x + ox - width // 2, center_y + oy - length // 2)
                    for ox in range(-radius, radius + 1)
                    for oy in range(-radius, radius + 1)
                    if max(abs(ox), abs(oy)) == radius
                ]
                random.shuffle(ring)
                candidates.extend(ring)
                if len(candidates) >= 250:
                    break
        else:
            candidates = [
                (random.randint(0, self.w - 1), random.randint(0, self.l - 1))
                for _ in range(150)
            ]

        for direction, rotation in orientations:
            dx, _dy = direction
            fw, fl = (length, width) if dx != 0 else (width, length)
            for x, y in candidates:
                if corridor_mode:
                    fits = self._corridor_stair_fits(x, y, fw, fl, z) and \
                           self._corridor_stair_fits(x, y, fw, fl, z + 1)
                else:
                    fits = self._room_fits(x, y, fw, fl, z, margin=margin) and \
                           self._room_fits(x, y, fw, fl, z + 1, margin=margin)
                if fits:
                    return x, y, fw, fl, rotation
        return None

    def _carve_stair_room(self, x, y, fw, fl, rotation, z, bend=None):
        """Reserves the fw x fl rectangle as a proper enclosed room on BOTH
        z and z+1 -- this is what makes the wall pass clean: every cell in
        the footprint is walkable on both floors, so walls only ever form at
        the rectangle's true outer edge, never as a special case around the
        stair itself.

        The stair runs the full footprint length along one center
        row/column (still bordered by walkable floor on either side, which
        doubles as the walkway around the stairwell); the level above gets a
        fixed 2-tile-wide, 1-tile-deep opening directly above the stair's
        top step -- sized independently of the room so it always reads as a
        stairwell hole rather than swallowing the whole upper floor. The
        rest of that upper footprint is ordinary floor, i.e. the upper level
        is a real room that already accommodates the stairwell below it,
        not a corridor punching an isolated hole into whatever was there.

        bend, if given (90 / -90 / 180, see _carve_bent_stair_path), tries
        a bent climb -- two straight segments through one landing -- INSIDE
        this same reserved rectangle instead of one straight run. Falls
        back to the ordinary straight run automatically (this method
        always successfully carves SOME valid stair) if the bent path
        doesn't fit -- see _carve_bent_stair_path's own docstring.

        Returns (lower_room, upper_room) dicts, in the same shape as
        self.rooms entries, so the caller can corridor-connect each into its
        level's existing room network."""
        dx, dy = DIRECTION_FOR_ROTATION.get(rotation, (0, 1))
        travel_along_x = dx != 0
        size_perp, size_along = (fl, fw) if travel_along_x else (fw, fl)

        # along_idx must walk in the SAME sense as (dx, dy) -- i.e. along_idx
        # 0 is always the entry (bottom of the climb) and size_along-1 is
        # always the exit (top of the climb, where the hole below goes) --
        # not just "increasing world coordinate". _build_stair_mesh rotates
        # its local climb axis to point along (dx, dy) from the run's start
        # cell, so for the two rotations where dx/dy is negative, a naive
        # always-increasing mapping would put the stair's physical low end
        # at along_idx=size_along-1 instead of 0, stranding the hole at the
        # entrance while the stairs themselves climb away from it.
        forward = dx > 0 or dy > 0

        def world_xy(perp_idx, along_idx):
            a = along_idx if forward else (size_along - 1 - along_idx)
            if travel_along_x:
                return (x + a, y + perp_idx)
            return (x + perp_idx, y + a)

        stair_perp_idx = size_perp // 2
        walk_perp_idx = 0 if stair_perp_idx != 0 else size_perp - 1

        lower_id = len(self.rooms)
        for perp_idx in range(size_perp):
            for along_idx in range(size_along):
                wx, wy = world_xy(perp_idx, along_idx)
                self.grid[wx][wy][z] = TILE_FLOOR
                self.room_id[wx][wy][z] = lower_id
        lwx, lwy = world_xy(walk_perp_idx, 0)
        lower_room = {'x': x, 'y': y, 'z': z, 'w': fw, 'l': fl, 'cx': lwx, 'cy': lwy}
        self.rooms.append(lower_room)
        self._rooms_by_level.setdefault(z, []).append(lower_room)

        upper_id = len(self.rooms)
        for perp_idx in range(size_perp):
            for along_idx in range(size_along):
                wx, wy = world_xy(perp_idx, along_idx)
                self.grid[wx][wy][z + 1] = TILE_FLOOR
                self.room_id[wx][wy][z + 1] = upper_id
        uwx, uwy = world_xy(walk_perp_idx, size_along - 1)
        upper_room = {'x': x, 'y': y, 'z': z + 1, 'w': fw, 'l': fl, 'cx': uwx, 'cy': uwy}
        self.rooms.append(upper_room)
        self._rooms_by_level.setdefault(z + 1, []).append(upper_room)

        if bend and self._carve_bent_stair_path(x, y, fw, fl, rotation, bend, z):
            return lower_room, upper_room

        # Leave a 1-tile walkable buffer before the first step and after the
        # last one, so the stair itself never occupies the room's full
        # length. Without this, the physical stair mesh (which spans
        # exactly the tiles it's carved into) touches the room's boundary
        # wall directly at both ends -- the top step visibly clips through
        # the far wall, and a corridor arriving at the entry lands the
        # player straight onto the first step with no flat ground to land
        # on. Degrades to no buffer (old behavior) only when the room is
        # too short along the climb axis to spare the tiles (e.g. the
        # absolute-minimum 2x2 emergency fallback).
        entry_offset = 1 if size_along >= 3 else 0
        climb_len = size_along - 2 * entry_offset

        run_id = self._next_stair_run_id
        self._next_stair_run_id += 1
        for i in range(climb_len):
            wx, wy = world_xy(stair_perp_idx, entry_offset + i)
            self.grid[wx][wy][z] = TILE_STAIR
            self.rotations[wx][wy][z] = rotation
            self.room_id[wx][wy][z] = -1
            self.stair_run_id[wx][wy][z] = run_id

        hole_along = entry_offset + climb_len - 1
        hole_b = stair_perp_idx + 1 if stair_perp_idx + 1 < size_perp else stair_perp_idx - 1
        for perp_idx in {stair_perp_idx, hole_b} & set(range(size_perp)):
            wx, wy = world_xy(perp_idx, hole_along)
            self.floor_openings.add((wx, wy, z + 1))

        return lower_room, upper_room

    def _carve_bent_stair_path(self, x, y, fw, fl, rotation, turn, z):
        """Carves a bent stairwell's climb -- two straight segments joined
        by one flat landing tile -- INSIDE the already-fully-floored fw x
        fl rectangle _carve_stair_room just reserved, rather than needing
        any non-rectangular room reservation of its own. Every tile outside
        the two climb segments and the landing is already ordinary walkable
        floor from that same reservation, so no separate walkway logic is
        needed here either -- exactly the same principle a straight run's
        own "the other lanes are already floor" already relies on.

        turn is the second segment's direction change relative to the
        first, in degrees: 90 (turns left), -90 (turns right), or 180
        (reverses -- offset sideways into a second parallel lane, since
        reversing straight back from the landing would walk directly
        through the first segment's own already-carved tiles; see
        BENT_STAIR_LANE_OFFSET).

        Every touched cell is bounds-checked against the reserved
        rectangle before anything is carved -- if the bent path would step
        outside it (a real possibility for a modestly-sized footprint,
        especially a 180-degree turn's offset second lane), this carves
        NOTHING and returns False, so the caller falls back to an ordinary
        straight run instead. All-or-nothing by design: a half-carved bent
        path would leave a real gap in what's supposed to be a continuous
        climb.

        The landing's own world-Z sits proportionally between this level's
        floor and the next, matching how far along the TOTAL climb (both
        segments combined) the first segment alone covers -- baked directly
        into cell_z_offset, the same mechanism WFC_Level_Solver.
        _apply_continuous_elevation already uses for elevated rooms, so
        Walls/Doors pick up the landing's correct height with no changes of
        their own. Safe to write here (rather than only from that pass):
        stairwell rooms are appended to self.rooms AFTER
        _apply_continuous_elevation's own snapshot of eligible room
        indices, so that pass never touches or overwrites this."""
        dx1, dy1 = DIRECTION_FOR_ROTATION.get(rotation, (0, 1))
        px, py = -dy1, dx1  # 90 degrees CCW from segment 1's own direction

        if turn == 180:
            dx2, dy2 = -dx1, -dy1
            shift_x, shift_y = px * BENT_STAIR_LANE_OFFSET, py * BENT_STAIR_LANE_OFFSET
        elif turn == 90:
            dx2, dy2 = px, py
            shift_x, shift_y = 0, 0
        else:  # -90
            dx2, dy2 = -px, -py
            shift_x, shift_y = 0, 0

        travel_along_x = dx1 != 0
        size_perp, size_along = (fl, fw) if travel_along_x else (fw, fl)
        forward = dx1 > 0 or dy1 > 0
        stair_perp_idx = size_perp // 2

        def world_xy(perp_idx, along_idx):
            a = along_idx if forward else (size_along - 1 - along_idx)
            if travel_along_x:
                return (x + a, y + perp_idx)
            return (x + perp_idx, y + a)

        entry_offset = 1 if size_along >= 3 else 0
        usable = size_along - 2 * entry_offset
        if usable < 3:
            return False  # not enough room along the climb axis for 2 segments + a landing
        climb1_len = usable // 2
        climb2_len = usable - climb1_len - 1  # usable minus climb1 minus the landing tile itself
        if climb1_len < 1 or climb2_len < 1:
            return False

        start_x, start_y = world_xy(stair_perp_idx, entry_offset)
        seg1_cells = [(start_x + dx1 * i, start_y + dy1 * i) for i in range(climb1_len)]
        landing_cell = (start_x + dx1 * climb1_len, start_y + dy1 * climb1_len)
        if turn == 180:
            seg2_start = (landing_cell[0] + shift_x, landing_cell[1] + shift_y)
        else:
            seg2_start = (landing_cell[0] + dx2, landing_cell[1] + dy2)
        seg2_cells = [(seg2_start[0] + dx2 * i, seg2_start[1] + dy2 * i) for i in range(climb2_len)]

        all_cells = seg1_cells + [landing_cell] + seg2_cells
        if not all(x <= cx < x + fw and y <= cy < y + fl for cx, cy in all_cells):
            return False  # bent path steps outside the reserved rectangle

        # Segment 1 is centered on its own perpendicular axis by
        # construction (stair_perp_idx = size_perp // 2), so it always has
        # a walkway tile free on both sides within the rectangle -- the
        # same guarantee a straight run gets for free. Segment 2's
        # perpendicular axis is the ORIGINAL along-axis, and its position
        # on that axis is just wherever the landing happened to land
        # (entry_offset + climb1_len), which has no such guarantee. If a
        # segment 2 tread ends up flush against the rectangle's own edge,
        # the wall built along that edge lands right on top of the tread
        # instead of past it. Bail out to a straight run instead of
        # carving a bent path that overlaps a wall.
        def _has_perp_buffer(cx, cy, ddx, ddy):
            pdx, pdy = -ddy, ddx
            return all(
                x <= cx + s * pdx < x + fw and y <= cy + s * pdy < y + fl
                for s in (1, -1)
            )

        if not all(_has_perp_buffer(cx, cy, dx1, dy1) for cx, cy in seg1_cells):
            return False
        if not all(_has_perp_buffer(cx, cy, dx2, dy2) for cx, cy in seg2_cells):
            return False

        rotation2 = STAIR_EXIT_ROTATION.get((dx2, dy2), rotation)
        run_id = self._next_stair_run_id
        self._next_stair_run_id += 1

        for cx, cy in seg1_cells:
            self.grid[cx][cy][z] = TILE_STAIR
            self.rotations[cx][cy][z] = rotation
            self.room_id[cx][cy][z] = -1
            self.stair_run_id[cx][cy][z] = run_id
            self.stair_segment_index[cx][cy][z] = 0

        lx, ly = landing_cell
        self.room_id[lx][ly][z] = -1
        self.cell_z_offset[lx][ly][z] = self.level_height * climb1_len / (climb1_len + climb2_len)

        for cx, cy in seg2_cells:
            self.grid[cx][cy][z] = TILE_STAIR
            self.rotations[cx][cy][z] = rotation2
            self.room_id[cx][cy][z] = -1
            self.stair_run_id[cx][cy][z] = run_id
            self.stair_segment_index[cx][cy][z] = 1

        # Ceiling opening spans segment 2's own final tile (directly above
        # the last actual step -- without this the climb dead-ends into a
        # solid ceiling) PLUS one adjacent tile for a bit of width, same
        # "stair's own lane + one adjacent lane" shape _carve_stair_room's
        # straight-run hole placement already uses, just relative to
        # segment 2's own travel axis instead of the run's single shared
        # one.
        hole_x, hole_y = seg2_cells[-1]
        self.floor_openings.add((hole_x, hole_y, z + 1))
        hole_px, hole_py = -dy2, dx2
        for ox, oy in ((hole_x + hole_px, hole_y + hole_py), (hole_x - hole_px, hole_y - hole_py)):
            if x <= ox < x + fw and y <= oy < y + fl:
                self.floor_openings.add((ox, oy, z + 1))
                break

        return True

    def _stair_footprint_chain(self, z, center_x, center_y, prefer_bend_size=False):
        """Tries progressively smaller/more permissive stairwell footprints
        around (center_x, center_y) on level z, room-based or
        corridor-based depending on self.corridor_stairs. Returns whatever
        _find_stair_footprint returns: (x, y, fw, fl, rotation), or None
        if nothing fit anywhere.

        Corridor mode needs far fewer fallback tiers than room mode --
        CORRIDOR_STAIR_WIDTH plus margin=0 is already close to the
        cheapest possible placement (no buffered ring, no separate
        walkway), so there's little room left to relax further before
        the length itself has to shrink.

        prefer_bend_size (ignored for Corridor Stairs -- bending is never
        offered there, see _pick_stair_bend) searches for at least
        MIN_BENT_STAIR_ROOM_WIDTH/LENGTH on the FIRST tier instead of the
        plain self.stair_room_width/length, when the caller already knows
        this stairwell is about to attempt a bend -- a bend carved into
        the ordinary (often smaller) default footprint would almost
        always fail its own bounds check and silently fall back to
        straight, which works but wastes the caller's RNG roll finding
        that out. The later fallback tiers still shrink to the ordinary
        MIN_STAIR_ROOM_WIDTH/LENGTH sizes if nothing bigger fits anywhere
        -- at that point a bend genuinely can't be spared, and
        _carve_bent_stair_path's own bounds check falls back to straight
        exactly as it would from any other footprint that turned out too
        small, not a special case here."""
        if self.corridor_stairs:
            return (
                self._find_stair_footprint(
                    z, CORRIDOR_STAIR_WIDTH, self.stair_room_length,
                    center_x=center_x, center_y=center_y, corridor_mode=True,
                ) or self._find_stair_footprint(
                    z, CORRIDOR_STAIR_WIDTH, FALLBACK_STAIR_ROOM_LENGTH,
                    center_x=center_x, center_y=center_y, corridor_mode=True,
                )
            )
        first_width = self.stair_room_width
        first_length = self.stair_room_length
        if prefer_bend_size:
            first_width = max(first_width, MIN_BENT_STAIR_ROOM_WIDTH)
            first_length = max(first_length, MIN_BENT_STAIR_ROOM_LENGTH)
        return (
            self._find_stair_footprint(
                z, first_width, first_length,
                center_x=center_x, center_y=center_y,
            ) or self._find_stair_footprint(
                z, MIN_STAIR_ROOM_WIDTH, MIN_STAIR_ROOM_LENGTH,
                center_x=center_x, center_y=center_y,
            ) or self._find_stair_footprint(
                z, MIN_STAIR_ROOM_WIDTH, FALLBACK_STAIR_ROOM_LENGTH,
                center_x=center_x, center_y=center_y,
            ) or self._find_stair_footprint(
                # Last try before giving up on this connection entirely:
                # same minimal footprint (still gives the stair its own
                # internal buffer via _carve_stair_room's entry_offset),
                # but margin=0 lets the stairwell room sit flush against
                # a neighbor instead of needing a full empty ring around
                # it. In dense layouts that empty ring is often what's
                # actually unavailable -- allowing a shared wall here
                # avoids falling all the way to the bufferless
                # single-tile emergency stair in _ensure_connectivity,
                # which is what visibly clips into/opens straight at a
                # wall.
                z, MIN_STAIR_ROOM_WIDTH, FALLBACK_STAIR_ROOM_LENGTH,
                center_x=center_x, center_y=center_y, margin=0,
            )
        )

    def _connect_room_to_point(self, from_x, from_y, to_x, to_y, z):
        """Corridor-connects (from_x, from_y) to (to_x, to_y) at level z --
        a straight L-shaped corridor for every room_shape except Cave,
        where a target-biased tunnel walk (see _carve_cave_tunnel) keeps
        the organic look instead of cutting one dead-straight line across
        open cave air. A stairwell's footprint search routinely lands far
        from the chamber it's meant to serve on a Cave floor -- chambers
        are densely surrounded by their own tunnels, leaving little open
        space nearby, so the search has to range much further out to find
        any at all -- so this needs exactly the same treatment
        _carve_cave_floors already gives the exit corner. The walk is only
        biased, not guaranteed to land exactly on the target, so a short
        straight bridge closes whatever's left; it's a no-op whenever the
        walk actually arrived."""
        if self.room_shape == 'CAVE':
            wx, wy = self._carve_cave_tunnel(from_x, from_y, z, target=(to_x, to_y))
            if (wx, wy) != (to_x, to_y):
                self._carve_corridor(wx, wy, to_x, to_y, z)
        else:
            self._carve_corridor(from_x, from_y, to_x, to_y, z)

    def _pick_stair_bend(self):
        """Rolls whether the NEXT stairwell placed should bend, and if so,
        by how much -- see stair_bend_chance's own __init__ comment. Never
        offered for Corridor Stairs (self.corridor_stairs) -- a 1-wide
        footprint has no room for a second lane or a landing, so
        _carve_bent_stair_path's own bounds check would just reject it
        anyway; skipped here instead so a Corridor Stairs level doesn't
        waste an RNG roll on something guaranteed to fall back to
        straight every time."""
        if self.corridor_stairs or random.random() >= self.stair_bend_chance:
            return None
        if self.stair_bend_style == 'L':
            return random.choice((90, -90))
        if self.stair_bend_style == 'U':
            return 180
        return random.choice((90, -90, 180))

    def _connect_levels_with_stairs(self):
        # Cap how many rooms per level actually get their own stair down --
        # one per room floods a big map with stairs; the level's own corridor
        # network (already fully connected via MST) means every room stays
        # reachable through however few stairs actually get placed.
        for z in range(self.h - 1):
            # Snapshot before the loop: _carve_stair_room appends new
            # stairwell rooms to these same level buckets as it runs, and
            # those shouldn't feed back in as more stairs to connect this
            # pass.
            lower_rooms = list(self._rooms_by_level.get(z, []))
            upper_rooms = list(self._rooms_by_level.get(z + 1, []))
            if not lower_rooms or not upper_rooms:
                continue

            if len(upper_rooms) > self.stairs_per_level:
                chosen_rooms = random.sample(upper_rooms, self.stairs_per_level)
            else:
                chosen_rooms = upper_rooms

            for upper in chosen_rooms:
                lower = min(lower_rooms, key=lambda lo: self._manhattan(lo, upper))

                # Decided BEFORE the footprint search, not after, so a
                # stairwell that's about to attempt a bend can search for
                # a large-enough footprint in the first place -- see
                # _stair_footprint_chain's own prefer_bend_size comment.
                bend = self._pick_stair_bend()
                placement = self._stair_footprint_chain(
                    z, upper['cx'], upper['cy'], prefer_bend_size=bool(bend),
                )
                if placement is None:
                    continue  # no room anywhere for a stairwell -- skip this connection

                x, y, fw, fl, rotation = placement
                lower_room, upper_room = self._carve_stair_room(x, y, fw, fl, rotation, z, bend=bend)
                self._connect_room_to_point(lower['cx'], lower['cy'], lower_room['cx'], lower_room['cy'], z)
                self._connect_room_to_point(upper['cx'], upper['cy'], upper_room['cx'], upper_room['cy'], z + 1)

    def _wire_entrance_and_exit(self):
        sx, sy, sz = self.start
        ex, ey, ez = self.end

        # Stamp as Floor for now (Entrance/Exit IDs are applied at the very
        # end of solve()) so wall propagation and BFS treat them as ordinary
        # walkable cells while corridors get carved into them.
        if self.grid[sx][sy][sz] == TILE_AIR:
            self.grid[sx][sy][sz] = TILE_FLOOR
        if self.grid[ex][ey][ez] == TILE_AIR:
            self.grid[ex][ey][ez] = TILE_FLOOR

        start_rooms = self._rooms_by_level.get(sz, [])
        end_rooms = self._rooms_by_level.get(ez, [])

        if start_rooms:
            nearest = min(start_rooms, key=lambda r: abs(r['cx'] - sx) + abs(r['cy'] - sy))
            self._carve_corridor(sx, sy, nearest['cx'], nearest['cy'], sz)
        if end_rooms:
            nearest = min(end_rooms, key=lambda r: abs(r['cx'] - ex) + abs(r['cy'] - ey))
            self._carve_corridor(ex, ey, nearest['cx'], nearest['cy'], ez)

    def _would_expose_stair_side(self, x, y, z):
        """True if turning (x, y, z) into Floor would open an unwalled side
        of an adjacent 1-wide (Corridor Stairs) run. Checks all 4
        neighbors; for any neighbor that's a TILE_STAIR cell, (x, y) is
        only safe if it's on that stair's TRAVEL axis (its front/back --
        exactly where a corridor is meant to attach). Any other neighbor
        of a stair cell is its PERPENDICULAR side, which a 1-wide corridor
        stair has no walkway or wall buffer for by design -- carving real
        floor there removes the wall that's supposed to enclose it,
        letting a player step onto the stairs from the side.

        Used by every corridor-carving path (_carve_corridor,
        _carve_cave_tunnel), not just Cave mode's own machinery: a plain
        RECT/ROUND floor using Corridor Stairs can hit this too, it's just
        far rarer there (corridors are sparse, so a stairwell's nearby
        empty space is unlikely to already border one) than on a Cave
        floor (chambers are densely surrounded by their own tunnels)."""
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if not self.in_bounds(nx, ny, z) or self.grid[nx][ny][z] != TILE_STAIR:
                continue
            tdx, tdy = DIRECTION_FOR_ROTATION.get(self.rotations[nx][ny][z], (0, 1))
            if (x, y) in ((nx + tdx, ny + tdy), (nx - tdx, ny - tdy)):
                continue  # travel-axis neighbor -- legitimate entry/exit
            return True
        return False

    def _carve_corridor(self, x0, y0, x1, y1, z):
        """L-shaped Manhattan corridor of Floor tiles at a fixed Z level.

        Deliberately does NOT apply _would_expose_stair_side here the way
        _carve_cave_tunnel does: this is a straight line with no alternate
        routing, used in places where connectivity must not be allowed to
        fail (bridging a gap to a just-placed stairwell, MST room
        corridors, _ensure_connectivity's repair pass) -- skipping one
        cell mid-path would leave a real hole in what's supposed to be an
        unbroken corridor, trading a rare cosmetic stair-side exposure for
        a guaranteed-worse disconnected floor. _carve_cave_tunnel's own
        guard (it can just try a different direction instead of skipping a
        step) already covers the large majority of this case -- see its
        docstring and _corridor_stair_fits for the placement-time half of
        the fix."""
        x, y = x0, y0
        step_x = 1 if x1 >= x0 else -1
        while x != x1:
            if self.in_bounds(x, y, z) and self.grid[x][y][z] == TILE_AIR:
                self.grid[x][y][z] = TILE_FLOOR
            x += step_x
        step_y = 1 if y1 >= y0 else -1
        while y != y1:
            if self.in_bounds(x, y, z) and self.grid[x][y][z] == TILE_AIR:
                self.grid[x][y][z] = TILE_FLOOR
            y += step_y

    # -- connectivity (BFS) + repair -------------------------------------------
    def _neighbors(self, cell):
        x, y, z = cell
        tid = self.grid[x][y][z]
        # Horizontal moves onto any walkable tile at the same level.
        for dx, dy in HORIZONTAL_NEIGHBORS:
            nx, ny = x + dx, y + dy
            if self.in_bounds(nx, ny, z) and self.grid[nx][ny][z] in WALKABLE:
                yield (nx, ny, z)
        # A stair's exit vector always goes straight up (adjacency constraint).
        if tid == TILE_STAIR and self.in_bounds(x, y, z + 1) and self.grid[x][y][z + 1] in WALKABLE:
            yield (x, y, z + 1)
        # Symmetric: standing on the floor tile a stair below feeds into.
        if self.in_bounds(x, y, z - 1) and self.grid[x][y][z - 1] == TILE_STAIR:
            yield (x, y, z - 1)

    def _bfs_reachable(self, start, goal):
        if self.grid[start[0]][start[1]][start[2]] not in WALKABLE:
            return False
        visited = {start}
        queue = deque([start])
        while queue:
            cell = queue.popleft()
            if cell == goal:
                return True
            for nxt in self._neighbors(cell):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)
        return False

    def _ensure_connectivity(self):
        if self._bfs_reachable(self.start, self.end):
            return

        # Repair pass: climb one Z level at a time from the entrance,
        # placing a stairwell as close as possible to wherever we actually
        # are, until we reach the exit's Z, then corridor straight into the
        # exit. Each iteration's search is centered on the CURRENT (x, y) --
        # not the exit's fixed corner -- otherwise every level's repair
        # stair converges on the exact same (x, y) column and each new
        # single-tile fallback overwrites the previous one's landing floor,
        # stacking unrelated stairs on top of each other with no landing
        # between them.
        x, y, z = self.start
        ex, ey, ez = self.end

        while z != ez:
            next_z = z + 1  # start.z is always 0 and end.z is always h-1, so z only climbs

            placement = self._stair_footprint_chain(z, x, y)
            if placement is not None:
                px, py, fw, fl, rotation = placement
                lower_room, upper_room = self._carve_stair_room(px, py, fw, fl, rotation, z)
                self._carve_corridor(x, y, lower_room['cx'], lower_room['cy'], z)
                x, y = upper_room['cx'], upper_room['cy']
            else:
                # Absolute last resort: a single steep tile with no
                # enclosing room, guaranteeing a path exists even if there's
                # truly no free space anywhere for a proper stairwell.
                #
                # Placed at the nearest genuinely EMPTY (TILE_AIR) cell,
                # never on (x, y) itself or a cell that already belongs to
                # some other room/corridor if avoidable. Checking only the
                # 4 immediate neighbors wasn't enough: whenever ALL of them
                # already belonged to an existing room (a very plausible
                # coincidence near a busy map corner), it fell through to
                # overwriting (x, y) or a neighbor that was already claimed
                # floor -- hijacking a tile out of an unrelated room with no
                # buffer around it, the exact wall-clipping symptom this was
                # meant to avoid. A growing ring search finds real empty
                # space much more often; only if the entire level truly has
                # no Air cell left does it fall back to (x, y).
                tx, ty = x, y
                found = False
                for radius in range(1, max(self.w, self.l) + 1):
                    ring = [
                        (x + ox, y + oy)
                        for ox in range(-radius, radius + 1)
                        for oy in range(-radius, radius + 1)
                        if max(abs(ox), abs(oy)) == radius
                    ]
                    random.shuffle(ring)
                    for nx, ny in ring:
                        if self.in_bounds(nx, ny, z) and self.grid[nx][ny][z] == TILE_AIR:
                            tx, ty = nx, ny
                            found = True
                            break
                    if found:
                        break
                if (tx, ty) != (x, y):
                    self._carve_corridor(x, y, tx, ty, z)

                # Orient the mesh to face back toward wherever it's actually
                # walked in from -- found by checking (tx, ty)'s own
                # cardinal neighbors post-corridor, NOT the raw (tx - x,
                # ty - y) placement delta. That delta can be diagonal (the
                # ring search above scans 8-connected rings, and a diagonal
                # jump isn't one of the 4 keys in STAIR_EXIT_ROTATION), and
                # even when x/y are orthogonal, _carve_corridor's own
                # L-shaped path can approach from a different side than the
                # straight-line delta implies. A fixed rotation regardless
                # of the real approach side is what made most of these
                # stairs visually unreachable (the ramp facing away from
                # its only connected neighbor).
                fallback_rotation = 0.0
                for ndx, ndy in HORIZONTAL_NEIGHBORS:
                    nnx, nny = tx + ndx, ty + ndy
                    if self.in_bounds(nnx, nny, z) and self.grid[nnx][nny][z] in WALKABLE:
                        fallback_rotation = STAIR_EXIT_ROTATION.get((-ndx, -ndy), 0.0)
                        break

                if self.grid[tx][ty][next_z] == TILE_AIR:
                    self.grid[tx][ty][next_z] = TILE_FLOOR
                self.grid[tx][ty][z] = TILE_STAIR
                self.rotations[tx][ty][z] = fallback_rotation
                self.stair_run_id[tx][ty][z] = self._next_stair_run_id
                self._next_stair_run_id += 1
                self.floor_openings.add((tx, ty, next_z))
                x, y = tx, ty

            z = next_z

        self._carve_corridor(x, y, ex, ey, z)

    # -- continuous room elevation (see DEVELOPMENT.md) -------------------------
    def _apply_continuous_elevation(self):
        """Middle-ground version of "true continuous room elevation": the
        grid, BFS connectivity, room-fit/carve and stairs are all already
        finished by the time this runs -- this only decides, per eligible
        room, a world-Z offset to render its floor at, and fills in
        self.cell_z_offset for that room's footprint plus EVERY doorway's
        corridor run leading to it, so the slope actually interpolates down
        to flat ground at each one instead of leaving a cliff.

        A room with N doorways needs all N ramped -- any doorway left flat
        would meet the room's raised/lowered floor as a cliff right there.
        So a room only gets elevated if EVERY one of its doorways can grow
        a usable ramp (see _room_elevation_paths); if even one can't, the
        whole room stays flat rather than partially ramping it.

        Only self.rooms[:self._scattered_room_count] are eligible --
        stairwell rooms (appended later, always at higher indices) keep
        their flat floor, since their geometry (floor_openings, the stair
        mesh itself) assumes it."""
        if self.elevation_chance <= 0.0 or self.elevation_range <= 0.0:
            return

        max_slope = math.radians(self.max_ramp_slope_deg)
        claimed = set()  # cells already spent on some room's ramp

        for room_index in range(self._scattered_room_count):
            if random.random() > self.elevation_chance:
                continue

            room = self.rooms[room_index]
            z = room['z']
            footprint = [
                (xi, yi)
                for xi in range(room['x'], room['x'] + room['w'])
                for yi in range(room['y'], room['y'] + room['l'])
                if self.room_id[xi][yi][z] == room_index
            ]
            footprint_set = set(footprint)
            if not footprint or footprint_set & claimed:
                continue

            paths = self._room_elevation_paths(room_index, z, footprint_set, claimed)
            if paths is None:
                continue  # at least one doorway has no usable ramp -- stay flat

            # One offset for the whole room, so every one of its ramps has
            # to individually satisfy the slope constraint -- the shortest
            # (steepest-constrained) doorway run caps what the room can use.
            max_offset = min(
                (len(path) - 1) * self.tile_size * math.tan(max_slope)
                for path in paths
            )
            if max_offset <= 0.0:
                continue

            raw_offset = random.uniform(-self.elevation_range, self.elevation_range)
            offset = max(-max_offset, min(max_offset, raw_offset))
            if offset == 0.0:
                continue

            for xi, yi in footprint:
                self.cell_z_offset[xi][yi][z] = offset
            for path in paths:
                usable_span = len(path) - 1
                for i, (px, py) in enumerate(path):
                    t = i / usable_span
                    self.cell_z_offset[px][py][z] = offset * (1.0 - t)

            claimed.update(footprint_set)
            for path in paths:
                claimed.update(path)

    def _room_elevation_paths(self, room_index, z, footprint_set, claimed):
        """Finds one ramp-corridor path per doorway of the given room's
        footprint, or None if any doorway can't grow a usable one (in which
        case the caller must leave the whole room flat -- see
        _apply_continuous_elevation).

        A "doorway" is one connected cluster of boundary cells (a wide
        corridor mouth is one doorway, not several) -- this matches how
        _build_door_mesh's own merge pass would read the same boundary as
        a single frame, not because this pass renders doors, but because
        treating each boundary cell as its own independent doorway would
        spawn redundant near-parallel ramps for what is really one
        entrance.

        Each path is grown the same conservative way V1 grows its single
        path: walk outward along single-file, room_id == -1 corridor
        cells, stopping at a dead end, a branch, or a cell that is itself
        a doorway into some OTHER room (which would otherwise meet this
        room's sloped floor as an unramped cliff). Cells already spent by
        an EARLIER doorway of this same room (tracked in `reserved`, kept
        separate from the caller's `claimed` until every doorway succeeds)
        or by any other room's ramp are never reused -- a path that runs
        into one simply ends there, same as hitting a dead end."""
        # TILE_FLOOR only (not just WALKABLE) -- a doorway that opens
        # straight onto a stair tile (possible with Corridor Stairs, whose
        # climb cells carry room_id == -1 exactly like an ordinary
        # corridor cell) must never become a ramp's start: the stair mesh
        # is built with its own fixed, offset-ignorant geometry, so
        # treating one as sloped floor would desync it from the render.
        thresholds = set()
        for xi, yi in footprint_set:
            for dx, dy in HORIZONTAL_NEIGHBORS:
                nx, ny = xi + dx, yi + dy
                if (nx, ny) in footprint_set:
                    continue
                if self.in_bounds(nx, ny, z) and self.grid[nx][ny][z] == TILE_FLOOR:
                    thresholds.add((nx, ny))
        if not thresholds:
            return None  # no doorway opens onto plain floor -- e.g. straight into a stair tile

        # Cluster adjacent threshold cells into doorway groups (connected
        # components over cardinal adjacency), then pick one deterministic
        # representative start cell per doorway.
        remaining = set(thresholds)
        starts = []
        while remaining:
            seed = min(remaining)
            stack = [seed]
            group = set()
            while stack:
                cell = stack.pop()
                if cell in group:
                    continue
                group.add(cell)
                remaining.discard(cell)
                cx, cy = cell
                for dx, dy in HORIZONTAL_NEIGHBORS:
                    nb = (cx + dx, cy + dy)
                    if nb in remaining:
                        stack.append(nb)
            starts.append(min(group))

        reserved = set()  # cells this room's own earlier doorway paths already used

        def is_clean(cell, own_path_visited):
            """A ramp cell must not touch (even diagonally-adjacent via a
            cardinal step) any OTHER room, any stair tile (Corridor
            Stairs' climb cells carry room_id == -1 too, but their mesh is
            built with fixed, offset-ignorant geometry -- meeting one
            head-on would desync it from a sloped floor beside it), or any
            cell already spent by ANY ramp -- this room's own earlier
            doorway included -- since two independently-interpolated ramps
            can pass a legal slope each on its own and still clash where
            they run side by side without ever sharing a cell.
            own_path_visited exempts the CURRENT path's own prior cells,
            which are of course adjacent to whatever comes next in that
            same, single interpolation."""
            cx, cy = cell
            for dx, dy in HORIZONTAL_NEIGHBORS:
                ax, ay = cx + dx, cy + dy
                if (ax, ay) in footprint_set or (ax, ay) in own_path_visited:
                    continue
                if not self.in_bounds(ax, ay, z):
                    continue
                neighbor_tile = self.grid[ax][ay][z]
                if neighbor_tile == TILE_STAIR:
                    return False
                if neighbor_tile not in WALKABLE:
                    continue
                if self.room_id[ax][ay][z] not in (-1, room_index):
                    return False
                if (ax, ay) in claimed or (ax, ay) in reserved:
                    return False
            return True

        paths = []
        for start in starts:
            if start in claimed or start in reserved or not is_clean(start, {start}):
                return None
            path = [start]
            visited = {start}
            current = start
            while True:
                candidates = [
                    (nx, ny)
                    for dx, dy in HORIZONTAL_NEIGHBORS
                    for nx, ny in [(current[0] + dx, current[1] + dy)]
                    if (nx, ny) not in visited
                    and (nx, ny) not in footprint_set
                    and (nx, ny) not in claimed
                    and (nx, ny) not in reserved
                    and self.in_bounds(nx, ny, z)
                    and self.room_id[nx][ny][z] == -1
                    and self.grid[nx][ny][z] == TILE_FLOOR
                    and is_clean((nx, ny), visited | {(nx, ny)})
                ]
                if len(candidates) != 1:
                    break
                current = candidates[0]
                visited.add(current)
                path.append(current)

            if len(path) < 2:
                return None  # this doorway has no usable run -- bail for the whole room
            paths.append(path)
            reserved.update(path)

        return paths


# ==============================================================================
# 2. AUTOMATIC GEOMETRY NODES GENERATOR
# ==============================================================================
# Design notes:
#   - Tile selection is built as a chain of Compare(==) -> Switch nodes rather
#     than a single Index Switch. Index Switch's Python item-collection API has
#     changed across Blender versions; a Compare/Switch chain uses socket names
#     that have been stable since GN's introduction, which matters more for a
#     "production-ready" addon than saving four nodes.
#   - "Isometric Mode", "Color Rooms/Corridors", "Floor Thickness" and "Merge
#     Distance" are all exposed as inputs *on the node group itself* (not
#     baked in at generation time), so users can tweak them live on the
#     modifier without regenerating the level.
#   - Rooms vs. corridors are told apart with real MATERIAL SLOTS driven by
#     Set Material Index, not a color-attribute multiply -- an earlier
#     approach relied on a point-domain attribute surviving Instance On
#     Points -> Realize Instances -> a shader Attribute node, which turned
#     out fragile (and invisible in Solid viewport shading regardless, since
#     Solid shading's default "Material" color mode reads each material's
#     flat Viewport Display color, not its node tree). Material slots read
#     correctly under both Solid and rendered shading.
def create_geometry_nodes_modifier(
    obj, iso_mode_default, materials,
    tile_size=4.0, level_height=4.0, color_rooms_default=False, floor_thickness_default=0.0,
    add_ceiling_default=False, ceiling_thickness_default=0.1,
    floor_level_count=1, entrance_material_index=None, exit_material_index=None,
):
    """materials[0 : floor_level_count] are corridor/structure slots, one
    per floor-level ramp position (and for rooms when the Color
    Rooms/Corridors toggle is off) -- floor_level_count=1 reproduces the
    original single-shared-corridor-slot behavior exactly, since a cell's
    level index MOD 1 is always 0. materials[floor_level_count:] are room
    slots -- either a single shared "room" tint, or one material per room
    for a distinct color per room; either way the GN graph clamps a room's
    computed index to the last available slot, so any length >= 1 works.
    entrance_material_index/exit_material_index, if given, override every
    other rule for entrance/exit cells -- those two markers should always
    read as themselves regardless of level or room."""
    for mod in list(obj.modifiers):
        if mod.type == 'NODES' and mod.name == "GN_Game_Renderer":
            old_group = mod.node_group
            obj.modifiers.remove(mod)
            if old_group is not None and old_group.users == 0:
                bpy.data.node_groups.remove(old_group)

    mod = obj.modifiers.new(name="GN_Game_Renderer", type='NODES')

    # modifiers.new() does NOT auto-create a node group when called from
    # Python (only the UI's "New" button does, via its own operator) -- build
    # one explicitly and give it the Geometry in/out sockets every GN modifier
    # needs.
    #
    # Deliberately NOT assigning `mod.node_group = node_group` yet: doing so
    # before every interface socket (and its default_value) exists syncs the
    # modifier's own per-input storage to each socket type's built-in zero
    # value (False / 0.0) at assignment time -- a LATER `.default_value`
    # write on the interface only updates the node group's own stored
    # default (relevant for a future/different modifier instance), it does
    # NOT retroactively re-sync THIS already-linked modifier's stored
    # override. Concretely: Color Rooms/Corridors defaults to True in the
    # UI, but every freshly-generated level silently rendered with it OFF
    # regardless, because the modifier's own Socket_3 override got stuck at
    # Blender's built-in False the moment it was created -- confirmed by
    # reading `mod.properties.inputs.Socket_3.value` directly (False) even
    # though `node_group.interface.items_tree` showed the intended True.
    # Assigning `mod.node_group` only once every socket exists with its real
    # default already set sidesteps the whole class of bug, for every
    # current and future GN input, not just this one.
    node_group = bpy.data.node_groups.new(name="GN_Game_Renderer_Tree", type='GeometryNodeTree')
    node_group.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    node_group.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

    obj.data.materials.clear()
    for m in materials:
        obj.data.materials.append(m)
    max_material_index = max(len(materials) - 1, 0)

    iso_socket = node_group.interface.new_socket(
        name="Isometric Mode", in_out='INPUT', socket_type='NodeSocketBool'
    )
    iso_socket.default_value = iso_mode_default

    color_rooms_socket = node_group.interface.new_socket(
        name="Color Rooms/Corridors", in_out='INPUT', socket_type='NodeSocketBool'
    )
    color_rooms_socket.default_value = color_rooms_default

    floor_thickness_socket = node_group.interface.new_socket(
        name="Floor Thickness", in_out='INPUT', socket_type='NodeSocketFloat'
    )
    floor_thickness_socket.default_value = floor_thickness_default
    _set_prop(floor_thickness_socket, 'min_value', 0.0)
    _set_prop(floor_thickness_socket, 'max_value', 0.5)

    # A zero-thickness floor cube degenerates into two coincident faces
    # (its top and bottom collapse onto the same plane) -- Merge Distance
    # welds those, and also welds ordinary seams between adjacent tiles.
    # 0.001m is tight enough for the exactly-coincident zero-thickness case;
    # 0.01m has slack for normal floating-point tile-boundary gaps.
    merge_distance_default = 0.009 if floor_thickness_default <= 0.0 else 0.01
    merge_distance_socket = node_group.interface.new_socket(
        name="Merge Distance", in_out='INPUT', socket_type='NodeSocketFloat'
    )
    merge_distance_socket.default_value = merge_distance_default
    _set_prop(merge_distance_socket, 'min_value', 0.0)
    _set_prop(merge_distance_socket, 'max_value', 0.1)

    # Ceiling: same cube-instanced-per-point idea as the floor, flipped to
    # sit at the TOP of this point's level band instead of the bottom --
    # see step 3b below. Off by default (Add Ceiling = False), since the
    # open-top "dollhouse" view is what every level generated before this
    # existed looked like; Isometric Mode's existing top-slice cull (step
    # 5) already strips anything in this band, so turning Isometric Mode
    # on hides the ceiling automatically with no extra wiring needed.
    add_ceiling_socket = node_group.interface.new_socket(
        name="Add Ceiling", in_out='INPUT', socket_type='NodeSocketBool'
    )
    add_ceiling_socket.default_value = add_ceiling_default

    ceiling_thickness_socket = node_group.interface.new_socket(
        name="Ceiling Thickness", in_out='INPUT', socket_type='NodeSocketFloat'
    )
    ceiling_thickness_socket.default_value = ceiling_thickness_default
    _set_prop(ceiling_thickness_socket, 'min_value', 0.0)
    _set_prop(ceiling_thickness_socket, 'max_value', 0.5)

    links = node_group.links
    nodes = node_group.nodes

    input_node = nodes.new(type="NodeGroupInput")
    input_node.location = (-800, 0)
    output_node = nodes.new(type="NodeGroupOutput")
    output_node.location = (1500, 0)

    # 1. Pull the Python-authored point attributes back into the graph.
    attr_id = nodes.new(type="GeometryNodeInputNamedAttribute")
    attr_id.data_type = 'INT'
    _set_input(attr_id, 'Name', "tile_id")
    attr_id.location = (-800, 300)

    attr_rot = nodes.new(type="GeometryNodeInputNamedAttribute")
    attr_rot.data_type = 'FLOAT'
    _set_input(attr_rot, 'Name', "tile_rotation")
    attr_rot.location = (-800, 100)

    attr_opening = nodes.new(type="GeometryNodeInputNamedAttribute")
    attr_opening.data_type = 'BOOLEAN'
    _set_input(attr_opening, 'Name', "floor_opening")
    attr_opening.location = (-800, -60)

    not_opening = nodes.new(type="FunctionNodeBooleanMath")
    _set_prop(not_opening, 'operation', 'NOT')
    not_opening.location = (-620, -60)
    links.new(attr_opening.outputs['Attribute'], not_opening.inputs[0])

    # ceiling_opening (baked in Python as "does the point directly above
    # mine have floor_opening set") -- skipped the same way floor_opening
    # skips a floor cube, so a stairwell hole stays open from above too
    # instead of Add Ceiling silently sealing it shut.
    attr_ceiling_opening = nodes.new(type="GeometryNodeInputNamedAttribute")
    attr_ceiling_opening.data_type = 'BOOLEAN'
    _set_input(attr_ceiling_opening, 'Name', "ceiling_opening")
    attr_ceiling_opening.location = (-800, -140)

    not_ceiling_opening = nodes.new(type="FunctionNodeBooleanMath")
    _set_prop(not_ceiling_opening, 'operation', 'NOT')
    not_ceiling_opening.location = (-620, -140)
    links.new(attr_ceiling_opening.outputs['Attribute'], not_ceiling_opening.inputs[0])

    ceiling_select_and = nodes.new(type="FunctionNodeBooleanMath")
    _set_prop(ceiling_select_and, 'operation', 'AND')
    ceiling_select_and.location = (-440, -140)
    links.new(input_node.outputs['Add Ceiling'], ceiling_select_and.inputs[0])
    links.new(not_ceiling_opening.outputs['Boolean'], ceiling_select_and.inputs[1])

    # 2. Master Tile primitives, sized off the single tile_size parameter so
    #    the whole kit stays proportional at any scale. Pivots are offset so
    #    each primitive sits correctly on the point it is instanced onto.
    marker_size = tile_size * 0.25
    marker_height = level_height * 0.625

    # Floor is a cube whose Z size is the live "Floor Thickness" input --
    # clamped to never fall below ~3x the live Merge Distance (below), so
    # top and bottom can NEVER land within welding range of each other, no
    # matter how thin Floor Thickness or how generous Merge Distance is set.
    # An exact 0.0 (or anything close enough to 0 relative to Merge
    # Distance) used to make the cube's top and bottom faces fully
    # coincident -- Merge Distance then welds ALL their vertices together,
    # and Blender's own de-duplication of the resulting fully-overlapping
    # faces silently kept only ONE of the two (confirmed: consistently the
    # downward-facing one, never the upward one) instead of the intended
    # "still reads as flat, but correctly two-sided" result the comment
    # above used to promise. That produced a floor that renders fine with
    # backface culling off (Blender's default) but reads as completely
    # transparent from directly above with it on -- confirmed directly: at
    # Floor Thickness 0.0, ALL 684 floor faces in one stress-tested level
    # pointed -Z, none pointing +Z. The clamped thickness below is still
    # visually flat at any normal viewing distance (a few centimeters at
    # most, tile sizes are meters), but keeps both faces distinct through
    # the merge, so both survive with their correct, independent winding --
    # exactly like the already-verified nonzero-thickness case. The pivot
    # (below) is offset so the floor's TOP surface stays flush with the
    # point either way, matching where the wall/stair/marker primitives
    # start.
    min_floor_thickness_math = nodes.new(type="ShaderNodeMath")
    _set_prop(min_floor_thickness_math, 'operation', 'MULTIPLY')
    min_floor_thickness_math.location = (-860, 500)
    links.new(input_node.outputs['Merge Distance'], min_floor_thickness_math.inputs[0])
    min_floor_thickness_math.inputs[1].default_value = 3.0

    clamped_floor_thickness_math = nodes.new(type="ShaderNodeMath")
    _set_prop(clamped_floor_thickness_math, 'operation', 'MAXIMUM')
    clamped_floor_thickness_math.location = (-780, 500)
    links.new(input_node.outputs['Floor Thickness'], clamped_floor_thickness_math.inputs[0])
    links.new(min_floor_thickness_math.outputs['Value'], clamped_floor_thickness_math.inputs[1])

    floor_size_combine = nodes.new(type="ShaderNodeCombineXYZ")
    floor_size_combine.location = (-680, 560)
    _set_input(floor_size_combine, 'X', tile_size)
    _set_input(floor_size_combine, 'Y', tile_size)
    links.new(clamped_floor_thickness_math.outputs['Value'], floor_size_combine.inputs['Z'])

    cube_floor = nodes.new(type="GeometryNodeMeshCube")
    cube_floor.location = (-500, 560)
    links.new(floor_size_combine.outputs['Vector'], cube_floor.inputs['Size'])

    floor_drop_math = nodes.new(type="ShaderNodeMath")
    _set_prop(floor_drop_math, 'operation', 'MULTIPLY')
    floor_drop_math.location = (-680, 440)
    links.new(clamped_floor_thickness_math.outputs['Value'], floor_drop_math.inputs[0])
    floor_drop_math.inputs[1].default_value = -0.5

    floor_translate_combine = nodes.new(type="ShaderNodeCombineXYZ")
    floor_translate_combine.location = (-500, 440)
    links.new(floor_drop_math.outputs['Value'], floor_translate_combine.inputs['Z'])

    transform_floor = nodes.new(type="GeometryNodeTransform")
    transform_floor.location = (-260, 500)
    links.new(cube_floor.outputs['Mesh'], transform_floor.inputs['Geometry'])
    links.new(floor_translate_combine.outputs['Vector'], transform_floor.inputs['Translation'])

    # Ceiling mirrors the floor exactly, just flipped: sized off "Ceiling
    # Thickness" instead of "Floor Thickness" (same clamp-against-Merge-
    # Distance treatment as the floor above, for the identical reason -- a
    # truly coincident top/bottom pair gets welded together and Blender
    # keeps only one of the two resulting duplicate faces, so an exact 0.0
    # Ceiling Thickness would risk the same "half the ceiling faces wound
    # backwards" bug the floor had), and its pivot is offset so its BOTTOM
    # surface sits at local Z = level_height -- i.e. flush with the FLOOR
    # of the point directly above (one whole level_height up, matching the
    # "z mod level_height" frame Isometric Mode's cull step already uses),
    # so multi-story levels get a seamless ceiling/floor sandwich between
    # stories with no extra per-point math needed.
    min_ceiling_thickness_math = nodes.new(type="ShaderNodeMath")
    _set_prop(min_ceiling_thickness_math, 'operation', 'MULTIPLY')
    min_ceiling_thickness_math.location = (-860, 700)
    links.new(input_node.outputs['Merge Distance'], min_ceiling_thickness_math.inputs[0])
    min_ceiling_thickness_math.inputs[1].default_value = 3.0

    clamped_ceiling_thickness_math = nodes.new(type="ShaderNodeMath")
    _set_prop(clamped_ceiling_thickness_math, 'operation', 'MAXIMUM')
    clamped_ceiling_thickness_math.location = (-780, 700)
    links.new(input_node.outputs['Ceiling Thickness'], clamped_ceiling_thickness_math.inputs[0])
    links.new(min_ceiling_thickness_math.outputs['Value'], clamped_ceiling_thickness_math.inputs[1])

    ceiling_size_combine = nodes.new(type="ShaderNodeCombineXYZ")
    ceiling_size_combine.location = (-680, 700)
    _set_input(ceiling_size_combine, 'X', tile_size)
    _set_input(ceiling_size_combine, 'Y', tile_size)
    links.new(clamped_ceiling_thickness_math.outputs['Value'], ceiling_size_combine.inputs['Z'])

    cube_ceiling = nodes.new(type="GeometryNodeMeshCube")
    cube_ceiling.location = (-500, 700)
    links.new(ceiling_size_combine.outputs['Vector'], cube_ceiling.inputs['Size'])

    ceiling_half_math = nodes.new(type="ShaderNodeMath")
    _set_prop(ceiling_half_math, 'operation', 'MULTIPLY')
    ceiling_half_math.location = (-680, 640)
    links.new(clamped_ceiling_thickness_math.outputs['Value'], ceiling_half_math.inputs[0])
    ceiling_half_math.inputs[1].default_value = 0.5

    ceiling_lift_math = nodes.new(type="ShaderNodeMath")
    _set_prop(ceiling_lift_math, 'operation', 'SUBTRACT')
    ceiling_lift_math.location = (-560, 640)
    ceiling_lift_math.inputs[0].default_value = level_height
    links.new(ceiling_half_math.outputs['Value'], ceiling_lift_math.inputs[1])

    ceiling_translate_combine = nodes.new(type="ShaderNodeCombineXYZ")
    ceiling_translate_combine.location = (-500, 640)
    links.new(ceiling_lift_math.outputs['Value'], ceiling_translate_combine.inputs['Z'])

    transform_ceiling = nodes.new(type="GeometryNodeTransform")
    transform_ceiling.location = (-260, 640)
    links.new(cube_ceiling.outputs['Mesh'], transform_ceiling.inputs['Geometry'])
    links.new(ceiling_translate_combine.outputs['Vector'], transform_ceiling.inputs['Translation'])

    # Entrance/Exit get a distinct low beacon marker instead of reusing the
    # wall mesh, so playtesters can actually see them from a distance.
    cube_marker = nodes.new(type="GeometryNodeMeshCube")
    cube_marker.location = (-500, -40)
    _set_input(cube_marker, 'Size', (marker_size, marker_size, marker_height))
    transform_marker = nodes.new(type="GeometryNodeTransform")
    transform_marker.location = (-260, -40)
    _set_input(transform_marker, 'Translation', (0.0, 0.0, marker_height / 2.0))
    links.new(cube_marker.outputs['Mesh'], transform_marker.inputs['Geometry'])

    # 3. Tile-select chain: default to Floor, then override per tile_id.
    def compare_id(value):
        cmp_node = nodes.new(type="FunctionNodeCompare")
        cmp_node.data_type = 'INT'
        cmp_node.operation = 'EQUAL'
        cmp_node.location = (-40, -200 - 60 * value)
        links.new(attr_id.outputs['Attribute'], cmp_node.inputs['A'])
        _set_input(cmp_node, 'B', value)
        return cmp_node

    def switch_geo(condition_socket, false_geo, true_geo, y):
        sw = nodes.new(type="GeometryNodeSwitch")
        sw.input_type = 'GEOMETRY'
        sw.location = (160, y)
        links.new(condition_socket, sw.inputs[0])       # Switch
        links.new(false_geo, sw.inputs[1])              # False
        links.new(true_geo, sw.inputs[2])                # True
        return sw.outputs[0]

    result = transform_floor.outputs['Geometry']  # covers TILE_FLOOR
    entrance_cmp = compare_id(TILE_ENTRANCE)
    exit_cmp = compare_id(TILE_EXIT)
    result = switch_geo(entrance_cmp.outputs['Result'], result, transform_marker.outputs['Geometry'], 380)
    result = switch_geo(exit_cmp.outputs['Result'], result, transform_marker.outputs['Geometry'], 320)

    # 4. Instancing engine: one primitive per point, rotated about local Z.
    combine_rot = nodes.new(type="ShaderNodeCombineXYZ")
    combine_rot.location = (160, -400)
    links.new(attr_rot.outputs['Attribute'], combine_rot.inputs['Z'])

    instance_node = nodes.new(type="GeometryNodeInstanceOnPoints")
    instance_node.location = (420, 0)
    links.new(input_node.outputs['Geometry'], instance_node.inputs['Points'])
    links.new(not_opening.outputs['Boolean'], instance_node.inputs['Selection'])  # skip stairwell openings
    links.new(result, instance_node.inputs['Instance'])
    links.new(combine_rot.outputs['Vector'], instance_node.inputs['Rotation'])

    realize_node = nodes.new(type="GeometryNodeRealizeInstances")
    realize_node.location = (620, 0)
    links.new(instance_node.outputs['Instances'], realize_node.inputs['Geometry'])

    # Ceiling gets its own Instance on Points, straight off the ORIGINAL
    # point cloud (not the tile_id-selected `result` chain above, since
    # every point is eligible for a ceiling regardless of which floor/wall
    # primitive it also got) -- gated entirely by ceiling_select_and, so
    # when Add Ceiling is off no ceiling geometry is created at all.
    ceiling_instance_node = nodes.new(type="GeometryNodeInstanceOnPoints")
    ceiling_instance_node.location = (420, -560)
    links.new(input_node.outputs['Geometry'], ceiling_instance_node.inputs['Points'])
    links.new(ceiling_select_and.outputs['Boolean'], ceiling_instance_node.inputs['Selection'])
    links.new(transform_ceiling.outputs['Geometry'], ceiling_instance_node.inputs['Instance'])

    ceiling_realize_node = nodes.new(type="GeometryNodeRealizeInstances")
    ceiling_realize_node.location = (620, -560)
    links.new(ceiling_instance_node.outputs['Instances'], ceiling_realize_node.inputs['Geometry'])

    # Isometric Mode: strip the top slice of the CEILING (only) so a
    # top-down camera can see into the rooms below, on every story at once
    # (modulo against level height, not a single global Z threshold).
    # Deliberately scoped to ceiling alone, applied BEFORE the floor+
    # ceiling join below -- walls used to live in this same graph and get
    # culled here too (hence "top slice of every level's walls" in this
    # step's original design), but they were split out into their own
    # separately-baked object (_build_wall_mesh) at some point and this
    # cull was never re-scoped to match. Left applying to the WHOLE
    # post-join geometry, it also culled FLOOR -- invisible for an
    # ordinary flat floor tile sitting at the very bottom of its band, but
    # a room shifted down by continuous elevation (Elevation Chance/Split
    # Level Chance) can land close enough to a sub-level boundary that a
    # small negative offset wraps the modulo around to just under the TOP
    # of the previous band, landing inside the cull zone -- confirmed
    # directly: an elevated room's entire floor (all 30 of its points)
    # silently deleted this way, visible as both "missing floor tiles"
    # under an elevated area and a round room's floor disc reading as
    # floating on nothing once its own supporting blocky floor vanished
    # underneath it. Floor should never be culled anyway -- the whole
    # point of Isometric Mode is seeing INTO the room, not through the
    # thing you're trying to look at.
    ceiling_band = level_height * 0.95  # local Z within a level above which ceiling geometry is culled

    ceiling_pos_node = nodes.new(type="GeometryNodeInputPosition")
    ceiling_pos_node.location = (620, -700)
    ceiling_sep_xyz = nodes.new(type="ShaderNodeSeparateXYZ")
    ceiling_sep_xyz.location = (620, -780)
    links.new(ceiling_pos_node.outputs['Position'], ceiling_sep_xyz.inputs['Vector'])

    ceiling_mod_z = nodes.new(type="ShaderNodeMath")
    _set_prop(ceiling_mod_z, 'operation', 'MODULO')
    ceiling_mod_z.location = (620, -860)
    links.new(ceiling_sep_xyz.outputs['Z'], ceiling_mod_z.inputs[0])
    ceiling_mod_z.inputs[1].default_value = level_height

    ceiling_compare_band = nodes.new(type="FunctionNodeCompare")
    ceiling_compare_band.data_type = 'FLOAT'
    ceiling_compare_band.operation = 'GREATER_THAN'
    ceiling_compare_band.location = (780, -860)
    links.new(ceiling_mod_z.outputs['Value'], ceiling_compare_band.inputs['A'])
    _set_input(ceiling_compare_band, 'B', ceiling_band)

    ceiling_delete_geom = nodes.new(type="GeometryNodeDeleteGeometry")
    ceiling_delete_geom.location = (780, -700)
    _set_prop(ceiling_delete_geom, 'domain', 'FACE')
    _set_prop(ceiling_delete_geom, 'mode', 'ALL')
    links.new(ceiling_realize_node.outputs['Geometry'], ceiling_delete_geom.inputs['Geometry'])
    links.new(ceiling_compare_band.outputs['Result'], ceiling_delete_geom.inputs['Selection'])

    # Live toggle: pick full ceiling or the top-slice-culled variant --
    # floor+markers (realize_node, below) never pass through this switch
    # at all, so Isometric Mode can no longer touch floor geometry.
    iso_switch = nodes.new(type="GeometryNodeSwitch")
    iso_switch.input_type = 'GEOMETRY'
    iso_switch.location = (940, -560)
    links.new(input_node.outputs['Isometric Mode'], iso_switch.inputs[0])
    links.new(ceiling_realize_node.outputs['Geometry'], iso_switch.inputs[1])  # False -> untouched
    links.new(ceiling_delete_geom.outputs['Geometry'], iso_switch.inputs[2])   # True  -> culled

    join_geo = nodes.new(type="GeometryNodeJoinGeometry")
    join_geo.location = (1100, -280)
    links.new(realize_node.outputs['Geometry'], join_geo.inputs['Geometry'])
    links.new(iso_switch.outputs[0], join_geo.inputs['Geometry'])

    # Snapshot room_id/logical_floor/level_z to FACE domain BEFORE the merge
    # below welds boundary vertices together. These are still POINT-domain
    # here, one clean value per point broadcast uniformly across its own
    # cube instance's corners -- unambiguous, since merging hasn't happened
    # yet. Merge By Distance welds a shared corner between TWO DIFFERENT
    # tiles' cubes (e.g. a room and its neighboring corridor, or two
    # adjacent rooms) into ONE vertex, and for a non-blendable INT
    # attribute it keeps only one of the colliding source values -- reading
    # room_id/level_z per-vertex AFTER that point (as both the material
    # Color Rooms/Corridors switch below and Separate-by-Floor/Room's
    # Python-side per-face read do) can silently pick up a face's
    # NEIGHBOR's value instead of its own. Confirmed directly: 484/1402
    # faces (35%) in one stress-tested level had inconsistent room_id
    # across their own 4 corner vertices post-merge, e.g. one single quad
    # face reading [9, 6, 4, 9] -- three different rooms' worth of corner
    # data on what should be one room's own floor tile. Storing each
    # attribute as FACE domain here captures the correct value once, before
    # any welding can contaminate it; the SAME-named GeometryNodeInputNamed
    # Attribute reads further down the graph (and Python's
    # _read_polygon_values, which already prefers the FACE-domain branch
    # when present) automatically pick up this protected value instead --
    # no other code needed to change for either consumer.
    pre_merge_geo = join_geo.outputs['Geometry']
    for snapshot_name in ("room_id", "logical_floor", "level_z"):
        snapshot_reader = nodes.new(type="GeometryNodeInputNamedAttribute")
        snapshot_reader.data_type = 'INT'
        snapshot_reader.location = (700, -360 - 60 * ("room_id", "logical_floor", "level_z").index(snapshot_name))
        _set_input(snapshot_reader, 'Name', snapshot_name)
        snapshot_store = nodes.new(type="GeometryNodeStoreNamedAttribute")
        snapshot_store.domain = 'FACE'
        snapshot_store.data_type = 'INT'
        snapshot_store.location = (
            860, -360 - 60 * ("room_id", "logical_floor", "level_z").index(snapshot_name)
        )
        _set_input(snapshot_store, 'Name', snapshot_name)
        links.new(pre_merge_geo, snapshot_store.inputs['Geometry'])
        links.new(snapshot_reader.outputs['Attribute'], snapshot_store.inputs['Value'])
        pre_merge_geo = snapshot_store.outputs['Geometry']

    # A UV map so Solid Shading's "Texture" color mode (a separate, simpler
    # display path from "Material" that samples an image directly instead
    # of reading a material's Viewport Display Color -- and unlike EEVEE,
    # has no Generated-coordinates fallback, so it shows nothing useful
    # without one) can actually display these materials' Image Texture.
    # Every Simple Viewport Colors swatch (Room1-18/Floor1-8/Wall0/Stairs/
    # Doors/Entrance/Exit .png) is a single flat color across the whole
    # image, so the exact UV value carried by a face genuinely doesn't
    # matter for correctness -- any coordinate samples the same pixel --
    # a constant (0.5, 0.5) for every corner is enough, no per-tile
    # mapping needed.
    uv_store = nodes.new(type="GeometryNodeStoreNamedAttribute")
    uv_store.domain = 'CORNER'
    uv_store.data_type = 'FLOAT2'
    uv_store.location = (700, -540)
    _set_input(uv_store, 'Name', "UVMap")
    links.new(pre_merge_geo, uv_store.inputs['Geometry'])
    _set_input(uv_store, 'Value', (0.5, 0.5, 0.0))
    pre_merge_geo = uv_store.outputs['Geometry']

    # Weld coincident/near-coincident verts -- required to clean up the
    # zero-thickness floor case, and generally good hygiene for the seams
    # between adjacent tile primitives (now including the ceiling's own
    # zero-thickness case, and the ceiling/floor seam between stories).
    merge_node = nodes.new(type="GeometryNodeMergeByDistance")
    merge_node.location = (1040, 0)
    links.new(pre_merge_geo, merge_node.inputs['Geometry'])
    links.new(input_node.outputs['Merge Distance'], merge_node.inputs['Distance'])

    # 6. Material index, three layers of priority:
    #      base:     corridor/structure slot = this cell's level index MOD
    #                floor_level_count (read from the "level_z" point
    #                attribute exported in Python, not re-derived via GN
    #                math -- floor_level_count=1 makes this always slot 0,
    #                reproducing the original single-corridor-slot behavior
    #                exactly, since anything MOD 1 is 0).
    #      room:     overrides the base slot when this cell belongs to a
    #                room (room_id >= 0) AND the live Color Rooms/Corridors
    #                toggle is on -- same "room_id" attribute read as
    #                before, just offset by floor_level_count instead of a
    #                fixed +1 now that the base layer can be more than one
    #                slot wide.
    #      entrance/exit: overrides everything else when given -- these two
    #                markers should always read as themselves regardless of
    #                level or room, reusing the SAME tile_id comparisons
    #                already computed for geometry selection above.
    attr_level_z = nodes.new(type="GeometryNodeInputNamedAttribute")
    attr_level_z.data_type = 'INT'
    _set_input(attr_level_z, 'Name', "level_z")
    attr_level_z.location = (1460, -520)

    level_slot_mod = nodes.new(type="ShaderNodeMath")
    _set_prop(level_slot_mod, 'operation', 'MODULO')
    level_slot_mod.location = (1620, -520)
    links.new(attr_level_z.outputs['Attribute'], level_slot_mod.inputs[0])
    level_slot_mod.inputs[1].default_value = float(floor_level_count)

    attr_room_id = nodes.new(type="GeometryNodeInputNamedAttribute")
    attr_room_id.data_type = 'INT'
    _set_input(attr_room_id, 'Name', "room_id")
    attr_room_id.location = (1460, -260)

    is_room = nodes.new(type="FunctionNodeCompare")
    is_room.data_type = 'INT'
    is_room.operation = 'GREATER_EQUAL'
    is_room.location = (1620, -260)
    links.new(attr_room_id.outputs['Attribute'], is_room.inputs['A'])
    _set_input(is_room, 'B', 0)

    room_slot_add = nodes.new(type="ShaderNodeMath")
    _set_prop(room_slot_add, 'operation', 'ADD')
    room_slot_add.location = (1620, -400)
    links.new(attr_room_id.outputs['Attribute'], room_slot_add.inputs[0])
    room_slot_add.inputs[1].default_value = float(floor_level_count)

    room_slot_clamp = nodes.new(type="ShaderNodeMath")
    _set_prop(room_slot_clamp, 'operation', 'MINIMUM')
    room_slot_clamp.location = (1780, -400)
    links.new(room_slot_add.outputs['Value'], room_slot_clamp.inputs[0])
    room_slot_clamp.inputs[1].default_value = float(max_material_index)

    show_rooms_and = nodes.new(type="FunctionNodeBooleanMath")
    _set_prop(show_rooms_and, 'operation', 'AND')
    show_rooms_and.location = (1780, -260)
    links.new(input_node.outputs['Color Rooms/Corridors'], show_rooms_and.inputs[0])
    links.new(is_room.outputs['Result'], show_rooms_and.inputs[1])

    material_index_switch = nodes.new(type="GeometryNodeSwitch")
    material_index_switch.input_type = 'INT'
    material_index_switch.location = (1940, -260)
    links.new(show_rooms_and.outputs['Boolean'], material_index_switch.inputs[0])
    links.new(level_slot_mod.outputs['Value'], material_index_switch.inputs[1])  # False -> level/corridor slot
    links.new(room_slot_clamp.outputs['Value'], material_index_switch.inputs[2])  # True -> room slot

    final_index_socket = material_index_switch.outputs[0]
    next_x = 2100

    if entrance_material_index is not None:
        entrance_index_switch = nodes.new(type="GeometryNodeSwitch")
        entrance_index_switch.input_type = 'INT'
        entrance_index_switch.location = (next_x, -260)
        links.new(entrance_cmp.outputs['Result'], entrance_index_switch.inputs[0])
        links.new(final_index_socket, entrance_index_switch.inputs[1])
        entrance_index_switch.inputs[2].default_value = entrance_material_index
        final_index_socket = entrance_index_switch.outputs[0]
        next_x += 160

    if exit_material_index is not None:
        exit_index_switch = nodes.new(type="GeometryNodeSwitch")
        exit_index_switch.input_type = 'INT'
        exit_index_switch.location = (next_x, -260)
        links.new(exit_cmp.outputs['Result'], exit_index_switch.inputs[0])
        links.new(final_index_socket, exit_index_switch.inputs[1])
        exit_index_switch.inputs[2].default_value = exit_material_index
        final_index_socket = exit_index_switch.outputs[0]
        next_x += 160

    set_material_index = nodes.new(type="GeometryNodeSetMaterialIndex")
    set_material_index.location = (next_x, 0)
    links.new(merge_node.outputs['Geometry'], set_material_index.inputs['Geometry'])
    links.new(final_index_socket, set_material_index.inputs['Material Index'])

    links.new(set_material_index.outputs['Geometry'], output_node.inputs['Geometry'])

    # See the long comment above, by node_group's creation: only assign the
    # modifier's node_group once every interface socket's real default is
    # already in place, so the modifier's own per-input storage initializes
    # from the correct values instead of each socket type's built-in zero.
    mod.node_group = node_group
    return mod


# ==============================================================================
# 3. PROTOTYPE MATERIAL ENGINE (procedural, zero image textures)
# ==============================================================================
def _make_ao_readability_chain(node_tree, base_color_socket, x, y):
    """AO -> high-contrast ColorRamp -> multiply into base color. Darkens
    corners/deep edges so geometry stays readable from a top-down isometric
    camera where lighting cues alone are too subtle."""
    links = node_tree.links
    nodes = node_tree.nodes

    ao_node = nodes.new(type="ShaderNodeAmbientOcclusion")
    ao_node.location = (x, y)
    ao_node.samples = 8
    _set_input(ao_node, 'Distance', 0.5)

    ramp = nodes.new(type="ShaderNodeValToRGB")
    ramp.location = (x + 200, y)
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0.15, 0.15, 0.15, 1.0)  # crushed shadow
    ramp.color_ramp.elements[1].position = 0.6
    ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
    links.new(ao_node.outputs['AO'], ramp.inputs['Fac'])

    mix = nodes.new(type="ShaderNodeMixRGB")
    _set_prop(mix, 'blend_type', 'MULTIPLY')
    mix.inputs['Fac'].default_value = 1.0
    mix.location = (x + 420, y)
    links.new(base_color_socket, mix.inputs['Color1'])
    links.new(ramp.outputs['Color'], mix.inputs['Color2'])
    return mix.outputs['Color']


def _finish_material(node_tree, color_socket, roughness=0.7, tint=None, mat=None):
    """tint, if given, is a literal RGBA constant multiplied into the base
    color -- used to bake a distinct "room" variant of each style material.
    A literal constant (rather than a shader-side attribute read) means this
    works regardless of whether Blender's Instance On Points -> Realize
    Instances pipeline propagates a given point attribute through to the
    final mesh, which is what makes the room/corridor split reliable: which
    material slot a face uses is decided in the GN graph via Set Material
    Index, not by this shader trying to read per-face state itself.

    When both tint and mat are given, also sets mat.diffuse_color = tint --
    style materials otherwise never set it at all (their look comes purely
    from the node tree), which left them invisible to anything reading
    diffuse_color directly: Solid Shading's "Material" color mode, and the
    "viewport_color" Color Attribute palette (see _add_viewport_color_
    attribute) built from it for "Attribute" color mode."""
    links = node_tree.links
    nodes = node_tree.nodes

    if tint is not None:
        tint_mix = nodes.new(type="ShaderNodeMixRGB")
        _set_prop(tint_mix, 'blend_type', 'MULTIPLY')
        tint_mix.inputs['Fac'].default_value = 1.0
        tint_mix.location = (700, 0)
        links.new(color_socket, tint_mix.inputs['Color1'])
        tint_mix.inputs['Color2'].default_value = tint
        color_socket = tint_mix.outputs['Color']
        if mat is not None:
            mat.diffuse_color = tint

    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (900, 0)
    links.new(color_socket, bsdf.inputs['Base Color'])
    _set_input(bsdf, 'Roughness', roughness)

    out = nodes.new(type="ShaderNodeOutputMaterial")
    out.location = (1150, 0)
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])


def create_dungeon_material(tint=None):
    """Brick Texture + Voronoi-driven micro-cracks along tile edges, for
    first-person close-up read."""
    mat = bpy.data.materials.new(name="LA_Dungeon_Bricks")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    links, nodes = nt.links, nt.nodes

    coord = nodes.new(type="ShaderNodeTexCoord")
    coord.location = (-800, 0)

    brick = nodes.new(type="ShaderNodeTexBrick")
    brick.location = (-500, 100)
    _set_input(brick, 'Color1', (0.35, 0.22, 0.18, 1.0))
    _set_input(brick, 'Color2', (0.28, 0.17, 0.14, 1.0))
    _set_input(brick, 'Mortar', (0.05, 0.05, 0.05, 1.0))
    _set_input(brick, 'Scale', 2.0)
    _set_input(brick, 'Mortar Size', 0.02)
    links.new(coord.outputs['Object'], brick.inputs['Vector'])

    voronoi = nodes.new(type="ShaderNodeTexVoronoi")
    _set_prop(voronoi, 'feature', 'DISTANCE_TO_EDGE')
    voronoi.location = (-500, -150)
    _set_input(voronoi, 'Scale', 18.0)
    links.new(coord.outputs['Object'], voronoi.inputs['Vector'])

    crack_ramp = nodes.new(type="ShaderNodeValToRGB")
    crack_ramp.location = (-260, -150)
    crack_ramp.color_ramp.elements[0].position = 0.0
    crack_ramp.color_ramp.elements[0].color = (0.05, 0.05, 0.05, 1.0)
    crack_ramp.color_ramp.elements[1].position = 0.08
    crack_ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
    links.new(voronoi.outputs['Distance'], crack_ramp.inputs['Fac'])

    crack_mix = nodes.new(type="ShaderNodeMixRGB")
    _set_prop(crack_mix, 'blend_type', 'MULTIPLY')
    crack_mix.inputs['Fac'].default_value = 0.6
    crack_mix.location = (-40, 0)
    links.new(brick.outputs['Color'], crack_mix.inputs['Color1'])
    links.new(crack_ramp.outputs['Color'], crack_mix.inputs['Color2'])

    final_color = _make_ao_readability_chain(nt, crack_mix.outputs['Color'], 200, 0)
    _finish_material(nt, final_color, roughness=0.85, tint=tint, mat=mat)
    return mat


def create_cave_material(tint=None):
    """Simplified triplanar: Object-space coordinates sampled on two axis
    pairs and blended by the surface normal's dominant axis, driving a
    high-frequency Noise texture (fBM-style, since Musgrave was folded into
    the Noise node) for a chiseled organic rock look without UV seams."""
    mat = bpy.data.materials.new(name="LA_Cave_Rock")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    links, nodes = nt.links, nt.nodes

    coord = nodes.new(type="ShaderNodeTexCoord")
    coord.location = (-900, 0)

    normal = nodes.new(type="ShaderNodeNewGeometry")
    normal.location = (-900, -250)
    abs_normal = nodes.new(type="ShaderNodeVectorMath")
    _set_prop(abs_normal, 'operation', 'ABSOLUTE')
    abs_normal.location = (-700, -250)
    links.new(normal.outputs['Normal'], abs_normal.inputs[0])
    sep_normal = nodes.new(type="ShaderNodeSeparateXYZ")
    sep_normal.location = (-500, -250)
    links.new(abs_normal.outputs['Vector'], sep_normal.inputs['Vector'])

    noise_a = nodes.new(type="ShaderNodeTexNoise")
    noise_a.location = (-600, 200)
    _set_prop(noise_a, 'noise_dimensions', '3D')
    _set_prop(noise_a, 'noise_type', 'RIDGED_MULTIFRACTAL')
    _set_input(noise_a, 'Scale', 12.0)
    _set_input(noise_a, 'Detail', 8.0)
    links.new(coord.outputs['Object'], noise_a.inputs['Vector'])

    noise_b = nodes.new(type="ShaderNodeTexNoise")
    noise_b.location = (-600, 20)
    _set_prop(noise_b, 'noise_dimensions', '3D')
    _set_prop(noise_b, 'noise_type', 'HETERO_TERRAIN')
    _set_input(noise_b, 'Scale', 20.0)
    _set_input(noise_b, 'Detail', 6.0)
    links.new(coord.outputs['Object'], noise_b.inputs['Vector'])

    triplanar_mix = nodes.new(type="ShaderNodeMixRGB")
    triplanar_mix.location = (-300, 100)
    links.new(sep_normal.outputs['Z'], triplanar_mix.inputs['Fac'])
    links.new(noise_a.outputs['Fac'], triplanar_mix.inputs['Color1'])
    links.new(noise_b.outputs['Fac'], triplanar_mix.inputs['Color2'])

    displaced_ramp = nodes.new(type="ShaderNodeValToRGB")
    displaced_ramp.location = (-60, 100)
    displaced_ramp.color_ramp.elements[0].color = (0.10, 0.10, 0.11, 1.0)
    displaced_ramp.color_ramp.elements[1].color = (0.45, 0.43, 0.40, 1.0)
    links.new(triplanar_mix.outputs['Color'], displaced_ramp.inputs['Fac'])

    final_color = _make_ao_readability_chain(nt, displaced_ramp.outputs['Color'], 200, 100)
    _finish_material(nt, final_color, roughness=0.95, tint=tint, mat=mat)

    # Bump the raw noise into the surface normal for a chiseled feel (the
    # displacement-free version of what Musgrave Displacement used to do).
    bump = nt.nodes.new(type="ShaderNodeBump")
    bump.location = (700, -200)
    _set_input(bump, 'Strength', 0.4)
    links.new(triplanar_mix.outputs['Color'], bump.inputs['Height'])
    bsdf = next(n for n in nt.nodes if n.type == 'BSDF_PRINCIPLED')
    links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])
    return mat


def create_open_area_material(tint=None):
    """Flat ground/barrier material: subtle noise variation plus the same
    AO readability boost, kept cheap since Open Area levels favor large
    unbroken surfaces read from a distance."""
    mat = bpy.data.materials.new(name="LA_Open_Area")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    links, nodes = nt.links, nt.nodes

    coord = nodes.new(type="ShaderNodeTexCoord")
    coord.location = (-700, 0)
    noise = nodes.new(type="ShaderNodeTexNoise")
    noise.location = (-450, 0)
    _set_prop(noise, 'noise_dimensions', '3D')
    _set_input(noise, 'Scale', 6.0)
    _set_input(noise, 'Detail', 3.0)
    links.new(coord.outputs['Object'], noise.inputs['Vector'])

    ramp = nodes.new(type="ShaderNodeValToRGB")
    ramp.location = (-220, 0)
    ramp.color_ramp.elements[0].color = (0.42, 0.42, 0.40, 1.0)
    ramp.color_ramp.elements[1].color = (0.55, 0.55, 0.52, 1.0)
    links.new(noise.outputs['Fac'], ramp.inputs['Fac'])

    final_color = _make_ao_readability_chain(nt, ramp.outputs['Color'], 0, 0)
    _finish_material(nt, final_color, roughness=0.6, tint=tint, mat=mat)
    return mat


STYLE_MATERIAL_FACTORY = {
    '0': create_dungeon_material,
    '1': create_cave_material,
    '2': create_open_area_material,
}
STYLE_MATERIAL_NAME = {
    '0': "LA_Dungeon_Bricks",
    '1': "LA_Cave_Rock",
    '2': "LA_Open_Area",
}

def get_or_create_style_material(style_key):
    name = STYLE_MATERIAL_NAME[style_key]
    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing
    mat = STYLE_MATERIAL_FACTORY[style_key](tint=None)
    mat.name = name
    return mat


# ==============================================================================
# 3b. SIMPLE VIEWPORT-COLOR MATERIALS (for blockout / layout work)
# ==============================================================================
# Solid viewport shading's default "Material" color mode reads each
# material's flat Viewport Display color, not its shader node tree -- so for
# fast modeling/layout iteration (no need for the procedural brick/rock
# shaders above) these materials drive an Image Texture -> Base Color chain
# when a matching file exists in Textures/, and ALSO set diffuse_color from
# that same image so Solid shading and Material Preview/Rendered agree
# without any manual tweaking. Falls back to a flat hex color (no node
# graph beyond a bare Principled BSDF) when the Textures folder or a
# specific file is missing, so generation never breaks for want of an
# image -- this is what lets the addon travel without its Textures/ folder,
# or run before that folder exists at all.
#
# Palette layout (agreed with the user, see the "Palette Assignment"
# artifact from this same session): 8 floor-level colors (cycled every 8
# stories), 18 pooled room colors, and one fixed color each for walls,
# stairs, doors (not generated yet), entrance and exit.
FLOOR_RAMP_HEX = ["7b334c", "c77369", "d37b86", "af5d8b", "5b3374", "4e6679", "89d9d9", "b1d480"]
FLOOR_RAMP_FILES = [f"Floor{i + 1}.png" for i in range(8)]

ROOM_POOL_HEX = [
    "a14d55", "e3a084", "f2cb9b", "804085", "412051", "5c486a",
    "dcdac9", "ffffe0", "b6f5db", "5c8ba8", "464969", "44355d",
    "3d003d", "621748", "942c4b", "e06b51", "fcef8d", "658d78",
]
ROOM_POOL_FILES = [f"Room{i + 1}.png" for i in range(18)]

WALL_HEX = "887d8d"
WALL_FILE = "Wall0.png"

STAIR_HEX = "f2a561"
STAIR_FILE = "Stairs.png"

DOOR_HEX = "72b6cf"
DOOR_FILES = ("Doors.png",)

ENTRANCE_HEX = "80b878"
ENTRANCE_FILES = ("Enterance.png", "Entrance.png")  # tolerate the common misspelling either way

EXIT_HEX = "c7424f"
EXIT_FILE = "Exit.png"

TORCH_HEX = "5c4326"
TORCH_FILE = "Torch.png"

TORCH_FLAME_HEX = "ff8c3d"
TORCH_FLAME_FILE = "TorchFlame.png"

PROP_HEX = "a97c50"
PROP_FILE = "Prop.png"

SIMPLE_ROOM_MATERIAL_PREFIX = "LA_Room_"


def _hex_to_rgba(hex_str):
    hex_str = hex_str.lstrip('#')
    return (
        int(hex_str[0:2], 16) / 255.0,
        int(hex_str[2:4], 16) / 255.0,
        int(hex_str[4:6], 16) / 255.0,
        1.0,
    )


def _textures_dir():
    """The Textures/ folder this addon expects to sit right beside its own
    .py file -- travels with the addon if the whole folder is copied or
    shared, rather than depending on a fixed absolute path."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "Textures")


def _load_texture_image(filename):
    """Loads (or reuses an already-loaded) image from Textures/. Returns
    None if the folder or file doesn't exist, so callers can fall back to
    a flat hex color instead of failing generation outright."""
    path = os.path.join(_textures_dir(), filename)
    if not os.path.isfile(path):
        return None
    try:
        return bpy.data.images.load(path, check_existing=True)
    except RuntimeError as exc:
        print(f"[Level Architect] Could not load texture '{filename}': {exc}")
        return None


def _sample_image_color(image):
    """Center-pixel color of an image -- these are solid-color swatches, so
    one sample is exactly representative, and far cheaper than averaging
    every pixel for a texture that might not stay tiny forever."""
    w, h = image.size
    if w == 0 or h == 0:
        return (0.8, 0.8, 0.8, 1.0)
    channels = image.channels or 4
    pixels = image.pixels
    idx = (h // 2 * w + w // 2) * channels
    r = pixels[idx]
    g = pixels[idx + 1] if channels > 1 else r
    b = pixels[idx + 2] if channels > 2 else r
    a = pixels[idx + 3] if channels > 3 else 1.0
    return (r, g, b, a)


def _new_textured_material(name, filenames, fallback_hex):
    """filenames may be a single string or a tuple of candidates tried in
    order (used for Entrance, where the file on disk is misspelled) --
    the first one found in Textures/ wins."""
    if isinstance(filenames, str):
        filenames = (filenames,)
    fallback_color = _hex_to_rgba(fallback_hex)

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    out_node = nodes.new(type="ShaderNodeOutputMaterial")
    out_node.location = (300, 0)
    links.new(bsdf.outputs['BSDF'], out_node.inputs['Surface'])

    image = None
    for filename in filenames:
        image = _load_texture_image(filename)
        if image is not None:
            break

    if image is not None:
        tex_node = nodes.new(type="ShaderNodeTexImage")
        tex_node.image = image
        _set_prop(tex_node, 'interpolation', 'Closest')
        tex_node.location = (-300, 0)
        links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
        mat.diffuse_color = _sample_image_color(image)
    else:
        _set_input(bsdf, 'Base Color', fallback_color)
        mat.diffuse_color = fallback_color

    return mat


def _get_or_create_named_material(name, filenames, fallback_hex):
    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing
    return _new_textured_material(name, filenames, fallback_hex)


def get_or_create_floor_level_materials():
    """One material per ramp position -- corridors take their level's color
    directly (level index MOD 8), so height reads at a glance without
    needing a separate per-room scheme to also carry that information."""
    return [
        _get_or_create_named_material(f"LA_Floor_Level_{i}", FLOOR_RAMP_FILES[i], FLOOR_RAMP_HEX[i])
        for i in range(len(FLOOR_RAMP_HEX))
    ]


def get_or_create_simple_wall_material():
    return _get_or_create_named_material("LA_Simple_Wall", WALL_FILE, WALL_HEX)


def get_or_create_simple_stair_material():
    return _get_or_create_named_material("LA_Simple_Stair", STAIR_FILE, STAIR_HEX)


def get_or_create_door_material():
    return _get_or_create_named_material("LA_Door", DOOR_FILES, DOOR_HEX)


def get_or_create_entrance_material():
    return _get_or_create_named_material("LA_Entrance", ENTRANCE_FILES, ENTRANCE_HEX)


def get_or_create_exit_material():
    return _get_or_create_named_material("LA_Exit", EXIT_FILE, EXIT_HEX)


def get_or_create_torch_material():
    return _get_or_create_named_material("LA_Torch", TORCH_FILE, TORCH_HEX)


def get_or_create_torch_flame_material():
    return _get_or_create_named_material("LA_Torch_Flame", TORCH_FLAME_FILE, TORCH_FLAME_HEX)


def get_or_create_prop_material():
    return _get_or_create_named_material("LA_Prop", PROP_FILE, PROP_HEX)


def create_simple_room_materials(room_count):
    """One material per room, cycling through the 18-texture room pool in a
    freshly shuffled order each generation -- guarantees no two of the
    first 18 rooms repeat a color (independent random-per-room could
    collide even with 18 options available), and keeps any repeats past
    that as spread out as possible. Room materials from a previous
    generation that are no longer used by any object (users == 0) are
    purged first so they don't pile up across repeated Generate clicks."""
    for mat in list(bpy.data.materials):
        if mat.name.startswith(SIMPLE_ROOM_MATERIAL_PREFIX) and mat.users == 0:
            bpy.data.materials.remove(mat)

    pool_order = list(range(len(ROOM_POOL_HEX)))
    random.shuffle(pool_order)

    materials = []
    for i in range(room_count):
        pool_idx = pool_order[i % len(pool_order)]
        materials.append(_new_textured_material(
            f"{SIMPLE_ROOM_MATERIAL_PREFIX}{i:04d}", ROOM_POOL_FILES[pool_idx], ROOM_POOL_HEX[pool_idx]
        ))
    return materials


# ==============================================================================
# 3c. STYLE-MODE PER-FLOOR/PER-ROOM COLORING
# ==============================================================================
# Style mode (the procedural dungeon/cave/open-area shaders) used to be a
# flat 2-slot system -- one corridor look, one room look, both the exact
# same color for the whole level regardless of floor or which room -- while
# Simple Viewport Colors got real per-room/per-floor variety. Same idea as
# Simple mode's palette (FLOOR_RAMP_HEX cycling per floor-level, ROOM_POOL_HEX
# per room), just multiplied onto the procedural shader as a tint
# (`_finish_material`'s `tint` param, already used for the single flat
# "Room" variant every style had) instead of driving a flat Image Texture --
# so a Style room STILL has its brick/rock/noise pattern, it's just also
# colored distinctly like a Simple-mode one. Naming/caching/shuffle
# conventions deliberately mirror get_or_create_floor_level_materials /
# create_simple_room_materials exactly, one style-material-factory call
# away from being the same function.
STYLE_ROOM_MATERIAL_PREFIX_FMT = "{}_Room_"
STYLE_ROOM_MATERIAL_PREFIXES = [STYLE_ROOM_MATERIAL_PREFIX_FMT.format(name) for name in STYLE_MATERIAL_NAME.values()]


def get_or_create_style_floor_level_materials(style_for_slot):
    """Style-mode equivalent of get_or_create_floor_level_materials(): one
    tinted variant of a style's shader per ramp position, reused across
    generations like the Simple-mode floor materials are (level 0 is
    always the same color, nothing to shuffle).

    style_for_slot(i) resolves which style ('0'/'1'/'2') ramp slot i uses
    -- with Per-Floor Overrides (see WFC_FloorProfile / _style_for_
    logical_floor), different slots can now use different styles, not
    just a single one shared by the whole level. Slot i and logical floor
    i are treated as the same axis here (correct whenever Sub-Levels per
    Floor is 1, the common case; an accepted approximation otherwise,
    same granularity Simple mode's own floor-level coloring already has)."""
    materials = []
    for i, hex_color in enumerate(FLOOR_RAMP_HEX):
        style_key = style_for_slot(i)
        name = f"{STYLE_MATERIAL_NAME[style_key]}_FloorLevel_{i}"
        existing = bpy.data.materials.get(name)
        if existing is None:
            existing = STYLE_MATERIAL_FACTORY[style_key](tint=_hex_to_rgba(hex_color))
            existing.name = name
        materials.append(existing)
    return materials


def get_or_create_style_room_materials(style_for_room, room_count):
    """Style-mode equivalent of create_simple_room_materials(): one tinted
    variant of a style's shader per actual room, freshly created and
    shuffled each generation exactly like the Simple-mode room materials
    are (relies on the same orphaned-material purge, not name reuse, so
    each generation's shuffle can differ).

    style_for_room(i) resolves which style room index i uses -- with
    Per-Floor Overrides, this is that room's own logical floor, so (unlike
    the floor-level slots above) there's no ramp-slot-cycling ambiguity:
    every room already gets its own individual material regardless."""
    for mat in list(bpy.data.materials):
        if mat.users == 0 and any(mat.name.startswith(p) for p in STYLE_ROOM_MATERIAL_PREFIXES):
            bpy.data.materials.remove(mat)

    pool_order = list(range(len(ROOM_POOL_HEX)))
    random.shuffle(pool_order)

    materials = []
    for i in range(room_count):
        pool_idx = pool_order[i % len(pool_order)]
        style_key = style_for_room(i)
        prefix = STYLE_ROOM_MATERIAL_PREFIX_FMT.format(STYLE_MATERIAL_NAME[style_key])
        mat = STYLE_MATERIAL_FACTORY[style_key](tint=_hex_to_rgba(ROOM_POOL_HEX[pool_idx]))
        mat.name = f"{prefix}{i:04d}"
        materials.append(mat)
    return materials


def get_or_create_style_entrance_material(style_key):
    name = f"{STYLE_MATERIAL_NAME[style_key]}_Entrance"
    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing
    mat = STYLE_MATERIAL_FACTORY[style_key](tint=_hex_to_rgba(ENTRANCE_HEX))
    mat.name = name
    return mat


def get_or_create_style_exit_material(style_key):
    name = f"{STYLE_MATERIAL_NAME[style_key]}_Exit"
    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing
    mat = STYLE_MATERIAL_FACTORY[style_key](tint=_hex_to_rgba(EXIT_HEX))
    mat.name = name
    return mat


# ==============================================================================
# 4. BLENDER OPERATOR & USER INTERFACE
# ==============================================================================
class OBJECT_OT_GenerateGameBlueprint(bpy.types.Operator):
    bl_idname = "object.generate_game_blueprint"
    bl_label = "Generate Game Blueprint"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene

        # Seed every random call this generation makes (room count, scatter
        # placement, MIXED room shape choice, stair sampling) so the whole
        # layout is reproducible. Random Seed on picks a fresh seed and
        # writes it back to the scene, so turning it off afterward always
        # reproduces whatever was just generated.
        if scene.wfc_random_seed:
            scene.wfc_seed = random.randint(0, 999_999)
        random.seed(scene.wfc_seed)

        rooms_min = min(scene.wfc_rooms_min, scene.wfc_rooms_max)
        rooms_max = max(scene.wfc_rooms_min, scene.wfc_rooms_max)
        room_count = random.randint(rooms_min, rooms_max)

        size_min = min(scene.wfc_room_size_min, scene.wfc_room_size_max)
        size_max = max(scene.wfc_room_size_min, scene.wfc_room_size_max)

        # Per-floor override breakpoints (see WFC_FloorProfile) -- built
        # once here from the scene's CollectionProperty into plain dicts,
        # the shape both WFC_Level_Solver (room size/shape) and the
        # material-style resolution below (_style_for_logical_floor) take.
        # Empty list when the user hasn't added any, which both consumers
        # already treat as "fall back to the flat scene values everywhere".
        floor_profiles = [
            {
                'floor_index': fp.floor_index,
                'room_size_min': min(fp.room_size_min, fp.room_size_max),
                'room_size_max': max(fp.room_size_min, fp.room_size_max),
                'room_shape': fp.room_shape,
                'style': fp.style,
            }
            for fp in scene.wfc_floor_profiles
        ]

        # Computed before the solver, not after: a bent stairwell's landing
        # needs the real meters-per-FINE-slice value (not scene.wfc_
        # level_height, the height of one whole LOGICAL floor) to bake its
        # own proportional mid-climb world-Z, since every solver fine-Z
        # step (z to z+1, whether a split-level step within one floor or a
        # jump to the next floor) always spans exactly one fine slice --
        # see _fine_level_height's own docstring.
        fine_level_height = _fine_level_height(scene)

        solver = WFC_Level_Solver(
            width=scene.wfc_width,
            length=scene.wfc_length,
            height=scene.wfc_height,
            room_count=room_count,
            room_size_min=size_min,
            room_size_max=size_max,
            stairs_per_level=scene.wfc_stairs_per_level,
            tile_size=scene.wfc_tile_size,
            level_height=fine_level_height,
            room_shape=scene.wfc_room_shape,
            stair_room_width=scene.wfc_stair_room_width,
            stair_room_length=scene.wfc_stair_room_length,
            corridor_stairs=scene.wfc_corridor_stairs,
            sub_levels_per_floor=scene.wfc_sub_levels_per_floor,
            split_level_chance=scene.wfc_split_level_chance,
            elevation_chance=scene.wfc_elevation_chance,
            elevation_range=scene.wfc_elevation_range,
            max_ramp_slope_deg=scene.wfc_max_ramp_slope,
            floor_profiles=floor_profiles,
            stair_bend_chance=scene.wfc_stair_bend_chance,
            stair_bend_style=scene.wfc_stair_bend_style,
        )
        solver.solve()

        mesh_name = BLUEPRINT_OBJECT_NAME
        if mesh_name in bpy.data.objects:
            old_mesh = bpy.data.objects[mesh_name].data
            bpy.data.objects.remove(bpy.data.objects[mesh_name], do_unlink=True)
            if old_mesh and old_mesh.users == 0:
                bpy.data.meshes.remove(old_mesh)

        vertices = []
        tile_ids = []
        tile_rots = []
        zone_types = []
        room_ids = []
        floor_openings = []
        stair_run_ids = []
        stair_segment_indices = []
        level_zs = []
        logical_floors = []
        z_offsets = []
        ceiling_openings = []

        scale_factor = scene.wfc_tile_size
        style_int = int(scene.wfc_style)
        for x in range(solver.w):
            for y in range(solver.l):
                for z in range(solver.h):
                    tid = solver.grid[x][y][z]
                    if tid != TILE_AIR:
                        z_offset = solver.cell_z_offset[x][y][z]
                        vertices.append((x * scale_factor, y * scale_factor, z * fine_level_height + z_offset))
                        tile_ids.append(tid)
                        tile_rots.append(solver.rotations[x][y][z])
                        zone_types.append(style_int)
                        room_ids.append(solver.room_id[x][y][z])
                        floor_openings.append((x, y, z) in solver.floor_openings)
                        stair_run_ids.append(solver.stair_run_id[x][y][z])
                        stair_segment_indices.append(solver.stair_segment_index[x][y][z])
                        level_zs.append(z)
                        # Baked in now (using THIS generation's actual
                        # solver.sub_levels), rather than re-derived later
                        # from the live scene property -- which could have
                        # drifted if the user changes Sub-Levels per Floor
                        # after generating but before separating.
                        logical_floors.append(z // solver.sub_levels)
                        # World-Z offset already folded into this point's Z
                        # above -- kept as its own attribute too so
                        # Walls/Doors (which build geometry, like wall
                        # boxes, that a raw vertex position alone can't
                        # describe) can read the exact continuous value
                        # directly instead of re-deriving it.
                        z_offsets.append(z_offset)
                        # True when the point directly above this one
                        # (z+1) is itself a floor_opening -- Add Ceiling
                        # skips instancing a ceiling here too, so a
                        # stairwell hole stays open looking both up and
                        # down instead of getting sealed shut from above.
                        ceiling_openings.append((x, y, z + 1) in solver.floor_openings)

        mesh_data = bpy.data.meshes.new(mesh_name + "_Mesh")
        mesh_data.from_pydata(vertices, [], [])
        mesh_data.update()

        level_obj = bpy.data.objects.new(mesh_name, mesh_data)
        context.collection.objects.link(level_obj)
        context.view_layer.objects.active = level_obj
        level_obj.select_set(True)

        mesh_data.attributes.new(name="tile_id", type="INT", domain="POINT")
        mesh_data.attributes["tile_id"].data.foreach_set("value", tile_ids)
        mesh_data.attributes.new(name="tile_rotation", type="FLOAT", domain="POINT")
        mesh_data.attributes["tile_rotation"].data.foreach_set("value", tile_rots)
        mesh_data.attributes.new(name="zone_type", type="INT", domain="POINT")
        mesh_data.attributes["zone_type"].data.foreach_set("value", zone_types)
        mesh_data.attributes.new(name="room_id", type="INT", domain="POINT")
        mesh_data.attributes["room_id"].data.foreach_set("value", room_ids)
        mesh_data.attributes.new(name="floor_opening", type="BOOLEAN", domain="POINT")
        mesh_data.attributes["floor_opening"].data.foreach_set("value", floor_openings)
        mesh_data.attributes.new(name="stair_run_id", type="INT", domain="POINT")
        mesh_data.attributes["stair_run_id"].data.foreach_set("value", stair_run_ids)
        mesh_data.attributes.new(name="stair_segment_index", type="INT", domain="POINT")
        mesh_data.attributes["stair_segment_index"].data.foreach_set("value", stair_segment_indices)
        mesh_data.attributes.new(name="level_z", type="INT", domain="POINT")
        mesh_data.attributes["level_z"].data.foreach_set("value", level_zs)
        mesh_data.attributes.new(name="logical_floor", type="INT", domain="POINT")
        mesh_data.attributes["logical_floor"].data.foreach_set("value", logical_floors)
        mesh_data.attributes.new(name="z_offset", type="FLOAT", domain="POINT")
        mesh_data.attributes["z_offset"].data.foreach_set("value", z_offsets)
        mesh_data.attributes.new(name="ceiling_opening", type="BOOLEAN", domain="POINT")
        mesh_data.attributes["ceiling_opening"].data.foreach_set("value", ceiling_openings)

        if scene.wfc_simple_materials:
            floor_level_materials = get_or_create_floor_level_materials()
            room_materials = create_simple_room_materials(len(solver.rooms))
            entrance_material = get_or_create_entrance_material()
            exit_material = get_or_create_exit_material()
            all_materials = floor_level_materials + room_materials + [entrance_material, exit_material]
            floor_level_count = len(floor_level_materials)
            entrance_material_index = len(floor_level_materials) + len(room_materials)
            exit_material_index = entrance_material_index + 1
        else:
            # Per-Floor Overrides' style breakpoints (see
            # _style_for_logical_floor): floor-level slots resolve by slot
            # index directly (== logical floor when Sub-Levels per Floor is
            # 1), rooms resolve by their own actual logical floor. Entrance/
            # Exit stay on the single global scene.wfc_style regardless --
            # those two are level-wide landmarks, not tied to one floor.
            style_for_slot = lambda i: _style_for_logical_floor(floor_profiles, i, scene.wfc_style)
            style_for_room = lambda i: _style_for_logical_floor(
                floor_profiles, solver.rooms[i]['z'] // solver.sub_levels, scene.wfc_style
            )
            floor_level_materials = get_or_create_style_floor_level_materials(style_for_slot)
            room_materials = get_or_create_style_room_materials(style_for_room, len(solver.rooms))
            entrance_material = get_or_create_style_entrance_material(scene.wfc_style)
            exit_material = get_or_create_style_exit_material(scene.wfc_style)
            all_materials = floor_level_materials + room_materials + [entrance_material, exit_material]
            floor_level_count = len(floor_level_materials)
            entrance_material_index = len(floor_level_materials) + len(room_materials)
            exit_material_index = entrance_material_index + 1

        create_geometry_nodes_modifier(
            level_obj, scene.wfc_iso_mode, all_materials,
            tile_size=scene.wfc_tile_size, level_height=fine_level_height,
            color_rooms_default=scene.wfc_color_rooms, floor_thickness_default=scene.wfc_floor_thickness,
            add_ceiling_default=scene.wfc_add_ceiling, ceiling_thickness_default=scene.wfc_ceiling_thickness,
            floor_level_count=floor_level_count,
            entrance_material_index=entrance_material_index, exit_material_index=exit_material_index,
        )

        # Round rooms get a real merged n-gon floor disc, drawn as a
        # separate cosmetic overlay that fully covers the Blueprint's own
        # (unmodified) per-tile floor cubes rather than touching that point
        # cloud/GN graph at all -- see _build_round_room_floor_mesh's own
        # docstring for why. room_materials is the SAME per-room material
        # list the Blueprint's own GN material slots above just used --
        # reused directly rather than calling create_simple_room_materials/
        # get_or_create_style_room_materials a second time, which would
        # consume a fresh random.shuffle and desync Simple mode's room
        # colors from what the Blueprint itself already committed to.
        if ROUND_FLOOR_OBJECT_NAME in bpy.data.objects:
            old_round_obj = bpy.data.objects[ROUND_FLOOR_OBJECT_NAME]
            old_round_mesh = old_round_obj.data
            bpy.data.objects.remove(old_round_obj, do_unlink=True)
            if old_round_mesh and old_round_mesh.users == 0:
                bpy.data.meshes.remove(old_round_mesh)

        round_verts, round_faces, round_mat_indices, round_room_ids = _build_round_room_floor_mesh(
            solver, scene.wfc_tile_size, fine_level_height, scene.wfc_room_shape_sides,
        )
        if round_faces:
            round_mesh = bpy.data.meshes.new(ROUND_FLOOR_OBJECT_NAME + "_Mesh")
            round_mesh.from_pydata(round_verts, [], round_faces)
            round_mesh.update()
            for rid in round_room_ids:
                round_mesh.materials.append(room_materials[rid])
            for poly, mat_idx in zip(round_mesh.polygons, round_mat_indices):
                poly.material_index = mat_idx
            round_obj = bpy.data.objects.new(ROUND_FLOOR_OBJECT_NAME, round_mesh)
            context.collection.objects.link(round_obj)

        # Room bounding-box + shape metadata for later steps (Walls) that
        # deliberately don't re-run the solver -- see
        # OBJECT_OT_GenerateLevelWalls, which reads this back to build a
        # real perimeter ring for Round rooms instead of blocky per-cell
        # boxes. Same "stash generation metadata as a string ID property"
        # precedent wfc_debug_params already uses.
        level_obj["gla_room_meta"] = json.dumps([
            {
                'x': room['x'], 'y': room['y'], 'w': room['w'], 'l': room['l'], 'z': room['z'],
                'shape': solver.room_shapes.get(i, 'RECT'),
            }
            for i, room in enumerate(solver.rooms)
        ])

        # a copy of what the game package needs, kept on the scene because "Separate by Floor/Room" consumes this object
        _walk_c, _ex_c = _read_blueprint_points(
            level_obj, scene.wfc_tile_size, _fine_level_height(scene), ("tile_id", "tile_rotation", "room_id", "z_offset"))
        scene["gla_package_cache"] = json.dumps({
            "cells": [[c[0], c[1], c[2], _ex_c["tile_id"].get(c, 0), round(_ex_c["tile_rotation"].get(c, 0.0), 4),
                       _ex_c["room_id"].get(c, -1), round(_ex_c["z_offset"].get(c, 0.0), 4)] for c in sorted(_walk_c)],
            "rooms": level_obj["gla_room_meta"],
        })

        self.report(
            {'INFO'},
            f"Blueprint generated: {len(vertices)} tiles across {room_count} rooms. Seed {scene.wfc_seed}."
        )
        _update_debug_snapshot(context, "Step 1: Generate Blueprint")
        return {'FINISHED'}


def _read_polygon_values(mesh_data, attr_name):
    """Returns one value per polygon/face for a point- or face-domain
    attribute. Geometry Nodes' Instance on Points -> Realize Instances can
    land a point attribute on either domain depending on Blender
    version/graph shape, so this reads whichever is actually present
    rather than assuming one -- returns None if the attribute doesn't
    exist at all."""
    layer = mesh_data.attributes.get(attr_name)
    if layer is None:
        return None
    if layer.domain == 'FACE':
        return [item.value for item in layer.data]
    return [layer.data[poly.vertices[0]].value for poly in mesh_data.polygons]


def _mesh_from_faces(mesh_data, face_indices, name):
    """Builds a standalone mesh from a subset of an existing mesh's faces
    (dedup-ing shared vertices into a fresh, densely-indexed vertex list),
    copying only the source materials this subset's faces actually use (in
    a freshly compacted slot list, each face's material_index remapped to
    match), and the source UV map (if any). Shared by every per-floor/
    per-room/per-corridor split below.

    Deliberately NOT copying the full source material list (every earlier
    version of this function did): a Room object only ever uses one room
    material, but inherited the WHOLE blueprint's slot list regardless --
    every floor-level color, every OTHER room's color, entrance, exit, all
    30-50+ of them for a real level. The faces still rendered with the
    right color (their material_index pointed at the right slot in that
    oversized list), but Blender's Properties > Material tab always shows
    the OBJECT's ACTIVE slot (index 0 by default, never touched by this
    code) as "the material" regardless of which slot a face actually
    uses -- with the full list copied, slot 0 was always LA_Floor_Level_0,
    so a Room object's Material field showed a floor-level color instead of
    its own, even though the viewport rendered it correctly. Found from
    user feedback: "we get Procedural_Level_Blueprint_Floor2_Room04 but
    material field is empty on this object, material should be
    LA_Room_0004." A compacted list makes the object's own single (or few)
    real material(s) the ones in slot 0+, so the default active slot is
    always one this object actually uses."""
    verts = []
    vert_remap = {}
    faces = []
    material_indices = []
    for pi in face_indices:
        poly = mesh_data.polygons[pi]
        face = []
        for vi in poly.vertices:
            if vi not in vert_remap:
                vert_remap[vi] = len(verts)
                verts.append(mesh_data.vertices[vi].co[:])
            face.append(vert_remap[vi])
        faces.append(tuple(face))
        material_indices.append(poly.material_index)

    new_mesh = bpy.data.meshes.new(name + "_Mesh")
    new_mesh.from_pydata(verts, [], faces)
    new_mesh.update()
    used_global_indices = sorted(set(material_indices))
    local_index_by_global = {g: i for i, g in enumerate(used_global_indices)}
    for g in used_global_indices:
        new_mesh.materials.append(mesh_data.materials[g] if 0 <= g < len(mesh_data.materials) else None)
    for new_poly, mat_idx in zip(new_mesh.polygons, material_indices):
        new_poly.material_index = local_index_by_global[mat_idx]

    # Without this, a split object has no UV map at all (from_pydata never
    # carries one over), and Solid Shading's "Texture" color mode -- a
    # separate, simpler display path from "Material" that actually needs a
    # real UV map, unlike EEVEE's node-tree evaluation -- shows nothing
    # useful on it. Deliberately NOT `.active` -- a UV attribute baked by
    # Geometry Nodes (GeometryNodeStoreNamedAttribute) never gets Blender's
    # "active UV map" flag set automatically, so `.active` reads None even
    # though the layer is right there; the first (and here, only) entry is
    # what we actually want regardless of that flag.
    source_uv = mesh_data.uv_layers[0] if len(mesh_data.uv_layers) > 0 else None
    if source_uv is not None:
        new_uv = new_mesh.uv_layers.new(name=source_uv.name)
        for pi, new_poly in zip(face_indices, new_mesh.polygons):
            for src_loop, new_loop in zip(mesh_data.polygons[pi].loop_indices, new_poly.loop_indices):
                new_uv.data[new_loop].uv = source_uv.data[src_loop].uv

    _add_viewport_color_attribute(new_mesh)

    return new_mesh


def _face_connected_components(mesh_data, face_indices):
    """Groups the given polygon indices into topologically-connected pieces
    based on shared vertices in the mesh. A room's floor tiles are normally
    all one component; a room-based stairwell's landing pair is a real
    exception -- the buffer tile before the first step and the one after
    the last step share the same room_id, but the stair itself (a separate
    tile_id, generated separately in Step 3) runs between them, so the two
    landings share no vertex with each other. Used to detect that case so
    it can be routed into the floor's shared Corridors object instead of
    becoming its own visibly-fragmented Room object."""
    vert_to_faces = {}
    for pi in face_indices:
        for vi in mesh_data.polygons[pi].vertices:
            vert_to_faces.setdefault(vi, []).append(pi)

    seen = set()
    components = []
    for start in face_indices:
        if start in seen:
            continue
        seen.add(start)
        stack = [start]
        component = []
        while stack:
            pi = stack.pop()
            component.append(pi)
            for vi in mesh_data.polygons[pi].vertices:
                for neighbor in vert_to_faces[vi]:
                    if neighbor not in seen:
                        seen.add(neighbor)
                        stack.append(neighbor)
        components.append(component)
    return components
    return new_mesh


class OBJECT_OT_SeparateLevelByFloor(bpy.types.Operator):
    """Splits the active object's mesh into one object per room (plus one
    combined corridor object) on each logical floor, using the
    "logical_floor" and "room_id" data baked in at generation time. Works
    directly on the Procedural Level Blueprint WITH its Geometry Nodes
    modifier still live -- evaluates it internally rather than requiring the
    user to apply it first.

    That used to be a documented precondition ("Object > Apply > Visual
    Geometry to Mesh" first), but Blender's own Apply/Convert-to-Mesh path
    (bpy.ops.object.convert / modifier_apply) replaces the object's mesh
    datablock with the evaluated geometry, which does NOT carry the
    original per-room material SLOT LIST with it -- confirmed directly:
    every face's material_index survives a real "Convert to Mesh" bit for
    bit, but the slot list itself collapses from (floor levels + rooms +
    entrance/exit) down to 1, so every index beyond 0 silently has nothing
    to resolve to and every room reads as one flat color. `Set Material
    Index` in the GN graph only ever wrote a numeric index; it never
    attached real material references to the geometry itself, so any code
    path that bakes the modifier's output into a fresh mesh has to
    re-attach the ORIGINAL object's material list by hand afterward. Doing
    that evaluation and re-attachment here, instead of requiring a manual
    pre-apply step that silently breaks it, fixes the bug at its actual
    source and removes an error-prone manual step at the same time.

    This exists because Blender's own Select Linked only understands
    vertex connectivity, not "which floor/room is this." Once Sub-Levels
    per Floor > 1, a floor's split-level room isn't even vertex-connected
    to the rest of its own floor (different height, no shared geometry),
    and two rooms joined only by a corridor share no verts either -- this
    reads the floor/room each face was generated on directly, so grouping
    is always correct regardless of vertex adjacency.

    Results land in a collection tree (Blueprint (Split) > Floor N > Rooms /
    Corridors / Ceilings) instead of loose objects, so a floor or a single
    room can be hidden/isolated/exported independently. Corridor tiles for a
    floor (room_id == -1, including entrance/exit) stay one combined object
    -- they're one connected network by construction, not discrete rooms.

    If Add Ceiling is on, every room's ceiling patch shares that room's
    room_id but sits a full level_height above its floor patch with no
    shared geometry -- left alone, that would make EVERY room read as
    "fragmented" the same way a stairwell landing pair does (see below),
    not just the rare genuine case, defeating the point of splitting by
    room at all. Ceiling faces (room_id >= 0 only -- a corridor's own
    ceiling stays bundled into its floor's single Corridors object, which
    was never meant to be one visually-cohesive shape anyway) are detected
    by local Z within their level band and pulled into their own per-floor
    Ceilings bucket before the room/corridor split below ever runs, so
    Rooms only ever contains actual floor tiles."""
    bl_idname = "object.separate_level_by_floor"
    bl_label = "Separate by Floor/Room"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh object first (the Procedural Level Blueprint).")
            return {'CANCELLED'}

        original_materials = list(obj.data.materials)
        original_mesh_data = obj.data
        original_node_group = None
        for m in obj.modifiers:
            if m.type == 'NODES':
                original_node_group = m.node_group
                break

        # This operator evaluates the GN modifier live and re-attaches the
        # ORIGINAL object's full material list itself -- see the class
        # docstring above for why a manual "Apply Modifier" first used to be
        # required and silently broke per-room materials (Blender's own
        # Apply/Convert-to-Mesh collapses the slot list down to 1). If the
        # modifier is already gone, that protection can't run: `obj.data`
        # is already the collapsed, applied mesh, `original_materials` here
        # would already only have whatever few slots survived the apply,
        # and every split object downstream would inherit that same
        # collapsed list -- a room whose real material_index isn't in that
        # tiny list gets an empty (None) material slot instead of its real
        # color. Refuse up front instead of silently producing that.
        if original_node_group is None:
            self.report(
                {'ERROR'},
                "This object's Geometry Nodes modifier (GN_Game_Renderer) isn't present -- "
                "already applied, or removed. Separate by Floor/Room evaluates it live and "
                "needs it there; applying it manually first discards the per-room material "
                "list Blender doesn't preserve across Apply Modifier. Regenerate the Blueprint "
                "(Step 1) and run Separate by Floor/Room directly on it, without applying the "
                "modifier first."
            )
            return {'CANCELLED'}

        depsgraph = context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
        if mesh is not None:
            # to_mesh() on evaluated GN output starts with its own (empty
            # or single default) material slot list -- Set Material Index
            # only ever wrote a numeric index into whatever list the object
            # already had, it never attached real materials to the geometry
            # itself, so that has to be rebuilt from the source object here.
            #
            # `mesh.materials.clear()` has a real, undocumented side effect:
            # it silently resets every polygon's material_index to 0 as it
            # empties the slot list -- re-appending the same materials
            # afterward does NOT restore them, that per-face data is already
            # gone. Confirmed directly: right after clear()+re-append, EVERY
            # polygon on the whole mesh read material_index 0, including
            # ones that correctly read a real room-pool index (8+) the
            # instant before. Every split object downstream then pointed at
            # slot 0 (a floor-level color) instead of its own room's color --
            # "Material"/"Texture" viewport color modes showed every room
            # identically, and only "Random" (which colors by object
            # identity, not material) showed any difference between rooms.
            # Fixed by saving each polygon's material_index BEFORE touching
            # the slot list at all, and restoring it after.
            material_indices_before_clear = [p.material_index for p in mesh.polygons]
            mesh.materials.clear()
            for m in original_materials:
                mesh.materials.append(m)
            for poly, mat_idx in zip(mesh.polygons, material_indices_before_clear):
                poly.material_index = mat_idx

        if mesh is None or not mesh.polygons:
            if mesh is not None:
                eval_obj.to_mesh_clear()
            self.report(
                {'ERROR'},
                "This object has no geometry to separate -- generate the Blueprint (Step 1) first."
            )
            return {'CANCELLED'}

        floor_values = _read_polygon_values(mesh, "logical_floor")
        room_values = _read_polygon_values(mesh, "room_id") if floor_values is not None else None
        if floor_values is None or room_values is None:
            eval_obj.to_mesh_clear()
            missing = "logical_floor" if floor_values is None else "room_id"
            self.report(
                {'ERROR'},
                f"This mesh has no '{missing}' data -- only works on the Procedural Level Blueprint."
            )
            return {'CANCELLED'}

        # Add Ceiling (if on) instances a second cube per point, flush with
        # the floor of the point directly above -- a room's own ceiling
        # patch shares its room_id but sits a full level_height above its
        # floor patch, with no shared geometry between them at all. Left
        # alone, that makes EVERY room "fragmented" whenever Add Ceiling is
        # on, not just the genuine stairwell-landing case below -- so
        # ceiling faces are pulled out into their own per-floor bucket
        # first, using the same Z-band idea Isometric Mode's own culling
        # already uses (a point's own floor sits near local Z 0 within its
        # level; its ceiling sits near local Z = level_height). Only
        # meaningful for room_id >= 0 (actual rooms) -- a corridor's
        # ceiling patch is left bundled into that floor's single combined
        # Corridors object, since Corridors was never meant to read as one
        # visually-cohesive shape the way a Room is.
        level_z_values = _read_polygon_values(mesh, "level_z")
        fine_level_height = context.scene.wfc_level_height / max(context.scene.wfc_sub_levels_per_floor, 1)
        ceiling_z_threshold = context.scene.wfc_level_height * 0.5

        def is_ceiling_face(pi):
            if level_z_values is None:
                return False
            poly = mesh.polygons[pi]
            face_mean_z = sum(mesh.vertices[vi].co.z for vi in poly.vertices) / len(poly.vertices)
            local_z = face_mean_z - level_z_values[pi] * fine_level_height
            return local_z > ceiling_z_threshold

        # floor_idx -> room_id (-1 for the floor's combined corridor bucket) -> [poly indices]
        faces_by_floor_room = {}
        # floor_idx -> [poly indices], only ever populated for room_id >= 0
        ceiling_faces_by_floor = {}
        for pi, (floor_idx, room_id) in enumerate(zip(floor_values, room_values)):
            if room_id >= 0 and is_ceiling_face(pi):
                ceiling_faces_by_floor.setdefault(floor_idx, []).append(pi)
            else:
                faces_by_floor_room.setdefault(floor_idx, {}).setdefault(room_id, []).append(pi)

        # A room's faces are normally all one topologically-connected blob.
        # The one real exception is a room-based stairwell's landing pair:
        # the buffer tile before the first step and the one after the last
        # share the same room_id, but the stair itself sits between them as
        # a separate tile_id (built separately in Step 3) -- so the two
        # landings share no vertex with each other and would otherwise
        # become one visibly-fragmented "Room" object (two disconnected
        # single tiles). Reroute any such room's faces into that floor's
        # shared Corridors bucket instead -- a landing pair reads much more
        # like a corridor than a room a player would recognize as one.
        for room_buckets in faces_by_floor_room.values():
            fragmented_room_ids = [
                room_id for room_id, face_indices in room_buckets.items()
                if room_id >= 0 and len(_face_connected_components(mesh, face_indices)) > 1
            ]
            for room_id in fragmented_room_ids:
                room_buckets.setdefault(-1, []).extend(room_buckets.pop(room_id))

        total_buckets = (
            sum(len(rooms) for rooms in faces_by_floor_room.values())
            + sum(1 for faces in ceiling_faces_by_floor.values() if faces)
        )
        if total_buckets <= 1:
            eval_obj.to_mesh_clear()
            self.report({'WARNING'}, "Only one piece of geometry found -- nothing to separate.")
            return {'CANCELLED'}

        top_collection = _get_or_create_collection(BLUEPRINT_SPLIT_COLLECTION_NAME, context.collection)

        created = []
        all_floor_indices = set(faces_by_floor_room) | set(ceiling_faces_by_floor)
        for floor_idx in sorted(all_floor_indices):
            floor_collection_name = f"{BLUEPRINT_SPLIT_COLLECTION_NAME} - Floor {floor_idx}"
            floor_collection = _get_or_create_collection(floor_collection_name, top_collection)
            rooms_collection = None
            corridors_collection = None

            room_buckets = faces_by_floor_room.get(floor_idx, {})
            for room_id in sorted(room_buckets):
                face_indices = room_buckets[room_id]
                if room_id < 0:
                    if corridors_collection is None:
                        corridors_collection = _get_or_create_collection(
                            f"{floor_collection_name} - Corridors", floor_collection
                        )
                    name = f"{obj.name}_Floor{floor_idx}_Corridors"
                    target_collection = corridors_collection
                else:
                    if rooms_collection is None:
                        rooms_collection = _get_or_create_collection(
                            f"{floor_collection_name} - Rooms", floor_collection
                        )
                    name = f"{obj.name}_Floor{floor_idx}_Room{room_id:02d}"
                    target_collection = rooms_collection

                new_mesh = _mesh_from_faces(mesh, face_indices, name)
                new_obj = bpy.data.objects.new(name, new_mesh)
                new_obj.matrix_world = obj.matrix_world.copy()
                target_collection.objects.link(new_obj)
                created.append(new_obj)

            ceiling_faces = ceiling_faces_by_floor.get(floor_idx)
            if ceiling_faces:
                ceilings_collection = _get_or_create_collection(
                    f"{floor_collection_name} - Ceilings", floor_collection
                )
                name = f"{obj.name}_Floor{floor_idx}_Ceilings"
                new_mesh = _mesh_from_faces(mesh, ceiling_faces, name)
                new_obj = bpy.data.objects.new(name, new_mesh)
                new_obj.matrix_world = obj.matrix_world.copy()
                ceilings_collection.objects.link(new_obj)
                created.append(new_obj)

        # The original combined object is now fully redundant -- every one
        # of its faces has been copied into a per-room/per-corridor object
        # above, so leaving it behind would just be a confusing duplicate.
        # Undoable like any other operator here (bl_options REGISTER/UNDO).
        # `mesh` is a temporary evaluated-mesh datablock from to_mesh() --
        # freed via to_mesh_clear() (the documented API for it), not
        # bpy.data.meshes.remove(). obj's own real data (the sparse source
        # point cloud) and its GN modifier's node group are separate
        # datablocks that only become orphaned once obj itself is removed.
        eval_obj.to_mesh_clear()
        bpy.data.objects.remove(obj, do_unlink=True)
        if original_mesh_data.users == 0:
            bpy.data.meshes.remove(original_mesh_data)
        if original_node_group is not None and original_node_group.users == 0:
            bpy.data.node_groups.remove(original_node_group)

        for o in created:
            o.select_set(True)
        context.view_layer.objects.active = created[-1]

        self.report(
            {'INFO'},
            f"Separated into {len(created)} objects across {len(all_floor_indices)} floor(s) "
            f"(rooms + one combined corridor object per floor, plus one combined ceiling "
            f"object per floor wherever Add Ceiling added any)."
        )
        return {'FINISHED'}


class OBJECT_OT_FreezeForTextureWork(bpy.types.Operator):
    """Renames every currently-generated object (Blueprint, Walls, Stairs,
    Doors, Torches, Decoration, Lights) out of the fixed-name pattern
    every Step operator's own _remove_objects_by_prefix matches against,
    and moves them into a dedicated new collection -- so the next
    Generate click (any step) builds a fresh set under the normal names
    with zero risk of touching this frozen one, leaving it safe for
    hand-applied materials/textures to survive across regenerations.

    Deliberately a rename, not a duplicate: no new mesh/material
    datablocks are created, so freezing a large level costs nothing
    beyond a handful of string renames and one new collection. A future
    generation's independence from the frozen set falls out of the rename
    alone -- every Step operator only ever looks up/deletes objects by
    matching a FIXED name (BLUEPRINT_OBJECT_NAME etc.) via
    _objects_matching_prefix's startswith(base_name + "_") check, which
    only ever looks at the FRONT of an object's name. The frozen tag below
    is therefore PREPENDED, never appended: a Per Floor/Per Stair grouped
    object already has a name like "Procedural_Level_Stairs_Floor2_02",
    and appending anything at the end can never stop a name that already
    started with a tracked base_name from matching again on the next
    regeneration -- silently deleting the "frozen" object right along with
    a fresh batch, exactly the failure this operator exists to prevent.
    Only prepending changes what the name STARTS WITH, removing it from
    every base_name's prefix match at once, for every grouping mode.
    This also makes the operator itself trivially safe to run twice:
    with nothing left to find under the fixed names after a freeze,
    running it again immediately (with nothing regenerated in between)
    just reports "nothing to freeze" rather than double-processing or
    erroring.

    The exact seed + every wfc_* setting behind this generation (already
    tracked in scene.wfc_debug_params by every Step operator, see
    _update_debug_snapshot) is copied onto the new collection as a custom
    property -- scene.wfc_debug_params itself gets overwritten by the
    NEXT generation, so without this copy a frozen set's own provenance
    (exactly what settings produced it) would be lost the moment you
    generate again."""
    bl_idname = "object.freeze_level_for_texture_work"
    bl_label = "Freeze for Texture Work"
    bl_description = (
        "Rename the current Blueprint/Walls/Stairs/Doors/Props out of the way so the next "
        "Generate click can't touch them -- safe to hand-apply materials/textures afterward"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene

        base_names = (
            BLUEPRINT_OBJECT_NAME, ROUND_FLOOR_OBJECT_NAME, WALLS_OBJECT_NAME, WALLS_ROUND_OBJECT_NAME,
            STAIRS_OBJECT_NAME, DOORS_OBJECT_NAME, DOORS_ROUND_OBJECT_NAME, PROPS_TORCH_OBJECT_NAME,
            PROPS_DECORATION_OBJECT_NAME, PROPS_LIGHT_NAME_PREFIX,
        )
        targets = []
        for base_name in base_names:
            targets.extend(_objects_matching_prefix(base_name))

        if not targets:
            self.report(
                {'ERROR'},
                "Nothing to freeze -- no Blueprint/Walls/Stairs/Doors/Props objects found under "
                "their normal names (already frozen, or nothing generated yet)."
            )
            return {'CANCELLED'}

        # One consistent label for this whole freeze -- disambiguated
        # against a PREVIOUS freeze at the same seed (e.g. regenerating at
        # an unchanged seed to try different downstream settings, then
        # freezing again) by bumping a trailing counter until the
        # collection name is free, rather than letting Blender's own
        # automatic ".001" collision suffix land on individual objects
        # inconsistently.
        label = f"Seed{scene.wfc_seed}"
        attempt = 1
        collection_name = f"{FROZEN_COLLECTION_PREFIX} - {label}"
        while bpy.data.collections.get(collection_name) is not None:
            attempt += 1
            collection_name = f"{FROZEN_COLLECTION_PREFIX} - {label} ({attempt})"
        tag = f"Frozen_{label}_" if attempt == 1 else f"Frozen_{label}_{attempt}_"

        frozen_collection = bpy.data.collections.new(collection_name)
        context.collection.children.link(frozen_collection)
        if scene.wfc_debug_params:
            frozen_collection["debug_params"] = scene.wfc_debug_params

        for obj in targets:
            # PREPENDED, never appended: an object using Per Floor/Per
            # Stair grouping already has a name like
            # "Procedural_Level_Stairs_Floor2_02" -- _objects_matching_
            # prefix matches on startswith(base_name + "_"), which only
            # looks at the FRONT of the string, so appending anything at
            # the end can never stop a name that already started with a
            # tracked base_name from matching again. Only changing what
            # the name STARTS WITH actually removes it from every future
            # base_name's prefix match, for every grouping mode at once.
            obj.name = tag + obj.name
            # Mesh/Light DATA keeps its own separate name -- renaming only
            # the object (above) would leave a frozen object's underlying
            # data-block still sitting on the exact name the next
            # regeneration tries to create a fresh one under, silently
            # bumping the new one to a numeric ".001" suffix instead.
            # Confirmed directly: every object type this operator touches
            # (Blueprint/Walls/Stairs/Doors/Door Panels/Round variants)
            # drifted this way after a single freeze+regenerate cycle, and
            # it compounds with every additional freeze. Guarded against
            # double-tagging in case two frozen objects ever share one
            # data-block (not currently possible given how every mesh here
            # is built fresh per-object, but cheap insurance).
            if obj.data is not None and not obj.data.name.startswith(tag):
                obj.data.name = tag + obj.data.name
            for coll in list(obj.users_collection):
                coll.objects.unlink(obj)
            frozen_collection.objects.link(obj)

        self.report(
            {'INFO'},
            f"Froze {len(targets)} object(s) into collection '{collection_name}' -- safe to "
            f"apply materials/textures now; the next Generate click won't touch them."
        )
        return {'FINISHED'}


def _gltf_export_targets(base_names, include_lights):
    """Every object a glTF export should include for the given set of
    base names, plus Lights when include_lights -- via the same
    _objects_matching_prefix helper OBJECT_OT_FreezeForTextureWork
    already uses, so every caller's notion of "which objects" can never
    drift apart, regardless of Per Floor/Per Stair grouping mode.
    Shared by both Export Level and Export Collision Mesh."""
    targets = []
    for base_name in base_names:
        targets.extend(_objects_matching_prefix(base_name))
    if include_lights:
        targets.extend(_objects_matching_prefix(PROPS_LIGHT_NAME_PREFIX))
        targets.extend(_objects_matching_prefix(TOWER_LIGHT_PREFIX))
    return targets


def _run_gltf_export(context, filepath, targets, include_lights):
    """Shared plumbing for both export operators: fixes filepath's
    extension to match Binary (.glb) vs separate .gltf, selects exactly
    `targets`, and calls Blender's own export_scene.gltf with
    use_selection + export_apply so live modifiers (the Blueprint's GN
    graph, Walls' optional Round Corners Bevel) bake into real exported
    geometry instead of their un-evaluated base mesh. Returns the
    (possibly extension-corrected) filepath actually written."""
    scene = context.scene
    export_format = 'GLB' if scene.wfc_export_binary else 'GLTF_SEPARATE'
    desired_ext = '.glb' if export_format == 'GLB' else '.gltf'
    stem, ext = os.path.splitext(filepath)
    if ext.lower() != desired_ext:
        filepath = stem + desired_ext

    bpy.ops.object.select_all(action='DESELECT')
    for obj in targets:
        obj.select_set(True)
    context.view_layer.objects.active = targets[0]

    bpy.ops.export_scene.gltf(
        filepath=filepath,
        export_format=export_format,
        use_selection=True,
        export_apply=True,
        export_lights=include_lights,
    )
    return filepath


class OBJECT_OT_ExportLevelGLTF(bpy.types.Operator, ExportHelper):
    """Selects every currently-generated object (Blueprint, Walls, Stairs,
    Doors, Torches, Decoration, and optionally Lights) and hands them to
    Blender's own bpy.ops.export_scene.gltf -- see _gltf_export_targets/
    _run_gltf_export. glTF's own exporter handles the Blender-Z-up ->
    glTF-Y-up axis conversion and Principled BSDF -> PBR material mapping
    itself -- no addon-side geometry or material translation needed here
    at all."""
    bl_idname = "object.export_level_gltf"
    bl_label = "Export Level (glTF/GLB)"
    bl_description = "Export every generated Blueprint/Walls/Stairs/Doors/Props object to glTF/GLB"
    bl_options = {'REGISTER'}

    filename_ext = ".glb"
    filter_glob: StringProperty(default="*.glb;*.gltf", options={'HIDDEN'})

    def execute(self, context):
        scene = context.scene
        base_names = (
            BLUEPRINT_OBJECT_NAME, ROUND_FLOOR_OBJECT_NAME, WALLS_OBJECT_NAME, WALLS_ROUND_OBJECT_NAME,
            STAIRS_OBJECT_NAME, DOORS_OBJECT_NAME, DOORS_ROUND_OBJECT_NAME, PROPS_TORCH_OBJECT_NAME,
            PROPS_DECORATION_OBJECT_NAME, TOWER_OBJECT_NAME, CASTLE_OBJECT_NAME, INTERIOR_PROPS_OBJECT_NAME,
            HALL_PROPS_OBJECT_NAME,
        )
        targets = _gltf_export_targets(base_names, scene.wfc_export_include_lights)

        if not targets:
            self.report(
                {'ERROR'},
                "Nothing to export -- no Blueprint/Walls/Stairs/Doors/Props objects found under "
                "their normal names. Generate a level first (Step 1)."
            )
            return {'CANCELLED'}

        if not hasattr(bpy.ops.export_scene, "gltf"):
            self.report(
                {'ERROR'},
                "glTF exporter isn't available -- enable Import-Export: glTF 2.0 in "
                "Preferences > Add-ons."
            )
            return {'CANCELLED'}

        filepath = _run_gltf_export(context, self.filepath, targets, scene.wfc_export_include_lights)

        light_count = len(_objects_matching_prefix(PROPS_LIGHT_NAME_PREFIX)) if scene.wfc_export_include_lights else 0
        self.report(
            {'INFO'},
            f"Exported {len(targets)} object(s) ({light_count} light(s)) to '{filepath}'."
        )
        return {'FINISHED'}


class OBJECT_OT_ExportLevelCollisionGLTF(bpy.types.Operator, ExportHelper):
    """Exports a filtered subset of the SAME already-built, already-
    verified objects OBJECT_OT_ExportLevelGLTF exports -- just Blueprint
    (floor) + Walls + Stairs, deliberately excluding Doors, Torches,
    Decoration, and Lights, so the result is suitable to assign as a
    level's collision geometry in an engine: Doors are a walk-through
    frame overlaid on an already-open gap (see _build_wall_mesh's
    is_exposed, which never places a wall box between two walkable
    cells), so leaving them out doesn't reopen anything -- it just avoids
    the door posts themselves becoming a minor physical snag at every
    doorway, matching the doorway's own "walk-through by design" intent.
    Torches/Decoration are cosmetic and shouldn't block movement; Lights
    obviously don't belong in a collision mesh.

    Deliberately NOT a freshly-built simplified/merged mesh -- there's no
    existing floor-region box-merging code in this file (a materially
    harder 2D problem than _build_wall_mesh's own 1D per-line wall run-
    merge), and re-exporting the already-verified visual meshes carries
    zero new geometry-correctness risk for what is, for static level
    architecture, already completely standard engine practice (Unity
    MeshCollider / Godot ConcavePolygonShape3D / Unreal per-poly static
    collision all commonly use the real level mesh directly)."""
    bl_idname = "object.export_level_collision_gltf"
    bl_label = "Export Collision Mesh (glTF/GLB)"
    bl_description = (
        "Export Floor + Walls + Stairs only (no Doors/Torches/Decoration/Lights) -- suitable to "
        "assign as a level's collision geometry in a game engine"
    )
    bl_options = {'REGISTER'}

    filename_ext = ".glb"
    filter_glob: StringProperty(default="*.glb;*.gltf", options={'HIDDEN'})

    def invoke(self, context, event):
        # Suggest a distinct default filename from the main Export Level
        # button -- without this, both buttons would default to
        # suggesting the exact same name (ExportHelper's own default is
        # just the current .blend's name + filename_ext), a real
        # accidental-overwrite footgun since a user is likely to click
        # both in the same session.
        if not self.filepath:
            blend_filepath = context.blend_data.filepath
            stem = os.path.splitext(blend_filepath)[0] if blend_filepath else "untitled"
            self.filepath = stem + "_collision" + self.filename_ext
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        base_names = (
            BLUEPRINT_OBJECT_NAME, WALLS_OBJECT_NAME, WALLS_ROUND_OBJECT_NAME, STAIRS_OBJECT_NAME,
        )
        targets = _gltf_export_targets(base_names, include_lights=False)

        if not targets:
            self.report(
                {'ERROR'},
                "Nothing to export -- no Blueprint/Walls/Stairs objects found under their normal "
                "names. Generate a level first (Step 1)."
            )
            return {'CANCELLED'}

        if not hasattr(bpy.ops.export_scene, "gltf"):
            self.report(
                {'ERROR'},
                "glTF exporter isn't available -- enable Import-Export: glTF 2.0 in "
                "Preferences > Add-ons."
            )
            return {'CANCELLED'}

        filepath = _run_gltf_export(context, self.filepath, targets, include_lights=False)

        self.report(
            {'INFO'},
            f"Exported {len(targets)} collision object(s) (Floor + Walls + Stairs only) to "
            f"'{filepath}'."
        )
        return {'FINISHED'}


def _add_planar_uv_map(mesh, uv_tile_size=1.0):
    """Every baked-mesh builder below (walls/doors/stairs/ramps/torches/
    decoration) builds its own geometry directly via from_pydata(), which
    never carries UV data -- same gap the Blueprint's GN graph and
    Separate by Floor/Room's _mesh_from_faces() had. Used to be patched
    with a flat constant (0.5, 0.5) UV on every corner: fine for a Simple
    Viewport Colors swatch (a single flat color across the whole image, so
    the actual UV value never mattered), but it meant a REAL tiling
    texture -- a trim sheet, a tileable brick/rock material -- sampled one
    single pixel across an entire wall run instead of repeating across it.

    This is real box mapping instead: each quad projects onto whichever of
    the XY/XZ/YZ planes its face normal is most aligned with, using the
    vertex's own world position -- already in meters, e.g.
    _build_wall_mesh's `x * tile_size` -- divided by uv_tile_size.
    uv_tile_size is meters-per-UV-tile (how large the artist's texture is
    meant to read in-world); 1.0 means "one texture tile per meter," the
    common trim-sheet/tiling-texture convention. Solid Shading's "Texture"
    color mode (a separate, simpler display path from "Material" that
    needs a real UV map and has no Generated-coordinates fallback the way
    EEVEE does) reads this the same as it read the old flat placeholder --
    nothing about that gap changes, only what the UV coordinates actually
    encode.

    Every box this file builds is axis-aligned in the space it's finally
    placed in EXCEPT one: _build_decoration_mesh's CRATE prop, rotated by
    an arbitrary `random.uniform(0.0, 2*pi)` angle (stairs/ramps also
    rotate their local geometry, but only by the four cardinal
    STAIR_EXIT_ROTATION values -- 0/90/180/270 degrees -- which stay
    axis-aligned in world space). Box mapping still produces a valid,
    fully-covered UV for a freely-rotated crate (picking the best-fit
    plane per face never fails), just with a slight per-face shear/stretch
    proportional to how far that face's real orientation has drifted from
    the projection axes -- imperceptible for a small placeholder prop, but
    worth knowing about before assuming every face here reads texture
    seams perfectly square."""
    uv_layer = mesh.uv_layers.new(name="UVMap")
    inv_scale = 1.0 / uv_tile_size if uv_tile_size else 1.0
    for poly in mesh.polygons:
        normal = poly.normal
        ax, ay, az = abs(normal.x), abs(normal.y), abs(normal.z)
        if az >= ax and az >= ay:
            axis_a, axis_b = 0, 1  # top/bottom-facing -- project onto XY
        elif ay >= ax:
            axis_a, axis_b = 0, 2  # front/back-facing -- project onto XZ
        else:
            axis_a, axis_b = 1, 2  # left/right-facing -- project onto YZ
        for loop_index in poly.loop_indices:
            co = mesh.vertices[mesh.loops[loop_index].vertex_index].co
            uv_layer.data[loop_index].uv = (co[axis_a] * inv_scale, co[axis_b] * inv_scale)


def _add_viewport_color_attribute(mesh):
    """Fills a "viewport_color" Color Attribute (FLOAT_COLOR, per-corner)
    from each face's already-resolved material's diffuse_color, and marks
    it active. Solid Shading's "Attribute" color mode reads this directly --
    unlike "Material" mode it needs no diffuse_color-carrying material at
    all beyond what we already copy here, and unlike "Texture" mode it
    needs no UV map either, so it's immune to both classes of gap this
    addon hit before (UV data missing entirely, and mesh.materials.clear()
    silently resetting material_index -- see Separate by Floor/Room's
    fix). Call this only after every material the mesh needs is already
    appended to mesh.materials and each polygon's material_index is set,
    so the color read here is correct."""
    fallback = (0.8, 0.8, 0.8, 1.0)
    color_layer = mesh.color_attributes.new(name="viewport_color", type='FLOAT_COLOR', domain='CORNER')
    for poly in mesh.polygons:
        mat = mesh.materials[poly.material_index] if 0 <= poly.material_index < len(mesh.materials) else None
        color = tuple(mat.diffuse_color) if mat is not None else fallback
        for loop_index in poly.loop_indices:
            color_layer.data[loop_index].color = color
    mesh.color_attributes.active_color_index = len(mesh.color_attributes) - 1


def _add_corner_rounding_modifier(obj, radius):
    """Adds a live Bevel modifier to `obj`, angle-limited so it only
    rounds genuinely sharp edges (real ~90-degree wall corners, and --
    if Cap Top is on -- the top rim where a wall's side meets its cap)
    rather than the near-flat edges running along a straight wall run.

    Deliberately a Bevel modifier and not hand-derived fillet geometry:
    _build_wall_mesh emits one merged box per straight run (see its own
    docstring), so a real per-corner quarter-cylinder fillet would need
    each run's two endpoints classified as an actual building corner
    (another run starting at the identical point) vs. a doorway/opening
    jamb (the wall just stops, nothing perpendicular meets it there) --
    real, doable, but enough extra geometry logic to be its own follow-up,
    not blindly added on top of an already-working mesh builder without a
    real Blender session to verify it against. The Bevel modifier is a
    long-stable, ordinary mesh modifier (not Geometry Nodes -- this file's
    documented reason for baking walls/stairs as plain Python meshes in
    the first place was specifically GN's uncertain live-API behavior, a
    risk this doesn't carry), so it's the lower-risk way to ship real
    rounded corners today.

    Honest limitation, not a bug: 'ANGLE' limit mode rounds every sharp
    edge uniformly, so it also rounds doorway/opening jambs (a wall run
    simply ending in open air) alongside true building corners, and the
    top rim too whenever Cap Top is on -- there's no way to tell those
    apart from edge angle alone (a jamb and a corner both meet at ~90
    degrees). All of that reads as a reasonable, if slightly broader than
    strictly "room corners," softened look; a future WEIGHT-based version
    that marks only genuine corner edges (see the class docstring's
    Ideas-for-future-work entry) would need each edge's exact bevel-weight
    attribute name/API verified live first -- Blender 4.0 moved Bevel
    Weight onto the generic attribute system, another exact detail not
    worth guessing blind.

    Boundary (single-face) edges -- every wall box's dropped bottom face,
    see add_box's own comment -- have no second face to measure an angle
    against, so 'ANGLE' limit mode leaves them alone by construction; no
    special-casing needed here for that.

    `radius` is the Bevel modifier's Width; Blender's own Clamp Overlap
    (left at its default True) already prevents an oversized radius from
    self-intersecting on a thin wall, so this doesn't need to duplicate
    that clamp against wall_thickness itself."""
    mod = obj.modifiers.new(name="Corner Rounding", type='BEVEL')
    _set_prop(mod, 'width', radius)
    _set_prop(mod, 'segments', 6)
    _set_prop(mod, 'limit_method', 'ANGLE')
    _set_prop(mod, 'angle_limit', math.radians(35.0))
    _set_prop(mod, 'harden_normals', True)
    return mod


def _build_round_room_floor_mesh(solver, tile_size, fine_level_height, room_shape_sides, epsilon=0.003):
    """A single flat n-gon face per Round room, sitting a hair above the
    existing per-tile floor cubes the Blueprint's own Geometry Nodes
    pipeline still instances underneath -- deliberately left untouched
    (see DEVELOPMENT.md's note on why touching the Blueprint's own point
    cloud/GN graph is the riskier path; every OTHER step -- Doors,
    Torches, Decoration, floor-by-story separation -- still reads that
    point cloud as its ground truth, unmodified). Purely a visual
    topper, not new collision geometry: one face, no sides/bottom.

    The n-gon's radius (rx=rw/2, ry=rl/2, the room's FULL bounding-box
    ellipse) is always larger than the <=0.8-threshold ellipse
    _carve_room actually carves cells with, so it fully covers every
    carved tile underneath with no visible gap at the edge -- the same
    relationship BrickSpitter's own disc already relies on.

    Returns (verts, faces, material_indices, room_ids_in_order) --
    room_ids_in_order[k] is which solver.rooms index produced the k-th
    face/material slot, so the caller can build a matching per-face
    material list (room_materials[room_ids_in_order[k]])."""
    verts, faces, material_indices = [], [], []
    room_ids_in_order = []
    for room_id, room in enumerate(solver.rooms):
        if solver.room_shapes.get(room_id) != 'ROUND':
            continue
        cells = solver.room_cells.get(room_id)
        if not cells:
            continue
        # The room's own carved cell nearest its true centroid -- not the
        # naive box center, which isn't guaranteed to have survived
        # _largest_connected_group's cleanup -- so the z_offset lookup
        # below always reads a cell that's actually part of this room.
        cx_cell = sum(c[0] for c in cells) / len(cells)
        cy_cell = sum(c[1] for c in cells) / len(cells)
        nearest = min(cells, key=lambda c: (c[0] - cx_cell) ** 2 + (c[1] - cy_cell) ** 2)
        z_offset = solver.cell_z_offset[nearest[0]][nearest[1]][room['z']]
        world_z = room['z'] * fine_level_height + z_offset + epsilon

        x, y, rw, rl = room['x'], room['y'], room['w'], room['l']
        # A grid cell xi is world-positioned/centered at xi*tile_size (see
        # _build_wall_mesh's left/right = (x -+ 0.5)*tile_size), so the rw
        # cells x..x+rw-1 have their TRUE world-space center at
        # (x + (rw-1)/2.0)*tile_size -- matching _carve_room's own
        # grid-space ellipse-membership test exactly (its cx is the same
        # (rw-1)/2.0 average). The previous +rw/2.0 (no -1) put the world
        # center half a tile off in both X and Y, which is small enough to
        # go unnoticed most of the time but is a real, confirmed bug: it
        # can leave a genuinely-carved corner cell just outside the disc's
        # rim on one side while the ring/disc overreaches empty space by a
        # whole half-tile on the opposite side -- the latter is what let a
        # legitimately-placed stairwell (that never violates the room's
        # own reserved rectangle) still get clipped by the ring.
        cx = (x + (rw - 1) / 2.0) * tile_size
        cy = (y + (rl - 1) / 2.0) * tile_size
        rx = (rw / 2.0) * tile_size
        ry = (rl / 2.0) * tile_size

        i = len(verts)
        for s in range(room_shape_sides):
            angle = 2.0 * math.pi * s / room_shape_sides
            verts.append((cx + rx * math.cos(angle), cy + ry * math.sin(angle), world_z))
        faces.append(tuple(i + s for s in range(room_shape_sides)))
        material_indices.append(len(room_ids_in_order))
        room_ids_in_order.append(room_id)
    return verts, faces, material_indices, room_ids_in_order


def _room_shape_sides_wall_positions(cx, cy, rx, ry, sides):
    return [
        (cx + rx * math.cos(2.0 * math.pi * s / sides), cy + ry * math.sin(2.0 * math.pi * s / sides))
        for s in range(sides)
    ]


ROUND_RING_INSET = 0.1  # metres the masonry ring (incl. its proud stones/frames) stays inside the room's rim


def _round_room_opening_ranges(room, room_id, room_id_grid, walkable, tile_size, min_width_m=1.4):
    """Parameter-angle ranges [(t0, t1), ...] (t1 > t0, possibly beyond 2*pi
    after merging) where a Round room's rim ellipse passes through a walkable
    cell that is NOT one of the room's own floor cells -- i.e. every place a
    corridor or a neighbouring room actually meets the ring, including the
    dead corner of the bounding rectangle a corridor may legitimately cross
    (see _build_round_room_walls_mesh for why that happens). The ring is
    sampled densely and tested against the cell grid (centered convention:
    cell i spans (i-0.5)..(i+0.5) tiles) with a small pad so a corridor that
    only touches the rim is still opened. Each run is widened to at least
    min_width_m (arc length) and runs closer than a frame's width are
    merged, so openings never overlap."""
    x, y, rw, rl, z = room['x'], room['y'], room['w'], room['l'], room['z']
    cx, cy = (x + (rw - 1) / 2.0) * tile_size, (y + (rl - 1) / 2.0) * tile_size
    rx, ry = (rw / 2.0) * tile_size - ROUND_RING_INSET, (rl / 2.0) * tile_size - ROUND_RING_INSET
    n = 1440
    pad = 0.05
    marked = [False] * n
    for k in range(n):
        t = TOWER_TAU * k / n
        px, py = cx + rx * math.cos(t), cy + ry * math.sin(t)
        for ox, oy in ((0.0, 0.0), (pad, 0.0), (-pad, 0.0), (0.0, pad), (0.0, -pad)):
            cell = (math.floor((px + ox) / tile_size + 0.5), math.floor((py + oy) / tile_size + 0.5), z)
            if cell in walkable and room_id_grid.get(cell) != room_id:
                marked[k] = True
                break
            if room_id_grid.get(cell) == room_id:
                # the ring crosses one of the room's own cells: open it if the half of
                # that cell nearest the ring leads straight out into a walkable neighbour
                lx, ly = (px + ox) - cell[0] * tile_size, (py + oy) - cell[1] * tile_size
                for ddx, ddy in HORIZONTAL_NEIGHBORS:
                    nb = (cell[0] + ddx, cell[1] + ddy, z)
                    if nb in walkable and room_id_grid.get(nb) != room_id and lx * ddx + ly * ddy >= 0.0:
                        marked[k] = True
                        break
                if marked[k]:
                    break
    if not any(marked):
        return []
    if all(marked):
        return [(0.0, TOWER_TAU)]
    start = next(k for k in range(n) if marked[k] and not marked[k - 1])
    runs, k, count = [], start, 0
    while count < n:
        if marked[k % n]:
            j = k
            while marked[(j + 1) % n] and (j + 1 - k) < n:
                j += 1
            runs.append([TOWER_TAU * k / n, TOWER_TAU * (j + 1) / n])
            count += j + 1 - k
            k = j + 1
        else:
            k += 1
            count += 1
    # perimeter (Ramanujan) -> metres per radian, to widen narrow runs
    per = math.pi * (3 * (rx + ry) - math.sqrt((3 * rx + ry) * (rx + 3 * ry)))
    m_per_rad = per / TOWER_TAU
    gap_merge = 1.0 / m_per_rad
    min_w = min_width_m / m_per_rad
    for r in runs:
        w = r[1] - r[0]
        if w < min_w:
            mid = (r[0] + r[1]) / 2.0
            r[0], r[1] = mid - min_w / 2.0, mid + min_w / 2.0
    runs.sort()
    merged = [runs[0]]
    for r in runs[1:]:
        if r[0] - merged[-1][1] < gap_merge:
            merged[-1][1] = max(merged[-1][1], r[1])
        else:
            merged.append(r)
    if len(merged) > 1 and merged[0][0] + TOWER_TAU - merged[-1][1] < gap_merge:
        merged[0][0] = merged[-1][0] - TOWER_TAU
        merged.pop()
    return [(a, b) for a, b in merged]


def _round_ring_inner_ellipse(room, tile_size, wall_thickness):
    """(cx, cy, rx, ry) of the INNER skin of a Round room's masonry ring --
    exactly the ellipse _build_round_room_masonry_mesh builds, so torches and
    props can sit against the wall instead of floating in the room."""
    x, y, rw, rl = room['x'], room['y'], room['w'], room['l']
    cx, cy = (x + (rw - 1) / 2.0) * tile_size, (y + (rl - 1) / 2.0) * tile_size
    rx, ry = (rw / 2.0) * tile_size - ROUND_RING_INSET, (rl / 2.0) * tile_size - ROUND_RING_INSET
    R = max(rx, ry)
    wall_c = min(wall_thickness, R * 0.4)
    return cx, cy, rx / R * (R - wall_c), ry / R * (R - wall_c)


def _ring_torch_mount(cell, geo, ranges, tile_size):
    """Where a torch for `cell` hangs on a Round room's ring: (wall_x, wall_y,
    dir_x, dir_y) with dir pointing from the room toward the wall, or None when
    that stretch of wall is a doorway."""
    cx, cy, rx, ry = geo
    px, py = cell[0] * tile_size, cell[1] * tile_size
    t = math.atan2((py - cy) / ry, (px - cx) / rx)
    for t0, t1 in ranges:
        if ((t - t0 + 0.14) % TOWER_TAU) <= (t1 - t0) + 0.28:
            return None
    nx, ny = math.cos(t) / rx, math.sin(t) / ry
    ln = math.hypot(nx, ny)
    return cx + rx * math.cos(t), cy + ry * math.sin(t), nx / ln, ny / ln


def _prop_inside_ring(kind, rot, px, py, geo, tile_size, margin=0.97):
    """True when a prop's rotated footprint stays inside a Round room's inner ellipse."""
    cx, cy, rx, ry = geo
    xmin, xmax, ymin, ymax = _prop_local_bounds(kind, tile_size)
    c, s_ = math.cos(rot), math.sin(rot)
    for lx in (xmin, xmax):
        for ly in (ymin, ymax):
            wx, wy = px + lx * c - ly * s_, py + lx * s_ + ly * c
            if ((wx - cx) / rx) ** 2 + ((wy - cy) / ry) ** 2 > margin * margin:
                return False
    return True


def _build_round_room_masonry_mesh(
    room_meta, room_id_grid, walkable_cells, tile_size, fine_level_height, wall_height,
    wall_thickness, z_offsets, door_style, door_height, cap_top, seed, name, ruin=0.0, room_colors=False,
    tint_map=None,
):
    """Round room walls as brick-textured masonry (the Round Tower's shell
    method, see _TowerBuilder) instead of the n-gon ring of plain boxes: a
    smooth textured ring around the room's rim ellipse, real arched/pointed/
    flat openings cut exactly where a corridor or room meets the ring (see
    _round_room_opening_ranges), dressed-stone frames, scattered proud
    stones, and an optional flat stone cap. The shell is built as a circle
    and stretched to the room's ellipse (a positive-determinant map, so
    face orientation survives); the outer skin sits ROUND_RING_INSET inside
    the rim and the wall grows inward, so the ring and everything proud of
    it stays inside the room's reserved rectangle.
    Material slots: 0 = brick, 1 = dressed stone."""
    walkable = set(walkable_cells)
    big = _TowerMesh()
    kind_for_style = {'FLAT': 'rect', 'ROUND': 'arch', 'POINTED': 'pointed'}
    for room_id, room in enumerate(room_meta):
        if room['shape'] != 'ROUND':
            continue
        x, y, rw, rl, z = room['x'], room['y'], room['w'], room['l'], room['z']
        cells_here = [c for c, rid in room_id_grid.items() if rid == room_id and c[2] == z]
        if not cells_here:
            continue
        cxc = sum(c[0] for c in cells_here) / len(cells_here)
        cyc = sum(c[1] for c in cells_here) / len(cells_here)
        nearest = min(cells_here, key=lambda c: (c[0] - cxc) ** 2 + (c[1] - cyc) ** 2)
        cx, cy = (x + (rw - 1) / 2.0) * tile_size, (y + (rl - 1) / 2.0) * tile_size
        # Inset: the proud stones and frames stand ~0.06 m outside the shell, and a ring exactly ON
        # the rim would push them into the neighbouring cell (a stair run or corridor wall right
        # outside the room's reserved rectangle). Keeping the whole ring inside it removes that.
        rx, ry = (rw / 2.0) * tile_size - ROUND_RING_INSET, (rl / 2.0) * tile_size - ROUND_RING_INSET
        R = max(rx, ry)
        wall_c = min(wall_thickness, R * 0.4)
        if R - wall_c < 0.5:
            continue
        sx, sy = rx / R, ry / R
        per = math.pi * (3 * (rx + ry) - math.sqrt((3 * rx + ry) * (rx + 3 * ry)))
        ranges = _round_room_opening_ranges(room, room_id, room_id_grid, walkable, tile_size)
        # seam in the middle of the largest stretch of solid wall
        seam = 0.0
        if ranges:
            ordered = sorted(ranges)
            best = -1.0
            for i, (a0, b0) in enumerate(ordered):
                nxt = ordered[(i + 1) % len(ordered)][0] + (TOWER_TAU if i + 1 == len(ordered) else 0.0)
                if nxt - b0 > best:
                    best, seam = nxt - b0, (b0 + nxt) / 2.0
        if len(ranges) == 1 and ranges[0][1] - ranges[0][0] >= TOWER_TAU - 1e-6:
            continue  # ring would be nothing but an opening
        stones = int(per * wall_height * 0.35)
        builder = _TowerBuilder(
            R, wall_height, wall_c, battlements=False, detail='MEDIUM', seed=seed + room_id,
            plinth=False, cap_top=cap_top, brick_cols=max(1, round(per / TOWER_TILE_W)),
            stones=stones, seam=seam, ruin=ruin, rubble_outside=False,
        )
        skip_room = False
        for t0, t1 in ranges:
            placed = False
            tries = [(kind_for_style.get(door_style, 'rect'), door_height),
                     ('rect', min(door_height, builder.Hs - 0.5)), ('gap', 0.0)]
            if builder.Hs < 1.4:
                tries = [('gap', 0.0)]
            for kind, h in tries:
                if builder.add_opening_range(t0, t1, 0.0, h, kind):
                    placed = True
                    break
            if not placed:
                skip_room = True  # opening wider than the ring allows: leave this room's wall out, never seal a corridor
                break
        if skip_room:
            continue
        builder.geometry(ground=False)
        z0 = z * fine_level_height + z_offsets.get(nearest, 0.0)
        mat_map = {0: (tint_map or {}).get(room_id, brick_tint_slot(room_id)), 1: len(BRICK_TINTS)} if room_colors else None
        big.append(builder.mb, rot=seam, sx=sx, sy=sy, offset=(cx, cy, z0), mat_map=mat_map)
    return big.to_mesh(name)


def _build_round_room_walls_mesh(
    room_meta, room_id_grid, walkable_cells, tile_size, fine_level_height, wall_height,
    wall_thickness, room_shape_sides, z_offsets, name,
):
    """A real perimeter ring for every Round room, hugging its actual
    n-gon rim -- one thin oriented wall segment per polygon edge, ported
    from BrickSpitter's own add_wall_segment/_build_round_room_walls_mesh
    (brickspitter.py). Rect rooms don't need this: their existing
    per-cell wall from _build_wall_mesh already traces their (already
    straight) boundary exactly.

    Skips whichever ring edge(s) sit where a corridor/doorway actually
    connects -- every one of this room's own cells that borders a
    walkable cell belonging to a DIFFERENT room (or no room at all) is a
    real doorway; its angle around the room's own ellipse (same
    parametrization the ring's vertices use) picks which edge to open,
    so the gap lines up with where the corridor actually meets the
    floor instead of sealing every room shut.

    room_meta: [{'x','y','w','l','z','shape'}, ...] as baked onto the
    Blueprint object (see OBJECT_OT_GenerateGameBlueprint). room_id_grid:
    {(x,y,z): room_id} read back from the Blueprint's own room_id point
    attribute. walkable_cells/z_offsets: same shape _build_wall_mesh
    itself already takes."""
    walkable = set(walkable_cells)
    half_t = wall_thickness / 2.0
    verts, faces, material_indices = [], [], []

    def add_wall_segment(x0, y0, x1, y1, z0, z1):
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length < 1e-9:
            return
        nx, ny = -dy / length * half_t, dx / length * half_t
        corners = ((x0 - nx, y0 - ny), (x1 - nx, y1 - ny), (x1 + nx, y1 + ny), (x0 + nx, y0 + ny))
        i = len(verts)
        verts.extend((cx, cy, z0) for cx, cy in corners)
        verts.extend((cx, cy, z1) for cx, cy in corners)
        faces.append((i + 4, i + 5, i + 6, i + 7))  # top
        faces.append((i + 5, i + 4, i + 0, i + 1))
        faces.append((i + 6, i + 5, i + 1, i + 2))
        faces.append((i + 7, i + 6, i + 2, i + 3))
        faces.append((i + 4, i + 7, i + 3, i + 0))
        material_indices.extend([0] * 5)

    for room_id, room in enumerate(room_meta):
        if room['shape'] != 'ROUND':
            continue
        x, y, rw, rl, z = room['x'], room['y'], room['w'], room['l'], room['z']
        # See _build_round_room_floor_mesh's matching comment: a grid cell
        # xi is world-centered at xi*tile_size, so the room's true
        # world-space center uses (rw-1)/2.0, matching _carve_room's own
        # grid-space ellipse test -- not +rw/2.0 (no -1), which is half a
        # tile off and was letting the ring clip things just outside the
        # room's actual reserved rectangle.
        cx, cy = (x + (rw - 1) / 2.0) * tile_size, (y + (rl - 1) / 2.0) * tile_size
        rx, ry = (rw / 2.0) * tile_size, (rl / 2.0) * tile_size

        room_cells_here = [c for c, rid in room_id_grid.items() if rid == room_id and c[2] == z]
        if not room_cells_here:
            continue
        # The room's own carved cell nearest its true (grid-space) centroid
        # -- not the naive box center, which isn't guaranteed to have
        # survived _largest_connected_group's cleanup -- so the z_offset
        # lookup below always reads a cell that's actually part of this room.
        centroid_x = sum(c[0] for c in room_cells_here) / len(room_cells_here)
        centroid_y = sum(c[1] for c in room_cells_here) / len(room_cells_here)
        nearest_cell = min(
            room_cells_here, key=lambda c: (c[0] - centroid_x) ** 2 + (c[1] - centroid_y) ** 2
        )

        open_edges = set()
        for (cellx, celly, cellz) in room_cells_here:
            exposed = False
            for dx, dy in HORIZONTAL_NEIGHBORS:
                neighbor = (cellx + dx, celly + dy, cellz)
                if neighbor in walkable and room_id_grid.get(neighbor) != room_id:
                    exposed = True
                    break
            if not exposed:
                continue
            px = (cellx + 0.5) * tile_size
            py = (celly + 0.5) * tile_size
            angle = math.atan2((py - cy) / ry, (px - cx) / rx) % (2.0 * math.pi)
            open_edges.add(int(angle / (2.0 * math.pi / room_shape_sides)) % room_shape_sides)

        # A Round room only carves cells inside its inscribed ellipse (see
        # _carve_room), leaving its own bounding-box corners TILE_AIR --
        # _room_fits now blocks a NEW room/stairwell from being placed
        # there, but a straight-line corridor (_carve_corridor, no
        # alternate routing, must never fail to connect) can still carve
        # through that "empty" corner on its way somewhere else. The loop
        # above never sees that cell (it's not one of this room's own
        # carved cells), so without this second pass the ring would seal
        # a real, walkable corridor behind a low wall the player would
        # have to jump rather than walk through. Any walkable cell
        # anywhere in the room's full rectangle that ISN'T this room's own
        # floor forces its ring edge open, regardless of 4-connected
        # adjacency to the carved ellipse.
        dead_corner_positions = _room_shape_sides_wall_positions(cx, cy, rx, ry, room_shape_sides)
        for cellx in range(x, x + rw):
            for celly in range(y, y + rl):
                cell = (cellx, celly, z)
                if room_id_grid.get(cell) == room_id or cell not in walkable:
                    continue
                px0, py0 = cellx * tile_size, celly * tile_size
                px1, py1 = px0 + tile_size, py0 + tile_size
                # A tile-sized cell can be wide relative to the room's own
                # radius (a small Round room's corner cell can span a large
                # angular slice) -- sampling only the cell's center angle
                # can land in a DIFFERENT bucket than the one its footprint
                # actually crosses, leaving a neighboring closed edge still
                # cutting through it (confirmed via a real repro). Sampling
                # all 4 corners and opening every bucket any of them falls
                # in is a safe over-approximation -- occasionally opens one
                # extra edge, never leaves a real collision.
                for px, py in ((px0, py0), (px1, py0), (px1, py1), (px0, py1)):
                    angle = math.atan2((py - cy) / ry, (px - cx) / rx) % (2.0 * math.pi)
                    open_edges.add(int(angle / (2.0 * math.pi / room_shape_sides)) % room_shape_sides)
                # The reverse size mismatch: on a MINIMUM-size (3x3) Round
                # room the radius can be small enough that a whole polygon
                # edge -- both its rim vertices -- lies entirely INSIDE one
                # grid cell's footprint, touching none of that cell's own
                # corners either (confirmed via the same real repro). Catch
                # that by opening both edges touching any rim vertex that
                # falls inside this cell's rectangle.
                for s in range(room_shape_sides):
                    vx, vy = dead_corner_positions[s]
                    if px0 <= vx <= px1 and py0 <= vy <= py1:
                        open_edges.add(s)
                        open_edges.add((s - 1) % room_shape_sides)

        z0 = z * fine_level_height + z_offsets.get(nearest_cell, 0.0)
        z1 = z0 + wall_height
        positions = _room_shape_sides_wall_positions(cx, cy, rx, ry, room_shape_sides)
        for s in range(room_shape_sides):
            if s in open_edges:
                continue
            x0, y0 = positions[s]
            x1, y1 = positions[(s + 1) % room_shape_sides]
            add_wall_segment(x0, y0, x1, y1, z0, z1)

    mesh_data = bpy.data.meshes.new(name + "_Mesh")
    mesh_data.from_pydata(verts, [], faces)
    mesh_data.update()
    for poly, mat_idx in zip(mesh_data.polygons, material_indices):
        poly.material_index = mat_idx
    return mesh_data


def _build_masonry_wall_mesh(
    walkable_cells, tile_size, level_height, wall_height, wall_thickness, z_offsets=None,
    forced_wall_edges=None, skip_cells=None, window_edges=None, window_width=1.0, window_sill=1.0,
    window_height=1.0, ruin=0.0, seed=1, name="Walls", room_ids=None, room_colors=False, tint_map=None,
):
    """Ordinary level walls (the exposed edges of rooms and corridors) as
    brick-textured masonry: every straight run of exposed edges becomes one
    _WallRunBuilder wall (smooth textured skins, dressed-stone caps, proud
    stones, stone frames around windows, optional ruin). Same run merging as
    _build_wall_mesh's merged path (a run ends where the exposed edge ends or
    the cell elevation changes). Corners: a run end that meets a perpendicular
    exposed edge is extended by half the thickness and left open (the two
    runs overlap and close the corner); any other end is a doorway jamb and
    gets an end cap. Returns (mesh, accepted_window_edges) -- a window whose
    opening the builder could not fit (too tall for the wall) is dropped, so
    the caller builds frames/glass only for the accepted ones. Material slots:
    0 brick, 1 dressed stone; with room_colors the slots are
    masonry_material_list(True): per-room brick tints (a run is split where
    the room changes, so a wall belongs to the room on its inner side) then stone."""
    walkable = set(walkable_cells)
    z_offsets = z_offsets or {}
    forced = forced_wall_edges or set()
    skip = skip_cells or set()
    window_edges = window_edges or set()
    room_ids = room_ids or {}
    n_tints = len(BRICK_TINTS)
    ht = wall_thickness / 2.0
    edges = []
    for cell in sorted(walkable):
        if cell in skip:
            continue
        x, y, z = cell
        for d in HORIZONTAL_NEIGHBORS:
            if (x + d[0], y + d[1], z) not in walkable or (cell, d) in forced:
                edges.append((cell, d))
    # which wall axes touch each corner point (in half-tile units)
    axes = {}
    for (x, y, z), (dx, dy) in edges:
        if dx != 0:
            for sy in (-1, 1):
                axes.setdefault((2 * x + dx, 2 * y + sy, z), set()).add('v')
        else:
            for sx in (-1, 1):
                axes.setdefault((2 * x + sx, 2 * y + dy, z), set()).add('h')
    # merge into runs
    lines = {}
    for (x, y, z), d in edges:
        key = ('h', y * 2 + d[1], d, z) if d[0] == 0 else ('v', x * 2 + d[0], d, z)
        lines.setdefault(key, []).append((x if d[0] == 0 else y, z_offsets.get((x, y, z), 0.0), (x, y, z)))
    big = _TowerMesh()
    accepted = set()
    seq = 0
    for key, items in lines.items():
        axis, line2, d, z = key
        items.sort()
        i = 0
        while i < len(items):
            j = i
            while (j + 1 < len(items) and items[j + 1][0] == items[j][0] + 1 and items[j + 1][1] == items[i][1]
                   and (not room_colors or room_ids.get(items[j + 1][2], -1) == room_ids.get(items[i][2], -1))):
                j += 1
            run = items[i:j + 1]
            i = j + 1
            p0, p1, off = run[0][0], run[-1][0], run[0][1]
            length = (p1 - p0 + 1) * tile_size
            theta = math.atan2(d[0], -d[1])  # local -y must point along d (outward)
            ux, uy = math.cos(theta), math.sin(theta)
            if axis == 'h':
                line = line2 * 0.5 * tile_size
                start = ((p0 - 0.5) * tile_size, line) if ux > 0 else ((p1 + 0.5) * tile_size, line)
                s_key = (2 * p0 - 1, line2, z) if ux > 0 else (2 * p1 + 1, line2, z)
                e_key = (2 * p1 + 1, line2, z) if ux > 0 else (2 * p0 - 1, line2, z)
                perp = 'v'
            else:
                line = line2 * 0.5 * tile_size
                start = (line, (p0 - 0.5) * tile_size) if uy > 0 else (line, (p1 + 0.5) * tile_size)
                s_key = (line2, 2 * p0 - 1, z) if uy > 0 else (line2, 2 * p1 + 1, z)
                e_key = (line2, 2 * p1 + 1, z) if uy > 0 else (line2, 2 * p0 - 1, z)
                perp = 'h'
            corner_s = perp in axes.get(s_key, ())
            corner_e = perp in axes.get(e_key, ())
            # At a corner the horizontal-axis run reaches half a thickness past the corner point (covering the
            # corner square) and the vertical-axis run stops half a thickness short (abutting the other's
            # skin), so no two caps ever overlap (coincident faces would also self-shadow in a renderer).
            sgn = 1.0 if axis == 'h' else -1.0
            ext_s = sgn * ht if corner_s else 0.0
            ext_e = sgn * ht if corner_e else 0.0
            wb = _WallRunBuilder(
                length + ext_s + ext_e, wall_height, wall_thickness, battlements=False, seed=seed + seq,
                stones=int(length * wall_height * 0.2), ruin=ruin, plinth=False, rubble=False,
                end_caps=(not corner_s, not corner_e),
            )
            seq += 1
            for _, _, cell in run:
                if (cell, d) in window_edges:
                    pos = (cell[0] if axis == 'h' else cell[1])
                    local = (pos - p0 + 0.5) * tile_size if (ux > 0 if axis == 'h' else uy > 0) else (p1 - pos + 0.5) * tile_size
                    w = min(window_width, tile_size - 0.2)
                    sill = max(0.0, min(window_sill, wall_height - 0.2))
                    top = min(sill + window_height, wall_height - 0.1)
                    if wb.add_opening(local + ext_s, w, sill, top - sill, 'rect'):
                        accepted.add((cell, d))
            wb.geometry()
            sx, sy = start[0] - ux * ext_s, start[1] - uy * ext_s
            rid_run = room_ids.get(run[0][2], -1)
            mat_map = {0: (tint_map or {}).get(rid_run, brick_tint_slot(rid_run)), 1: n_tints} if room_colors else None
            big.append(wb.mb, rot=theta, offset=(sx, sy, z * level_height + off), mat_map=mat_map)
    return big.to_mesh(name), accepted


def _build_wall_mesh(
    walkable_cells, tile_size, level_height, wall_height, wall_thickness, cap_top, name,
    organic_amount=0.0, z_offsets=None, forced_wall_edges=None, uv_tile_size=1.0, skip_cells=None,
    window_edges=None, window_width=1.0, window_sill=1.0, window_height=1.0,
):
    """Fully-baked wall geometry, computed in plain Python rather than a
    Geometry Nodes region-extrude (whose exact Selection/mode defaults proved
    too uncertain to get right blind, across two attempts, without a real
    Blender to test against). For every side of every walkable cell that
    borders a non-walkable cell -- i.e. every exposed edge of that level's
    silhouette -- this emits one solid box spanning that edge, wall_thickness
    deep (centered on the edge) and wall_height tall. Adjacent boxes along a
    straight run sit exactly edge-to-edge (though as separate, non-shared
    vertices), so the result reads as one continuous wall with automatic
    doorway-sized gaps wherever a corridor enters a room -- same visual
    result as a merged silhouette, far simpler to get right.

    Every stairwell is a fully enclosed room reserved identically on the
    level it starts on and the level above it (see
    WFC_Level_Solver._carve_stair_room), so the far end of a stair run is
    just another walkable cell inside that same room, never a boundary edge
    -- no special-case exemption needed here anymore.

    organic_amount (meters, 0 = off) jitters each wall segment's top height
    and thickness independently for a hand-built/crumbling look, purely
    cosmetic -- it never touches which cells get walled, so it can't affect
    connectivity or doorway placement.

    z_offsets (optional {(x,y,z): meters}) follows a cell's own continuous
    elevation offset (see WFC_Level_Solver._apply_continuous_elevation) --
    a wall box's z0 uses the WALKABLE cell it's attached to, so it rises
    with that cell's floor and never floats above or clips below it.

    forced_wall_edges (optional {((x,y,z), (ddx,ddy)), ...}) adds a wall on
    that specific cell+direction even when the neighbor IS walkable --
    Corridor Stairs' perpendicular sides (see
    WFC_Level_Solver._corridor_stair_fits) are only ever checked for a
    clear neighbor AT THE TIME that stairwell is placed; a corridor
    pathfound afterward can still end up running directly alongside one
    (residual ~7-10% of stair cells, see DEVELOPMENT.md), and a 1-wide
    Corridor Stairs run has no side walkway by design -- unlike a
    room-based stairwell, where that same neighbor cell IS the intended
    walkway and must stay open. The caller is responsible for only ever
    populating this for actual Corridor Stairs cells (Generate Level Walls
    only does when wfc_corridor_stairs is on), never room-based ones.

    skip_cells (optional set of (x,y,z)) -- cells that still count as
    walkable for is_exposed's neighbor test (so a Rect room right next to
    a Round one still gets a correct boundary wall against it), but never
    get their own box emitted. Used for Round rooms, which get a real
    perimeter ring instead (see _build_round_room_walls_mesh) -- their
    per-cell blocky wall would otherwise still render underneath it.

    window_edges (optional {((x,y,z), (ddx,ddy)), ...}, see
    _pick_window_edges) -- exposed edges that get a real rectangular
    opening (window_width wide, centered on the tile edge, sill at
    window_sill and window_height tall) instead of a solid box: two
    full-height piers plus a sill box below and a lintel box above, so the
    hole is genuine geometry (visible through, walkable-collision-correct).
    A window edge never takes part in a merged run, so runs split around
    it. Opening is clamped so a pier of at least 0.1 m and a lintel of at
    least 0.1 m always remain.

    Polycount: with Organic Irregularity off, every box along a straight
    run has identical thickness/height, so adjacent per-tile boxes are
    already perfectly flush/coplanar at their shared seam -- merging them
    into one longer box changes nothing about the visible surface, only
    removes vertices and the (already-invisible, coincident/internal)
    duplicate faces at each seam. That's only true when nothing varies
    tile-to-tile, so this path is skipped -- falling back to the original
    one-box-per-edge behavior -- whenever organic_amount > 0 (jitter needs
    per-tile granularity to read as hand-built) or two adjacent cells in a
    run carry different z_offset (a sloped run genuinely can't be one
    flat box without slanting it, which is out of scope here)."""
    walkable = set(walkable_cells)
    half_thick = wall_thickness / 2.0
    z_offsets = z_offsets or {}
    forced_wall_edges = forced_wall_edges or set()
    skip_cells = skip_cells or set()
    window_edges = window_edges or set()
    win_w = min(window_width, tile_size - 0.2)
    win_sill = max(0.0, min(window_sill, wall_height - 0.2))
    win_top = min(win_sill + window_height, wall_height - 0.1)

    def is_exposed(x, y, z, ddx, ddy):
        return (x + ddx, y + ddy, z) not in walkable or ((x, y, z), (ddx, ddy)) in forced_wall_edges

    verts = []
    faces = []

    def jitter(amount):
        return random.uniform(-amount, amount) if amount > 0 else 0.0

    def add_box(cx0, cy0, cx1, cy1, z0, z1, top=None, bottom=False):
        # top/bottom override the default face culling: a window sill needs
        # its top face and a lintel its underside, both genuinely visible.
        # Winding: vertex order reversed from the "obvious" per-corner
        # sweep -- verified against a real evaluated mesh in Blender
        # (tests/blender_headless_test.py) that the naive order pointed
        # every face's normal inward (invisible in Solid shading, which
        # doesn't cull backfaces by default, but genuinely inside-out for
        # any renderer/engine that does). This order is confirmed correct;
        # every other add_box-style helper in this file mirrors it exactly.
        # No bottom face: every wall box's z0 sits exactly at the walkable
        # cell's own floor level, so the bottom face is always coincident
        # with (and hidden behind) that floor tile's own top surface --
        # never visible in any normal view. Dropping it is pure polycount
        # reduction (a wall-heavy level's walls are usually the single
        # biggest geometry contributor), not a visual change; see
        # DEVELOPMENT.md "Delete interior/hidden faces for faster
        # rendering."
        i = len(verts)
        verts.extend([
            (cx0, cy0, z0), (cx1, cy0, z0), (cx1, cy1, z0), (cx0, cy1, z0),
            (cx0, cy0, z1), (cx1, cy0, z1), (cx1, cy1, z1), (cx0, cy1, z1),
        ])
        if cap_top if top is None else top:
            faces.append((i + 4, i + 5, i + 6, i + 7))  # top
        if bottom:
            faces.append((i + 3, i + 2, i + 1, i + 0))  # bottom
        faces.append((i + 5, i + 4, i + 0, i + 1))  # -Y side
        faces.append((i + 6, i + 5, i + 1, i + 2))  # +X side
        faces.append((i + 7, i + 6, i + 2, i + 3))  # +Y side
        faces.append((i + 4, i + 7, i + 3, i + 0))  # -X side

    def add_window_wall(axis, fixed, lo, hi, z0, ht, wall_top):
        """One tile-wide wall segment with a window opening. axis 'x' means
        the wall extends along X at Y=fixed; 'y' along Y at X=fixed."""
        mid = (lo + hi) / 2.0
        w0, w1 = mid - win_w / 2.0, mid + win_w / 2.0

        def box(a0, a1, zz0, zz1, **kw):
            if axis == 'x':
                add_box(a0, fixed - ht, a1, fixed + ht, zz0, zz1, **kw)
            else:
                add_box(fixed - ht, a0, fixed + ht, a1, zz0, zz1, **kw)

        box(lo, w0, z0, wall_top)
        box(w1, hi, z0, wall_top)
        if win_sill > 0.0:
            box(w0, w1, z0, z0 + win_sill, top=True)
        box(w0, w1, z0 + win_top, wall_top, bottom=True)

    if organic_amount > 0:
        for x, y, z in walkable_cells:
            if (x, y, z) in skip_cells:
                continue
            z0 = z * level_height + z_offsets.get((x, y, z), 0.0)
            left = (x - 0.5) * tile_size
            right = (x + 0.5) * tile_size
            bottom = (y - 0.5) * tile_size
            top = (y + 0.5) * tile_size

            if is_exposed(x, y, z, -1, 0):
                ht = max(0.02, half_thick + jitter(organic_amount * 0.3))
                wt = z0 + wall_height + jitter(organic_amount)
                if ((x, y, z), (-1, 0)) in window_edges:
                    add_window_wall('y', left, bottom, top, z0, ht, wt)
                else:
                    add_box(left - ht, bottom, left + ht, top, z0, wt)
            if is_exposed(x, y, z, 1, 0):
                ht = max(0.02, half_thick + jitter(organic_amount * 0.3))
                wt = z0 + wall_height + jitter(organic_amount)
                if ((x, y, z), (1, 0)) in window_edges:
                    add_window_wall('y', right, bottom, top, z0, ht, wt)
                else:
                    add_box(right - ht, bottom, right + ht, top, z0, wt)
            if is_exposed(x, y, z, 0, -1):
                ht = max(0.02, half_thick + jitter(organic_amount * 0.3))
                wt = z0 + wall_height + jitter(organic_amount)
                if ((x, y, z), (0, -1)) in window_edges:
                    add_window_wall('x', bottom, left, right, z0, ht, wt)
                else:
                    add_box(left, bottom - ht, right, bottom + ht, z0, wt)
            if is_exposed(x, y, z, 0, 1):
                ht = max(0.02, half_thick + jitter(organic_amount * 0.3))
                wt = z0 + wall_height + jitter(organic_amount)
                if ((x, y, z), (0, 1)) in window_edges:
                    add_window_wall('x', top, left, right, z0, ht, wt)
                else:
                    add_box(left, top - ht, right, top + ht, z0, wt)
    else:
        z1_top = wall_height  # relative rise, added to each run's own z0 below

        # -X / +X facing runs extend along Y at a fixed X boundary;
        # -Y / +Y facing runs extend along X at a fixed Y boundary. Each
        # direction is grouped independently -- a cell can start a run in
        # more than one direction at once (e.g. an outward corner).
        for dx in (-1, 1):
            lines = {}  # (x, z) -> sorted [(y, z_offset), ...]
            for (x, y, z) in walkable_cells:
                if (x, y, z) in skip_cells:
                    continue
                if is_exposed(x, y, z, dx, 0):
                    if ((x, y, z), (dx, 0)) in window_edges:
                        z0w = z * level_height + z_offsets.get((x, y, z), 0.0)
                        add_window_wall(
                            'y', (x + 0.5 * dx) * tile_size, (y - 0.5) * tile_size,
                            (y + 0.5) * tile_size, z0w, half_thick, z0w + z1_top,
                        )
                        continue
                    lines.setdefault((x, z), []).append((y, z_offsets.get((x, y, z), 0.0)))
            for (x, z), items in lines.items():
                items.sort()
                wall_x = (x + 0.5 * dx) * tile_size
                i = 0
                n = len(items)
                while i < n:
                    j = i
                    y0, off0 = items[i]
                    while j + 1 < n and items[j + 1][0] == items[j][0] + 1 and items[j + 1][1] == off0:
                        j += 1
                    y1 = items[j][0]
                    z0 = z * level_height + off0
                    bottom = (y0 - 0.5) * tile_size
                    top = (y1 + 0.5) * tile_size
                    add_box(wall_x - half_thick, bottom, wall_x + half_thick, top, z0, z0 + z1_top)
                    i = j + 1

        for dy in (-1, 1):
            lines = {}  # (y, z) -> sorted [(x, z_offset), ...]
            for (x, y, z) in walkable_cells:
                if (x, y, z) in skip_cells:
                    continue
                if is_exposed(x, y, z, 0, dy):
                    if ((x, y, z), (0, dy)) in window_edges:
                        z0w = z * level_height + z_offsets.get((x, y, z), 0.0)
                        add_window_wall(
                            'x', (y + 0.5 * dy) * tile_size, (x - 0.5) * tile_size,
                            (x + 0.5) * tile_size, z0w, half_thick, z0w + z1_top,
                        )
                        continue
                    lines.setdefault((y, z), []).append((x, z_offsets.get((x, y, z), 0.0)))
            for (y, z), items in lines.items():
                items.sort()
                wall_y = (y + 0.5 * dy) * tile_size
                i = 0
                n = len(items)
                while i < n:
                    j = i
                    x0, off0 = items[i]
                    while j + 1 < n and items[j + 1][0] == items[j][0] + 1 and items[j + 1][1] == off0:
                        j += 1
                    x1 = items[j][0]
                    z0 = z * level_height + off0
                    left = (x0 - 0.5) * tile_size
                    right = (x1 + 0.5) * tile_size
                    add_box(left, wall_y - half_thick, right, wall_y + half_thick, z0, z0 + z1_top)
                    i = j + 1

    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    _add_planar_uv_map(mesh, uv_tile_size)
    return mesh


def _pick_window_edges(
    walkable_cells, room_ids, tile_size, wall_height, window_sill, window_height,
    chance, seed, skip_cells=None, forced_wall_edges=None, min_gap=2,
):
    """Deterministically chooses which exposed room-wall edges get a window.
    Returns {((x,y,z), (dx,dy)), ...}, shared by the wall builder (cuts the
    opening) and the window builder (fills it) so the two always agree.

    Only edges of ROOM cells qualify (never corridors, so a corridor's
    solid walls stay solid), never Round rooms (skip_cells -- their ring
    wall is a different mesh) and never a forced Corridor-Stairs side.
    Two windows on the same wall line are at least min_gap tiles apart so
    a long wall reads as rhythm, not a perforated strip. The wall must be
    tall enough to keep a sill and a lintel, else nothing is picked."""
    if chance <= 0.0 or tile_size < 0.6 or wall_height < window_sill + 0.3:
        return set()
    skip_cells = skip_cells or set()
    forced_wall_edges = forced_wall_edges or set()
    walkable = set(walkable_cells)
    rng = random.Random(seed * 7919 + 31)
    picked = set()
    taken = {}  # (axis_kind, line, z) -> [positions]
    for cell in sorted(walkable):
        x, y, z = cell
        if room_ids.get(cell, -1) < 0 or cell in skip_cells:
            continue
        for dx, dy in HORIZONTAL_NEIGHBORS:
            if (x + dx, y + dy, z) in walkable or (cell, (dx, dy)) in forced_wall_edges:
                continue
            if rng.random() >= chance:
                continue
            key = ('x', x + 0.5 * dx, z) if dx != 0 else ('y', y + 0.5 * dy, z)
            pos = y if dx != 0 else x
            if any(abs(pos - other) < min_gap for other in taken.get(key, [])):
                continue
            taken.setdefault(key, []).append(pos)
            picked.add((cell, (dx, dy)))
    return picked


def _build_window_mesh(
    window_edges, tile_size, level_height, wall_thickness, window_width, window_sill,
    window_height, wall_height, z_offsets, name, uv_tile_size=1.0,
):
    """Frame + mullion cross + a thin glass pane for each window edge picked
    by _pick_window_edges. Material slot 0 = frame, 1 = glass. The frame
    bars sit inside the opening cut by _build_wall_mesh (same clamped
    width/sill/top maths), so nothing overlaps the wall's own faces."""
    win_w = min(window_width, tile_size - 0.2)
    sill = max(0.0, min(window_sill, wall_height - 0.2))
    top = min(sill + window_height, wall_height - 0.1)
    depth = max(0.04, wall_thickness * 0.5)
    bar = 0.05
    verts, faces, mats = [], [], []

    def add_box(x0, y0, x1, y1, z0, z1, mat):
        i = len(verts)
        verts.extend([
            (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
            (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
        ])
        for f in ((3, 2, 1, 0), (4, 5, 6, 7), (5, 4, 0, 1), (6, 5, 1, 2), (7, 6, 2, 3), (4, 7, 3, 0)):
            faces.append(tuple(i + k for k in f))
            mats.append(mat)

    for (x, y, z), (dx, dy) in sorted(window_edges):
        z0 = z * level_height + z_offsets.get((x, y, z), 0.0)
        zb, zt = z0 + sill, z0 + top
        zm = (zb + zt) / 2.0
        if dx != 0:
            fixed, mid = (x + 0.5 * dx) * tile_size, y * tile_size

            def box(a0, a1, b0, b1, mat, thick=depth):
                add_box(fixed - thick, mid + a0, fixed + thick, mid + a1, b0, b1, mat)
        else:
            fixed, mid = (y + 0.5 * dy) * tile_size, x * tile_size

            def box(a0, a1, b0, b1, mat, thick=depth):
                add_box(mid + a0, fixed - thick, mid + a1, fixed + thick, b0, b1, mat)
        hw = win_w / 2.0
        box(-hw, -hw + bar, zb, zt, 0)           # left jamb
        box(hw - bar, hw, zb, zt, 0)             # right jamb
        box(-hw, hw, zb, zb + bar, 0)            # bottom rail
        box(-hw, hw, zt - bar, zt, 0)            # top rail
        box(-bar / 2.0, bar / 2.0, zb, zt, 0, depth * 0.7)   # vertical mullion
        box(-hw, hw, zm - bar / 2.0, zm + bar / 2.0, 0, depth * 0.7)  # transom
        box(-hw + bar, hw - bar, zb + bar, zt - bar, 1, 0.008)  # glass

    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    _add_planar_uv_map(mesh, uv_tile_size)
    for poly, m in zip(mesh.polygons, mats):
        poly.material_index = m
    return mesh


def get_or_create_window_frame_material():
    return _get_or_create_named_material("LA_Window_Frame", "WindowFrame.png", "4a3524")


def get_or_create_window_glass_material():
    existing = bpy.data.materials.get("LA_Window_Glass")
    if existing is not None:
        return existing
    mat = _new_textured_material("LA_Window_Glass", "WindowGlass.png", "9fc8e0")
    # Translucent pane: alpha lives on the Principled node when it exists.
    bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if bsdf is not None:
        _set_input(bsdf, 'Alpha', 0.35)
    _set_prop(mat, 'blend_method', 'BLEND')
    return mat


def _cluster_nearby_points(points, merge_distance):
    """Groups points (line, b) -- both grid-space ints -- into clusters
    where every point is within merge_distance (Chebyshev, in tiles) of at
    least one other member of its cluster, then keeps only the smallest
    point (by (line, b) order) from each cluster.

    Doorways on the exact same line (e.g. a 1-tile corridor hitting a room
    at two nearby points) differ only in b -- a plain per-line scan would
    catch that. But a WIDE opening (a 2+-tile corridor, or two rooms
    sharing a long edge) produces boundary detections on ADJACENT lines
    too, one tile apart -- those never share a line, so a per-line-only
    merge leaves every one of them as its own door, which is exactly the
    "multiple doors in the same room next to each other" symptom. Checking
    both axes together (line AND b) catches that case as well."""
    n = len(points)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        li, bi = points[i]
        for j in range(i + 1, n):
            lj, bj = points[j]
            if abs(li - lj) <= merge_distance and abs(bi - bj) <= merge_distance:
                union(i, j)

    clusters = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(points[i])

    return [min(members) for members in clusters.values()]


# How many stepped boxes approximate one arch's curved silhouette --
# matches the scale of every other curve-via-N-segments primitive already
# in this file (barrel/cone use sides=10, Round Corners' Bevel modifier
# uses segments=6).
DOOR_ARCH_SEGMENTS = 8

# Entrance/Exit get a fixed, always-arched "Gate" treatment regardless of
# the ordinary Door Style setting, scaled up from a regular doorway's own
# dimensions -- the whole point is that these two fixed, always-present
# landmarks read as visually distinct from every ordinary room doorway in
# every Door Style configuration, including when ordinary doors are FLAT.
GATE_STYLE = 'ROUND'
GATE_HEIGHT_SCALE = 1.35
GATE_FRAME_THICKNESS_SCALE = 1.6
GATE_ARCH_HEIGHT_SCALE = 1.6


def _round_arch_profile(half_span, rise, segments):
    """(y, z) points, y relative to the doorway's own center and z above
    the springline, tracing a half-ELLIPSE (not a true circle unless
    rise == half_span -- deliberately independently adjustable instead,
    the same "close enough, not literally the named shape" tradeoff
    already used for Round rooms' ellipse carve) from the left spring
    point (-half_span, 0) up over the apex (0, rise) to the right spring
    point (half_span, 0)."""
    return [
        (-half_span * math.cos(math.pi * i / segments), rise * math.sin(math.pi * i / segments))
        for i in range(segments + 1)
    ]


def _pointed_arch_profile(half_span, rise, segments):
    """(y, z) points tracing a two-centered ("Gothic"/lancet) arch: two
    circular arcs, each centered on the springline, meeting at a shared
    apex point (0, rise) directly above center. The sharp apex -- a real
    tangent discontinuity between the two arcs, not a smooth curve
    through it -- is what reads as "pointed" rather than "round".

    The classic hand-drafted construction centers each arc at the
    OPPOSITE spring point (radius == full span), which locks rise to a
    fixed proportion of half_span (an equilateral arch) -- generalized
    here to solve for a center position c (on the springline) and radius
    r = half_span + c such that the arc still passes through both its own
    spring point and the shared apex for ANY requested rise, so `rise`
    controls a POINTED arch exactly the same way it controls a ROUND one:
        c = (rise^2 - half_span^2) / (2 * half_span)
    Positive c (rise < half_span) places both centers OUTSIDE the span --
    a shallow "drop arch". Negative c (rise > half_span) places them
    INSIDE -- a tall "lancet". Both remain valid, correctly-meeting arcs;
    only the equilateral case (rise == half_span, c == 0, centers exactly
    at the opposite spring points) matches the traditional construction
    exactly."""
    if half_span <= 1e-6:
        return [(-half_span, 0.0), (half_span, 0.0)]
    c = (rise * rise - half_span * half_span) / (2.0 * half_span)
    r = half_span + c
    if r <= 1e-6:
        return [(-half_span, 0.0), (0.0, rise), (half_span, 0.0)]
    half_segments = max(1, segments // 2)
    start_angle = math.atan2(0.0, -half_span - c)
    apex_angle = math.atan2(rise, -c)
    left = [
        (
            c + r * math.cos(start_angle + (apex_angle - start_angle) * (i / half_segments)),
            r * math.sin(start_angle + (apex_angle - start_angle) * (i / half_segments)),
        )
        for i in range(half_segments + 1)
    ]
    right = [(-y, z) for y, z in reversed(left[:-1])]
    return left + right


def _find_ordinary_doorways(
    walkable_cells, room_ids, tile_size, level_height, merge_distance,
    z_offsets=None, stair_cells=None, skip_room_ids=None,
):
    """Every ordinary doorway (a same-Z boundary between two walkable cells
    whose room_id differs, excluding stairs and any room in skip_room_ids)
    as a resolved world-space record: {'axis', 'z0', 'center', 'span_min',
    'span_max'}. 'axis' 'X' means the opening spans Y (walked through
    east-west, matches add_frame_facing_x in _build_door_mesh); 'axis' 'Y'
    spans X (matches add_frame_facing_y).

    Extracted from _build_door_mesh's own former Pass 1/2 so both the door
    FRAME and the door PANEL (see _build_door_panels) build from the exact
    same doorway set, with no risk of the two drifting apart. See
    _build_door_mesh's docstring for the full reasoning behind the
    boundary-detection/clustering approach -- this is that same logic with
    geometry-building removed, kept behaviorally identical (same groups
    dict construction and iteration order) so extracting it here changed
    nothing about what _build_door_mesh actually draws."""
    walkable = set(walkable_cells)
    z_offsets = z_offsets or {}
    stair_cells = stair_cells or set()
    skip_room_ids = skip_room_ids or set()

    groups = {}
    for x, y, z in walkable_cells:
        if (x, y, z) in stair_cells:
            continue
        rid = room_ids.get((x, y, z), -1)

        east = (x + 1, y, z)
        east_rid = room_ids.get(east, -1)
        if (
            east in walkable and east not in stair_cells and east_rid != rid
            and rid not in skip_room_ids and east_rid not in skip_room_ids
        ):
            groups.setdefault(('X', z), []).append((y, x))

        north = (x, y + 1, z)
        north_rid = room_ids.get(north, -1)
        if (
            north in walkable and north not in stair_cells and north_rid != rid
            and rid not in skip_room_ids and north_rid not in skip_room_ids
        ):
            groups.setdefault(('Y', z), []).append((x, y))

    records = []
    for (axis, z), points in groups.items():
        kept = _cluster_nearby_points(points, merge_distance)
        for line, b in kept:
            if axis == 'X':
                offset = (z_offsets.get((b, line, z), 0.0) + z_offsets.get((b + 1, line, z), 0.0)) / 2.0
                records.append({
                    'axis': 'X',
                    'z0': z * level_height + offset,
                    'center': (b + 0.5) * tile_size,
                    'span_min': (line - 0.5) * tile_size,
                    'span_max': (line + 0.5) * tile_size,
                })
            else:
                offset = (z_offsets.get((line, b, z), 0.0) + z_offsets.get((line, b + 1, z), 0.0)) / 2.0
                records.append({
                    'axis': 'Y',
                    'z0': z * level_height + offset,
                    'center': (b + 0.5) * tile_size,
                    'span_min': (line - 0.5) * tile_size,
                    'span_max': (line + 0.5) * tile_size,
                })
    return records


def _build_door_mesh(
    walkable_cells, room_ids, tile_size, level_height, door_height, frame_thickness, name,
    merge_distance=2, z_offsets=None, stair_cells=None, uv_tile_size=1.0,
    door_style='FLAT', arch_height=0.6, entrance_cells=None, exit_cells=None, skip_room_ids=None,
):
    """A walk-through frame (two side posts + a top, deliberately no panel
    filling the gap) at every same-Z boundary between two walkable cells
    whose room_id differs -- i.e. every point a corridor enters a room, or
    two rooms directly meet. That's exactly where _build_wall_mesh already
    leaves a gap (both cells are walkable, so no wall forms), so this
    never needs to reason about walls directly -- it can't place a frame
    anywhere a wall would actually be, and can't miss a real doorway
    either, since it's reading the identical walkable_cells silhouette off
    the same baked blueprint data.

    room_ids maps (x, y, z) -> room_id (-1 for corridor/stair, else the
    room's index -- see WFC_Level_Solver.room_id). Checking only the +X and
    +Y neighbor of each cell (never -X/-Y) visits every boundary edge
    exactly once, so no doorway gets double-framed.

    Two rooms connected by a short corridor otherwise get a doorway at
    EACH end -- fine for a long hallway, but for a 1-2 tile connector that
    reads as two frames standing right on top of each other. A wide
    corridor or shared room edge causes the same problem sideways: several
    boundary cells in a row each produce their own doorway, side by side.
    merge_distance (in tiles, Chebyshev) collapses any cluster of
    same-axis, same-z doorways that are that close or closer -- on either
    the along-corridor axis or the side-by-side axis -- down to a single
    frame, via a first pass that only collects boundary positions and a
    second pass (_cluster_nearby_points) that builds geometry for one
    survivor per cluster.

    z_offsets (optional {(x,y,z): meters}) follows continuous room
    elevation (see WFC_Level_Solver._apply_continuous_elevation) -- a
    frame's z0 averages the offset of the two cells it sits between (by
    construction they match exactly wherever this pass can place a door at
    all, since a room's floor and the corridor cell right outside its one
    doorway always carry the same offset; averaging is just cheap
    insurance against a future edge case, not something expected to ever
    matter today).

    stair_cells (optional set of (x,y,z)) excludes any boundary touching a
    TILE_STAIR tile. A stairwell room's walkway and its climb column share
    the same room_id == -1 room_id (climb cells get reset to -1 just like
    an ordinary corridor cell, so BFS/connectivity treats them uniformly)
    -- without this exclusion, that internal walkway-to-climb-column
    boundary reads as "a corridor entering a room" exactly like a real
    doorway, and gets a frame plastered onto the stairs themselves. A
    stairwell's real, legitimate doorway (where an outside corridor
    enters its walkway) is unaffected, since that boundary never touches
    a stair tile on either side.

    door_style ('FLAT' / 'ROUND' / 'POINTED') controls every ORDINARY
    doorway found by the room_id-boundary passes below; arch_height is
    that arch's rise above the springline (ignored for FLAT). Entrance and
    Exit each get their OWN fixed, always-arched "Gate" treatment (see
    GATE_STYLE/GATE_*_SCALE) regardless of door_style, so the two are
    always visually distinct from ordinary room doorways in every
    configuration -- entrance_cells/exit_cells (each an optional set of
    (x,y,z), normally exactly one cell) are placed via a SEPARATE pass
    keyed off the exposed side(s) of the cell itself (same 4-neighbor
    exposure check _build_wall_mesh's own wall pass uses), not the
    room_id-boundary logic below -- the entrance/exit cell's own room_id
    is -1, same as any corridor cell, so it usually wouldn't produce an
    ordinary doorway there at all, and even where it would, "flush against
    the fixed map corner" is a more reliable anchor than "wherever the
    nearest room_id boundary happens to be."

    Three material slots throughout, always: 0 = ordinary door, 1 =
    Entrance gate, 2 = Exit gate (matching the order the caller is
    expected to append door/entrance/exit materials in).

    skip_room_ids (optional set of room_index) -- a boundary touching a
    room in this set on EITHER side is skipped entirely here, even though
    it's a real doorway. Used for Round rooms, which get their own
    angled frame instead (see _build_round_room_doors_mesh) that actually
    follows the curved wall instead of standing at a mismatched straight
    angle against it."""
    walkable = set(walkable_cells)
    verts = []
    faces = []
    material_indices = []
    half_frame = frame_thickness / 2.0
    z_offsets = z_offsets or {}
    stair_cells = stair_cells or set()
    entrance_cells = entrance_cells or set()
    exit_cells = exit_cells or set()
    skip_room_ids = skip_room_ids or set()

    def add_box(cx0, cy0, cx1, cy1, z0, z1, floor_touching=True, mat_idx=0):
        # See the matching comment in _build_wall_mesh's add_box -- this
        # winding was verified correct against real evaluated Blender
        # geometry; the naive per-corner order pointed every normal inward.
        #
        # floor_touching (default True, matches every post box) drops the
        # bottom face -- always coincident with/hidden behind the floor
        # tile it stands on, same reasoning as walls. A FLAT door's LINTEL
        # (and every arch-silhouette box, see add_arch_silhouette) is
        # suspended above the posts; its underside IS genuinely visible to
        # anyone standing underneath it, so those calls pass
        # floor_touching=False specifically to keep it.
        i = len(verts)
        verts.extend([
            (cx0, cy0, z0), (cx1, cy0, z0), (cx1, cy1, z0), (cx0, cy1, z0),
            (cx0, cy0, z1), (cx1, cy0, z1), (cx1, cy1, z1), (cx0, cy1, z1),
        ])
        added = 5 if floor_touching else 6
        if not floor_touching:
            faces.append((i + 3, i + 2, i + 1, i + 0))  # bottom
        faces.append((i + 4, i + 5, i + 6, i + 7))  # top
        faces.append((i + 5, i + 4, i + 0, i + 1))
        faces.append((i + 6, i + 5, i + 1, i + 2))
        faces.append((i + 7, i + 6, i + 2, i + 3))
        faces.append((i + 4, i + 7, i + 3, i + 0))
        material_indices.extend([mat_idx] * added)

    def add_arch_silhouette(axis, center_a, half_frame_a, span_min, span_max, z_spring, rise, style, mat_idx):
        """Replaces a flat lintel with a stepped approximation of an
        arch's outer silhouette -- DOOR_ARCH_SEGMENTS small boxes whose
        top height follows the arch profile at that slice, built entirely
        from the same add_box already verified correct above rather than
        hand-deriving new winding for a smoothly curved surface. Solid
        from the springline up to the curve at each slice (not a separate
        thin inner/outer band tracing a true hollow arch ring) -- at the
        depth (frame_thickness) a door frame actually has, this reads
        visually the same as a true arch from either side of the
        doorway, and is far lower-risk to get right without a live
        Blender session to check surface winding against."""
        profile_fn = _round_arch_profile if style == 'ROUND' else _pointed_arch_profile
        center_b = (span_min + span_max) / 2.0
        half_span = (span_max - span_min) / 2.0
        profile = profile_fn(half_span, rise, DOOR_ARCH_SEGMENTS)
        a0, a1 = center_a - half_frame_a, center_a + half_frame_a
        for i in range(DOOR_ARCH_SEGMENTS):
            b0, h0 = profile[i]
            b1, h1 = profile[i + 1]
            seg_b0, seg_b1 = sorted((center_b + b0, center_b + b1))
            seg_top = z_spring + max(h0, h1)
            if seg_top <= z_spring:
                continue  # degenerate sliver right at a spring point -- skip
            if axis == 'X':
                add_box(a0, seg_b0, a1, seg_b1, z_spring, seg_top, floor_touching=False, mat_idx=mat_idx)
            else:
                add_box(seg_b0, a0, seg_b1, a1, z_spring, seg_top, floor_touching=False, mat_idx=mat_idx)

    def add_frame_facing_x(center_x, y_min, y_max, z0, style='FLAT', rise=0.0, mat_idx=0):
        """Doorway replacing a north-south wall (found via a +X neighbor
        check) -- opening spans Y, walked through east-west. Posts at the
        Y ends; FLAT caps with a flat lintel spanning the full Y width,
        ROUND/POINTED cap with a stepped arch silhouette instead."""
        z1 = z0 + door_height
        add_box(center_x - half_frame, y_min, center_x + half_frame, y_min + frame_thickness, z0, z1, mat_idx=mat_idx)
        add_box(center_x - half_frame, y_max - frame_thickness, center_x + half_frame, y_max, z0, z1, mat_idx=mat_idx)
        if style == 'FLAT':
            add_box(
                center_x - half_frame, y_min, center_x + half_frame, y_max, z1, z1 + frame_thickness,
                floor_touching=False, mat_idx=mat_idx,
            )
        else:
            add_arch_silhouette('X', center_x, half_frame, y_min, y_max, z1, rise, style, mat_idx)

    def add_frame_facing_y(center_y, x_min, x_max, z0, style='FLAT', rise=0.0, mat_idx=0):
        """Doorway replacing an east-west wall (found via a +Y neighbor
        check) -- opening spans X, walked through north-south."""
        z1 = z0 + door_height
        add_box(x_min, center_y - half_frame, x_min + frame_thickness, center_y + half_frame, z0, z1, mat_idx=mat_idx)
        add_box(x_max - frame_thickness, center_y - half_frame, x_max, center_y + half_frame, z0, z1, mat_idx=mat_idx)
        if style == 'FLAT':
            add_box(
                x_min, center_y - half_frame, x_max, center_y + half_frame, z1, z1 + frame_thickness,
                floor_touching=False, mat_idx=mat_idx,
            )
        else:
            add_arch_silhouette('Y', center_y, half_frame, x_min, x_max, z1, rise, style, mat_idx)

    # Pass 1/2: find every ordinary doorway (see _find_ordinary_doorways,
    # which is this exact former inline logic extracted so the door PANEL
    # builder can reuse the identical doorway set -- unchanged behavior).
    for rec in _find_ordinary_doorways(
        walkable_cells, room_ids, tile_size, level_height, merge_distance,
        z_offsets=z_offsets, stair_cells=stair_cells, skip_room_ids=skip_room_ids,
    ):
        if rec['axis'] == 'X':
            add_frame_facing_x(rec['center'], rec['span_min'], rec['span_max'], rec['z0'], style=door_style, rise=arch_height)
        else:
            add_frame_facing_y(rec['center'], rec['span_min'], rec['span_max'], rec['z0'], style=door_style, rise=arch_height)

    # Pass 3: Entrance/Exit gates -- see this function's own docstring for
    # why this is a separate pass instead of extending Pass 1/2.
    gate_frame_thickness = frame_thickness * GATE_FRAME_THICKNESS_SCALE
    gate_half_frame = gate_frame_thickness / 2.0
    gate_height = door_height * GATE_HEIGHT_SCALE
    gate_arch_height = arch_height * GATE_ARCH_HEIGHT_SCALE

    def add_gate_facing_x(center_x, y_min, y_max, z0, mat_idx):
        z1 = z0 + gate_height
        add_box(
            center_x - gate_half_frame, y_min, center_x + gate_half_frame, y_min + gate_frame_thickness,
            z0, z1, mat_idx=mat_idx,
        )
        add_box(
            center_x - gate_half_frame, y_max - gate_frame_thickness, center_x + gate_half_frame, y_max,
            z0, z1, mat_idx=mat_idx,
        )
        add_arch_silhouette('X', center_x, gate_half_frame, y_min, y_max, z1, gate_arch_height, GATE_STYLE, mat_idx)

    def add_gate_facing_y(center_y, x_min, x_max, z0, mat_idx):
        z1 = z0 + gate_height
        add_box(
            x_min, center_y - gate_half_frame, x_min + gate_frame_thickness, center_y + gate_half_frame,
            z0, z1, mat_idx=mat_idx,
        )
        add_box(
            x_max - gate_frame_thickness, center_y - gate_half_frame, x_max, center_y + gate_half_frame,
            z0, z1, mat_idx=mat_idx,
        )
        add_arch_silhouette('Y', center_y, gate_half_frame, x_min, x_max, z1, gate_arch_height, GATE_STYLE, mat_idx)

    def add_gate(cell, mat_idx):
        x, y, z = cell
        z0 = z * level_height + z_offsets.get(cell, 0.0)
        for dx, dy in HORIZONTAL_NEIGHBORS:
            neighbor = (x + dx, y + dy, z)
            if neighbor not in walkable or neighbor in stair_cells:
                continue
            if dx == 1:
                add_gate_facing_x((x + 0.5) * tile_size, (y - 0.5) * tile_size, (y + 0.5) * tile_size, z0, mat_idx)
            elif dx == -1:
                add_gate_facing_x((x - 0.5) * tile_size, (y - 0.5) * tile_size, (y + 0.5) * tile_size, z0, mat_idx)
            elif dy == 1:
                add_gate_facing_y((y + 0.5) * tile_size, (x - 0.5) * tile_size, (x + 0.5) * tile_size, z0, mat_idx)
            else:
                add_gate_facing_y((y - 0.5) * tile_size, (x - 0.5) * tile_size, (x + 0.5) * tile_size, z0, mat_idx)

    for cell in entrance_cells:
        add_gate(cell, 1)
    for cell in exit_cells:
        add_gate(cell, 2)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    for poly, mat_idx in zip(mesh.polygons, material_indices):
        poly.material_index = mat_idx
    _add_planar_uv_map(mesh, uv_tile_size)
    return mesh


def _build_door_panels(
    doorway_records, door_height, frame_thickness, door_material, name_prefix,
    panel_clearance=0.04, panel_thickness_scale=0.4, uv_tile_size=1.0,
):
    """One separate mesh Object per doorway record from
    _find_ordinary_doorways -- unlike every other mesh category in this
    file, panels are NOT merged into one shared mesh, because a hinge is
    inherently object-level (its own origin, its own transform, its own
    physics/constraint data). Each panel is built in LOCAL space with its
    hinge edge at local (0,0,0); the caller sets obj.location to that
    edge's world position, so obj IS the hinge pivot -- no Empty or driver
    needed to fake one.

    Always hinges on the doorway's span_min side, for a predictable,
    level-wide-consistent swing direction. If the opening is too narrow to
    fit a panel plus clearance inside the frame posts, that doorway is
    skipped (frame-only, matching how it already looks today) rather than
    emitting a degenerate sliver.

    Local-to-world orientation (derived from add_frame_facing_x/y's own
    post placement, not guessed): an 'X' doorway's span runs along world Y
    with post thickness along world X, so the panel (local width along
    local +X) gets rotated 90 deg around Z; a 'Y' doorway's span already
    runs along world X with thickness along world Y, matching the panel's
    local axes directly, so no added rotation. Verified against real
    evaluated mesh bounds in tests/blender_headless_test.py, not just
    reasoned about on paper -- see the "Doors: panel" checks there.

    Returns a list of the created Objects (not yet linked into any
    collection or scene -- see OBJECT_OT_GenerateLevelDoors, which also
    calls _try_setup_hinge_physics on each one only after linking, since
    UPBGE's rigid body operators need the object to already be in the
    view layer)."""
    created = []
    for i, rec in enumerate(doorway_records):
        span = rec['span_max'] - rec['span_min']
        panel_width = span - 2.0 * (frame_thickness + panel_clearance)
        if panel_width <= 0.01:
            continue
        panel_height = max(0.01, door_height - panel_clearance)
        panel_thickness = frame_thickness * panel_thickness_scale
        half_t = panel_thickness / 2.0

        # Same 8-vert/face winding as this file's other add_box helpers
        # (verified correct against real evaluated geometry there; reused
        # verbatim here rather than re-derived), just written out directly
        # since this is a single standalone box per call, not accumulated
        # into a shared verts/faces list like the frame builders use.
        verts = [
            (0.0, -half_t, 0.0), (panel_width, -half_t, 0.0), (panel_width, half_t, 0.0), (0.0, half_t, 0.0),
            (0.0, -half_t, panel_height), (panel_width, -half_t, panel_height),
            (panel_width, half_t, panel_height), (0.0, half_t, panel_height),
        ]
        faces = [
            (3, 2, 1, 0),  # bottom -- always visible on a panel, unlike a floor-touching post
            (4, 5, 6, 7),  # top
            (5, 4, 0, 1),
            (6, 5, 1, 2),
            (7, 6, 2, 3),
            (4, 7, 3, 0),
        ]

        mesh = bpy.data.meshes.new(f"{name_prefix}_{i:03d}_Mesh")
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        mesh.materials.append(door_material)
        _add_planar_uv_map(mesh, uv_tile_size)

        obj = bpy.data.objects.new(f"{name_prefix}_{i:03d}", mesh)
        if rec['axis'] == 'X':
            obj.location = (rec['center'], rec['span_min'], rec['z0'])
            obj.rotation_euler = (0.0, 0.0, math.radians(90.0))
        else:
            obj.location = (rec['span_min'], rec['center'], rec['z0'])
            obj.rotation_euler = (0.0, 0.0, 0.0)

        created.append(obj)
    return created


def _try_setup_hinge_physics(context, obj):
    """Best-effort, EXPERIMENTAL only -- off by default (see
    wfc_upbge_hinge_physics) for a concrete, demonstrated reason, not just
    caution: `context.temp_override(object=obj, active_object=obj)`
    reliably targets `obj` on UPBGE 0.53-alpha/Blender 5.3.0, but on UPBGE
    0.50/Blender 5.0.1 it does NOT -- confirmed directly, the rigid body
    operators silently acted on a stale, unrelated, already-selected
    object from an earlier generation step instead (a Stairs object
    repeatedly, uselessly re-targeted, while every door panel got no
    constraint at all), and running that misdirected path through this
    addon's full repeated-regeneration test suite crashed Blender outright
    (segfault) on that same older version. Selection state (select_set +
    view_layer.objects.active) is used here instead of temp_override,
    since it's the older, more broadly-compatible way to give an operator
    an unambiguous target -- confirmed by direct inspection to correctly
    target `obj` on both tested Blender/UPBGE versions where temp_override
    alone did not -- but given temp_override itself already looked correct
    in isolated testing before the version-dependent failure surfaced, no
    single fix here should be trusted without the SAME kind of direct
    re-verification (not just "it didn't raise") before ever defaulting
    this back on.

    If running on UPBGE (object.game exists -- absent on stock Blender,
    confirmed empirically), sets obj up as a RIGID_BODY and adds a HINGE
    RigidBodyConstraint clamped to swing roughly closed-to-open (0 to
    ~100 degrees), not spin freely. Whether UPBGE's LIVE game runtime
    actually simulates this constraint during real-time play, versus it
    only being used for Blender's own pre-baked physics animation, ALSO
    could not be verified headlessly -- that needs an actual interactive
    UPBGE session (Start Game, push the door).

    Never raises: any failure -- including the constraint ending up
    missing or misdirected, checked explicitly below rather than just
    trusting the operators didn't error -- is returned as a message string
    for the caller to report as a warning, not an exception. `obj` must
    already be linked into the scene/view layer before calling this."""
    if not hasattr(obj, 'game'):
        return None
    try:
        obj.game.physics_type = 'RIGID_BODY'

        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj

        bpy.ops.rigidbody.object_add(type='ACTIVE')
        bpy.ops.rigidbody.constraint_add(type='HINGE')

        rbc = obj.rigid_body_constraint
        if rbc is None:
            return "rigidbody.constraint_add reported success but obj.rigid_body_constraint is still None"

        # object_add/constraint_add with a single object selected creates
        # the constraint DATA on obj but leaves object1/object2 both None
        # -- an unconnected constraint, confirmed by direct inspection to
        # do nothing. Setting object1 = obj is what actually anchors the
        # panel's rigid body to this constraint; object2 stays None
        # deliberately, since there's no separate rigid body for "the
        # wall" to hinge against -- that anchors the hinge to a fixed
        # point in world space instead (the constraint object's own
        # transform, i.e. obj's), which is exactly what a
        # door-hinged-to-a-fixed-frame needs.
        rbc.object1 = obj
        rbc.use_limit_ang_z = True
        rbc.limit_ang_z_lower = 0.0
        rbc.limit_ang_z_upper = math.radians(100.0)

        if rbc.object1 is not obj:
            return f"rigid_body_constraint.object1 did not end up as {obj.name!r} after setting it"
        return None
    except Exception as exc:
        return str(exc)


def _build_round_room_doors_mesh(
    room_meta, room_id_grid, walkable_cells, tile_size, level_height, door_height,
    frame_thickness, room_shape_sides, z_offsets, door_style, arch_height, name,
    uv_tile_size=1.0,
):
    """A door frame for every Round room's real doorway opening, oriented
    along that opening's own actual rim edge instead of forced to a
    straight X/Y axis -- so the frame actually matches the curved wall
    ring (_build_round_room_walls_mesh) instead of standing at a
    mismatched straight angle against it. Rect rooms keep their existing
    straight, axis-aligned doors from _build_door_mesh -- unchanged,
    nothing to fix there. Only material slot 0 (ordinary door) is used
    here; Entrance/Exit gates are always axis-aligned map-corner
    landmarks (see _build_door_mesh's own docstring), untouched by this.

    Recomputes each Round room's open rim edges the same way
    _build_round_room_walls_mesh does (a room cell bordering a walkable
    cell belonging to a DIFFERENT room is a real doorway; its angle
    around the room's own ellipse picks which polygon edge it's on) --
    so a door here always lands exactly where the wall ring's own gap
    is, by construction, not by coincidence."""
    walkable = set(walkable_cells)
    half_frame = frame_thickness / 2.0
    verts, faces, material_indices = [], [], []

    def add_oriented_box(x0, y0, x1, y1, half_thickness, z0, z1, floor_touching, mat_idx=0):
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length < 1e-9:
            return
        nx, ny = -dy / length * half_thickness, dx / length * half_thickness
        corners = ((x0 - nx, y0 - ny), (x1 - nx, y1 - ny), (x1 + nx, y1 + ny), (x0 + nx, y0 + ny))
        i = len(verts)
        verts.extend((cx, cy, z0) for cx, cy in corners)
        verts.extend((cx, cy, z1) for cx, cy in corners)
        added = 5 if floor_touching else 6
        if not floor_touching:
            faces.append((i + 3, i + 2, i + 1, i + 0))  # bottom
        faces.append((i + 4, i + 5, i + 6, i + 7))  # top
        faces.append((i + 5, i + 4, i + 0, i + 1))
        faces.append((i + 6, i + 5, i + 1, i + 2))
        faces.append((i + 7, i + 6, i + 2, i + 3))
        faces.append((i + 4, i + 7, i + 3, i + 0))
        material_indices.extend([mat_idx] * added)

    def add_arch_silhouette_oriented(cx, cy, tx, ty, half_span, half_frame_a, z_spring, rise, style):
        """Same stepped-arch-silhouette technique _build_door_mesh's own
        add_arch_silhouette already uses (DOOR_ARCH_SEGMENTS boxes along
        the profile), expressed in the doorway's own local (tangent,
        normal) basis instead of a hardcoded world X/Y axis --
        add_oriented_box already derives the perpendicular (normal) from
        whatever two tangent-direction points it's given, so no separate
        normal vector needs computing here."""
        profile_fn = _round_arch_profile if style == 'ROUND' else _pointed_arch_profile
        profile = profile_fn(half_span, rise, DOOR_ARCH_SEGMENTS)
        for i in range(DOOR_ARCH_SEGMENTS):
            b0, h0 = profile[i]
            b1, h1 = profile[i + 1]
            seg_top = z_spring + max(h0, h1)
            if seg_top <= z_spring:
                continue
            x0, y0 = cx + tx * b0, cy + ty * b0
            x1, y1 = cx + tx * b1, cy + ty * b1
            add_oriented_box(x0, y0, x1, y1, half_frame_a, z_spring, seg_top, floor_touching=False)

    for room_id, room in enumerate(room_meta):
        if room['shape'] != 'ROUND':
            continue
        x, y, rw, rl, z = room['x'], room['y'], room['w'], room['l'], room['z']
        # See _build_round_room_floor_mesh's matching comment: a grid cell
        # xi is world-centered at xi*tile_size, so the room's true
        # world-space center uses (rw-1)/2.0, matching _carve_room's own
        # grid-space ellipse test -- not +rw/2.0 (no -1), which is half a
        # tile off and was letting the ring clip things just outside the
        # room's actual reserved rectangle.
        cx, cy = (x + (rw - 1) / 2.0) * tile_size, (y + (rl - 1) / 2.0) * tile_size
        rx, ry = (rw / 2.0) * tile_size, (rl / 2.0) * tile_size

        room_cells_here = [c for c, rid in room_id_grid.items() if rid == room_id and c[2] == z]
        if not room_cells_here:
            continue
        centroid_x = sum(c[0] for c in room_cells_here) / len(room_cells_here)
        centroid_y = sum(c[1] for c in room_cells_here) / len(room_cells_here)
        nearest_cell = min(
            room_cells_here, key=lambda c: (c[0] - centroid_x) ** 2 + (c[1] - centroid_y) ** 2
        )

        open_edges = set()
        for (cellx, celly, cellz) in room_cells_here:
            exposed = False
            for dx, dy in HORIZONTAL_NEIGHBORS:
                neighbor = (cellx + dx, celly + dy, cellz)
                if neighbor in walkable and room_id_grid.get(neighbor) != room_id:
                    exposed = True
                    break
            if not exposed:
                continue
            px = (cellx + 0.5) * tile_size
            py = (celly + 0.5) * tile_size
            angle = math.atan2((py - cy) / ry, (px - cx) / rx) % (2.0 * math.pi)
            open_edges.add(int(angle / (2.0 * math.pi / room_shape_sides)) % room_shape_sides)

        # Same dead-corner fix as _build_round_room_walls_mesh -- a
        # corridor that got carved into this room's own uncarved
        # bounding-box corner (see _room_fits's docstring) is invisible to
        # the loop above (it's not one of this room's own carved cells),
        # so without this a doorway could be missing exactly where the
        # wall ring now opens for that corridor.
        dead_corner_positions = _room_shape_sides_wall_positions(cx, cy, rx, ry, room_shape_sides)
        for cellx in range(x, x + rw):
            for celly in range(y, y + rl):
                cell = (cellx, celly, z)
                if room_id_grid.get(cell) == room_id or cell not in walkable:
                    continue
                px0, py0 = cellx * tile_size, celly * tile_size
                px1, py1 = px0 + tile_size, py0 + tile_size
                # A tile-sized cell can be wide relative to the room's own
                # radius (a small Round room's corner cell can span a large
                # angular slice) -- sampling only the cell's center angle
                # can land in a DIFFERENT bucket than the one its footprint
                # actually crosses, leaving a neighboring closed edge still
                # cutting through it (confirmed via a real repro). Sampling
                # all 4 corners and opening every bucket any of them falls
                # in is a safe over-approximation -- occasionally opens one
                # extra edge, never leaves a real collision.
                for px, py in ((px0, py0), (px1, py0), (px1, py1), (px0, py1)):
                    angle = math.atan2((py - cy) / ry, (px - cx) / rx) % (2.0 * math.pi)
                    open_edges.add(int(angle / (2.0 * math.pi / room_shape_sides)) % room_shape_sides)
                # The reverse size mismatch: on a MINIMUM-size (3x3) Round
                # room the radius can be small enough that a whole polygon
                # edge -- both its rim vertices -- lies entirely INSIDE one
                # grid cell's footprint, touching none of that cell's own
                # corners either (confirmed via the same real repro). Catch
                # that by opening both edges touching any rim vertex that
                # falls inside this cell's rectangle.
                for s in range(room_shape_sides):
                    vx, vy = dead_corner_positions[s]
                    if px0 <= vx <= px1 and py0 <= vy <= py1:
                        open_edges.add(s)
                        open_edges.add((s - 1) % room_shape_sides)

        z0 = z * level_height + z_offsets.get(nearest_cell, 0.0)
        z1 = z0 + door_height
        positions = [
            (
                cx + rx * math.cos(2.0 * math.pi * s / room_shape_sides),
                cy + ry * math.sin(2.0 * math.pi * s / room_shape_sides),
            )
            for s in range(room_shape_sides)
        ]
        for s in open_edges:
            x0e, y0e = positions[s]
            x1e, y1e = positions[(s + 1) % room_shape_sides]
            length = math.hypot(x1e - x0e, y1e - y0e)
            if length < 1e-6 or length <= 2 * frame_thickness:
                continue  # opening too narrow for two inset posts to fit without overlapping
            tx, ty = (x1e - x0e) / length, (y1e - y0e) / length
            ecx, ecy = (x0e + x1e) / 2.0, (y0e + y1e) / 2.0
            half_span = length / 2.0

            near_a, near_b = -half_span, -half_span + frame_thickness
            far_b, far_a = half_span, half_span - frame_thickness
            add_oriented_box(
                ecx + tx * near_a, ecy + ty * near_a, ecx + tx * near_b, ecy + ty * near_b,
                half_frame, z0, z1, floor_touching=True,
            )
            add_oriented_box(
                ecx + tx * far_a, ecy + ty * far_a, ecx + tx * far_b, ecy + ty * far_b,
                half_frame, z0, z1, floor_touching=True,
            )
            if door_style == 'FLAT':
                add_oriented_box(
                    ecx + tx * near_a, ecy + ty * near_a, ecx + tx * far_b, ecy + ty * far_b,
                    half_frame, z1, z1 + frame_thickness, floor_touching=False,
                )
            else:
                add_arch_silhouette_oriented(ecx, ecy, tx, ty, half_span, half_frame, z1, arch_height, door_style)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    for poly, mat_idx in zip(mesh.polygons, material_indices):
        poly.material_index = mat_idx
    _add_planar_uv_map(mesh, uv_tile_size)
    return mesh


def _build_stair_mesh(
    stair_runs, tile_size, level_height, steps_per_tile, name, organic_amount=0.0, uv_tile_size=1.0,
):
    """Fully-baked ascending stair geometry, same reasoning as
    _build_wall_mesh: plain Python boxes rather than a Geometry Nodes
    instancing pass. stair_runs is a list of {'z': z, 'segments': [(x, y,
    rotation, length), ...]} dicts (see _read_stair_runs) -- (x, y) is a
    segment's own lowest/starting tile, rotation is one of the four
    cardinal values baked into tile_rotation, and length is how many
    tiles long that segment is. 'segments' has one entry for an ordinary
    straight run, two for a bent one (see WFC_Level_Solver.
    stair_bend_chance) with a flat landing between them. The climb is
    spread across the WHOLE run (every segment combined) -- steps_per_tile
    * total_tiles boxes total, each one step taller than the last -- rather
    than always cramming a full level's rise into a single tile, which is
    what made stairs steep. A bent run's second segment continues the
    SAME cumulative step/height progression its first segment left off at
    (exactly matching the landing tile's own baked z_offset -- both derive
    the split point from the same climb1_len/total_tiles proportion), not
    a fresh climb starting over from the floor.

    organic_amount (meters, 0 = off) jitters each tread's WIDTH only
    (worn-stone edges), never its depth or height -- the run's cumulative
    depth and rise have to land exactly on the room's far buffer tile and
    the upper floor's height (already relied on for the hole/wall
    placement), so only the axis that can't break that stays untouched."""
    half = tile_size / 2.0

    verts = []
    faces = []

    def add_box(local_xy, z0, z1, cx, cy, angle):
        # Same winding fix as _build_wall_mesh's add_box (rotation doesn't
        # change the winding/normal relationship -- it's a proper rotation
        # applied uniformly to every vertex).
        #
        # No bottom face: every step's z0 is the SAME as the run's entry
        # floor level regardless of how far along the run it is (see the
        # loop below), and the room floor under a stair run sits at that
        # exact same level -- so every step's bottom is always coincident
        # with, and hidden behind, real floor geometry underneath it. Same
        # reasoning/fix as _build_wall_mesh's add_box.
        c, s = math.cos(angle), math.sin(angle)
        i = len(verts)
        for lx, ly in local_xy:
            verts.append((cx + lx * c - ly * s, cy + lx * s + ly * c, z0))
        for lx, ly in local_xy:
            verts.append((cx + lx * c - ly * s, cy + lx * s + ly * c, z1))
        faces.append((i + 4, i + 5, i + 6, i + 7))  # top (tread)
        faces.append((i + 5, i + 4, i + 0, i + 1))
        faces.append((i + 6, i + 5, i + 1, i + 2))
        faces.append((i + 7, i + 6, i + 2, i + 3))
        faces.append((i + 4, i + 7, i + 3, i + 0))

    for run in stair_runs:
        z = run['z']
        segments = run['segments']
        total_tiles = sum(seg[3] for seg in segments)
        total_steps = max(1, steps_per_tile * total_tiles)
        step_depth = tile_size / steps_per_tile
        step_height = level_height / total_steps
        z0 = z * level_height
        step_offset = 0  # cumulative step count from any earlier segment in this same run
        for x, y, rot, length in segments:
            cx = x * tile_size
            cy = y * tile_size
            seg_steps = steps_per_tile * length
            for i in range(seg_steps):
                rise = step_height * (step_offset + i + 1)
                y0 = -half + step_depth * i
                y1 = y0 + step_depth
                hw = half + (random.uniform(-organic_amount, organic_amount) if organic_amount > 0 else 0.0)
                corners = [(-hw, y0), (hw, y0), (hw, y1), (-hw, y1)]
                add_box(corners, z0, z0 + rise, cx, cy, rot)
            step_offset += seg_steps

    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    _add_planar_uv_map(mesh, uv_tile_size)
    return mesh


def _build_ramp_mesh(stair_runs, tile_size, level_height, name, organic_amount=0.0, uv_tile_size=1.0):
    """One continuous sloped ramp per run instead of discrete steps -- same
    stair_runs data as _build_stair_mesh (same rooms, same buffer, same
    orientation fix, same segment-list shape for a bent run; this only
    swaps the mesh representation), better suited to caves/open terrain
    than a boxy staircase. The ramp tapers to a flush zero-height edge at
    the entry (matching the lower floor exactly, no lip to trip on) and
    reaches full level_height at the exit edge (matching the upper floor)
    -- for a bent run, a second segment's own ramp continues smoothly from
    the height its first segment's ramp already reached (matching the
    landing tile's own baked z_offset), rather than tapering back to zero
    at the landing.

    With organic_amount == 0 (the default), the whole run is a single
    smooth-sided wedge. With organic_amount > 0 it's built from several
    segments instead, each boundary's width independently jittered for a
    hand-carved edge -- except the very first and last boundaries, which
    stay exactly tile-width so the ramp still joins cleanly with the floor
    tiles on either end (no gap or overlap where it meets real floor
    geometry). Every segment shares the same flat z0 base and reuses
    _build_stair_mesh's add_box vertex/face ordering (just with the near
    face's height allowed to be 0, degenerating cleanly into the same
    triangle-based wedge used for the single-segment case)."""
    half = tile_size / 2.0
    segments = 6 if organic_amount > 0 else 1

    verts = []
    faces = []

    def add_segment(cx, cy, angle, y0, y1, h0, h1, w0, w1, z0):
        c, s = math.cos(angle), math.sin(angle)

        def to_world(lx, ly):
            return (cx + lx * c - ly * s, cy + lx * s + ly * c)

        i = len(verts)
        blx, bly = to_world(-w0, y0)
        brx, bry = to_world(w0, y0)
        frx, fry = to_world(w1, y1)
        flx, fly = to_world(-w1, y1)

        verts.append((blx, bly, z0))        # 0 near-bottom-left
        verts.append((brx, bry, z0))        # 1 near-bottom-right
        verts.append((frx, fry, z0))        # 2 far-bottom-right
        verts.append((flx, fly, z0))        # 3 far-bottom-left
        verts.append((blx, bly, z0 + h0))   # 4 near-top-left  (== vert 0 when h0 == 0)
        verts.append((brx, bry, z0 + h0))   # 5 near-top-right (== vert 1 when h0 == 0)
        verts.append((frx, fry, z0 + h1))   # 6 far-top-right
        verts.append((flx, fly, z0 + h1))   # 7 far-top-left

        # Same winding fix as _build_wall_mesh's add_box -- see its comment.
        # No bottom face: z0 is the run's entry floor level for every
        # segment along the run, same as _build_stair_mesh's add_box, and
        # for the identical reason -- always coincident with the real
        # floor underneath.
        faces.append((i + 4, i + 5, i + 6, i + 7))  # sloped top (the walkable surface)
        faces.append((i + 5, i + 4, i + 0, i + 1))  # near wall (degenerate when h0 == 0)
        faces.append((i + 6, i + 5, i + 1, i + 2))  # right wall
        faces.append((i + 7, i + 6, i + 2, i + 3))  # far wall
        faces.append((i + 4, i + 7, i + 3, i + 0))  # left wall

    for run in stair_runs:
        z = run['z']
        run_segments = run['segments']
        total_tiles = sum(seg[3] for seg in run_segments)
        z0 = z * level_height
        height_offset = 0.0  # cumulative rise from any earlier segment in this same run
        for x, y, rot, length in run_segments:
            cx = x * tile_size
            cy = y * tile_size
            run_span = tile_size * length
            seg_span = run_span / segments
            seg_total_height = level_height * length / total_tiles

            heights = [height_offset + seg_total_height * (k / segments) for k in range(segments + 1)]
            widths = [half for _ in range(segments + 1)]
            for k in range(1, segments):  # leave the two ends at exactly tile width
                widths[k] = half + random.uniform(-organic_amount, organic_amount)

            for k in range(segments):
                y0 = -half + seg_span * k
                y1 = y0 + seg_span
                add_segment(cx, cy, rot, y0, y1, heights[k], heights[k + 1], widths[k], widths[k + 1], z0)
            height_offset += seg_total_height

    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    _add_planar_uv_map(mesh, uv_tile_size)
    return mesh


def _read_stair_runs(blueprint_obj, tile_size, level_height):
    """Reads tile_id/tile_rotation/stair_run_id/stair_segment_index off the
    blueprint mesh and groups stair cells back into continuous runs, for
    the stairs operator (which needs one run per stairwell instead of one
    per tile, to build a single continuous stair/ramp mesh rather than
    len(run) disconnected single-tile ones).

    Returns a list of {'z': gz, 'segments': [(start_x, start_y, rotation,
    length), ...]} dicts, or None if the blueprint predates these
    attributes. 'segments' has exactly one entry for an ordinary straight
    run (the only shape that existed before bent stairwells -- see
    WFC_Level_Solver.stair_bend_chance) or two for a bent one, ordered
    first-climbed-first via the baked stair_segment_index attribute
    directly rather than inferred from geometry afterward."""
    mesh = blueprint_obj.data
    tile_id_layer = mesh.attributes.get("tile_id")
    tile_rot_layer = mesh.attributes.get("tile_rotation")
    run_id_layer = mesh.attributes.get("stair_run_id")
    segment_layer = mesh.attributes.get("stair_segment_index")
    if tile_id_layer is None or tile_rot_layer is None or run_id_layer is None or segment_layer is None:
        return None

    # Bulk-read via foreach_get instead of per-vertex attribute access --
    # see _read_blueprint_points for why. This function filters to
    # TILE_STAIR specifically (not "any walkable" like that helper), so
    # it stays a standalone bulk read rather than reusing it directly.
    n = len(mesh.vertices)
    coords = [0.0] * (n * 3)
    mesh.vertices.foreach_get("co", coords)
    tile_ids = [0] * n
    tile_id_layer.data.foreach_get("value", tile_ids)
    rotations = [0.0] * n
    tile_rot_layer.data.foreach_get("value", rotations)
    run_ids = [0] * n
    run_id_layer.data.foreach_get("value", run_ids)
    segment_indices = [0] * n
    segment_layer.data.foreach_get("value", segment_indices)

    # Stairwell cells are never continuous-elevation candidates (see
    # WFC_Level_Solver._apply_continuous_elevation), and a bent run's own
    # landing tile is never itself a TILE_STAIR cell (see
    # _carve_bent_stair_path -- it's excluded from this collection
    # entirely, same as it's excluded from any run's tile COUNT), so
    # every cell collected here has an exact world-Z with no offset to
    # account for -- rounding it back to a grid index stays exact.
    cells_by_run_segment = {}  # (run_id, segment_index) -> [(gx,gy,gz,rot), ...]
    for i in range(n):
        if tile_ids[i] != TILE_STAIR:
            continue
        gx = round(coords[i * 3] / tile_size)
        gy = round(coords[i * 3 + 1] / tile_size)
        gz = round(coords[i * 3 + 2] / level_height)
        key = (run_ids[i], segment_indices[i])
        cells_by_run_segment.setdefault(key, []).append((gx, gy, gz, rotations[i]))

    runs_by_id = {}
    for (run_id, seg_idx), cells in cells_by_run_segment.items():
        _, _, gz0, rot = cells[0]
        dx, dy = _direction_for_rotation(rot)
        if dx or dy:
            start = min(cells, key=lambda c: c[0] * dx + c[1] * dy)
        else:
            start = cells[0]
        run = runs_by_id.setdefault(run_id, {'z': gz0, 'segments': {}})
        run['segments'][seg_idx] = (start[0], start[1], rot, len(cells))

    stair_runs = []
    for run in runs_by_id.values():
        ordered_segments = [run['segments'][i] for i in sorted(run['segments'])]
        stair_runs.append({'z': run['z'], 'segments': ordered_segments})
    return stair_runs


def _format_debug_param_value(value):
    """Renders one scene property value as a Python literal, matching the
    `dict(wfc_foo=..., ...)` override style already used by
    tests/generate_test_blends.py's SCENARIOS list -- so a pasted snapshot
    is directly reusable there too, not just readable. Bool must be
    checked before int (bool is an int subclass in Python); floats are
    rounded since Blender's UI sliders carry more float noise than anyone
    debugging a layout needs to see."""
    if isinstance(value, bool):
        return repr(value)
    if isinstance(value, float):
        return repr(round(value, 4))
    if isinstance(value, (int, str)):
        return repr(value)
    try:
        return repr(tuple(round(v, 4) if isinstance(v, float) else v for v in value))
    except TypeError:
        return repr(value)


def _update_debug_snapshot(context, step_label):
    """Records every current wfc_* scene setting into wfc_debug_params,
    purely for human debugging -- lets the user paste the exact settings
    behind a specific generated level back into a bug report instead of
    re-describing slider positions from memory. Property names are
    discovered from the Scene type's own bl_rna rather than hardcoded here,
    so this never drifts out of sync as properties are added/removed in
    register(). Called at the end of every Step operator (not just
    Blueprint), always snapshotting the full settings set, since a bug
    report might hinge on a Walls/Doors/Props-only setting just as easily
    as a layout one."""
    scene = context.scene
    names = sorted(
        p.identifier for p in scene.bl_rna.properties
        if p.identifier.startswith("wfc_") and p.identifier != "wfc_debug_params"
    )
    lines = [f"    {name}={_format_debug_param_value(getattr(scene, name))}," for name in names]
    scene.wfc_debug_params = (
        f"# Level Architect debug snapshot -- captured after '{step_label}'\n"
        "dict(\n" + "\n".join(lines) + "\n)"
    )


class OBJECT_OT_CopyLevelArchitectParams(bpy.types.Operator):
    bl_idname = "object.copy_level_architect_params"
    bl_label = "Copy Parameters"
    bl_description = "Copy the settings behind the most recent generation step to the clipboard"

    def execute(self, context):
        text = context.scene.wfc_debug_params
        if not text:
            self.report({'WARNING'}, "Nothing generated yet -- run a step first.")
            return {'CANCELLED'}
        context.window_manager.clipboard = text
        self.report({'INFO'}, "Parameters copied to clipboard.")
        return {'FINISHED'}


def _objects_matching_prefix(base_name):
    """Every object whose name is exactly base_name, or base_name +
    "_..." (a grouped variant -- e.g. "_Floor0", "_Floor0_02" -- from
    Per Floor/Per Stair grouping, which can change between generations).
    Shared by _remove_objects_by_prefix (what a fresh generation deletes)
    and OBJECT_OT_FreezeForTextureWork (what a freeze protects) so both
    agree on exactly the same set with no risk of the two definitions
    drifting apart."""
    return [
        obj for obj in bpy.data.objects
        if obj.name == base_name or obj.name.startswith(base_name + "_")
    ]


def _remove_objects_by_prefix(base_name):
    """Removes the exact single base_name object from an older generation,
    plus any grouped variant (base_name + "_...") from a previous run --
    grouping mode and floor/stair count can both change between
    generations, so matching by prefix is what actually clears everything
    a prior run could have created, not just today's object names.

    Data-block cleanup follows the object's own type -- LIGHT objects
    (see PROPS_LIGHT_NAME_PREFIX) own a Light data-block, not a Mesh, and
    removing the wrong one would either error or silently leak."""
    for obj in _objects_matching_prefix(base_name):
        data = obj.data
        obj_type = obj.type
        bpy.data.objects.remove(obj, do_unlink=True)
        if data and data.users == 0:
            if obj_type == 'LIGHT':
                bpy.data.lights.remove(data)
            else:
                bpy.data.meshes.remove(data)


def _collection_contains(ancestor, candidate):
    """True if `candidate` is `ancestor` itself, or lives anywhere inside
    it (searched recursively through child collections)."""
    if candidate is ancestor:
        return True
    return any(_collection_contains(child, candidate) for child in ancestor.children)


def _get_or_create_collection(name, parent):
    """Returns the collection with this name, creating and linking a new
    one under `parent` if it doesn't exist yet -- re-running props/split
    generation reuses the same collection tree instead of spawning
    duplicate nested collections each time.

    If linking the existing collection under `parent` would create a
    cycle (`parent` IS that collection, or already lives somewhere inside
    it), leave it where it already is instead of trying to relink it --
    Blender raises a RuntimeError for that relink attempt otherwise.
    Found from a real crash: `context.collection` is whatever collection
    is currently ACTIVE in the outliner, which Blender itself moves to the
    last one a previous operator run created/linked into -- running
    Separate by Floor/Room a second time with the active collection still
    sitting inside last time's own "Floor 0 - Rooms" tried to link this
    call's top-level "Procedural Level Blueprint (Split)" collection
    (found by name, from the FIRST run) as a child of its own descendant,
    which Blender correctly refuses. Generate Props builds an equally
    nested tree (Level Props > Torches/Lights/Decoration) the same way and
    was equally exposed to this, just not yet hit by a report."""
    existing = bpy.data.collections.get(name)
    if existing is not None:
        if _collection_contains(existing, parent):
            return existing
        if not any(c is existing for c in parent.children):
            parent.children.link(existing)
        return existing
    new_collection = bpy.data.collections.new(name)
    parent.children.link(new_collection)
    return new_collection


def _read_blueprint_points(blueprint_obj, tile_size, level_height, extra_attrs=()):
    """Bulk-reads the blueprint's point cloud with foreach_get instead of
    per-vertex Python attribute access -- Walls/Doors/Stairs/Props each
    used to do `for i, vert in enumerate(mesh.vertices): vert.co.x, ...`,
    which touches Blender's Python/RNA wrapper once per vertex per
    attribute. foreach_get instead does one bulk C-level array copy per
    attribute regardless of vertex count, which is the standard fix for
    this exact pattern and matters once a level has thousands of tiles.

    Returns (walkable_cells, extra) -- walkable_cells is a set of
    (gx, gy, gz) grid tuples, extra is {attr_name: {cell: value}} for
    every name in extra_attrs that actually exists on this blueprint
    (older blueprints predating a given attribute just get an empty dict
    for that name, same graceful-degradation the per-vertex version had).
    Grid Z prefers the exact baked "level_z" attribute over inferring it
    from vertex position, same reasoning as every other caller of this
    pattern already used."""
    mesh = blueprint_obj.data
    n = len(mesh.vertices)

    coords = [0.0] * (n * 3)
    mesh.vertices.foreach_get("co", coords)

    tile_id_layer = mesh.attributes.get("tile_id")
    tile_ids = [0] * n
    tile_id_layer.data.foreach_get("value", tile_ids)

    level_z_layer = mesh.attributes.get("level_z")
    level_zs = [0] * n
    if level_z_layer is not None:
        level_z_layer.data.foreach_get("value", level_zs)

    extra_buffers = {}
    for name in extra_attrs:
        layer = mesh.attributes.get(name)
        if layer is None:
            continue
        buf = [0] * n
        layer.data.foreach_get("value", buf)
        extra_buffers[name] = buf

    walkable_cells = set()
    extra = {name: {} for name in extra_attrs}
    for i in range(n):
        if tile_ids[i] not in WALKABLE:
            continue
        gx = round(coords[i * 3] / tile_size)
        gy = round(coords[i * 3 + 1] / tile_size)
        gz = level_zs[i] if level_z_layer is not None else round(coords[i * 3 + 2] / level_height)
        cell = (gx, gy, gz)
        walkable_cells.add(cell)
        for name, buf in extra_buffers.items():
            extra[name][cell] = buf[i]

    return walkable_cells, extra


def _build_torch_mesh(torches, tile_size, torch_height, name, uv_tile_size=1.0):
    """Fully-baked wall-mounted torch placeholder: a thin bracket box
    protruding from the wall face, capped by a slightly larger "flame"
    box at its outer end -- two material slots (bracket, flame), same
    per-polygon material_index assignment pattern as
    OBJECT_OT_SeparateLevelByFloor uses for its own rebuilt meshes. Real
    illumination comes from a separate Point light placed at each flame
    position (see OBJECT_OT_GenerateLevelProps) -- this mesh is only the
    visual placeholder.

    torches: list of (x, y, z0, dx, dy) -- (x, y) is the wall-adjacent
    walkable cell's grid position, z0 is that cell's own WORLD floor Z
    (already includes any continuous-elevation offset -- see
    WFC_Level_Solver._apply_continuous_elevation), (dx, dy) points from
    the cell TOWARD the wall it's mounted on (the same convention
    _build_wall_mesh's own neighbor checks use), so the torch protrudes
    into the room along the opposite direction."""
    haft_len = 0.3
    haft_half_w = 0.045
    flame_half = 0.09

    verts = []
    faces = []
    material_indices = []

    def add_box(cx0, cy0, cx1, cy1, z0, z1, mat_idx):
        # Same winding fix as _build_wall_mesh's add_box -- see its
        # comment. Unlike Walls/Doors/Stairs/Ramps/Decoration, NEITHER box
        # this builds (haft or flame) is floor-touching -- both are wall-
        # mounted, floating at roughly torch_height above the actual
        # floor -- so there's no always-hidden bottom face to drop here;
        # the haft's underside in particular is genuinely visible to
        # anyone standing beneath it. Deliberately left as a full 6-face
        # box, unlike the other builders' hidden-face cleanup.
        i = len(verts)
        verts.extend([
            (cx0, cy0, z0), (cx1, cy0, z0), (cx1, cy1, z0), (cx0, cy1, z0),
            (cx0, cy0, z1), (cx1, cy0, z1), (cx1, cy1, z1), (cx0, cy1, z1),
        ])
        faces.append((i + 3, i + 2, i + 1, i + 0))
        faces.append((i + 4, i + 5, i + 6, i + 7))
        faces.append((i + 5, i + 4, i + 0, i + 1))
        faces.append((i + 6, i + 5, i + 1, i + 2))
        faces.append((i + 7, i + 6, i + 2, i + 3))
        faces.append((i + 4, i + 7, i + 3, i + 0))
        material_indices.extend([mat_idx] * 6)

    def add_oriented(x0, y0, x1, y1, half_w, z0, z1, mat_idx):
        # same face layout as add_box, along an arbitrary horizontal direction
        dx_, dy_ = x1 - x0, y1 - y0
        ln = math.hypot(dx_, dy_)
        px_, py_ = -dy_ / ln * half_w, dx_ / ln * half_w
        i = len(verts)
        c4 = [(x0 - px_, y0 - py_), (x1 - px_, y1 - py_), (x1 + px_, y1 + py_), (x0 + px_, y0 + py_)]
        verts.extend((cx_, cy_, z0) for cx_, cy_ in c4)
        verts.extend((cx_, cy_, z1) for cx_, cy_ in c4)
        faces.append((i + 3, i + 2, i + 1, i + 0))
        faces.append((i + 4, i + 5, i + 6, i + 7))
        faces.append((i + 5, i + 4, i + 0, i + 1))
        faces.append((i + 6, i + 5, i + 1, i + 2))
        faces.append((i + 7, i + 6, i + 2, i + 3))
        faces.append((i + 4, i + 7, i + 3, i + 0))
        material_indices.extend([mat_idx] * 6)

    for torch in torches:
        x, y, z0, dx, dy = torch[:5]
        top_z = z0 + torch_height
        haft_z0 = top_z - haft_half_w * 2.0
        if len(torch) == 7:
            # mounted on a curved ring: (dx, dy) points toward the wall, (wx, wy) is where it touches
            wx, wy = torch[5], torch[6]
            ox, oy = wx - dx * haft_len, wy - dy * haft_len
            add_oriented(wx, wy, ox, oy, haft_half_w, haft_z0, top_z, 0)
            add_box(ox - flame_half, oy - flame_half, ox + flame_half, oy + flame_half,
                    top_z - flame_half, top_z + flame_half, 1)
            continue
        if dx != 0:
            wall_x = (x + 0.5 * dx) * tile_size
            outer_x = wall_x - dx * haft_len  # protrudes opposite the wall direction
            cy_center = y * tile_size
            x0, x1 = sorted((wall_x, outer_x))
            add_box(x0, cy_center - haft_half_w, x1, cy_center + haft_half_w, haft_z0, top_z, 0)
            flame_cx, flame_cy = outer_x, cy_center
        else:
            wall_y = (y + 0.5 * dy) * tile_size
            outer_y = wall_y - dy * haft_len
            cx_center = x * tile_size
            y0, y1 = sorted((wall_y, outer_y))
            add_box(cx_center - haft_half_w, y0, cx_center + haft_half_w, y1, haft_z0, top_z, 0)
            flame_cx, flame_cy = cx_center, outer_y

        add_box(
            flame_cx - flame_half, flame_cy - flame_half, flame_cx + flame_half, flame_cy + flame_half,
            top_z - flame_half, top_z + flame_half, 1,
        )

    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    _add_planar_uv_map(mesh, uv_tile_size)
    for poly, mat_idx in zip(mesh.polygons, material_indices):
        poly.material_index = mat_idx
    return mesh


# Composite decoration kinds beyond the original CRATE/BARREL/CONE. Each is
# a short list of box/cylinder parts (see _build_decoration_mesh.add_part)
# sized in meters for a 2 m tile and scaled by tile_size / 2. Front faces +X
# in the prop's local frame. The idea for these shapes (and the theme
# groupings below) comes from the sibling Dracula adventure project's prop
# library, rebuilt here as plain primitives so the addon stays dependency-
# free and everything stays in one baked mesh.
PROP_THEMES = {
    # theme -> (floor kinds, wall kinds); kinds picked uniformly
    'CRYPT': (('COFFIN', 'TOMB', 'COLUMN', 'CANDLESTAND', 'CRATE'), ('COLUMN',)),
    'LIBRARY': (('TABLE', 'CHAIR', 'CANDLESTAND', 'CHEST'), ('BOOKSHELF', 'BOOKSHELF', 'CHEST')),
    'HALL': (('TABLE', 'CHAIR', 'CHAIR', 'BARREL', 'CANDLESTAND'), ('CHEST', 'BARREL')),
    'BEDROOM': (('BED', 'CHEST', 'CHAIR', 'CANDLESTAND'), ('BED', 'BOOKSHELF', 'CHEST')),
    'STORAGE': (('CRATE', 'BARREL', 'BARREL', 'CHEST'), ('CRATE', 'BARREL')),
}


def _composite_prop_parts(kind, k):
    """Parts list for a composite prop kind; k = tile_size / 2.0. A part's
    material is not tracked -- decoration shares one slot."""
    def box(lx, ly, dz, hx, hy, h):
        return ('box', lx * k, ly * k, dz * k, hx * k, hy * k, h * k)

    def cyl(lx, ly, dz, r, h):
        return ('cyl', lx * k, ly * k, dz * k, r * k, h * k)

    if kind == 'TABLE':
        parts = [box(0, 0, 0.7, 0.55, 0.3, 0.06)]
        parts += [box(sx * 0.48, sy * 0.24, 0, 0.04, 0.04, 0.7) for sx in (-1, 1) for sy in (-1, 1)]
        return parts
    if kind == 'CHAIR':
        parts = [box(0, 0, 0.42, 0.2, 0.2, 0.05), box(-0.18, 0, 0.47, 0.025, 0.2, 0.45)]
        parts += [box(sx * 0.16, sy * 0.16, 0, 0.025, 0.025, 0.42) for sx in (-1, 1) for sy in (-1, 1)]
        return parts
    if kind == 'CHEST':
        return [box(0, 0, 0, 0.35, 0.22, 0.32), box(0, 0, 0.32, 0.37, 0.24, 0.1),
                box(0.35, 0, 0.18, 0.02, 0.05, 0.1)]
    if kind == 'BOOKSHELF':
        # back at -X, open front at +X; shelves + a few book blocks
        parts = [box(-0.17, 0, 0, 0.03, 0.45, 2.0),
                 box(0, -0.43, 0, 0.2, 0.03, 2.0), box(0, 0.43, 0, 0.2, 0.03, 2.0)]
        parts += [box(0, 0, z, 0.2, 0.43, 0.04) for z in (0.0, 0.5, 1.0, 1.5, 1.96)]
        for z in (0.04, 0.54, 1.04, 1.54):
            for i, ly in enumerate((-0.33, -0.2, -0.05, 0.1, 0.26)):
                parts.append(box(0.0, ly, z, 0.15, 0.05, 0.28 + 0.04 * (i % 3)))
        return parts
    if kind == 'COLUMN':
        return [box(0, 0, 0, 0.26, 0.26, 0.18), cyl(0, 0, 0.18, 0.18, 2.4), box(0, 0, 2.58, 0.27, 0.27, 0.18)]
    if kind == 'COFFIN':
        return [box(0, 0, 0.0, 0.85, 0.38, 0.1), box(0, 0, 0.1, 0.8, 0.34, 0.38),
                box(0.05, 0, 0.48, 0.82, 0.36, 0.06)]
    if kind == 'TOMB':
        return [box(0, 0, 0, 0.8, 0.45, 0.5), box(0, 0, 0.5, 0.85, 0.5, 0.1)]
    if kind == 'BED':
        # head at -X
        parts = [box(0, 0, 0.2, 0.8, 0.5, 0.18), box(0.05, 0, 0.38, 0.72, 0.46, 0.14),
                 box(-0.8, 0, 0.0, 0.05, 0.5, 0.8)]
        parts += [box(sx * 0.75, sy * 0.46, 0, 0.04, 0.04, 0.2) for sx in (-1, 1) for sy in (-1, 1)]
        parts.append(box(-0.6, 0, 0.52, 0.15, 0.35, 0.1))
        return parts
    if kind == 'CANDLESTAND':
        return [cyl(0, 0, 0, 0.14, 0.04), cyl(0, 0, 0.04, 0.03, 1.0),
                cyl(0, 0, 1.04, 0.1, 0.03)] + [cyl(dx * 0.07, dy * 0.07, 1.07, 0.02, 0.18)
                                                 for dx, dy in ((1, 0), (-1, 0), (0, 1))]
    return []


def _prop_fits(kind, rot, ox, oy, wall_dirs, half_room, tile_size):
    """True if a prop at offset (ox, oy) from its cell centre, rotated by
    rot (any angle; extents come from the rotated local bounding box),
    stays inside half_room on every side that has a wall and inside the
    cell on every open side (so it never pokes into a distant wall)."""
    xmin, xmax, ymin, ymax = _prop_local_bounds(kind, tile_size)
    c, s_ = math.cos(rot), math.sin(rot)
    pts = [(lx * c - ly * s_, lx * s_ + ly * c) for lx in (xmin, xmax) for ly in (ymin, ymax)]
    for dx, dy in HORIZONTAL_NEIGHBORS:
        reach = max(px * dx + py * dy for px, py in pts) + ox * dx + oy * dy
        limit = half_room if (dx, dy) in wall_dirs else tile_size / 2.0
        if reach > limit + 1e-6:
            return False
    return True


def _prop_local_bounds(kind, tile_size):
    """(xmin, xmax, ymin, ymax) of a prop in its local frame (front = +X),
    from the same parts _build_decoration_mesh emits -- lets placement keep
    a prop clear of the wall without hand-tuned depth constants."""
    if kind == 'CRATE':
        r = tile_size * 0.22
        return (-r, r, -r, r)
    if kind in ('BARREL', 'CONE'):
        r = tile_size * (0.18 if kind == 'BARREL' else 0.2)
        return (-r, r, -r, r)
    xs0, xs1, ys0, ys1 = [], [], [], []
    for part in _composite_prop_parts(kind, tile_size / 2.0):
        hx = part[4]
        hy = part[5] if part[0] == 'box' else part[4]
        xs0.append(part[1] - hx)
        xs1.append(part[1] + hx)
        ys0.append(part[2] - hy)
        ys1.append(part[2] + hy)
    return (min(xs0), max(xs1), min(ys0), max(ys1))


def _build_decoration_mesh(props, tile_size, name, uv_tile_size=1.0):
    """Fully-baked placeholder decoration -- crates, barrels, and simple
    cone-topped props (chests/furniture/dressing in general), scattered
    per room by OBJECT_OT_GenerateLevelProps. One shared material slot;
    variety comes from which primitive kind, its rotation, and where it
    lands, not from per-piece detail -- these are explicitly placeholders
    for whatever real asset kit eventually replaces them.

    props: list of (cx, cy, z0, kind, rot) -- (cx, cy, z0) is the WORLD
    position to place the base of the prop at (z0 already includes any
    continuous-elevation offset), kind is 'CRATE' / 'BARREL' / 'CONE',
    rot is a random Z-rotation in radians (only meaningful for CRATE,
    since barrel/cone are rotationally symmetric about Z). Any other kind
    is a composite from _composite_prop_parts (see PROP_THEMES)."""
    verts = []
    faces = []

    def add_box(cx, cy, z0, half_w, half_d, height, angle, bottom=False):
        # Same winding fix as _build_wall_mesh's add_box -- see its
        # comment. No bottom face: z0 is always the prop's real resting
        # floor level (its own docstring above), so the base is always
        # coincident with, and hidden behind, the floor underneath it --
        # same reasoning/fix as _build_wall_mesh's add_box.
        c, s = math.cos(angle), math.sin(angle)
        local = [(-half_w, -half_d), (half_w, -half_d), (half_w, half_d), (-half_w, half_d)]
        i = len(verts)
        for lx, ly in local:
            verts.append((cx + lx * c - ly * s, cy + lx * s + ly * c, z0))
        for lx, ly in local:
            verts.append((cx + lx * c - ly * s, cy + lx * s + ly * c, z0 + height))
        faces.append((i + 4, i + 5, i + 6, i + 7))
        if bottom:  # raised composite parts (table tops, bed frames) show their underside
            faces.append((i + 3, i + 2, i + 1, i + 0))
        faces.append((i + 5, i + 4, i + 0, i + 1))
        faces.append((i + 6, i + 5, i + 1, i + 2))
        faces.append((i + 7, i + 6, i + 2, i + 3))
        faces.append((i + 4, i + 7, i + 3, i + 0))

    def add_cylinder(cx, cy, z0, radius, height, sides=10, bottom=False):
        # No bottom cap, same reasoning as add_box above -- a barrel always
        # rests directly on real floor geometry.
        i = len(verts)
        for k in range(sides):
            a = 2.0 * math.pi * k / sides
            verts.append((cx + radius * math.cos(a), cy + radius * math.sin(a), z0))
        for k in range(sides):
            a = 2.0 * math.pi * k / sides
            verts.append((cx + radius * math.cos(a), cy + radius * math.sin(a), z0 + height))
        faces.append(tuple(range(i + sides, i + 2 * sides)))
        if bottom:
            faces.append(tuple(reversed(range(i, i + sides))))
        for k in range(sides):
            a0, a1 = i + k, i + (k + 1) % sides
            b0, b1 = i + sides + k, i + sides + (k + 1) % sides
            faces.append((a0, a1, b1, b0))

    def add_cone(cx, cy, z0, radius, height, sides=10):
        # No base cap, same reasoning as add_box above -- a cone prop
        # always rests directly on real floor geometry.
        i = len(verts)
        for k in range(sides):
            a = 2.0 * math.pi * k / sides
            verts.append((cx + radius * math.cos(a), cy + radius * math.sin(a), z0))
        apex = len(verts)
        verts.append((cx, cy, z0 + height))
        for k in range(sides):
            a0, a1 = i + k, i + (k + 1) % sides
            faces.append((a0, a1, apex))

    def add_part(cx, cy, z0, rot, part):
        # Composite props: ('box', lx, ly, dz, half_x, half_y, h) or
        # ('cyl', lx, ly, dz, r, h), in the prop's local frame (front = +X),
        # rotated by rot about the prop origin and lifted dz above z0.
        # Parts of a composite overlap on purpose (legs into tops, etc.),
        # so nothing relies on exact face contact and no bottom-face
        # culling is needed between them; the whole prop still rests on
        # the floor, so the lowest parts keep the usual hidden base.
        c, s_ = math.cos(rot), math.sin(rot)
        lx, ly = part[1], part[2]
        px, py = cx + lx * c - ly * s_, cy + lx * s_ + ly * c
        if part[0] == 'box':
            add_box(px, py, z0 + part[3], part[4], part[5], part[6], rot, bottom=part[3] > 1e-6)
        else:
            add_cylinder(px, py, z0 + part[3], part[4], part[5], bottom=part[3] > 1e-6)

    for cx, cy, z0, kind, rot in props:
        if kind == 'CRATE':
            add_box(cx, cy, z0, tile_size * 0.22, tile_size * 0.22, tile_size * 0.4, rot)
        elif kind == 'BARREL':
            add_cylinder(cx, cy, z0, tile_size * 0.18, tile_size * 0.45)
        elif kind == 'CONE':
            add_cone(cx, cy, z0, tile_size * 0.2, tile_size * 0.5)
        else:
            for part in _composite_prop_parts(kind, tile_size / 2.0):
                add_part(cx, cy, z0, rot, part)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    _add_planar_uv_map(mesh, uv_tile_size)
    return mesh


class OBJECT_OT_GenerateLevelWalls(bpy.types.Operator):
    """Builds the wall silhouette object(s) from the already-generated
    blueprint's tile_id data -- run "Generate Game Blueprint" first.
    Single Object (default) or one object per logical floor, per the Wall
    Grouping setting -- lets you isolate/hide/select a whole floor's walls
    directly instead of relying on Select Linked, which can't tell a
    floor's split-level room from an unrelated island once Sub-Levels per
    Floor > 1 breaks vertex adjacency between a floor's own sub-heights."""
    bl_idname = "object.generate_level_walls"
    bl_label = "Generate Level Walls"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene

        blueprint_obj = bpy.data.objects.get(BLUEPRINT_OBJECT_NAME)
        if blueprint_obj is None or blueprint_obj.type != 'MESH':
            self.report({'ERROR'}, "Generate a Game Blueprint first.")
            return {'CANCELLED'}

        if blueprint_obj.data.attributes.get("tile_id") is None:
            self.report({'ERROR'}, "Blueprint has no tile_id data -- regenerate it.")
            return {'CANCELLED'}

        tile_size = scene.wfc_tile_size
        level_height = _fine_level_height(scene)

        walkable_cells, extra = _read_blueprint_points(
            blueprint_obj, tile_size, level_height, ("z_offset", "tile_id", "tile_rotation", "room_id")
        )
        z_offsets = extra["z_offset"]
        room_id_grid = extra["room_id"]

        if not walkable_cells:
            self.report({'WARNING'}, "No walkable tiles found in the blueprint.")
            return {'CANCELLED'}

        # Round rooms get a real perimeter ring (see
        # _build_round_room_walls_mesh) instead of the blocky per-cell
        # wall _build_wall_mesh would otherwise still build for them --
        # room shape/bounding-box metadata was baked onto the Blueprint at
        # Step 1 time (see OBJECT_OT_GenerateGameBlueprint), since this
        # step deliberately never re-runs the solver.
        room_meta = json.loads(blueprint_obj.get("gla_room_meta", "[]"))
        round_room_ids = {i for i, r in enumerate(room_meta) if r['shape'] == 'ROUND'}
        skip_cells = {cell for cell, rid in room_id_grid.items() if rid in round_room_ids}

        # Corridor Stairs (see WFC_Level_Solver._corridor_stair_fits) has no
        # side walkway by design -- a walkable neighbor directly beside a
        # tread/landing is only ever checked for at THAT stairwell's own
        # placement time, so a corridor pathfound afterward can still end
        # up running alongside one (residual ~7-10% of stair cells, known
        # issue). Fixed here, at wall-generation time, rather than by
        # further tightening solver placement: every TILE_STAIR cell's two
        # PERPENDICULAR sides (derived from its baked travel rotation) are
        # forced to wall regardless of neighbor walkability. Room-based
        # stairs are untouched -- that same neighbor cell there is the
        # room's own intended walkway, not a placement gap, so this only
        # ever runs when Corridor Stairs is on.
        forced_wall_edges = None
        if scene.wfc_corridor_stairs:
            tile_ids = extra["tile_id"]
            tile_rotations = extra["tile_rotation"]
            forced_wall_edges = set()
            for cell in walkable_cells:
                if tile_ids.get(cell) == TILE_STAIR:
                    dx, dy = _direction_for_rotation(tile_rotations.get(cell, 0.0))
                    forced_wall_edges.add((cell, (-dy, dx)))
                    forced_wall_edges.add((cell, (dy, -dx)))

        _remove_objects_by_prefix(WALLS_OBJECT_NAME)
        _remove_objects_by_prefix(WALLS_ROUND_OBJECT_NAME)
        _remove_objects_by_prefix(WINDOWS_OBJECT_NAME)

        window_edges = _pick_window_edges(
            walkable_cells, room_id_grid, tile_size, scene.wfc_wall_height, scene.wfc_window_sill,
            scene.wfc_window_height, scene.wfc_window_chance, scene.wfc_seed,
            skip_cells=skip_cells, forced_wall_edges=forced_wall_edges,
        )
        window_kwargs = dict(
            window_edges=window_edges, window_width=scene.wfc_window_width,
            window_sill=scene.wfc_window_sill, window_height=scene.wfc_window_height,
        )
        masonry_walls = scene.wfc_wall_style == 'MASONRY'
        tint_map = room_tint_map(room_id_grid)   # neighbouring rooms get different brick tints
        accepted_windows = set()

        def _walls_mesh(cells, mesh_name, organic):
            if masonry_walls:
                mesh, ok = _build_masonry_wall_mesh(
                    cells, tile_size, level_height, scene.wfc_wall_height, scene.wfc_wall_thickness,
                    z_offsets=z_offsets, forced_wall_edges=forced_wall_edges, skip_cells=skip_cells,
                    ruin=scene.wfc_wall_ruin, seed=scene.wfc_seed, name=mesh_name,
                    room_ids=room_id_grid, room_colors=scene.wfc_masonry_room_colors, tint_map=tint_map, **window_kwargs,
                )
                accepted_windows.update(ok)
                return mesh
            return _build_wall_mesh(
                cells, tile_size, level_height, scene.wfc_wall_height, scene.wfc_wall_thickness,
                scene.wfc_wall_cap_top, mesh_name, organic_amount=organic, z_offsets=z_offsets,
                forced_wall_edges=forced_wall_edges, uv_tile_size=scene.wfc_uv_tile_size,
                skip_cells=skip_cells, **window_kwargs,
            )

        def _wall_materials(mesh_data):
            if masonry_walls:
                for mat_ in masonry_material_list(scene.wfc_masonry_room_colors):
                    mesh_data.materials.append(mat_)
            else:
                mesh_data.materials.append(wall_material)

        if scene.wfc_simple_materials:
            wall_material = get_or_create_simple_wall_material()
        else:
            wall_material = get_or_create_style_material(scene.wfc_style)

        # Organic Irregularity jitter is randomized, so seed it the same
        # way blueprint generation does -- reusing the level's own seed is
        # fine (it's just a different consumer of the same reproducible
        # value), and means re-running this step with the same seed always
        # gives the same jitter pattern.
        random.seed(scene.wfc_seed)
        organic_amount = scene.wfc_organic_amount

        # A wall's exposed-edge check only ever looks at same-Z neighbors
        # (see _build_wall_mesh), so splitting walkable_cells by floor
        # before building produces byte-identical geometry to one combined
        # call -- just as separate objects instead of separate faces.
        sub_levels = max(1, scene.wfc_sub_levels_per_floor)
        per_floor = scene.wfc_wall_grouping == 'PER_FLOOR'

        masonry_rings = scene.wfc_round_wall_style == 'MASONRY'

        def _add_round_ring(name, meta_for_floor):
            if masonry_rings:
                ring_mesh_data = _build_round_room_masonry_mesh(
                    meta_for_floor, room_id_grid, walkable_cells, tile_size, level_height,
                    scene.wfc_wall_height, scene.wfc_wall_thickness, z_offsets,
                    scene.wfc_door_style, scene.wfc_door_height, scene.wfc_wall_cap_top,
                    scene.wfc_seed, name, ruin=scene.wfc_round_wall_ruin, room_colors=scene.wfc_masonry_room_colors,
                    tint_map=tint_map,
                )
            else:
                ring_mesh_data = _build_round_room_walls_mesh(
                    meta_for_floor, room_id_grid, walkable_cells, tile_size, level_height,
                    scene.wfc_wall_height, scene.wfc_wall_thickness, scene.wfc_room_shape_sides,
                    z_offsets, name,
                )
            if not ring_mesh_data.vertices:
                bpy.data.meshes.remove(ring_mesh_data)
                return None
            ring_obj = bpy.data.objects.new(name, ring_mesh_data)
            context.collection.objects.link(ring_obj)
            if masonry_rings:
                for mat_ in masonry_material_list(scene.wfc_masonry_room_colors):
                    ring_mesh_data.materials.append(mat_)
                ring_obj["gla_masonry_ring"] = True
            else:
                ring_mesh_data.materials.append(wall_material)
            _add_viewport_color_attribute(ring_mesh_data)
            return ring_obj

        created = []
        if per_floor:
            cells_by_floor = {}
            for cell in walkable_cells:
                cells_by_floor.setdefault(cell[2] // sub_levels, set()).add(cell)
            for floor_idx in sorted(cells_by_floor):
                name = f"{WALLS_OBJECT_NAME}_Floor{floor_idx}"
                wall_mesh_data = _walls_mesh(cells_by_floor[floor_idx], name, organic_amount)
                if not wall_mesh_data.vertices:
                    bpy.data.meshes.remove(wall_mesh_data)
                else:
                    obj = bpy.data.objects.new(name, wall_mesh_data)
                    context.collection.objects.link(obj)
                    _wall_materials(wall_mesh_data)
                    _add_viewport_color_attribute(wall_mesh_data)
                    if masonry_walls:
                        obj["gla_masonry_ring"] = True
                    created.append(obj)

                meta_for_floor = [r for r in room_meta if r['z'] // sub_levels == floor_idx]
                ring_obj = _add_round_ring(f"{WALLS_ROUND_OBJECT_NAME}_Floor{floor_idx}", meta_for_floor)
                if ring_obj is not None:
                    created.append(ring_obj)
        else:
            wall_mesh_data = _walls_mesh(walkable_cells, WALLS_OBJECT_NAME, organic_amount)
            obj = bpy.data.objects.new(WALLS_OBJECT_NAME, wall_mesh_data)
            context.collection.objects.link(obj)
            _wall_materials(wall_mesh_data)
            _add_viewport_color_attribute(wall_mesh_data)
            if masonry_walls:
                obj["gla_masonry_ring"] = True
            created.append(obj)

            ring_obj = _add_round_ring(WALLS_ROUND_OBJECT_NAME, room_meta)
            if ring_obj is not None:
                created.append(ring_obj)

        if scene.wfc_wall_corner_rounding:
            for obj in created:
                if obj.get("gla_masonry_ring"):
                    continue  # smooth textured ring: a Bevel would only soften its stone details
                _add_corner_rounding_modifier(obj, scene.wfc_wall_corner_radius)

        # Rounding is applied before the window object is added on purpose:
        # frames/glass are separate geometry and must stay crisp.
        if masonry_walls:
            window_edges = accepted_windows  # only the openings the masonry builder could actually cut
        if window_edges:
            win_mesh = _build_window_mesh(
                window_edges, tile_size, level_height, scene.wfc_wall_thickness,
                scene.wfc_window_width, scene.wfc_window_sill, scene.wfc_window_height,
                scene.wfc_wall_height, z_offsets, WINDOWS_OBJECT_NAME,
                uv_tile_size=scene.wfc_uv_tile_size,
            )
            win_obj = bpy.data.objects.new(WINDOWS_OBJECT_NAME, win_mesh)
            context.collection.objects.link(win_obj)
            win_mesh.materials.append(get_or_create_window_frame_material())
            win_mesh.materials.append(get_or_create_window_glass_material())
            _add_viewport_color_attribute(win_mesh)
            created.append(win_obj)

        for obj in created:
            obj.select_set(True)
        if created:
            context.view_layer.objects.active = created[-1]

        self.report(
            {'INFO'},
            f"Walls generated from {len(walkable_cells)} exposed edges, in {len(created)} object(s)"
            f"{f', {len(window_edges)} windows' if window_edges else ''}."
        )
        _update_debug_snapshot(context, "Step 2: Generate Walls")
        return {'FINISHED'}


class OBJECT_OT_GenerateLevelStairs(bpy.types.Operator):
    """Builds stair object(s) from the already-generated blueprint's
    tile_id/tile_rotation data -- run "Generate Game Blueprint" first.
    Grouped into one object per floor or one object per individual
    stairwell, per the Grouping setting, rather than a single object
    combining every stair on the map -- easier to isolate, hide, or
    regenerate a specific floor or stair without touching the rest."""
    bl_idname = "object.generate_level_stairs"
    bl_label = "Generate Level Stairs"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene

        blueprint_obj = bpy.data.objects.get(BLUEPRINT_OBJECT_NAME)
        if blueprint_obj is None or blueprint_obj.type != 'MESH':
            self.report({'ERROR'}, "Generate a Game Blueprint first.")
            return {'CANCELLED'}

        tile_size = scene.wfc_tile_size
        level_height = _fine_level_height(scene)

        stair_runs = _read_stair_runs(blueprint_obj, tile_size, level_height)
        if stair_runs is None:
            self.report({'ERROR'}, "Blueprint has no stair data -- regenerate it.")
            return {'CANCELLED'}
        if not stair_runs:
            self.report({'WARNING'}, "No stair tiles found in the blueprint.")
            return {'CANCELLED'}

        _remove_objects_by_prefix(STAIRS_OBJECT_NAME)

        if scene.wfc_simple_materials:
            stair_material = get_or_create_simple_stair_material()
        else:
            stair_material = get_or_create_style_material(scene.wfc_style)

        # Same reasoning as the walls operator: reuse the level's seed so
        # Organic Irregularity jitter is reproducible across re-runs.
        random.seed(scene.wfc_seed)
        organic_amount = scene.wfc_organic_amount

        # Group by LOGICAL floor (run[2] // sub_levels), not the raw fine
        # Z-slice -- with Sub-Levels per Floor > 1, a floor's split-level
        # room and its base-height rooms sit at different fine slices but
        # are still meant to read as one floor. Grouping by fine Z instead
        # would produce more stair objects than the map actually has
        # floors, and "Per Floor" wouldn't select a whole floor's worth of
        # stairs at once.
        sub_levels = max(1, scene.wfc_sub_levels_per_floor)
        runs_by_floor = {}
        for run in stair_runs:
            runs_by_floor.setdefault(run['z'] // sub_levels, []).append(run)

        per_stair = scene.wfc_stair_grouping == 'PER_STAIR'
        created = []
        for floor_idx in sorted(runs_by_floor):
            runs_here = runs_by_floor[floor_idx]
            groups = [[run] for run in runs_here] if per_stair else [runs_here]
            for idx, group in enumerate(groups):
                name = (
                    f"{STAIRS_OBJECT_NAME}_Floor{floor_idx}_{idx + 1:02d}" if per_stair
                    else f"{STAIRS_OBJECT_NAME}_Floor{floor_idx}"
                )
                if scene.wfc_stair_mesh_style == 'RAMP':
                    mesh_data = _build_ramp_mesh(
                        group, tile_size, level_height, name,
                        organic_amount=organic_amount, uv_tile_size=scene.wfc_uv_tile_size,
                    )
                else:
                    mesh_data = _build_stair_mesh(
                        group, tile_size, level_height, scene.wfc_stair_steps, name,
                        organic_amount=organic_amount, uv_tile_size=scene.wfc_uv_tile_size,
                    )
                obj = bpy.data.objects.new(name, mesh_data)
                context.collection.objects.link(obj)
                mesh_data.materials.append(stair_material)
                _add_viewport_color_attribute(mesh_data)
                created.append(obj)

        for obj in created:
            obj.select_set(True)
        if created:
            context.view_layer.objects.active = created[-1]

        total_tiles = sum(seg[3] for run in stair_runs for seg in run['segments'])
        self.report(
            {'INFO'},
            f"Stairs generated: {len(stair_runs)} runs across {total_tiles} tiles, in {len(created)} object(s)."
        )
        _update_debug_snapshot(context, "Step 3: Generate Stairs")
        return {'FINISHED'}


class OBJECT_OT_GenerateLevelDoors(bpy.types.Operator):
    """Builds walk-through door frame object(s) from the already-generated
    blueprint's tile_id/room_id data -- run "Generate Game Blueprint"
    first. A frame (two posts + a top) is placed at every point a corridor
    enters a room or two rooms directly meet -- exactly wherever the wall
    silhouette already leaves a gap, so this never conflicts with or
    duplicates wall geometry. Door Style (Flat/Round/Pointed) controls
    every ordinary doorway's top; Entrance and Exit always get their own
    fixed, larger, always-arched "Gate" instead, so the two are visually
    distinct from ordinary doors regardless of Door Style -- see
    _build_door_mesh's own docstring for why that's a separate pass rather
    than an extension of the ordinary-doorway logic.

    Generate Door Panels (on by default) additionally builds one real,
    separate swinging panel Object per ordinary doorway (never for
    Entrance/Exit gates, which stay open set pieces) -- see
    _build_door_panels. On UPBGE, each panel also gets a best-effort HINGE
    rigid body constraint (see _try_setup_hinge_physics); on stock
    Blender, that step is a silent no-op and only the panel geometry
    appears."""
    bl_idname = "object.generate_level_doors"
    bl_label = "Generate Level Doors"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene

        blueprint_obj = bpy.data.objects.get(BLUEPRINT_OBJECT_NAME)
        if blueprint_obj is None or blueprint_obj.type != 'MESH':
            self.report({'ERROR'}, "Generate a Game Blueprint first.")
            return {'CANCELLED'}

        if blueprint_obj.data.attributes.get("tile_id") is None or blueprint_obj.data.attributes.get("room_id") is None:
            self.report({'ERROR'}, "Blueprint has no tile_id/room_id data -- regenerate it.")
            return {'CANCELLED'}

        tile_size = scene.wfc_tile_size
        level_height = _fine_level_height(scene)

        walkable_cells, extra = _read_blueprint_points(
            blueprint_obj, tile_size, level_height, ("room_id", "z_offset", "tile_id")
        )
        room_ids = extra["room_id"]
        z_offsets = extra["z_offset"]
        stair_cells = {cell for cell, tid in extra["tile_id"].items() if tid == TILE_STAIR}
        entrance_cells = {cell for cell, tid in extra["tile_id"].items() if tid == TILE_ENTRANCE}
        exit_cells = {cell for cell, tid in extra["tile_id"].items() if tid == TILE_EXIT}

        if not walkable_cells:
            self.report({'WARNING'}, "No walkable tiles found in the blueprint.")
            return {'CANCELLED'}

        # Round rooms get a real angled frame (see
        # _build_round_room_doors_mesh) instead of the straight-axis frame
        # _build_door_mesh would otherwise still build for them -- room
        # shape/bounding-box metadata was baked onto the Blueprint at
        # Step 1 time (see OBJECT_OT_GenerateGameBlueprint), since this
        # step deliberately never re-runs the solver.
        room_meta = json.loads(blueprint_obj.get("gla_room_meta", "[]"))
        round_room_ids = {i for i, r in enumerate(room_meta) if r['shape'] == 'ROUND'}

        _remove_objects_by_prefix(DOORS_OBJECT_NAME)
        _remove_objects_by_prefix(DOORS_ROUND_OBJECT_NAME)

        # Order matters -- _build_door_mesh bakes material_index 0/1/2 for
        # ordinary/Entrance/Exit respectively, matching this exact order.
        # With Masonry walls the door FRAMES are dressed stone (the swinging panels stay wood); the frame UVs
        # use the masonry tile size so the stone blocks come out at the same scale as the walls'.
        masonry_frames = scene.wfc_wall_style == 'MASONRY'
        panel_material = get_or_create_door_material()
        door_materials = [get_or_create_tower_stone_material() if masonry_frames else panel_material,
                          get_or_create_entrance_material(), get_or_create_exit_material()]
        door_uv = TOWER_TILE_W if masonry_frames else scene.wfc_uv_tile_size

        panel_warnings = []

        def _add_door_panels_for(cells_for_panels, room_ids_for_panels, name_prefix):
            # Reuses the exact doorway set _build_door_mesh itself just
            # found for these same cells (see _find_ordinary_doorways),
            # so panels can never drift out of sync with frames.
            if not scene.wfc_generate_door_panels:
                return []
            doorway_records = _find_ordinary_doorways(
                cells_for_panels, room_ids_for_panels, tile_size, level_height,
                merge_distance=scene.wfc_door_merge_distance, z_offsets=z_offsets,
                stair_cells=stair_cells, skip_room_ids=round_room_ids,
            )
            panels = _build_door_panels(
                doorway_records, scene.wfc_door_height, scene.wfc_door_frame_thickness,
                panel_material, name_prefix, uv_tile_size=scene.wfc_uv_tile_size,
            )
            if panels:
                panels_collection = _get_or_create_collection(DOOR_PANELS_COLLECTION_NAME, context.collection)
                for panel_obj in panels:
                    panels_collection.objects.link(panel_obj)
                    if scene.wfc_upbge_hinge_physics:
                        warning = _try_setup_hinge_physics(context, panel_obj)
                        if warning:
                            panel_warnings.append(warning)
            return panels

        def _add_round_doors(name, meta_for_floor):
            if scene.wfc_round_wall_style == 'MASONRY':
                return None  # the masonry ring carries its own arched/flat stone frames
            round_mesh_data = _build_round_room_doors_mesh(
                meta_for_floor, room_ids, walkable_cells, tile_size, level_height,
                scene.wfc_door_height, scene.wfc_door_frame_thickness, scene.wfc_room_shape_sides,
                z_offsets, scene.wfc_door_style, scene.wfc_door_arch_height, name,
                uv_tile_size=door_uv,
            )
            if not round_mesh_data.vertices:
                bpy.data.meshes.remove(round_mesh_data)
                return None
            round_obj = bpy.data.objects.new(name, round_mesh_data)
            context.collection.objects.link(round_obj)
            round_mesh_data.materials.append(door_materials[0])
            _add_viewport_color_attribute(round_mesh_data)
            return round_obj

        sub_levels = max(1, scene.wfc_sub_levels_per_floor)
        per_floor = scene.wfc_door_grouping == 'PER_FLOOR'

        created = []
        if per_floor:
            cells_by_floor = {}
            for cell in walkable_cells:
                cells_by_floor.setdefault(cell[2] // sub_levels, set()).add(cell)
            for floor_idx in sorted(cells_by_floor):
                name = f"{DOORS_OBJECT_NAME}_Floor{floor_idx}"
                floor_cells = cells_by_floor[floor_idx]
                floor_room_ids = {c: room_ids[c] for c in floor_cells}
                door_mesh_data = _build_door_mesh(
                    floor_cells, floor_room_ids, tile_size, level_height,
                    scene.wfc_door_height, scene.wfc_door_frame_thickness, name,
                    merge_distance=scene.wfc_door_merge_distance, z_offsets=z_offsets,
                    stair_cells=stair_cells, uv_tile_size=door_uv,
                    door_style=scene.wfc_door_style, arch_height=scene.wfc_door_arch_height,
                    entrance_cells=entrance_cells, exit_cells=exit_cells, skip_room_ids=round_room_ids,
                )
                if not door_mesh_data.vertices:
                    bpy.data.meshes.remove(door_mesh_data)
                else:
                    obj = bpy.data.objects.new(name, door_mesh_data)
                    context.collection.objects.link(obj)
                    for mat in door_materials:
                        door_mesh_data.materials.append(mat)
                    _add_viewport_color_attribute(door_mesh_data)
                    created.append(obj)

                created.extend(_add_door_panels_for(floor_cells, floor_room_ids, f"{DOORS_OBJECT_NAME}_Floor{floor_idx}_Panel"))

                meta_for_floor = [r for r in room_meta if r['z'] // sub_levels == floor_idx]
                round_obj = _add_round_doors(f"{DOORS_ROUND_OBJECT_NAME}_Floor{floor_idx}", meta_for_floor)
                if round_obj is not None:
                    created.append(round_obj)
        else:
            door_mesh_data = _build_door_mesh(
                walkable_cells, room_ids, tile_size, level_height,
                scene.wfc_door_height, scene.wfc_door_frame_thickness, DOORS_OBJECT_NAME,
                merge_distance=scene.wfc_door_merge_distance, z_offsets=z_offsets,
                stair_cells=stair_cells, uv_tile_size=door_uv,
                door_style=scene.wfc_door_style, arch_height=scene.wfc_door_arch_height,
                entrance_cells=entrance_cells, exit_cells=exit_cells, skip_room_ids=round_room_ids,
            )
            if door_mesh_data.vertices:
                obj = bpy.data.objects.new(DOORS_OBJECT_NAME, door_mesh_data)
                context.collection.objects.link(obj)
                for mat in door_materials:
                    door_mesh_data.materials.append(mat)
                _add_viewport_color_attribute(door_mesh_data)
                created.append(obj)
            else:
                bpy.data.meshes.remove(door_mesh_data)

            created.extend(_add_door_panels_for(walkable_cells, room_ids, f"{DOORS_OBJECT_NAME}_Panel"))

            round_obj = _add_round_doors(DOORS_ROUND_OBJECT_NAME, room_meta)
            if round_obj is not None:
                created.append(round_obj)

        if not created:
            self.report({'WARNING'}, "No doorways found -- every walkable boundary shares a room_id.")
            return {'CANCELLED'}

        for obj in created:
            obj.select_set(True)
        context.view_layer.objects.active = created[-1]

        if panel_warnings:
            print(f"Generate Level Doors: hinge physics setup failed for {len(panel_warnings)} panel(s):")
            for warning in panel_warnings:
                print(f"  - {warning}")
            self.report(
                {'WARNING'},
                f"Doors generated, in {len(created)} object(s). Panel geometry is fine, but hinge "
                f"physics setup failed for {len(panel_warnings)} panel(s) -- see the console for detail.",
            )
        else:
            self.report({'INFO'}, f"Doors generated, in {len(created)} object(s).")
        _update_debug_snapshot(context, "Step 4: Generate Doors")
        return {'FINISHED'}


class OBJECT_OT_GenerateLevelProps(bpy.types.Operator):
    """Scatters placeholder props from the already-generated blueprint's
    tile_id/room_id data -- run "Generate Game Blueprint" first. Two
    kinds: wall-mounted torches (a baked-mesh bracket + a real Point
    light, so they actually illuminate the level, not just look like
    they would) and floor decoration (crates/barrels/cone props,
    scattered per room). Everything lands in a
    "Procedural Level Props" collection tree (Torches / Lights /
    Decoration sub-collections) so it can be hidden, isolated, or bulk-
    deleted independently of the structural geometry."""
    bl_idname = "object.generate_level_props"
    bl_label = "Generate Level Props"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene

        blueprint_obj = bpy.data.objects.get(BLUEPRINT_OBJECT_NAME)
        if blueprint_obj is None or blueprint_obj.type != 'MESH':
            self.report({'ERROR'}, "Generate a Game Blueprint first.")
            return {'CANCELLED'}

        if blueprint_obj.data.attributes.get("tile_id") is None or blueprint_obj.data.attributes.get("room_id") is None:
            self.report({'ERROR'}, "Blueprint has no tile_id/room_id data -- regenerate it.")
            return {'CANCELLED'}

        tile_size = scene.wfc_tile_size
        level_height = _fine_level_height(scene)

        walkable_cells, extra = _read_blueprint_points(
            blueprint_obj, tile_size, level_height, ("room_id", "z_offset")
        )
        room_ids = extra["room_id"]
        z_offsets = extra["z_offset"]

        if not walkable_cells:
            self.report({'WARNING'}, "No walkable tiles found in the blueprint.")
            return {'CANCELLED'}

        _remove_objects_by_prefix(PROPS_TORCH_OBJECT_NAME)
        _remove_objects_by_prefix(PROPS_DECORATION_OBJECT_NAME)
        _remove_objects_by_prefix(PROPS_LIGHT_NAME_PREFIX)

        # Reuses the level's own seed, same reasoning as every other
        # cosmetic-randomization consumer in this file (Organic
        # Irregularity, continuous elevation): re-running this step with
        # the same seed always scatters the same props in the same spots.
        random.seed(scene.wfc_seed)

        props_collection = _get_or_create_collection(PROPS_COLLECTION_NAME, context.collection)
        torch_collection = _get_or_create_collection(PROPS_TORCH_COLLECTION_NAME, props_collection)
        light_collection = _get_or_create_collection(PROPS_LIGHT_COLLECTION_NAME, props_collection)
        decoration_collection = _get_or_create_collection(PROPS_DECORATION_COLLECTION_NAME, props_collection)

        def cell_z0(cell):
            return cell[2] * level_height + z_offsets.get(cell, 0.0)

        # -- Torches: every wall-adjacent walkable cell is a candidate --
        wall_adjacent = {}  # cell -> [(dx, dy), ...] directions with a wall
        for cell in walkable_cells:
            x, y, z = cell
            options = [
                (dx, dy) for dx, dy in HORIZONTAL_NEIGHBORS
                if (x + dx, y + dy, z) not in walkable_cells
            ]
            if options:
                wall_adjacent[cell] = options

        # Torch mesh density and actual (real, runtime-costly) light count
        # are deliberately decoupled: `torches` controls how many torch
        # MESHES get placed (cheap, purely visual, driven by Torch
        # Chance), separately from which of them get a real Point light
        # (driven by Torch Light Chance, capped at Max Lights). "Rooms
        # need lights" is re-applied at the LIGHT stage below, not just
        # the mesh stage -- a room whose only torch loses its Torch Light
        # Chance roll would otherwise go dark despite having a torch mesh.
        torches = []  # (x, y, z0, dx, dy) or, mounted on a Round room's masonry ring, (x, y, z0, dx, dy, wall_x, wall_y)
        torch_room_id = []  # parallel: this torch's room_id, -1 for corridor
        rooms_with_mesh = set()

        # Round rooms with Masonry walls: the ring is a curve well inside/outside the cells' square
        # edges, so a torch hung on a cell edge would float in the room. Mount those on the ring.
        ring_geo = {}     # room_id -> inner ellipse (props keep inside it)
        ring_ranges = {}  # room_id -> doorway parameter ranges (torches keep out of them)
        if scene.wfc_round_wall_style == 'MASONRY':
            meta_for_ring = json.loads(blueprint_obj.get("gla_room_meta", "[]"))
            walk_for_ring = set(walkable_cells)
            for rid_r, room_r in enumerate(meta_for_ring):
                if room_r['shape'] == 'ROUND':
                    ring_geo[rid_r] = _round_ring_inner_ellipse(room_r, tile_size, scene.wfc_wall_thickness)
                    ring_ranges[rid_r] = _round_room_opening_ranges(room_r, rid_r, room_ids, walk_for_ring, tile_size)
        ring_torches_ok = scene.wfc_round_wall_ruin <= 0.0  # a broken wall has nowhere to hang a torch

        def make_torch(cell, options):
            x, y, z = cell
            rid = room_ids.get(cell, -1)
            if rid in ring_geo:
                if not ring_torches_ok:
                    return None
                mount = _ring_torch_mount(cell, ring_geo[rid], ring_ranges[rid], tile_size)
                if mount is None:
                    return None
                return (x, y, cell_z0(cell), mount[2], mount[3], mount[0], mount[1])
            dx, dy = random.choice(options)
            return (x, y, cell_z0(cell), dx, dy)

        for cell, options in wall_adjacent.items():
            if random.random() >= scene.wfc_torch_chance:
                continue
            rid = room_ids.get(cell, -1)
            torch = make_torch(cell, options)
            if torch is None:
                continue
            torches.append(torch)
            torch_room_id.append(rid)
            if rid >= 0:
                rooms_with_mesh.add(rid)

        # Guarantee every room that HAS a wall to mount one on gets at
        # least one torch MESH, regardless of how the random pass rolled.
        cells_by_room = {}
        for cell in wall_adjacent:
            rid = room_ids.get(cell, -1)
            if rid >= 0:
                cells_by_room.setdefault(rid, []).append(cell)
        for rid, cells in cells_by_room.items():
            if rid in rooms_with_mesh:
                continue
            candidates_t = list(cells)
            random.shuffle(candidates_t)
            for cell in candidates_t:
                torch = make_torch(cell, wall_adjacent[cell])
                if torch is not None:
                    torches.append(torch)
                    torch_room_id.append(rid)
                    rooms_with_mesh.add(rid)
                    break

        # Lights: one guaranteed-lit torch per room (any of that room's
        # torches -- the mesh guarantee above already ensures every room
        # has at least one to pick from), then Torch Light Chance decides
        # every other torch independently, then Max Lights trims the
        # optional ones if the total still runs too high (the one
        # guaranteed pick per room is never trimmed by the cap).
        torches_by_room = {}
        for i, rid in enumerate(torch_room_id):
            if rid >= 0:
                torches_by_room.setdefault(rid, []).append(i)

        must_light = {random.choice(indices) for indices in torches_by_room.values()}
        lit_indices = set(must_light)
        for i in range(len(torches)):
            if i in lit_indices:
                continue
            if random.random() < scene.wfc_torch_light_chance:
                lit_indices.add(i)

        if len(lit_indices) > scene.wfc_max_lights:
            optional = list(lit_indices - must_light)
            budget = max(0, scene.wfc_max_lights - len(must_light))
            lit_indices = must_light | set(random.sample(optional, min(budget, len(optional))))
        lit_indices = sorted(lit_indices)
        rooms_with_torch = {torch_room_id[i] for i in lit_indices if torch_room_id[i] >= 0}

        # -- Decoration: scatter crates/barrels/cones per room, away from
        # doorways so nothing blocks a passage --
        cells_by_room_all = {}
        for cell in walkable_cells:
            rid = room_ids.get(cell, -1)
            if rid >= 0:
                cells_by_room_all.setdefault(rid, []).append(cell)

        decorations = []  # (cx, cy, z0, kind, rot)
        prop_kinds = ('CRATE', 'BARREL', 'CONE')
        theme_setting = scene.wfc_prop_theme
        theme_rng = random.Random(scene.wfc_seed * 104729 + 17)
        theme_names = sorted(PROP_THEMES)
        for rid, cells in cells_by_room_all.items():
            thresholds = set()
            for xi, yi, zi in cells:
                for dx, dy in HORIZONTAL_NEIGHBORS:
                    nb = (xi + dx, yi + dy, zi)
                    if nb in walkable_cells and room_ids.get(nb, -1) != rid:
                        thresholds.add((xi, yi, zi))
                        break
            candidates = [c for c in cells if c not in thresholds]
            if not candidates:
                continue
            prop_count = min(len(candidates), round(len(candidates) * scene.wfc_prop_chance))
            geo_here = ring_geo.get(rid)
            if theme_setting == 'GENERIC':
                for cell in random.sample(candidates, prop_count):
                    x, y, z = cell
                    kind = random.choice(prop_kinds)
                    rot = random.uniform(0.0, 2.0 * math.pi)
                    if geo_here is not None and not _prop_inside_ring(kind, rot, x * tile_size, y * tile_size, geo_here, tile_size):
                        continue
                    decorations.append((x * tile_size, y * tile_size, cell_z0(cell), kind, rot))
                continue

            theme = theme_rng.choice(theme_names) if theme_setting == 'MIXED' else theme_setting
            floor_kinds, wall_kinds = PROP_THEMES[theme]
            half_room = tile_size / 2.0 - scene.wfc_wall_thickness / 2.0 - 0.03  # cell centre -> wall's inner face
            # Wall-adjacent cells mostly take wall kinds pushed back against the wall;
            # every other placement is a quarter-turn that provably fits the cell's walls.
            for cell in theme_rng.sample(candidates, prop_count):
                x, y, z = cell
                wall_dirs = [
                    (dx, dy) for dx, dy in HORIZONTAL_NEIGHBORS if (x + dx, y + dy, z) not in walkable_cells
                ]
                if geo_here is not None:
                    wall_dirs = []  # the curved ring is the wall; square-cell wall props would float or clip
                if wall_dirs and theme_rng.random() < 0.7:
                    dx, dy = theme_rng.choice(wall_dirs)
                    kind = theme_rng.choice(wall_kinds)
                    xmin, xmax, ymin, ymax = _prop_local_bounds(kind, tile_size)
                    rot = math.atan2(-dy, -dx)  # local +X (front) faces into the room
                    off = half_room - (-xmin)  # back (-X side) touches the wall's inner face
                    cx, cy = x * tile_size + dx * off, y * tile_size + dy * off
                    # lateral fit along the wall: a prop wider than the tile just doesn't go here
                    if max(-ymin, ymax) > tile_size / 2.0:
                        continue
                    # if another wall is also close (a corner), make sure it still fits
                    if not _prop_fits(kind, rot, cx - x * tile_size, cy - y * tile_size, wall_dirs, half_room, tile_size):
                        continue
                else:
                    kind = theme_rng.choice(floor_kinds)
                    turns = [0, 1, 2, 3]
                    theme_rng.shuffle(turns)
                    rot = None
                    for t in turns:
                        if _prop_fits(kind, t * math.pi / 2.0, 0.0, 0.0, wall_dirs, half_room, tile_size):
                            rot = t * math.pi / 2.0
                            break
                    if rot is None:
                        continue
                    cx, cy = x * tile_size, y * tile_size
                if geo_here is not None and not _prop_inside_ring(kind, rot, cx, cy, geo_here, tile_size):
                    continue
                decorations.append((cx, cy, cell_z0(cell), kind, rot))

        created = []

        if torches:
            torch_mesh = _build_torch_mesh(
                torches, tile_size, scene.wfc_torch_height, PROPS_TORCH_OBJECT_NAME,
                uv_tile_size=scene.wfc_uv_tile_size,
            )
            torch_obj = bpy.data.objects.new(PROPS_TORCH_OBJECT_NAME, torch_mesh)
            torch_collection.objects.link(torch_obj)
            torch_mesh.materials.append(get_or_create_torch_material())
            torch_mesh.materials.append(get_or_create_torch_flame_material())
            _add_viewport_color_attribute(torch_mesh)
            created.append(torch_obj)

            flame_color = tuple(scene.wfc_torch_light_color)
            for idx in lit_indices:
                x, y, z0, dx, dy = torches[idx][:5]
                top_z = z0 + scene.wfc_torch_height
                if len(torches[idx]) == 7:
                    flame_x = torches[idx][5] - dx * 0.3
                    flame_y = torches[idx][6] - dy * 0.3
                elif dx != 0:
                    wall_x = (x + 0.5 * dx) * tile_size
                    flame_x = wall_x - dx * 0.3
                    flame_y = y * tile_size
                else:
                    wall_y = (y + 0.5 * dy) * tile_size
                    flame_x = x * tile_size
                    flame_y = wall_y - dy * 0.3
                light_data = bpy.data.lights.new(name=f"{PROPS_LIGHT_NAME_PREFIX}_Data", type='POINT')
                light_data.energy = scene.wfc_torch_light_energy
                light_data.color = flame_color
                light_data.shadow_soft_size = scene.wfc_torch_light_radius
                light_obj = bpy.data.objects.new(f"{PROPS_LIGHT_NAME_PREFIX}_{idx:04d}", light_data)
                light_obj.location = (flame_x, flame_y, top_z)
                light_collection.objects.link(light_obj)
                created.append(light_obj)

        if decorations:
            decoration_mesh = _build_decoration_mesh(
                decorations, tile_size, PROPS_DECORATION_OBJECT_NAME, uv_tile_size=scene.wfc_uv_tile_size,
            )
            decoration_obj = bpy.data.objects.new(PROPS_DECORATION_OBJECT_NAME, decoration_mesh)
            # the placement list itself, so an engine can swap in its own models (see _build_game_package)
            decoration_obj["gla_props"] = json.dumps([[round(c, 4) for c in d[:3]] + [d[3], round(d[4], 4)] for d in decorations])
            decoration_collection.objects.link(decoration_obj)
            decoration_mesh.materials.append(get_or_create_prop_material())
            _add_viewport_color_attribute(decoration_mesh)
            created.append(decoration_obj)

        if not created:
            self.report({'WARNING'}, "No props placed -- check Torch/Prop Chance settings.")
            return {'CANCELLED'}

        for obj in created:
            obj.select_set(True)
        context.view_layer.objects.active = created[-1]

        self.report(
            {'INFO'},
            f"Props generated: {len(torches)} torch meshes, {len(lit_indices)} real lights "
            f"({len(rooms_with_torch)} rooms lit), {len(decorations)} decoration pieces."
        )
        _update_debug_snapshot(context, "Step 5: Generate Props")
        return {'FINISHED'}


# ==============================================================================
# 7. ROUND TOWER (brick-textured shell + real hard-surface details)
# ==============================================================================
# A round room / tower is NOT modelled brick by brick (a 9 m tower needs ~1400
# bricks, ~8 000 vertices, and still reads ragged). Instead:
#   * the wall is a smooth cylindrical shell (outer + inner skin) carrying a
#     procedural brick albedo + normal map -- bricks, joints and per-brick
#     variation cost zero geometry;
#   * everything that defines the SILHOUETTE stays real geometry: door/window
#     openings are cut into the shell (round arch, lancet-free rect slits) with
#     reveals, and framed with voussoir/jamb blocks; plinth, cornice and
#     battlements are wedge blocks; scattered proud stones break up the surface.
# Brick Detail picks how much of the second group is built (Low/Medium/High).
# All maths is plain Python (no Geometry Nodes), baked, and exports to glTF
# like every other part of the addon. See DEVELOPMENT.md section 2 (0.27.0).
TOWER_OBJECT_NAME = "Procedural_Level_Tower"
TOWER_LIGHT_PREFIX = "Procedural_Level_LanternLight"
INTERIOR_PROPS_OBJECT_NAME = "Procedural_Level_InteriorProps"   # tower storeys' furniture (not a TOWER_OBJECT_NAME prefix)
HALL_PROPS_OBJECT_NAME = "Procedural_Level_HallProps"           # the castle keep's furniture
TOWER_TAU = 2.0 * math.pi
TOWER_TILE_W = 2.4
TOWER_ROW_H = 0.26
TOWER_ROWS = 8


def _masonry_images(prefix, rows, row_h, lens_choices, palette, seed, joint_m=0.011, bevel_m=0.016, wear=0.12):
    """(albedo, normal) procedural masonry images, generated once per session
    with numpy and packed into the .blend so glTF export embeds them. rows *
    row_h must equal the brick tile height so every material shares one UV
    scale. `palette(np, tint, tint2, hv)` returns the (H, W, 3) display-space
    base colour. Returns None when numpy is unavailable (callers fall back to
    a flat colour) -- Blender ships numpy, so that only happens offline."""
    alb = bpy.data.images.get(prefix + "_Albedo")
    nrm = bpy.data.images.get(prefix + "_Normal")
    if alb is not None and nrm is not None:
        return alb, nrm
    try:
        import numpy as np
    except ImportError:
        return None
    W = 1024
    tile_h = rows * row_h
    H = int(round(W * tile_h / TOWER_TILE_W))
    ppm = W / TOWER_TILE_W
    rng = np.random.default_rng(seed)
    bid = np.zeros((H, W), dtype=np.int32)
    d_edge = np.zeros((H, W), dtype=np.float32)
    yy, xx = np.mgrid[0:H, 0:W]
    vals = []
    for r in range(rows):
        y0, y1 = int(round(r * row_h * ppm)), int(round((r + 1) * row_h * ppm))
        lens, tot = [], 0.0
        while tot < TOWER_TILE_W - 0.25:
            l = float(rng.choice(lens_choices))
            lens.append(l)
            tot += l
        lens = np.array(lens) * TOWER_TILE_W / sum(lens)
        edges = np.concatenate([[0], np.cumsum(lens)]) * ppm
        shift = rng.uniform(0, TOWER_TILE_W) * ppm
        for k in range(len(lens)):
            x0, x1 = edges[k] + shift, edges[k + 1] + shift
            xs = (xx[y0:y1] - x0) % W  # wraps, so every row tiles horizontally
            inside = xs < (x1 - x0)
            bid_rows, d_rows = bid[y0:y1], d_edge[y0:y1]
            bid_rows[inside] = len(vals)
            dx = np.minimum(xs, (x1 - x0) - 1 - xs)
            dy = np.minimum(yy[y0:y1] - y0, y1 - 1 - yy[y0:y1])
            d_rows[inside] = np.minimum(dx, dy)[inside]
            vals.append((rng.uniform(0.82, 1.0), rng.uniform(-1, 1), rng.uniform(-1, 1)))
    vals = np.array(vals, dtype=np.float32)
    hv, tint, tint2 = vals[bid, 0], vals[bid, 1], vals[bid, 2]
    joint, bevel = joint_m * ppm, bevel_m * ppm
    t = np.clip((d_edge - joint) / bevel, 0, 1)
    height = t * t * (3 - 2 * t) * hv

    def blur(a, n):
        for _ in range(n):
            a = (a + np.roll(a, 1, 0) + np.roll(a, -1, 0) + np.roll(a, 1, 1) + np.roll(a, -1, 1)) / 5
        return a
    noise = blur(rng.normal(0, 1, (H, W)).astype(np.float32), 2)
    height = height + noise * 0.15
    # large soft weathering blotches (tileable: a coarse random grid, blurred with wrap-around)
    coarse = np.kron(rng.random((9, 8)).astype(np.float32), np.ones((H // 9 + 1, W // 8 + 1), dtype=np.float32))[:H, :W]
    blotch = blur(coarse, 40) - 0.5
    base = palette(np, tint, tint2, hv)
    base = base * (0.80 + 0.40 * (hv[..., None] - 0.82) / 0.18) * (1 + noise[..., None] * 0.5)
    base = base * (1.0 + blotch[..., None] * wear * 4.0)
    mortar = np.array([0.20, 0.19, 0.17])
    albedo = np.where((d_edge < joint + 0.5)[..., None], mortar, base)
    albedo = np.clip(albedo * (0.55 + 0.45 * np.clip(height * 1.6, 0, 1))[..., None], 0, 1)
    dhx = (np.roll(height, -1, 1) - np.roll(height, 1, 1)) * 0.5
    dhy = (np.roll(height, -1, 0) - np.roll(height, 1, 0)) * 0.5
    nrm_arr = np.stack([-dhx * 5.0, -dhy * 5.0, np.ones_like(height)], -1)
    nrm_arr /= np.linalg.norm(nrm_arr, axis=-1, keepdims=True)
    nrm_arr = nrm_arr * 0.5 + 0.5

    def make(name, arr, colorspace):
        img = bpy.data.images.new(name, W, H, alpha=True)
        # Colorspace first: changing it AFTER writing pixels regenerates a
        # generated image back to blank black.
        img.colorspace_settings.name = colorspace
        if colorspace == 'sRGB':
            arr = np.power(arr, 2.2)  # pixels[] is linear; the palette is display-space
        rgba = np.concatenate([arr, np.ones((H, W, 1))], -1).astype(np.float32)
        img.pixels.foreach_set(rgba.ravel())
        img.update()
        img.pack()
        return img
    return make(prefix + "_Albedo", albedo, 'sRGB'), make(prefix + "_Normal", nrm_arr, 'Non-Color')


def _brick_palette(np, tint, tint2, hv):
    # muted fired-clay reds and browns, much less saturated than the first version
    return np.stack([0.50 + 0.07 * tint + 0.03 * tint2, 0.42 + 0.05 * tint, 0.37 + 0.045 * tint - 0.02 * tint2], -1)


def _stone_palette(np, tint, tint2, hv):
    # warm grey limestone with the odd cooler or yellower block
    return np.stack([0.56 + 0.05 * tint + 0.02 * tint2, 0.54 + 0.045 * tint, 0.50 + 0.04 * tint - 0.03 * tint2], -1)


def _tower_brick_images():
    return _masonry_images("LA_Tower_Brick", TOWER_ROWS, TOWER_ROW_H, [0.45, 0.6, 0.75, 0.9, 1.1], _brick_palette, 3)


def _tower_stone_images():
    # 4 rows of 0.52 m: the same 2.08 m tile as the bricks, but large dressed blocks
    return _masonry_images("LA_Tower_Stone", TOWER_ROWS // 2, TOWER_ROW_H * 2, [0.7, 0.9, 1.1, 1.4], _stone_palette, 7,
                           joint_m=0.014, bevel_m=0.02, wear=0.10)


def _masonry_material(name, images, fallback_file, fallback_hex, roughness=0.9):
    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing
    if images is None:
        return _get_or_create_named_material(name, fallback_file, fallback_hex)
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out_node = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    tex_a = nodes.new("ShaderNodeTexImage")
    tex_a.image = images[0]
    tex_n = nodes.new("ShaderNodeTexImage")
    tex_n.image = images[1]
    nmap = nodes.new("ShaderNodeNormalMap")
    _set_input(bsdf, 'Roughness', roughness)
    links.new(tex_a.outputs['Color'], bsdf.inputs['Base Color'])
    links.new(tex_n.outputs['Color'], nmap.inputs['Color'])
    links.new(nmap.outputs['Normal'], bsdf.inputs['Normal'])
    links.new(bsdf.outputs['BSDF'], out_node.inputs['Surface'])
    mat.diffuse_color = _hex_to_rgba(fallback_hex)
    return mat


def get_or_create_tower_brick_material():
    return _masonry_material("LA_Tower_Brick", _tower_brick_images() if bpy.data.materials.get("LA_Tower_Brick") is None else None,
                             "TowerBrick.png", "3a3028")


# Per-room brick tints as Hue/Saturation/Value adjustments of the brick albedo (a plain multiply cannot move
# red-brown bricks toward blue or green): (hue, saturation, value) with Blender's convention, hue 0.5 = no shift.
# Index 0 is the untinted brick used for corridors; rooms cycle through 1..N-1. The brick hue sits near 0.05,
# so a hue parameter h shifts it by (h - 0.5).
BRICK_TINTS = [
    (0.50, 1.00, 1.00),   # 0 corridors / default
    (0.53, 0.90, 1.25),   # 1 warm ochre
    (0.05, 0.55, 1.05),   # 2 slate blue-grey
    (0.75, 0.60, 1.00),   # 3 mossy green-grey
    (0.44, 0.85, 1.00),   # 4 rosy red
    (0.50, 0.70, 0.55),   # 5 dark umber
    (0.52, 0.45, 1.35),   # 6 pale sandy
]


BRICK_COLOR_ITEMS = [
    ('PLAIN', "Plain", "The plain brick colour"),
    ('OCHRE', "Warm Ochre", ""),
    ('SLATE', "Slate", ""),
    ('MOSS', "Moss", ""),
    ('ROSE', "Rose", ""),
    ('UMBER', "Dark Umber", ""),
    ('SAND', "Pale Sand", ""),
]
BRICK_COLOR_INDEX = {key: i for i, (key, _, _) in enumerate(BRICK_COLOR_ITEMS)}


def room_tint_map(room_ids, near=2):
    """{room_id: tint slot} giving rooms that stand within `near` tiles of each other (same level, Chebyshev
    distance between any two of their cells) different tints whenever the palette allows. Greedy in room order, each
    room trying slots from its own preferred one (1 + id % (N-1)) so the colours still vary level to level."""
    n = len(BRICK_TINTS) - 1
    by_room = {}
    for cell, rid in room_ids.items():
        if rid >= 0:
            by_room.setdefault(rid, []).append(cell)
    neighbours = {rid: set() for rid in by_room}
    owner = {c: rid for rid, cells in by_room.items() for c in cells}
    for cell, rid in owner.items():
        x, y, z = cell
        for dx in range(-near, near + 1):
            for dy in range(-near, near + 1):
                other = owner.get((x + dx, y + dy, z))
                if other is not None and other != rid:
                    neighbours[rid].add(other)
    chosen = {}
    for rid in sorted(by_room):
        used = [chosen[o] for o in neighbours[rid] if o in chosen]
        pref = rid % n
        order = [1 + (pref + k) % n for k in range(n)]
        free = [slot for slot in order if slot not in used]
        chosen[rid] = free[0] if free else min(order, key=lambda sl: used.count(sl))
    return chosen


def brick_tint_slot(room_id):
    """Material slot for a room's bricks: corridors (room_id < 0) stay untinted."""
    return 0 if room_id < 0 else 1 + room_id % (len(BRICK_TINTS) - 1)


def get_or_create_tower_brick_tint_material(index):
    """The brick material with BRICK_TINTS[index] applied (Hue/Saturation node between the albedo image and the
    shader). Index 0 is the plain brick material."""
    if index == 0:
        return get_or_create_tower_brick_material()
    name = f"LA_Tower_Brick_Tint{index}"
    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing
    base = get_or_create_tower_brick_material()
    mat = base.copy()
    mat.name = name
    hue, sat, val = BRICK_TINTS[index]
    import colorsys
    h0, s0, v0 = colorsys.rgb_to_hsv(*mat.diffuse_color[:3])
    r, g, b = colorsys.hsv_to_rgb((h0 + hue - 0.5) % 1.0, max(0.0, min(1.0, s0 * sat)), max(0.0, min(1.0, v0 * val)))
    mat.diffuse_color = (r, g, b, 1.0)
    if mat.use_nodes and mat.node_tree is not None:
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
        tex = next((n for n in nodes if n.type == 'TEX_IMAGE' and n.image is not None and "Albedo" in n.image.name), None)
        if bsdf is not None and tex is not None:
            hs = nodes.new("ShaderNodeHueSaturation")
            hs.inputs['Hue'].default_value = hue
            hs.inputs['Saturation'].default_value = sat
            hs.inputs['Value'].default_value = val
            hs.inputs['Fac'].default_value = 1.0
            links.new(tex.outputs['Color'], hs.inputs['Color'])
            links.new(hs.outputs['Color'], bsdf.inputs['Base Color'])
        elif bsdf is not None:
            bsdf.inputs['Base Color'].default_value = (r, g, b, 1.0)
    return mat


def masonry_material_list(room_colors):
    """Material slots for masonry meshes: [brick] + [stone], or with per-room colours
    [tint0 .. tintN-1] + [stone] (see _TowerMesh.append's mat_map)."""
    if room_colors:
        return [get_or_create_tower_brick_tint_material(i) for i in range(len(BRICK_TINTS))] + [get_or_create_tower_stone_material()]
    return [get_or_create_tower_brick_material(), get_or_create_tower_stone_material()]


def get_or_create_tower_stone_material():
    return _masonry_material("LA_Tower_Stone", _tower_stone_images() if bpy.data.materials.get("LA_Tower_Stone") is None else None,
                             "TowerStone.png", "3a3632", roughness=0.85)


def _cyl_point(a, r, z):
    return (r * math.cos(a), r * math.sin(a), z)


class _TowerMesh:
    """Shared-vertex polygon soup with per-loop UVs, per-face material and
    smooth flag. `poly` orients each face so its normal points `toward`
    (a world direction), which makes winding correct by construction --
    the same outward-normal guarantee tests/blender_headless_test.py checks
    for the other builders."""

    def __init__(self):
        self.verts, self.index = [], {}
        self.faces, self.uvs, self.mats, self.smooth = [], [], [], []

    def _vid(self, group, p):
        key = (group, round(p[0], 4), round(p[1], 4), round(p[2], 4))
        i = self.index.get(key)
        if i is None:
            i = len(self.verts)
            self.verts.append(tuple(p))
            self.index[key] = i
        return i

    def poly(self, group, pts, uvs, toward, mat=0, smooth=False):
        nx = ny = nz = 0.0
        n_pts = len(pts)
        for i in range(n_pts):
            a, b = pts[i], pts[(i + 1) % n_pts]
            nx += (a[1] - b[1]) * (a[2] + b[2])
            ny += (a[2] - b[2]) * (a[0] + b[0])
            nz += (a[0] - b[0]) * (a[1] + b[1])
        if nx * nx + ny * ny + nz * nz < 1e-18:
            return
        if nx * toward[0] + ny * toward[1] + nz * toward[2] < 0:
            pts, uvs = pts[::-1], uvs[::-1]
        ids = [self._vid(group, p) for p in pts]
        if len(set(ids)) < 3:
            return
        self.faces.append(ids)
        self.uvs.append(uvs)
        self.mats.append(mat)
        self.smooth.append(smooth)

    def append(self, other, rot=0.0, sx=1.0, sy=1.0, offset=(0.0, 0.0, 0.0), mat_map=None):
        """Appends another soup, rotated about Z by rot, then stretched by
        (sx, sy) along X/Y (an ellipse from a circle), then moved. Both
        operations have a positive determinant, so outward-facing winding
        survives."""
        base = len(self.verts)
        c, s_ = math.cos(rot), math.sin(rot)
        for x, y, z in other.verts:
            xr, yr = x * c - y * s_, x * s_ + y * c
            self.verts.append((xr * sx + offset[0], yr * sy + offset[1], z + offset[2]))
        for ids in other.faces:
            self.faces.append([i + base for i in ids])
        self.uvs.extend(other.uvs)
        self.mats.extend([mat_map.get(m, m) for m in other.mats] if mat_map else other.mats)
        self.smooth.extend(other.smooth)

    def to_mesh(self, name):
        mesh = bpy.data.meshes.new(name + "_Mesh")
        mesh.from_pydata(self.verts, [], self.faces)
        mesh.update()
        uv_layer = mesh.uv_layers.new(name="UVMap")
        li = 0
        for poly, uvs, mat, sm in zip(mesh.polygons, self.uvs, self.mats, self.smooth):
            poly.material_index = mat
            poly.use_smooth = sm
            for uv in uvs:
                uv_layer.data[li].uv = uv
                li += 1
        return mesh


class _WallRunBuilder:
    """A straight masonry wall run -- the flat sibling of _TowerBuilder, same
    ideas: smooth brick-textured outer/inner skins, real openings (arch,
    pointed, flat, gap) with reveals and dressed-stone frames, dressed
    plinth, battlements or a ruined stepped top, proud stones and rubble.
    Local frame: x along the run (0..length), outer face at y = -thickness/2,
    inner face at y = +thickness/2, z up. Material slots: 0 brick, 1 stone."""

    def __init__(self, length, height, thickness, battlements=True, seed=1, stones=None,
                 ruin=0.0, plinth=True, rubble=True, end_caps=False):
        self.L, self.H, self.t = length, height, thickness
        self.ruin = max(0.0, min(1.0, ruin))
        self.battle = battlements and self.ruin <= 0.0
        self.Hs = height - (1.0 if self.battle else 0.0)
        self.plinth, self.rubble, self.end_caps = plinth, rubble, end_caps
        self.stones = stones
        self.tile_w, self.tile_h = TOWER_TILE_W, TOWER_ROWS * TOWER_ROW_H
        self.rng = random.Random(seed)
        nr = random.Random(seed * 131 + 11)
        n = max(4, int(length / 0.9) + 2)
        self._lat1 = [nr.random() for _ in range(n)]
        self._lat2 = [nr.random() for _ in range(max(3, n // 3))]
        self._notches = [(nr.uniform(0.0, length), nr.uniform(0.5, 1.6)) for _ in range(1 + int(self.ruin * 3))]
        self._notch_depth = [nr.uniform(0.55, 1.0) for _ in self._notches]
        self.mb = _TowerMesh()
        self.openings = []
        self.columns = []

    # -- openings
    def add_opening(self, xc, width, sill, height, kind='arch'):
        x0, x1 = xc - width / 2.0, xc + width / 2.0
        if x0 < 0.25 or x1 > self.L - 0.25 or width < 0.15:
            return False
        rise = 0.0
        if kind == 'arch':
            spring = sill + max(height - width / 2.0, 0.2)
            apex = spring + width / 2.0
            rise = width / 2.0
        elif kind == 'pointed':
            rise = min(width * 0.85, max(height - 0.4, 0.3))
            spring = sill + height - rise
            apex = sill + height
        elif kind == 'gap':
            spring = apex = self.Hs
        else:
            spring = apex = sill + height
        if kind != 'gap' and apex + 0.4 > self.Hs:
            return False
        for o in self.openings:
            if (x0 < o['x1'] + 0.6 and o['x0'] < x1 + 0.6) and sill < o['apex'] + 0.4 and o['sill'] < apex + 0.4:
                return False
        self.openings.append(dict(xc=xc, w=width, sill=sill, spring=spring, apex=apex, kind=kind, rise=rise, x0=x0, x1=x1))
        return True

    # -- ruin profile
    @staticmethod
    def _lat(vals, x, span):
        n = len(vals)
        u = max(0.0, min(span, x)) / max(span, 1e-6) * (n - 1)
        i = min(int(u), n - 2)
        f = (1.0 - math.cos((u - i) * math.pi)) / 2.0
        return vals[i] * (1.0 - f) + vals[i + 1] * f

    def _ruin_top(self, x):
        if self.ruin <= 0.0:
            return self.Hs
        v = 0.65 * self._lat(self._lat1, x, self.L) + 0.35 * self._lat(self._lat2, x, self.L)
        top = self.Hs * (1.0 - self.ruin * (0.12 + 0.88 * v))
        for (c, half), depth in zip(self._notches, self._notch_depth):
            d = abs(x - c)
            if d < half:
                top *= 1.0 - self.ruin * depth * (1.0 - d / half) ** 0.6
        return max(0.5, min(self.Hs, math.floor(top / TOWER_ROW_H) * TOWER_ROW_H))

    def _build_columns(self):
        colw = 0.35 if self.ruin > 0.0 else 0.5
        if self.ruin > 0.0:
            self.openings = [o for o in self.openings if o['sill'] < self._ruin_top(o['xc']) - 0.3]
        cuts = {0.0, self.L}
        for o in self.openings:
            cuts.update((o['x0'], o['x1']))
        cuts = sorted(cuts)
        cols = []
        for a, b in zip(cuts[:-1], cuts[1:]):
            ops = sorted((o for o in self.openings if o['x0'] - 1e-6 <= a and b <= o['x1'] + 1e-6), key=lambda o: o['sill'])
            if ops:
                k = max(8 if o['kind'] == 'pointed' else 6 if o['kind'] == 'arch' else 1 for o in ops)
            else:
                k = max(1, round((b - a) / colw))
            for i in range(k):
                cols.append(dict(x0=a + (b - a) * i / k, x1=a + (b - a) * (i + 1) / k, ops=ops, gap=None, top=self.Hs))
        if self.ruin > 0.0:
            for c in cols:
                c['top'] = self._ruin_top((c['x0'] + c['x1']) / 2.0)
                need = max((o['apex'] + 0.4 for o in c['ops'] if o['kind'] != 'gap'), default=0.0)
                if need <= self.Hs:
                    c['top'] = max(c['top'], need)
            for o in self.openings:
                if o['kind'] != 'gap' and o['apex'] + 0.4 > self._ruin_top(o['xc']):
                    o['kind'] = 'gap'
        for c in cols:
            gaps = [o for o in c['ops'] if o['kind'] == 'gap']
            c['gap'] = max(gaps, key=lambda o: o['sill']) if gaps else None
        for o in self.openings:
            if o['kind'] != 'gap' or self.ruin <= 0.0:
                continue
            idx = [i for i, c in enumerate(cols) if o in c['ops']]
            left = cols[idx[0] - 1] if idx[0] > 0 else None
            right = cols[idx[-1] + 1] if idx[-1] + 1 < len(cols) else None
            h = min(c['top'] for c in (left, right) if c is not None) if (left or right) else self.Hs
            o['spring'] = o['apex'] = max(o['sill'] + 0.1, min(h, self.Hs))
        self.columns = cols

    def _standing_top(self, x):
        for c in self.columns:
            if c['x0'] - 1e-9 <= x <= c['x1'] + 1e-9:
                return c['gap']['sill'] if c['gap'] is not None else c['top']
        return 0.0

    # -- geometry
    def _uv(self, x, z):
        return (x / self.tile_w, z / self.tile_h)

    def _skin(self, outer):
        y = -self.t / 2.0 if outer else self.t / 2.0
        ny = -1.0 if outer else 1.0

        def face(xz):
            pts = [(x, y, z) for x, z in xz]
            self.mb.poly('out' if outer else 'in', pts, [self._uv(x, z) for x, z in xz], (0.0, ny, 0.0), 0, False)

        for c in self.columns:
            a, b, top_c = c['x0'], c['x1'], c['top']
            z = 0.0
            for op in c['ops']:
                if op['sill'] > z + 1e-6:
                    face([(a, z), (b, z), (b, op['sill']), (a, op['sill'])])
                if op['kind'] == 'gap':
                    z = None
                    break
                top = op['apex'] + (0.2 if op['kind'] in ('arch', 'pointed') else 0.0)
                if op['kind'] in ('arch', 'pointed'):
                    h0 = _TowerBuilder._arch_h(op, a - op['xc'])
                    h1 = _TowerBuilder._arch_h(op, b - op['xc'])
                    face([(a, h0), (b, h1), (b, top), (a, top)])
                z = top
            if z is not None and z < top_c - 1e-6:
                face([(a, z), (b, z), (b, top_c), (a, top_c)])

    def _quad(self, group, pts, toward, mat=0, uvs=None):
        self.mb.poly(group, pts, uvs or [self._uv(p[0], p[2]) for p in pts], toward, mat, False)

    def _reveals(self):
        hy = self.t / 2.0
        for o in self.openings:
            hole = (o['xc'], 0.0, (o['sill'] + o['spring']) / 2.0)

            def quad(pa, pb):
                pts = [(pa[0], -hy, pa[1]), (pb[0], -hy, pb[1]), (pb[0], hy, pb[1]), (pa[0], hy, pa[1])]
                c = tuple(sum(p[k] for p in pts) / 4.0 for k in range(3))
                uvs = [(pa[0] / self.tile_w, 0.0), (pb[0] / self.tile_w, 0.0), (pb[0] / self.tile_w, self.t / self.tile_h), (pa[0] / self.tile_w, self.t / self.tile_h)]
                self._quad('rev', pts, (hole[0] - c[0], hole[1] - c[1], hole[2] - c[2]), 0, uvs)

            for x in (o['x0'], o['x1']):
                quad((x, o['sill']), (x, o['spring']))
            if o['kind'] in ('arch', 'pointed'):
                curve = _TowerBuilder._arch_curve(o, 10)
                for k in range(len(curve) - 1):
                    quad((o['xc'] + curve[k][0], curve[k][1]), (o['xc'] + curve[k + 1][0], curve[k + 1][1]))
            elif o['kind'] != 'gap':
                quad((o['x0'], o['spring']), (o['x1'], o['spring']))
            quad((o['x0'], o['sill']), (o['x1'], o['sill']))

    def _block(self, x0, x1, y0, y1, z0, z1, mat=1):
        pts = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        self._solid8(pts, mat)

    def _solid8(self, pts, mat=1):
        c = tuple(sum(p[k] for p in pts) / 8.0 for k in range(3))
        grp = 'b%d' % len(self.mb.faces)
        for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            fp = [pts[i] for i in f]
            fc = tuple(sum(p[k] for p in fp) / 4.0 for k in range(3))
            self.mb.poly(grp, fp, [self._uv(p[0] + p[1], p[2]) for p in fp], (fc[0] - c[0], fc[1] - c[1], fc[2] - c[2]), mat, False)

    def _frames(self):
        hy, proud = self.t / 2.0, 0.07
        for o in self.openings:
            if o['kind'] == 'gap':
                continue
            fw = 0.28 if o['kind'] in ('arch', 'pointed') else 0.2
            for side in (-1.0, 1.0):
                ya, yb = (side * (hy - 0.02), side * (hy + proud))
                ya, yb = sorted((ya, yb))
                z, i = o['sill'], 0
                while z < o['spring'] - 1e-4:
                    hh = min(0.36, o['spring'] - z)
                    ext = fw + (0.12 if i % 2 else 0.0)
                    self._block(o['x0'] - ext, o['x0'], ya, yb, z, z + hh)
                    self._block(o['x1'], o['x1'] + ext, ya, yb, z, z + hh)
                    z += hh
                    i += 1
                if o['kind'] in ('arch', 'pointed'):
                    curve = _TowerBuilder._arch_curve(o, 10)
                    for k in range(len(curve) - 1):
                        (xa, za, nxa, nza), (xb, zb, nxb, nzb) = curve[k], curve[k + 1]
                        wd = fw + (0.1 if k % 2 else 0.0)
                        xc = o['xc']
                        self._solid8([(xc + xa, ya, za), (xc + xb, ya, zb), (xc + xb + nxb * wd, ya, zb + nzb * wd), (xc + xa + nxa * wd, ya, za + nza * wd),
                                      (xc + xa, yb, za), (xc + xb, yb, zb), (xc + xb + nxb * wd, yb, zb + nzb * wd), (xc + xa + nxa * wd, yb, za + nza * wd)])
                else:
                    self._block(o['x0'] - fw, o['x1'] + fw, ya, yb, o['spring'], o['spring'] + 0.3)
                if o['sill'] > 0.2:
                    self._block(o['x0'] - fw - 0.05, o['x1'] + fw + 0.05, ya, yb + side * 0.06, o['sill'] - 0.14, o['sill'])

    def _plinth_and_battlements(self):
        hy = self.t / 2.0
        floor_doors = [o for o in self.openings if o['sill'] < 0.2]
        n = max(1, round(self.L / 0.6))
        if self.plinth:
            for k in range(n):
                a, b = self.L * k / n, self.L * (k + 1) / n
                if any(a < o['x1'] + 0.28 and b > o['x0'] - 0.28 for o in floor_doors):
                    continue
                self._block(a, b, -hy - 0.14, -hy + 0.02, 0.0, 0.45)
        if self.battle:
            pitch = 1.5
            m = max(1, int(self.L / pitch))
            # parapet on the outer half only; the rest of the wall top is a walkway
            pt = min(0.5, self.t * 0.45)
            for k in range(m):
                a = self.L * k / m
                w = self.L / m * 0.62
                self._block(a, a + w, -hy, -hy + pt, self.Hs, self.H)
            self._block(0.0, self.L, -hy - 0.12, -hy + 0.02, self.Hs - 0.16, self.Hs)

    def _caps_and_steps(self):
        hy = self.t / 2.0
        cols = self.columns
        for c in cols:
            if c['gap'] is not None:
                if c['gap']['sill'] <= 1e-6:
                    continue
                z = c['gap']['sill']
            else:
                z = c['top']
            a, b = c['x0'], c['x1']
            self._quad('cap', [(a, -hy, z), (b, -hy, z), (b, hy, z), (a, hy, z)], (0.0, 0.0, 1.0), 1,
                       [(a / self.tile_w, 0.0), (b / self.tile_w, 0.0), (b / self.tile_w, self.t / self.tile_h), (a / self.tile_w, self.t / self.tile_h)])
        for i in range(len(cols) - 1):
            ca, cb = cols[i], cols[i + 1]
            xb = cb['x0']
            ga, gb = ca['gap'] is not None, cb['gap'] is not None
            if ga and gb:
                continue
            if ga or gb:
                gap, other = (ca, cb) if ga else (cb, ca)
                lo, hi = gap['gap']['spring'], other['top']
                lower_is_cb = gb
            else:
                lo, hi = sorted((ca['top'], cb['top']))
                lower_is_cb = cb['top'] < ca['top']
            if hi - lo < 1e-4:
                continue
            pts = [(xb, -hy, lo), (xb, -hy, hi), (xb, hy, hi), (xb, hy, lo)]
            self._quad('step', pts, (1.0 if lower_is_cb else -1.0, 0.0, 0.0), 0,
                       [(0.0, lo / self.tile_h), (0.0, hi / self.tile_h), (self.t / self.tile_w, hi / self.tile_h), (self.t / self.tile_w, lo / self.tile_h)])
        caps = tuple(self.end_caps) if isinstance(self.end_caps, (tuple, list)) else (bool(self.end_caps),) * 2
        for (x, nx), cap in zip(((0.0, -1.0), (self.L, 1.0)), caps):
            if cap:
                c = cols[0] if x == 0.0 else cols[-1]
                top = c['gap']['spring'] if c['gap'] is not None else c['top']
                pts = [(x, -hy, 0.0), (x, -hy, top), (x, hy, top), (x, hy, 0.0)]
                self._quad('endc', pts, (nx, 0.0, 0.0), 0, [(0.0, 0.0), (0.0, top / self.tile_h), (self.t / self.tile_w, top / self.tile_h), (self.t / self.tile_w, 0.0)])

    def _stones(self, count):
        hy = self.t / 2.0
        for _ in range(count):
            x = self.rng.uniform(0.4, self.L - 0.4)
            z = self.rng.uniform(0.7, max(0.8, self.Hs - 0.6))
            wl, hh, pr = self.rng.uniform(0.45, 0.8), self.rng.uniform(0.2, 0.3), self.rng.uniform(0.025, 0.05)
            if x - wl / 2 < 0.05 or x + wl / 2 > self.L - 0.05:
                continue
            if any(abs(x - o['xc']) < o['w'] / 2 + 0.55 + wl / 2 and o['sill'] - 0.5 < z < o['apex'] + 0.55 for o in self.openings):
                continue
            if self.ruin > 0.0 and z + hh > min(self._standing_top(x + k * wl / 2) for k in (-1, 0, 1)) - 0.05:
                continue
            side = self.rng.choice((-1.0, 1.0))
            ya, yb = sorted((side * (hy - 0.02), side * (hy + pr)))
            self._block(x - wl / 2, x + wl / 2, ya, yb, z, z + hh)

    def _rubble(self):
        if self.ruin <= 0.0 or not self.rubble:
            return
        hy = self.t / 2.0
        for _ in range(int(self.ruin * self.L * 1.4)):
            x = self.rng.uniform(0.3, self.L - 0.3)
            if any(o['sill'] < 0.3 and abs(x - o['xc']) < o['w'] / 2 + 0.7 for o in self.openings):
                continue
            side = self.rng.choice((-1.0, 1.0))
            y = side * (hy + self.rng.uniform(0.3, 1.8))
            hx, hyy, h = self.rng.uniform(0.12, 0.3), self.rng.uniform(0.1, 0.22), self.rng.uniform(0.1, 0.25)
            yaw = self.rng.uniform(0.0, math.pi)
            c_, s_ = math.cos(yaw), math.sin(yaw)
            bot = [(x + lx * c_ - ly * s_, y + lx * s_ + ly * c_, 0.0) for lx, ly in ((-hx, -hyy), (hx, -hyy), (hx, hyy), (-hx, hyy))]
            pts = bot + [(px, py, h) for px, py, _ in bot]
            self._solid8_open(pts)

    def _solid8_open(self, pts):
        """Box resting on the ground: top and four sides only."""
        cen = tuple(sum(p[k] for p in pts) / 8.0 for k in range(3))
        grp = 'rub%d' % len(self.mb.faces)
        for f in ((4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            fp = [pts[i] for i in f]
            fc = tuple(sum(p[k] for p in fp) / 4.0 for k in range(3))
            self.mb.poly(grp, fp, [self._uv(p[0] + p[1], p[2]) for p in fp], (fc[0] - cen[0], fc[1] - cen[1], fc[2] - cen[2]), 1, False)

    def geometry(self):
        self._build_columns()
        self._skin(True)
        self._skin(False)
        self._reveals()
        self._frames()
        self._plinth_and_battlements()
        if self.ruin > 0.0 or True:
            self._caps_and_steps()
        stones = self.stones if self.stones is not None else int(self.L * self.Hs * 0.35)
        self._stones(stones)
        self._rubble()
        return self.mb


def _remap_soup_materials(soup, brick_slot):
    """Point a finished soup's brick faces (slot 0) at BRICK tint slot `brick_slot` and its stone faces (slot 1)
    at the stone slot of masonry_material_list(True)."""
    stone = len(BRICK_TINTS)
    soup.mats = [brick_slot if m == 0 else stone for m in soup.mats]


class _TowerBuilder:
    """Builds one round tower. Openings are (angle, width, sill, height, kind)
    with kind 'arch' (round-headed, e.g. doors) or 'rect' (slit windows)."""

    DETAIL_STONES = {'LOW': 0, 'MEDIUM': 70, 'HIGH': 320}

    def __init__(self, radius, height, wall, battlements=True, detail='MEDIUM', seed=1,
                 interior=False, stair_width=1.0, stair_start_deg=0.0,
                 plinth=True, cap_top=False, brick_cols=None, stones=None, seam=0.0,
                 ruin=0.0, rubble_outside=True, floor_levels=None, stair_rail=True, lanterns=False):
        self.R, self.H, self.wall = radius, height, wall
        self.ruin = max(0.0, min(1.0, ruin))
        self.rubble_outside = rubble_outside
        self.stair_rail = stair_rail
        self.lanterns = lanterns
        self.lantern_points = []   # (z) of every lantern's flame, in the tower's own frame (on the axis)
        if self.ruin > 0.0:
            battlements = False  # nothing crenellated survives a ruin
        nr = random.Random(seed * 131 + 7)
        self._lat1 = [nr.random() for _ in range(48)]
        self._lat2 = [nr.random() for _ in range(12)]
        self._notches = [(nr.uniform(0, TOWER_TAU), nr.uniform(0.35, 1.1) / max(radius, 1.0), nr.uniform(0.55, 1.0))
                         for _ in range(1 + int(self.ruin * 3))]
        self.plinth = plinth
        self.cap_top = cap_top
        self.stones = stones            # None: from detail; else an explicit count
        self.seam = seam                # world param angle where the shell's angular sweep starts/ends
        self.interior = interior
        self.stair_w = stair_width
        # snapped to the 64-segment slab grid so the slab hole ends exactly where a stair arrives
        self.stair_a0 = (round(((math.radians(stair_start_deg) - seam) % TOWER_TAU) / (TOWER_TAU / 64.0))
                         * (TOWER_TAU / 64.0))
        self.tile_w, self.tile_h = TOWER_TILE_W, TOWER_ROWS * TOWER_ROW_H
        self.Ko = brick_cols or max(1, round(TOWER_TAU * radius / self.tile_w))
        self.Ki = max(1, round(self.Ko * (radius - wall) / radius))
        self.battle = battlements
        self.detail = detail
        self.rng = random.Random(seed)
        self.mb = _TowerMesh()
        self.Hs = height - (1.0 if battlements else 0.0)  # shell height (battlements sit on top)
        # Storeys are >= 3 m and divide the shell height exactly, so the top
        # storey's slab is the roof platform right behind the battlements.
        self.n_storeys = max(1, int(self.Hs // 3.0))
        self.sh = self.Hs / self.n_storeys
        # slab heights bottom to top; explicit floor_levels (e.g. a castle putting a floor exactly at
        # the wall-walk height) replace the even split
        if floor_levels:
            self.levels = [0.0] + sorted(floor_levels)
            self.n_storeys = len(self.levels) - 1
        else:
            self.levels = [k * self.sh for k in range(self.n_storeys + 1)]
        self.openings = []

    # -- mapping helpers
    def _u(self, a, K):
        return a / TOWER_TAU * K

    def _v(self, z):
        return z / self.tile_h

    def add_opening(self, deg, width, sill, height, kind='arch'):
        """deg is a WORLD angle; the shell sweep starts at self.seam, so convert."""
        ac = (math.radians(deg) - self.seam) % TOWER_TAU
        half = width / 2.0 / self.R
        # keep the whole opening inside (0, 2*pi): the shell is built as one angular sweep
        ac = min(max(ac, half + 0.02), TOWER_TAU - half - 0.02)
        return self._register_opening(ac, half, sill, height, kind)

    def add_opening_range(self, t0, t1, sill, height, kind='arch'):
        """Opening spanning the world parameter angles t0..t1 (t1 > t0); the
        shell's seam is rotated away by self.seam, so it must not straddle it."""
        half = (t1 - t0) / 2.0
        ac = ((t0 + t1) / 2.0 - self.seam) % TOWER_TAU
        if ac - half < 0.01 or ac + half > TOWER_TAU - 0.01:
            return False
        return self._register_opening(ac, half, sill, height, kind)

    @staticmethod
    def _curved(o):
        return o['kind'] in ('arch', 'pointed')

    def _register_opening(self, ac, half, sill, height, kind):
        width = 2.0 * half * self.R
        rise = 0.0
        if kind == 'arch':
            spring = sill + max(height - width / 2.0, 0.2)
            apex = spring + width / 2.0
            rise = width / 2.0
        elif kind == 'pointed':
            rise = min(width * 0.85, max(height - 0.4, 0.3))
            spring = sill + height - rise
            apex = sill + height
        elif kind == 'gap':
            # full-height opening with no frame or lintel: for walls too low to hold a real door
            spring = apex = self.Hs
        else:
            spring = sill + height
            apex = spring
        if (kind != 'gap' and apex + 0.4 > self.Hs) or width >= self.R * 1.9 or width < 0.15:
            return False
        for o in self.openings:  # no overlapping openings
            sep = abs(ac - o['ac']) * self.R
            if sep < (width + o['w']) / 2.0 + 0.6 and sill < o['apex'] + 0.4 and o['sill'] < apex + 0.4:
                return False
        self.openings.append(dict(ac=ac, w=width, sill=sill, spring=spring, apex=apex, kind=kind,
                                  rise=rise, a0=ac - half, a1=ac + half))
        return True

    def storey_of(self, z):
        """Index of the storey whose floor is at or below z."""
        k = 0
        for i in range(self.n_storeys):
            if self.levels[i] <= z + 1e-6:
                k = i
        return k

    def step_blocks_at(self, deg, width):
        """[(z_bottom, z_top), ...] of the spiral steps in front of a wall point at world angle deg, over the
        angular span of `width` metres. Empty without an interior. Mirrors _stairs (same step count, rise, start)."""
        if not self.interior:
            return []
        a = (math.radians(deg) - self.seam) % TOWER_TAU
        half = width / 2.0 / self.R + 0.03
        out = []
        for k in range(self.n_storeys):
            z_lo, z_hi = self.levels[k], self.levels[k + 1]
            h = z_hi - z_lo
            steps = max(12, round(h / 0.18))
            rise = h / steps
            lo = ((a - half - self.stair_a0) % TOWER_TAU) / TOWER_TAU * steps
            hi = lo + 2 * half / TOWER_TAU * steps
            for j in range(int(math.floor(lo)), int(math.floor(hi)) + 1):
                top = z_lo + ((j % steps) + 1) * rise
                out.append((top - 0.30, top))
        return out

    def add_window(self, deg, width, sill, height):
        """A slit window that keeps clear of the spiral steps: the sill is moved (up or down, nearest first, inside
        its storey) until no step block overlaps the opening plus a small margin; dropped when nothing fits."""
        blocks = self.step_blocks_at(deg, width)
        if not blocks:
            return self.add_opening(deg, width, sill, height, 'rect')
        k = self.storey_of(sill)
        z_min, z_max = self.levels[k] + 0.5, self.levels[k + 1] - 0.6
        for shift in [0.0] + [d * s_ for d in range(1, 30) for s_ in (0.1, -0.1)]:
            sl = sill + shift
            if sl < z_min or sl + height > z_max:
                continue
            if any(b0 < sl + height + 0.12 and sl - 0.12 < b1 for b0, b1 in blocks):
                continue
            return self.add_opening(deg, width, sl, height, 'rect')
        return False

    @staticmethod
    def _arch_h(o, s):
        if o['kind'] == 'arch':
            s = max(-o['w'] / 2.0, min(o['w'] / 2.0, s))
            return o['spring'] + math.sqrt(max(0.0, (o['w'] / 2.0) ** 2 - s * s))
        if o['kind'] == 'pointed':
            hs = o['w'] / 2.0
            c = (o['rise'] ** 2 - hs * hs) / (2.0 * hs)
            r = hs + c
            x = abs(max(-hs, min(hs, s))) + c
            return o['spring'] + math.sqrt(max(0.0, r * r - x * x))
        return o['spring']

    @staticmethod
    def _arch_curve(o, n=10):
        """Intrados of a curved opening as (s, z, nx, nz): points left spring
        -> apex -> right spring with the outward unit normal in the (s, z) plane."""
        hs = o['w'] / 2.0
        pts = []
        if o['kind'] == 'arch':
            for k in range(n + 1):
                t = math.pi * (1.0 - k / n)
                pts.append((hs * math.cos(t), o['spring'] + hs * math.sin(t), math.cos(t), math.sin(t)))
            return pts
        c = (o['rise'] ** 2 - hs * hs) / (2.0 * hs)
        r = hs + c
        phi_a = math.acos(max(-1.0, min(1.0, -c / r)))
        half_n = max(1, n // 2)
        left = []
        for k in range(half_n + 1):
            phi = math.pi + (phi_a - math.pi) * k / half_n
            left.append((c + r * math.cos(phi), o['spring'] + r * math.sin(phi), math.cos(phi), math.sin(phi)))
        right = [(-x, z, -nx, nz) for x, z, nx, nz in reversed(left[:-1])]
        return left + right

    # -- ruin profile: wall top height as a function of the world angle t
    @staticmethod
    def _lattice(vals, t):
        n = len(vals)
        u = (t % TOWER_TAU) / TOWER_TAU * n
        i = int(u) % n
        f = u - int(u)
        f = (1.0 - math.cos(f * math.pi)) / 2.0
        return vals[i] * (1.0 - f) + vals[(i + 1) % n] * f

    def _ruin_top(self, t):
        """Wall top at world angle t: smooth low-frequency noise plus a few deep
        notches (breaches), snapped down to whole brick courses so the broken
        edge steps like real masonry. Unruined walls return Hs."""
        if self.ruin <= 0.0:
            return self.Hs
        v = 0.65 * self._lattice(self._lat1, t) + 0.35 * self._lattice(self._lat2, t * 1.7)
        top = self.Hs * (1.0 - self.ruin * (0.12 + 0.88 * v))
        for c, half, depth in self._notches:
            d = abs(((t - c + math.pi) % TOWER_TAU) - math.pi)
            if d < half:
                top *= 1.0 - self.ruin * depth * (1.0 - d / half) ** 0.6
        top = math.floor(top / TOWER_ROW_H) * TOWER_ROW_H
        return max(0.5, min(self.Hs, top))

    def _standing_top(self, a):
        """Height of masonry actually standing at shell angle a (0 across a
        breach whose sill is the ground). Needs self.columns."""
        for c in self.columns:
            if c['a0'] - 1e-9 <= a % TOWER_TAU <= c['a1'] + 1e-9:
                if c['gap'] is not None:
                    return c['gap']['sill']
                return c['top']
        return 0.0

    def _build_columns(self):
        """Angular columns shared by both skins, caps and steps. Each is a dict
        with a0, a1, ops (every opening whose angular span contains it, lowest
        first -- stacked windows share columns), gap (the opening that has
        become a plain breach there, if any) and top."""
        colw = 0.35 if self.ruin > 0.0 else 0.5
        if self.ruin > 0.0:
            # an opening whose sill is above the broken wall top there simply fell with it
            self.openings = [o for o in self.openings if o['sill'] < self._ruin_top(o['ac'] + self.seam) - 0.3]
        hard = {0.0, TOWER_TAU}
        for o in self.openings:
            hard.update((o['a0'], o['a1']))
        hard = sorted(hard)
        cols = []
        for a0, a1 in zip(hard[:-1], hard[1:]):
            ops = sorted((o for o in self.openings if o['a0'] - 1e-6 <= a0 and a1 <= o['a1'] + 1e-6),
                         key=lambda o: o['sill'])
            k = 1
            if not ops:
                k = max(1, round((a1 - a0) * self.R / colw))
            else:
                k = max(8 if o['kind'] == 'pointed' else 6 if o['kind'] == 'arch' else 1 for o in ops)
            for i in range(k):
                cols.append(dict(a0=a0 + (a1 - a0) * i / k, a1=a0 + (a1 - a0) * (i + 1) / k,
                                 ops=ops, gap=None, top=self.Hs))
        if self.ruin > 0.0:
            for c in cols:
                mid = (c['a0'] + c['a1']) / 2.0 + self.seam
                c['top'] = self._ruin_top(mid)
                need = max((o['apex'] + 0.4 for o in c['ops'] if o['kind'] != 'gap'), default=0.0)
                c['top'] = max(c['top'], need) if need <= self.Hs else c['top']
            for o in self.openings:
                if o['kind'] != 'gap' and o['apex'] + 0.4 > self._ruin_top(o['ac'] + self.seam):
                    o['kind'] = 'gap'  # arch/lintel did not survive: becomes a breach
        for c in cols:
            gaps = [o for o in c['ops'] if o['kind'] == 'gap']
            c['gap'] = max(gaps, key=lambda o: o['sill']) if gaps else None
        n = len(cols)
        for o in self.openings:
            if o['kind'] != 'gap':
                continue
            idx = [i for i, c in enumerate(cols) if o in c['ops']]
            left, right = cols[(idx[0] - 1) % n], cols[(idx[-1] + 1) % n]
            if self.ruin > 0.0:
                h = min(left['top'], right['top'])
                o['spring'] = o['apex'] = max(o['sill'] + 0.1, min(h, self.Hs))
        self.columns = cols

    # -- smooth textured shell, outer or inner skin
    def _shell(self, outer):
        R = self.R if outer else self.R - self.wall
        K = self.Ko if outer else self.Ki
        group = 'out' if outer else 'in'

        def face(az):
            pts = [_cyl_point(a, R, z) for a, z in az]
            uvs = [(self._u(a, K), self._v(z)) for a, z in az]
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            sgn = 1.0 if outer else -1.0
            self.mb.poly(group, pts, uvs, (cx * sgn, cy * sgn, 0.0), 0, True)

        for c in self.columns:
            a0, a1, top_c = c['a0'], c['a1'], c['top']
            z = 0.0
            for op in c['ops']:
                if op['sill'] > z + 1e-6:
                    face([(a0, z), (a1, z), (a1, op['sill']), (a0, op['sill'])])
                if op['kind'] == 'gap':
                    z = None  # everything above a breach is gone
                    break
                top = op['apex'] + (0.2 if self._curved(op) else 0.0)
                if self._curved(op):
                    h0 = self._arch_h(op, (a0 - op['ac']) * self.R)
                    h1 = self._arch_h(op, (a1 - op['ac']) * self.R)
                    face([(a0, h0), (a1, h1), (a1, top), (a0, top)])
                z = top
            if z is not None and z < top_c - 1e-6:
                face([(a0, z), (a1, z), (a1, top_c), (a0, top_c)])

    def _reveals(self):
        Ro, Ri = self.R, self.R - self.wall
        for o in self.openings:
            a0, a1 = o['a0'], o['a1']
            hole = _cyl_point(o['ac'], (Ro + Ri) / 2.0, (o['sill'] + o['spring']) / 2.0)

            def quad(pa, pb):
                pts = [_cyl_point(pa[0], Ro, pa[1]), _cyl_point(pb[0], Ro, pb[1]),
                       _cyl_point(pb[0], Ri, pb[1]), _cyl_point(pa[0], Ri, pa[1])]
                cx = sum(p[0] for p in pts) / 4.0
                cy = sum(p[1] for p in pts) / 4.0
                cz = sum(p[2] for p in pts) / 4.0
                uvs = [(self._u(pa[0], self.Ko), self._v(pa[1])), (self._u(pb[0], self.Ko), self._v(pb[1])),
                       (self._u(pb[0], self.Ko), self._v(pb[1]) + 0.2), (self._u(pa[0], self.Ko), self._v(pa[1]) + 0.2)]
                self.mb.poly('rev', pts, uvs, (hole[0] - cx, hole[1] - cy, hole[2] - cz), 0, False)

            for a in (a0, a1):
                quad((a, o['sill']), (a, o['spring']))
            if self._curved(o):
                prev = (a0, o['spring'])
                m = 8 if o['kind'] == 'pointed' else 6
                for i in range(1, m + 1):
                    a = a0 + (a1 - a0) * i / m
                    cur = (a, self._arch_h(o, (a - o['ac']) * self.R))
                    quad(prev, cur)
                    prev = cur
            elif o['kind'] != 'gap':
                quad((a0, o['spring']), (a1, o['spring']))
            quad((a0, o['sill']), (a1, o['sill']))

    # -- dressed-stone blocks
    def _solid(self, corners, mat=1):
        """corners: 8 (a, z, r): bottom four (CCW as seen from above) then top four."""
        pts = [_cyl_point(a, r, z) for a, z, r in corners]
        cx = sum(p[0] for p in pts) / 8.0
        cy = sum(p[1] for p in pts) / 8.0
        cz = sum(p[2] for p in pts) / 8.0
        group = 'b%d' % len(self.mb.faces)
        for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
            fp = [pts[i] for i in f]
            fx = sum(p[0] for p in fp) / 4.0
            fy = sum(p[1] for p in fp) / 4.0
            fz = sum(p[2] for p in fp) / 4.0
            uvs = [(self._u(corners[i][0], self.Ko), self._v(corners[i][1])) for i in f]
            self.mb.poly(group, fp, uvs, (fx - cx, fy - cy, fz - cz), mat, False)

    def _wedge(self, a0, a1, r0, r1, z0, z1, mat=1):
        self._solid([(a0, z0, r0), (a1, z0, r0), (a1, z0, r1), (a0, z0, r1),
                     (a0, z1, r0), (a1, z1, r0), (a1, z1, r1), (a0, z1, r1)], mat)

    def _frames(self):
        Ro, proud = self.R, 0.06
        for o in self.openings:
            if o['kind'] == 'gap':
                continue
            fw = 0.26 if o['kind'] == 'arch' else 0.18
            ac, w = o['ac'], o['w']

            def blk(s0, s1, z0, z1, r1=Ro + proud):
                self._wedge(ac + s0 / Ro, ac + s1 / Ro, Ro - 0.02, r1, z0, z1)

            z, i = o['sill'], 0
            while z < o['spring'] - 1e-4:
                hh = min(0.34, o['spring'] - z)
                ext = fw + (0.12 if i % 2 else 0.0)
                blk(-w / 2 - ext, -w / 2, z, z + hh)
                blk(w / 2, w / 2 + ext, z, z + hh)
                z += hh
                i += 1
            if self._curved(o):
                curve = self._arch_curve(o, 10)
                r0, r1 = Ro - 0.02, Ro + proud
                for k in range(len(curve) - 1):
                    (xa, za, nxa, nza), (xb, zb, nxb, nzb) = curve[k], curve[k + 1]
                    wa = fw + (0.1 if k % 2 else 0.0)
                    xa2, za2 = xa + nxa * wa, za + nza * wa
                    xb2, zb2 = xb + nxb * wa, zb + nzb * wa
                    self._solid([(ac + xa / Ro, za, r0), (ac + xb / Ro, zb, r0), (ac + xb2 / Ro, zb2, r0), (ac + xa2 / Ro, za2, r0),
                                 (ac + xa / Ro, za, r1), (ac + xb / Ro, zb, r1), (ac + xb2 / Ro, zb2, r1), (ac + xa2 / Ro, za2, r1)])
            else:
                blk(-w / 2 - fw, w / 2 + fw, o['spring'], o['spring'] + 0.3)
            if o['sill'] > 0.2:  # a window sill stone; a floor-level doorway has no sill (it would sink below the floor)
                blk(-w / 2 - fw - 0.05, w / 2 + fw + 0.05, o['sill'] - 0.14, o['sill'], Ro + proud + 0.08)

    def _rings(self):
        Ro = self.R
        n = max(24, round(TOWER_TAU * Ro / 0.6))
        doors = [o for o in self.openings if o['sill'] < 0.2]
        for k in range(n):
            a0, a1 = TOWER_TAU * k / n, TOWER_TAU * (k + 1) / n
            am = (a0 + a1) / 2.0
            if any(abs(((am - o['ac'] + math.pi) % TOWER_TAU) - math.pi) < o['w'] / 2 / Ro + 0.28 for o in doors):
                continue
            if self.plinth:
                self._wedge(a0, a1, Ro - 0.02, Ro + 0.16, 0.0, 0.45)
            if self.battle:
                self._wedge(a0, a1, Ro - 0.02, Ro + 0.18, self.Hs - 0.16, self.Hs)

    def _battlements(self):
        if not self.battle:
            return
        Ro, Ri = self.R, self.R - self.wall
        n = max(6, round(TOWER_TAU * Ro / 1.5))
        for k in range(n):
            a0 = TOWER_TAU * k / n
            a1 = a0 + TOWER_TAU / n * 0.62
            self._wedge(a0, a1, Ri, Ro, self.Hs, self.H)
            self._wedge(a1, TOWER_TAU * (k + 1) / n, Ri, Ro, self.Hs - 0.001, self.Hs + 0.001)

    def _stones(self, count):
        Ro = self.R
        for _ in range(count):
            a = self.rng.uniform(0.0, TOWER_TAU)
            z = self.rng.uniform(0.7, max(0.8, self.Hs - 0.6))
            if any(abs(((a - o['ac'] + math.pi) % TOWER_TAU) - math.pi) * Ro < o['w'] / 2 + 0.55
                   and o['sill'] - 0.5 < z < o['apex'] + 0.55 for o in self.openings):
                continue
            wl, hh, pr = self.rng.uniform(0.45, 0.8), self.rng.uniform(0.2, 0.3), self.rng.uniform(0.025, 0.05)
            if self.ruin > 0.0 and z + hh > min(self._standing_top(a + k * wl / 2 / Ro) for k in (-1, 0, 1)) - 0.05:
                continue  # would float above the broken edge or across a breach
            self._wedge(a - wl / 2 / Ro, a + wl / 2 / Ro, Ro - 0.02, Ro + pr, z, z + hh)

    def _caps_and_steps(self):
        """Flat stone cap on every standing column plus the vertical end faces
        where neighbouring columns differ in height (ruined edge) or meet a
        breach. Used for ruins and for rooms with Cap Top."""
        Ro, Ri = self.R, self.R - self.wall
        cols = self.columns
        n = len(cols)
        for c in cols:
            if c['gap'] is not None:
                if c['gap']['sill'] > 1e-6:
                    z = c['gap']['sill']
                else:
                    continue
            else:
                z = c['top']
            a0, a1 = c['a0'], c['a1']
            pts = [_cyl_point(a0, Ro, z), _cyl_point(a1, Ro, z), _cyl_point(a1, Ri, z), _cyl_point(a0, Ri, z)]
            vi = self.wall / self.tile_h  # cap: u along the wall, v across its thickness
            self.mb.poly('cap', pts, [(self._u(a0, self.Ko), 0.0), (self._u(a1, self.Ko), 0.0), (self._u(a1, self.Ko), vi), (self._u(a0, self.Ko), vi)], (0.0, 0.0, 1.0), 1)
        for i in range(n):
            ca, cb = cols[i], cols[(i + 1) % n]
            b = cb['a0']  # boundary angle (0 for the seam join)
            ga = ca['gap'] is not None
            gb = cb['gap'] is not None
            if ga and gb:
                continue
            if ga or gb:
                gap, other = (ca, cb) if ga else (cb, ca)
                lo, hi = gap['gap']['spring'], other['top']
                lower_is_cb = gb  # the face looks into the breach
            else:
                lo, hi = sorted((ca['top'], cb['top']))
                lower_is_cb = cb['top'] < ca['top']
            if hi - lo < 1e-4:
                continue
            pts = [_cyl_point(b, Ro, lo), _cyl_point(b, Ro, hi), _cyl_point(b, Ri, hi), _cyl_point(b, Ri, lo)]
            direction = 1.0 if lower_is_cb else -1.0  # +tangent points toward the cb column
            ui = self.wall / self.tile_w * self.Ko / max(1.0, self.Ko)  # u across the wall's thickness
            u0 = self._u(b, self.Ko)
            self.mb.poly('step', pts, [(u0, self._v(lo)), (u0, self._v(hi)), (u0 + ui, self._v(hi)), (u0 + ui, self._v(lo))],
                         (-math.sin(b) * direction, math.cos(b) * direction, 0.0), 0)

    def _rubble(self):
        """Fallen blocks: yawed boxes scattered by the foot of the wall,
        keeping clear of floor-level openings."""
        if self.ruin <= 0.0:
            return
        n = int(self.ruin * TOWER_TAU * self.R * 1.2)
        inside_ok = not self.interior and not self.rubble_outside
        for _ in range(n):
            a = self.rng.uniform(0.0, TOWER_TAU)
            if self.rubble_outside:
                r = self.R + self.rng.uniform(0.35, 2.2)
            elif inside_ok:
                r = self.R - self.wall - self.rng.uniform(0.25, 0.9)
            else:
                continue
            if any(o['sill'] < 0.3 and abs(((a - o['ac'] + math.pi) % TOWER_TAU) - math.pi) * self.R < o['w'] / 2 + 0.7
                   for o in self.openings):
                continue
            hx, hy, h = self.rng.uniform(0.12, 0.3), self.rng.uniform(0.1, 0.22), self.rng.uniform(0.1, 0.25)
            yaw = self.rng.uniform(0.0, math.pi)
            cx, cy = r * math.cos(a), r * math.sin(a)
            c_, s_ = math.cos(yaw), math.sin(yaw)
            corners = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]
            bot = [(cx + lx * c_ - ly * s_, cy + lx * s_ + ly * c_, 0.0) for lx, ly in corners]
            top = [(x, y, h) for x, y, _ in bot]
            pts = bot + top
            cen = (cx, cy, h / 2.0)
            grp = 'rub%d' % len(self.mb.faces)
            for f in ((4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
                fp = [pts[i] for i in f]
                fc = tuple(sum(p[k] for p in fp) / 4.0 for k in range(3))
                uvs = [((p[0] + p[1]) / self.tile_w, p[2] / self.tile_h) for p in fp]
                self.mb.poly(grp, fp, uvs, (fc[0] - cen[0], fc[1] - cen[1], fc[2] - cen[2]), 1)

    def _ground(self):
        Ri = self.R - self.wall
        n = max(16, round(TOWER_TAU * Ri / 0.4))
        for k in range(n):
            a0, a1 = TOWER_TAU * k / n, TOWER_TAU * (k + 1) / n
            pts = [(0.0, 0.0, 0.0), _cyl_point(a0, Ri, 0.0), _cyl_point(a1, Ri, 0.0)]
            uvs = [(p[0] / self.tile_w, p[1] / self.tile_w) for p in pts]
            self.mb.poly('floor', pts, uvs, (0.0, 0.0, 1.0), 1, False)

    # -- interior: floor slabs + one full turn of spiral stairs per storey
    SLAB_T = 0.25
    SLAB_SEGS = 64

    def _slab(self, z, hole=None):
        """Floor/roof slab, top face at z. hole = (first_seg, last_seg) slab
        segments whose outer band (the stair lane) is left open, else solid
        to the wall. The inner disc is always solid."""
        Ri = self.R - self.wall + 0.02
        rb = max(0.3, self.R - self.wall - self.stair_w) if hole is not None else Ri
        n, t = self.SLAB_SEGS, self.SLAB_T
        grp = 'slab%d' % len(self.mb.faces)
        up, down = (0.0, 0.0, 1.0), (0.0, 0.0, -1.0)
        c = _cyl_point

        def uv(p):
            return (p[0] / self.tile_w, p[1] / self.tile_w)

        def in_hole(i):
            if hole is None:
                return False
            a, b = hole
            i %= n
            return (a <= i <= b) if a <= b else (i >= a or i <= b)

        for i in range(n):
            a0, a1 = TOWER_TAU * i / n, TOWER_TAU * (i + 1) / n
            for zz, nrm in ((z, up), (z - t, down)):
                pts = [(0.0, 0.0, zz), c(a0, rb, zz), c(a1, rb, zz)]
                self.mb.poly(grp, pts, [uv(p) for p in pts], nrm, 1)
            if in_hole(i):
                if self.stair_rail:
                    self._wedge(a0, a1, rb - 0.06, rb + 0.06, z, z + 0.9)  # balustrade round the stairwell opening
                am = (a0 + a1) / 2.0
                pts = [c(a0, rb, z), c(a1, rb, z), c(a1, rb, z - t), c(a0, rb, z - t)]
                self.mb.poly(grp, pts, [uv(p) for p in pts], (math.cos(am), math.sin(am), 0.0), 1)
                for nb, a_edge, sgn in ((i - 1, a0, 1.0), (i + 1, a1, -1.0)):
                    if not in_hole(nb):
                        # where the solid band begins; this face looks into the hole
                        pts = [c(a_edge, rb, z), c(a_edge, Ri, z), c(a_edge, Ri, z - t), c(a_edge, rb, z - t)]
                        self.mb.poly(grp, pts, [uv(p) for p in pts],
                                     (-math.sin(a_edge) * sgn, math.cos(a_edge) * sgn, 0.0), 1)
                continue
            if rb < Ri:
                for zz, nrm in ((z, up), (z - t, down)):
                    pts = [c(a0, rb, zz), c(a1, rb, zz), c(a1, Ri, zz), c(a0, Ri, zz)]
                    self.mb.poly(grp, pts, [uv(p) for p in pts], nrm, 1)

    def _stairs(self):
        r0 = max(0.3, self.R - self.wall - self.stair_w)
        r1 = self.R - self.wall + 0.02
        n = self.SLAB_SEGS
        seg = TOWER_TAU / n
        a0_seg = int(round(self.stair_a0 / seg)) % n
        tmin = min((c['top'] for c in self.columns if c['gap'] is None), default=self.Hs)
        for k in range(self.n_storeys):
            z_lo, z_hi = self.levels[k], self.levels[k + 1]
            if self.ruin > 0.0 and z_hi > tmin + 0.3:
                break  # floors above the lowest broken wall top have collapsed
            h = z_hi - z_lo
            steps = max(12, round(h / 0.18))
            rise = h / steps
            # the slab above is open over every step whose top is within 2.2 m of it
            j_hole = next(j for j in range(steps) if (j + 1) * rise > h - 2.2)
            hole_segs = max(1, int(math.ceil((steps - j_hole) / steps * n)))
            hole = ((a0_seg - hole_segs) % n, (a0_seg - 1) % n)
            self.stair_hole = hole
            for j in range(steps):
                a = self.stair_a0 + TOWER_TAU * j / steps
                b = self.stair_a0 + TOWER_TAU * (j + 1) / steps
                top = z_lo + (j + 1) * rise
                self._wedge(a, b, r0, r1, 0.0 if k == 0 and j < 2 else top - 0.30, top)
                if self.stair_rail:
                    # a stone balustrade along the open (inner) edge of the lane, 0.9 m above each tread
                    self._wedge(a, b, r0 - 0.06, r0 + 0.06, top, top + 0.9)
            self._slab(z_hi, hole)
            if self.lanterns:
                self._lantern(z_hi)

    def _lantern(self, z_ceiling):
        """A lantern on a thin chain under a floor slab, on the tower's axis (the one place the stair lane never
        reaches). Four wedge quadrants each for the chain and the lamp body."""
        z_lamp0 = z_ceiling - self.SLAB_T - 0.62
        for q in range(4):
            a0, a1 = q * math.pi / 2.0, (q + 1) * math.pi / 2.0
            self._wedge(a0, a1, 0.0, 0.025, z_lamp0 + 0.3, z_ceiling - self.SLAB_T)      # chain
            self._wedge(a0, a1, 0.0, 0.15, z_lamp0, z_lamp0 + 0.3)                        # lamp body
        self.lantern_points.append(z_lamp0 + 0.15)

    def geometry(self, ground=True):
        self._build_columns()
        self._shell(True)
        self._shell(False)
        self._reveals()
        if self.detail != 'LOW':
            self._frames()
        self._rings()
        self._battlements()
        if self.cap_top or self.ruin > 0.0:
            self._caps_and_steps()
        self._rubble()
        self._stones(self.stones if self.stones is not None else self.DETAIL_STONES.get(self.detail, 70))
        if ground:
            self._ground()
        if self.interior:
            self._stairs()
        return self.mb

    def build(self, name):
        self.geometry()
        return self.mb.to_mesh(name)


def _prop_bounds_fit(kind, rot, cx, cy, check):
    """True when `check(x, y)` holds for the four corners of a prop's rotated footprint (tile size 2 = scale 1)."""
    xmin, xmax, ymin, ymax = _prop_local_bounds(kind, 2.0)
    c, s_ = math.cos(rot), math.sin(rot)
    return all(check(cx + lx * c - ly * s_, cy + lx * s_ + ly * c) for lx in (xmin, xmax) for ly in (ymin, ymax))


def _tower_interior_props(builder, seed):
    """Furniture for a tower's interior, in the tower's own frame: a few pieces on every floor slab (and the roof
    platform), kept inside the disc the stair lane leaves free. [(x, y, z0, kind, rot), ...]"""
    if not builder.interior:
        return []
    rng = random.Random(seed * 977 + 5)
    free_r = builder.R - builder.wall - builder.stair_w - 0.25
    if free_r < 0.7:
        return []
    kinds = ('CHEST', 'BARREL', 'CRATE', 'TABLE', 'CHAIR', 'CANDLESTAND')
    tmin = min((c['top'] for c in builder.columns if c['gap'] is None), default=builder.Hs) if builder.columns else builder.Hs
    out = []
    for k in range(builder.n_storeys + 1):
        z0 = builder.levels[k]
        if k > 0 and builder.ruin > 0.0 and z0 > tmin + 0.3:
            break
        base = rng.uniform(0.0, math.tau)
        count = 2 if free_r > 1.0 else 1
        for i in range(count):
            for _try in range(12):
                kind = rng.choice(kinds)
                ang = base + math.pi * i + rng.uniform(-0.5, 0.5)
                rad = rng.uniform(0.45, max(0.5, free_r - 0.5))
                px, py = rad * math.cos(ang), rad * math.sin(ang)
                rot = ang + math.pi   # facing the axis
                if _prop_bounds_fit(kind, rot, px, py, lambda x, y: math.hypot(x, y) <= free_r):
                    out.append((px, py, z0, kind, rot))
                    break
    return out


def _keep_hall_layout(ks, kt, kcx, kcy):
    """Furniture of the castle keep's hall in castle-local coordinates: a long table with chairs, bookshelves along the
    north wall, chests along the west wall, a bed against the east wall and candle stands in the corners. The south
    door lane (|x - kcx| < 0.8) stays clear. [(x, y, z0, kind, rot), ...]"""
    inner = ks / 2.0 - kt / 2.0
    tx, ty = kcx, kcy + 0.4
    out = [
        (tx - 0.6, ty, 0.0, 'TABLE', 0.0), (tx + 0.6, ty, 0.0, 'TABLE', 0.0),
        (tx - 1.0, ty + 0.95, 0.0, 'CHAIR', -math.pi / 2), (tx + 1.0, ty + 0.95, 0.0, 'CHAIR', -math.pi / 2),
        (tx - 1.0, ty - 0.95, 0.0, 'CHAIR', math.pi / 2), (tx + 1.0, ty - 0.95, 0.0, 'CHAIR', math.pi / 2),
        (tx + 1.75, ty, 0.0, 'CHAIR', math.pi),
        (kcx - 1.3, kcy + inner - 0.25, 0.0, 'BOOKSHELF', -math.pi / 2), (kcx + 1.3, kcy + inner - 0.25, 0.0, 'BOOKSHELF', -math.pi / 2),
        (kcx - inner + 0.5, kcy - 1.2, 0.0, 'CHEST', 0.0), (kcx - inner + 0.5, kcy + 0.1, 0.0, 'CHEST', 0.0),
        (kcx + inner - 0.95, kcy - 1.3, 0.0, 'BED', math.pi),
    ]
    for sx in (-1, 1):
        for sy in (-1, 1):
            out.append((kcx + sx * (inner - 0.4), kcy + sy * (inner - 0.4), 0.0, 'CANDLESTAND', 0.0))
    return out


def _tower_openings_from_settings(builder, scene):
    """Door at wfc_tower_door_angle, then wfc_tower_windows slit windows per
    storey (3 m storeys), staggered per storey."""
    if scene.wfc_tower_door:
        builder.add_opening(scene.wfc_tower_door_angle, 1.3, 0.0, min(2.6, builder.Hs - 1.0), 'arch')
    count = scene.wfc_tower_windows
    for k in range(builder.n_storeys):
        if count <= 0:
            break
        sill = builder.levels[k] + 1.2
        for i in range(count):
            deg = scene.wfc_tower_door_angle + 360.0 * (i + 0.25 + 0.5 * (k % 2)) / count
            builder.add_window(deg % 360.0, 0.28, sill, 1.3)


class OBJECT_OT_GenerateLevelTower(bpy.types.Operator):
    """Builds a round tower at the 3D cursor: brick-textured cylindrical
    shell with real arched door and slit windows, dressed-stone frames,
    plinth, cornice and battlements. Standalone -- independent of the
    level blueprint -- and replaces any previous tower made by this
    operator."""
    bl_idname = "object.generate_level_tower"
    bl_label = "Generate Round Tower"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        radius, height, wall = scene.wfc_tower_radius, scene.wfc_tower_height, scene.wfc_tower_wall
        if wall >= radius - 0.3:
            self.report({'ERROR'}, "Wall Thickness must be at least 0.3 m smaller than the Radius.")
            return {'CANCELLED'}
        _remove_objects_by_prefix(TOWER_OBJECT_NAME)
        _remove_objects_by_prefix(TOWER_LIGHT_PREFIX)
        _remove_objects_by_prefix(INTERIOR_PROPS_OBJECT_NAME)
        builder = _TowerBuilder(
            radius, height, wall, battlements=scene.wfc_tower_battlements,
            detail=scene.wfc_tower_detail, seed=scene.wfc_seed,
            ruin=scene.wfc_tower_ruin,
            interior=scene.wfc_tower_interior and radius - wall >= 1.6, stair_rail=scene.wfc_tower_stair_rail,
            lanterns=scene.wfc_tower_lights,
            stair_width=scene.wfc_tower_stair_width,
            stair_start_deg=scene.wfc_tower_door_angle + 60.0,
        )
        _tower_openings_from_settings(builder, scene)
        tint = BRICK_COLOR_INDEX[scene.wfc_tower_brick_color]
        builder.geometry()
        if tint:
            _remap_soup_materials(builder.mb, tint)
        mesh = builder.mb.to_mesh(TOWER_OBJECT_NAME)
        obj = bpy.data.objects.new(TOWER_OBJECT_NAME, mesh)
        context.collection.objects.link(obj)
        obj.location = scene.cursor.location
        for mat_ in masonry_material_list(bool(tint)):
            mesh.materials.append(mat_)
        if scene.wfc_tower_props:
            props_list = _tower_interior_props(builder, scene.wfc_seed)
            if props_list:
                pm = _build_decoration_mesh(props_list, 2.0, INTERIOR_PROPS_OBJECT_NAME, uv_tile_size=scene.wfc_uv_tile_size)
                po = bpy.data.objects.new(INTERIOR_PROPS_OBJECT_NAME, pm)
                context.collection.objects.link(po)
                po.location = obj.location
                pm.materials.append(get_or_create_prop_material())
                _add_viewport_color_attribute(pm)
                po["gla_props"] = json.dumps([[round(c, 4) for c in d[:3]] + [d[3], round(d[4], 4)] for d in props_list])
        if scene.wfc_tower_lights:
            for li, zl in enumerate(builder.lantern_points):
                light_data = bpy.data.lights.new(name=f"{TOWER_LIGHT_PREFIX}_Data", type='POINT')
                light_data.energy = scene.wfc_torch_light_energy
                light_data.color = tuple(scene.wfc_torch_light_color)
                light_data.shadow_soft_size = scene.wfc_torch_light_radius
                light_obj = bpy.data.objects.new(f"{TOWER_LIGHT_PREFIX}_{li:02d}", light_data)
                light_obj.location = (obj.location.x, obj.location.y, obj.location.z + zl)
                context.collection.objects.link(light_obj)
        _add_viewport_color_attribute(mesh)
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        note = ""
        if scene.wfc_tower_interior and not builder.interior:
            note = " (interior skipped: inner radius under 1.6 m)"
        self.report(
            {'INFO'},
            f"Tower generated: {len(mesh.vertices)} vertices, {len(builder.openings)} openings, "
            f"{builder.n_storeys} storeys{note}."
        )
        _update_debug_snapshot(context, "Round Tower")
        return {'FINISHED'}


CASTLE_OBJECT_NAME = "Procedural_Level_Castle"


def _castle_wall_openings(wb, gate, wall_h, kind_gate='arch'):
    """Gate in the middle of the run (when asked) plus arrow slits at a
    regular spacing."""
    if gate and wb.L > 6.0:
        wb.add_opening(wb.L / 2.0, 3.0, 0.0, min(4.0, wb.Hs - 1.2), kind_gate)
    spacing = 4.5
    k = 1
    while k * spacing < wb.L - 1.0:
        wb.add_opening(k * spacing, 0.28, wall_h * 0.42, 1.4, 'rect')
        k += 1


def _build_castle_mesh(width, depth, wall_h, wall_t, tower_r, tower_h, gate, keep, ruin, detail, seed,
                       tower_wall=0.55, interior=True, brick_color='PLAIN'):
    """A walled castle assembled from the Round Tower and straight wall run
    builders: four corner towers, four curtain walls whose ends are buried in
    the tower masonry, a gate arch in the south wall, arrow slits, an
    optional central keep (four more wall runs with a door facing the gate)
    and a stone courtyard slab. Everything is centered on the origin; the
    Ruin amount is shared by all parts (each part gets its own seed)."""
    big = _TowerMesh()
    W, D = width, depth
    # brick colour: one tint for the whole castle, or MIXED = walls, keep and each tower get their own
    mixed = brick_color == 'MIXED'
    base_tint = 0 if mixed else BRICK_COLOR_INDEX.get(brick_color, 0)

    def part_map(kind, i):
        if mixed:
            tint = (2, 3, 4, 6)[i % 4] if kind == 'tower' else (1 if kind == 'wall' else 5)
        else:
            tint = base_tint
        return {0: tint, 1: len(BRICK_TINTS)} if (mixed or base_tint) else None

    stones_scale = {'LOW': 0.0, 'MEDIUM': 1.0, 'HIGH': 3.0}.get(detail, 1.0)
    tower_h = max(tower_h, wall_h + 3.0)
    hy = wall_t / 2.0
    # -- courtyard
    for pts in ([(-W / 2, -D / 2, 0.0), (W / 2, -D / 2, 0.0), (W / 2, D / 2, 0.0), (-W / 2, D / 2, 0.0)],):
        big.poly('yard', pts, [(p[0] / TOWER_TILE_W, p[1] / TOWER_TILE_W) for p in pts], (0.0, 0.0, 1.0),
                 len(BRICK_TINTS) if (mixed or base_tint) else 1)
    # -- corner towers: a floor exactly at the wall-walk height, doors out onto both walls
    hs_wall = wall_h - 1.0
    corners = [(-W / 2, -D / 2), (W / 2, -D / 2), (W / 2, D / 2), (-W / 2, D / 2)]
    for i, (cx, cy) in enumerate(corners):
        m = math.degrees(math.atan2(-math.copysign(1.0, cy), -math.copysign(1.0, cx))) % 360.0   # the courtyard diagonal (wall doors then sit exactly on the wall axes)
        levels = [hs_wall, tower_h - 1.0]
        # stairs arrive at m + 190 deg: the ground door (at m) then sits ~170 deg into the climb, well
        # above head height, and the open stretch of the upper slab stays clear of the wall-walk doors
        tb = _TowerBuilder(
            tower_r, tower_h, tower_wall, battlements=True, detail=detail, seed=seed + 11 * i,
            interior=interior and tower_r - tower_wall >= 1.6, stair_width=1.0,
            stair_start_deg=m + 190.0, ruin=ruin, floor_levels=levels, seam=math.radians(m + 180.0),
        )
        tb.add_opening(m, 1.3, 0.0, min(2.6, tb.Hs - 1.0), 'arch')
        for ang in (m - 45.0, m + 45.0):
            tb.add_opening(ang % 360.0, 1.3, hs_wall, 2.2, 'arch')
        for k in range(tb.n_storeys):
            tb.add_window((m + 180.0 + (40.0 if k % 2 else -40.0)) % 360.0, 0.28, tb.levels[k] + 1.2, 1.3)
        tb.geometry(ground=True)
        big.append(tb.mb, rot=tb.seam, offset=(cx, cy, 0.0), mat_map=part_map('tower', i))
    # -- curtain walls
    xe = math.sqrt(max((tower_r - tower_wall / 2.0) ** 2 - hy * hy, 0.1))
    sides = [
        ((-W / 2 + xe, -D / 2), 0.0, W - 2 * xe, gate),
        ((W / 2, -D / 2 + xe), math.pi / 2, D - 2 * xe, False),
        ((W / 2 - xe, D / 2), math.pi, W - 2 * xe, False),
        ((-W / 2, D / 2 - xe), 3 * math.pi / 2, D - 2 * xe, False),
    ]
    for i, (start, rot, length, has_gate) in enumerate(sides):
        wb = _WallRunBuilder(length, wall_h, wall_t, battlements=True, seed=seed + 101 + i, ruin=ruin,
                             stones=int(length * wall_h * 0.35 * stones_scale))
        _castle_wall_openings(wb, has_gate, wall_h)
        wb.geometry()
        big.append(wb.mb, rot=rot, offset=(start[0], start[1], 0.0), mat_map=part_map('wall', 0))
    # -- keep
    if keep:
        ks = max(6.0, min(W, D) * 0.38)
        kcx, kcy = 0.0, D * 0.12
        kh = max(wall_h * 1.45, wall_h + 3.0)
        kt = max(wall_t, 1.0)
        corners_k = [(kcx - ks / 2, kcy - ks / 2), (kcx + ks / 2, kcy - ks / 2), (kcx + ks / 2, kcy + ks / 2), (kcx - ks / 2, kcy + ks / 2)]
        dirs = [(1, 0, 0.0), (0, 1, math.pi / 2), (-1, 0, math.pi), (0, -1, 3 * math.pi / 2)]
        for i, ((cx, cy), (dx, dy, rot)) in enumerate(zip(corners_k, dirs)):
            wb = _WallRunBuilder(ks + kt, kh, kt, battlements=True, seed=seed + 301 + i, ruin=ruin,
                                 stones=int(ks * kh * 0.3 * stones_scale))
            if i == 0:
                wb.add_opening(wb.L / 2.0, 2.0, 0.0, 2.8, 'arch')
            else:
                wb.add_opening(wb.L / 2.0, 0.3, kh * 0.45, 1.5, 'rect')
            wb.geometry()
            big.append(wb.mb, rot=rot, offset=(cx - dx * kt / 2.0, cy - dy * kt / 2.0, 0.0), mat_map=part_map('keep', 0))
        # interior hall: stone floor and a ceiling slab at the walkway level (top face = the roof walkway)
        inner = ks / 2.0 - kt / 2.0
        stone_slot = len(BRICK_TINTS) if (mixed or base_tint) else 1
        z_roof = kh - 1.0
        fl = [(kcx - inner, kcy - inner, 0.0), (kcx + inner, kcy - inner, 0.0), (kcx + inner, kcy + inner, 0.0), (kcx - inner, kcy + inner, 0.0)]
        big.poly('keepfloor', fl, [(q[0] / TOWER_TILE_W, q[1] / TOWER_TILE_W) for q in fl], (0.0, 0.0, 1.0), stone_slot)
        for zz, nrm in ((z_roof, (0.0, 0.0, 1.0)), (z_roof - 0.3, (0.0, 0.0, -1.0))):
            rf = [(q[0], q[1], zz) for q in fl]
            big.poly('keeproof', rf, [(q[0] / TOWER_TILE_W, q[1] / TOWER_TILE_W) for q in rf], nrm, stone_slot)
    return big


class OBJECT_OT_GenerateLevelCastle(bpy.types.Operator):
    """Builds a walled castle at the 3D cursor from masonry parts: four
    corner towers (with interiors), curtain walls with battlements, arrow
    slits and a gate, an optional keep, and a courtyard. Ruin breaks the
    whole thing down. Standalone, like the tower, and replaces any
    previous castle made by this operator."""
    bl_idname = "object.generate_level_castle"
    bl_label = "Generate Castle"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        if scene.wfc_castle_tower_radius * 2.0 + 3.0 > min(scene.wfc_castle_width, scene.wfc_castle_depth):
            self.report({'ERROR'}, "Towers are too large for the courtyard: raise Width/Depth or lower the tower radius.")
            return {'CANCELLED'}
        _remove_objects_by_prefix(CASTLE_OBJECT_NAME)
        soup = _build_castle_mesh(
            scene.wfc_castle_width, scene.wfc_castle_depth, scene.wfc_castle_wall_height,
            scene.wfc_castle_wall_thickness, scene.wfc_castle_tower_radius, scene.wfc_castle_tower_height,
            scene.wfc_castle_gate, scene.wfc_castle_keep, scene.wfc_castle_ruin,
            scene.wfc_tower_detail, scene.wfc_seed, brick_color=scene.wfc_castle_brick_color,
        )
        mesh = soup.to_mesh(CASTLE_OBJECT_NAME)
        obj = bpy.data.objects.new(CASTLE_OBJECT_NAME, mesh)
        context.collection.objects.link(obj)
        obj.location = scene.cursor.location
        for mat_ in masonry_material_list(scene.wfc_castle_brick_color != 'PLAIN'):
            mesh.materials.append(mat_)
        _remove_objects_by_prefix(HALL_PROPS_OBJECT_NAME)
        if scene.wfc_castle_keep and scene.wfc_castle_hall_props:
            W_, D_ = scene.wfc_castle_width, scene.wfc_castle_depth
            ks_ = max(6.0, min(W_, D_) * 0.38)
            kt_ = max(scene.wfc_castle_wall_thickness, 1.0)
            hall_list = _keep_hall_layout(ks_, kt_, 0.0, D_ * 0.12)
            hm = _build_decoration_mesh(hall_list, 2.0, HALL_PROPS_OBJECT_NAME, uv_tile_size=scene.wfc_uv_tile_size)
            ho = bpy.data.objects.new(HALL_PROPS_OBJECT_NAME, hm)
            context.collection.objects.link(ho)
            ho.location = obj.location
            hm.materials.append(get_or_create_prop_material())
            _add_viewport_color_attribute(hm)
            ho["gla_props"] = json.dumps([[round(c, 4) for c in d[:3]] + [d[3], round(d[4], 4)] for d in hall_list])
        _add_viewport_color_attribute(mesh)
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        self.report({'INFO'}, f"Castle generated: {len(mesh.vertices)} vertices.")
        _update_debug_snapshot(context, "Castle")
        return {'FINISHED'}


# ==============================================================================
# 8. GAME PACKAGE EXPORT (glb + JSON description)
# ==============================================================================
# glTF carries the visuals; an engine also needs to know where a character may
# walk, where the entrance and exit are, which rooms exist and where the
# lights hang. The JSON ("gla-export/1") describes exactly that, in the
# engine's own coordinates: x right, y up, z = -Blender y (what the glTF
# importer produces). Walkable cells are merged into a few rectangles so an
# engine with rectangle-based navigation (Vampire Adventure) can use them
# as they are; engines with a navmesh can ignore them and bake from the
# collision export.
GAME_PACKAGE_FORMAT = "gla-export/1"


def _merge_cells_to_rects(cells):
    """Greedy rectangle cover of a set of (x, y) grid cells: horizontal runs per
    row, then equal runs on consecutive rows are stacked. Returns [(x0, y0, x1, y1)]
    in INCLUSIVE cell units. Exact (no cell is lost or double counted)."""
    rows = {}
    for x, y in cells:
        rows.setdefault(y, []).append(x)
    runs = {}
    for y, xs in rows.items():
        xs.sort()
        start = prev = xs[0]
        out = []
        for x in xs[1:]:
            if x == prev + 1:
                prev = x
            else:
                out.append((start, prev))
                start = prev = x
        out.append((start, prev))
        runs[y] = out
    rects, active = [], {}
    for y in sorted(runs):
        row = set(runs[y])
        for key in list(active):
            y_start, y_end = active[key]
            if key in row and y_end == y - 1:
                active[key][1] = y
                row.discard(key)
            else:
                rects.append((key[0], y_start, key[1], y_end))
                del active[key]
        for key in row:
            active[key] = [y, y]
    for key, (y_start, y_end) in active.items():
        rects.append((key[0], y_start, key[1], y_end))
    return sorted(rects, key=lambda r: (r[1], r[0]))


def _to_engine(x, y, z):
    """Blender world (x, y, z-up) -> engine/glTF (x, y-up, z)."""
    return [round(x, 4), round(z, 4), round(-y, 4)]


def _package_source(scene, blueprint_obj):
    """(walkable, extra, room_meta) from the live Blueprint, or from the copy stored at generation time
    when Separate by Floor/Room has already consumed the Blueprint object."""
    ts = scene.wfc_tile_size
    fine_h = _fine_level_height(scene)
    if blueprint_obj is not None and blueprint_obj.data.attributes.get("tile_id") is not None:
        walkable, extra = _read_blueprint_points(
            blueprint_obj, ts, fine_h, ("tile_id", "tile_rotation", "room_id", "z_offset"))
        return walkable, extra, json.loads(blueprint_obj.get("gla_room_meta", "[]"))
    cache = json.loads(scene["gla_package_cache"])
    walkable = {(c[0], c[1], c[2]) for c in cache["cells"]}
    extra = {"tile_id": {}, "tile_rotation": {}, "room_id": {}, "z_offset": {}}
    for x, y, z, tid, rot, rid, zo in cache["cells"]:
        extra["tile_id"][(x, y, z)] = tid
        extra["tile_rotation"][(x, y, z)] = rot
        extra["room_id"][(x, y, z)] = rid
        extra["z_offset"][(x, y, z)] = zo
    return walkable, extra, json.loads(cache["rooms"])


def _stair_links(walkable, extra, ts, fine_h):
    """One record per stairwell: the cell it starts on (floor z), where it arrives
    (the cell the run points at, one floor up), and the way back down (the cell
    above the stair cell, arriving at the cell behind it)."""
    tile_ids = extra.get("tile_id", {})
    rotations = extra.get("tile_rotation", {})
    links = []
    for c in sorted(walkable):
        if tile_ids.get(c) != TILE_STAIR:
            continue
        x, y, z = c
        dx, dy = _direction_for_rotation(rotations.get(c, 0.0))
        top = (x + dx, y + dy, z + 1)
        bottom = (x - dx, y - dy, z)
        if top not in walkable or (x, y, z + 1) not in walkable:
            continue  # a stair that does not reach a walkable landing is decoration only
        links.append({"cell": [x, y], "from_z": z, "to_z": z + 1, "dir": [dx, -dy],
                      "up": {"trigger": _to_engine(x * ts, y * ts, z * fine_h), "arrive": _to_engine(top[0] * ts, top[1] * ts, (z + 1) * fine_h)},
                      "down": {"trigger": _to_engine(x * ts, y * ts, (z + 1) * fine_h), "arrive": _to_engine(bottom[0] * ts, bottom[1] * ts, z * fine_h)}})
    return links


def _build_game_package(scene, blueprint_obj, glb_name="", floor=None):
    """The JSON description of the generated level (see the section comment).
    Pure data: reads the blueprint's attributes and the generated light objects.
    floor=k makes a package of ONE floor (grid level z == k): positions are
    relative to that floor's level (the loader shifts the scene down by
    `floor_y`), stairs become links to the neighbouring floors' packages."""
    ts = scene.wfc_tile_size
    fine_h = _fine_level_height(scene)
    walkable, extra, room_meta = _package_source(scene, blueprint_obj)
    tile_ids = extra.get("tile_id", {})
    rotations = extra.get("tile_rotation", {})
    room_ids = extra.get("room_id", {})
    by_z = {}
    for cell in walkable:
        by_z.setdefault(cell[2], set()).add((cell[0], cell[1]))
    all_levels = sorted(by_z)
    floors = []
    for z in all_levels:
        if floor is not None and z != floor:
            continue
        rects = []
        for x0, y0, x1, y1 in _merge_cells_to_rects(by_z[z]):
            ex0, ex1 = (x0 - 0.5) * ts, (x1 + 0.5) * ts
            ey0, ey1 = (y0 - 0.5) * ts, (y1 + 0.5) * ts
            rects.append([round(ex0, 4), round(-ey1, 4), round(ex1, 4), round(-ey0, 4)])  # [x0, z0, x1, z1]
        floors.append({"z": z, "y": round(z * fine_h, 4), "cells": len(by_z[z]), "walk_rects": rects})

    def marker(tile):
        found = [c for c in sorted(walkable) if tile_ids.get(c) == tile and (floor is None or c[2] == floor)]
        if not found:
            return None
        c = found[0]
        y = c[2] * fine_h + extra.get("z_offset", {}).get(c, 0.0)
        return {"floor": c[2], "cell": [c[0], c[1]], "pos": _to_engine(c[0] * ts, c[1] * ts, y - (floor or 0) * fine_h)}

    stairs = []
    for c in sorted(walkable):
        if tile_ids.get(c) == TILE_STAIR:
            dx, dy = _direction_for_rotation(rotations.get(c, 0.0))
            y = c[2] * fine_h + extra.get("z_offset", {}).get(c, 0.0)
            stairs.append({"floor": c[2], "cell": [c[0], c[1]], "pos": _to_engine(c[0] * ts, c[1] * ts, y),
                           "dir": [dx, -dy]})
    links_all = _stair_links(walkable, extra, ts, fine_h)
    rooms = []
    for i, r in enumerate(room_meta):
        if floor is not None and r['z'] != floor:
            continue
        ex0, ex1 = (r['x'] - 0.5) * ts, (r['x'] + r['w'] - 0.5) * ts
        ey0, ey1 = (r['y'] - 0.5) * ts, (r['y'] + r['l'] - 0.5) * ts
        rooms.append({"id": i, "shape": r['shape'], "floor": r['z'],
                      "rect": [round(ex0, 4), round(-ey1, 4), round(ex1, 4), round(-ey0, 4)],
                      "center": [round((ex0 + ex1) / 2, 4), round(-(ey0 + ey1) / 2, 4)]})
    lights = []
    for obj in _objects_matching_prefix(PROPS_LIGHT_NAME_PREFIX):
        if obj.type != 'LIGHT':
            continue
        loc = obj.matrix_world.translation
        if floor is not None and abs(loc.z - floor * fine_h) > fine_h * 0.5 + 0.01:
            continue
        lights.append({"pos": _to_engine(loc.x, loc.y, loc.z - (floor or 0) * fine_h), "color": [round(c, 4) for c in obj.data.color],
                       "energy_w": round(obj.data.energy, 3), "radius": round(obj.data.shadow_soft_size, 3)})
    props = []
    deco = bpy.data.objects.get(PROPS_DECORATION_OBJECT_NAME)
    if deco is not None and deco.get("gla_props"):
        for x, y, z, kind, rot in json.loads(deco["gla_props"]):
            if floor is not None and abs(z - floor * fine_h) > fine_h * 0.5 + 0.01:
                continue
            props.append({"kind": kind, "pos": _to_engine(x, y, z - (floor or 0) * fine_h), "yaw": rot})
    return {
        "format": GAME_PACKAGE_FORMAT,
        "generator": "Game Level Architect " + ".".join(str(v) for v in bl_info["version"]),
        "seed": scene.wfc_seed,
        "glb": glb_name,
        "tile_size": ts,
        "level_height": fine_h,
        "wall_height": scene.wfc_wall_height,
        "props": props,
        "floor_index": floor,
        "floor_count": len(all_levels),
        "floor_y": round((floor or 0) * fine_h, 4),
        "stair_links": [dict(l, **{"direction": "up", "to_floor": l["to_z"]}) for l in links_all if floor is not None and l["from_z"] == floor]
                       + [dict(l, **{"direction": "down", "to_floor": l["from_z"]}) for l in links_all if floor is not None and l["to_z"] == floor],
        "coordinates": "engine: x right, y up, z = -blender_y",
        "floors": floors,
        "entrance": marker(TILE_ENTRANCE),
        "exit": marker(TILE_EXIT),
        "stairs": stairs,
        "rooms": rooms,
        "lights": lights,
    }


class OBJECT_OT_ExportGamePackage(bpy.types.Operator, ExportHelper):
    """Exports the level as glTF AND a JSON description (walkable rectangles,
    entrance/exit, rooms, stairs, lights) next to it, so an engine loader does
    not have to guess where a character may walk."""
    bl_idname = "object.export_game_package"
    bl_label = "Export Game Package (glb + json)"
    bl_description = "Export the level as glTF plus a JSON file describing walkable areas, entrance/exit, rooms and lights"
    bl_options = {'REGISTER'}

    filename_ext = ".glb"
    filter_glob: StringProperty(default="*.glb", options={'HIDDEN'})
    per_floor: BoolProperty(
        name="One package per floor", default=False,
        description="Write <name>_f0.glb/.json, <name>_f1.glb/.json ... one self-contained package per floor, linked "
                    "by stair records. Needs Wall/Door/Stair grouping = Per Floor and Separate by Floor/Room run on the Blueprint")

    @staticmethod
    def _band_copy(obj, z_lo, z_hi, label):
        """A temporary copy of obj keeping only the faces whose centre lies in [z_lo, z_hi). None when nothing
        is left. Used to cut one grid level out of an object that holds several (sub-levels per floor)."""
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        drop = [f for f in bm.faces if not (z_lo <= f.calc_center_median().z < z_hi)]
        bmesh.ops.delete(bm, geom=drop, context='FACES')
        if not bm.faces:
            bm.free()
            return None
        mesh = bpy.data.meshes.new(obj.name + label + "_Mesh")
        bm.to_mesh(mesh)
        bm.free()
        for mat in obj.data.materials:
            mesh.materials.append(mat)
        temp = bpy.data.objects.new(obj.name + label, mesh)
        bpy.context.collection.objects.link(temp)
        return temp

    def _floor_targets(self, z, fine_h, sub):
        """Objects of grid level z. With one level per logical floor that is simply the floor's own objects; with
        several (Sub-Levels per Floor) every floor object is cut down to the faces of this level, door panels are
        taken whole by their hinge height, and the Round-room floor overlay is cut by height."""
        floor = z // sub
        pattern = re.compile(r"_Floor%d(_|$)" % floor)
        z_lo, z_hi = z * fine_h - 0.15, (z + 1) * fine_h - 0.15
        targets, temps = [], []
        candidates = [o for o in bpy.data.objects
                      if o.type == 'MESH' and o.name.startswith("Procedural_Level_") and pattern.search(o.name)
                      and not o.name.startswith(PROPS_TORCH_OBJECT_NAME)]
        for o in candidates:
            if sub == 1:
                targets.append(o)
            elif "_Panel_" in o.name:
                if z_lo <= o.matrix_world.translation.z < z_hi:
                    targets.append(o)
            else:
                t = self._band_copy(o, z_lo, z_hi, f"_Z{z}")
                if t is not None:
                    targets.append(t)
                    temps.append(t)
        rf = bpy.data.objects.get(ROUND_FLOOR_OBJECT_NAME)
        if rf is not None:
            t = self._band_copy(rf, z_lo, z_hi, f"_Z{z}")
            if t is not None:
                targets.append(t)
                temps.append(t)
        return targets, temps

    def _export_floors(self, context, stem, blueprint_obj):
        scene = context.scene
        sub = max(1, scene.wfc_sub_levels_per_floor)
        fine_h = _fine_level_height(scene)
        base = _build_game_package(scene, blueprint_obj, "")
        levels = [f["z"] for f in base["floors"]]
        written = []
        previous = scene.wfc_export_binary
        scene.wfc_export_binary = True
        try:
            for z in levels:
                targets, temps = self._floor_targets(z, fine_h, sub)
                if not any(o.name.startswith(BLUEPRINT_OBJECT_NAME) for o in targets):
                    self.report({'ERROR'}, f"Floor {z}: no per-floor Blueprint object. Set Wall/Door/Stair grouping to Per Floor, "
                                           f"generate them, and run Separate by Floor/Room on the Blueprint first.")
                    return {'CANCELLED'}
                glb = f"{stem}_f{z}.glb"
                try:
                    _run_gltf_export(context, glb, targets, False)
                finally:
                    for temp in temps:
                        mesh = temp.data
                        bpy.data.objects.remove(temp, do_unlink=True)
                        bpy.data.meshes.remove(mesh)
                package = _build_game_package(scene, blueprint_obj, os.path.basename(glb), floor=z)
                with open(f"{stem}_f{z}.json", "w", encoding="utf-8") as fh:
                    json.dump(package, fh, indent=1)
                written.append(os.path.basename(glb))
        finally:
            scene.wfc_export_binary = previous
        self.report({'INFO'}, "Exported per-floor packages: " + ", ".join(written))
        return {'FINISHED'}

    def execute(self, context):
        scene = context.scene
        blueprint_obj = bpy.data.objects.get(BLUEPRINT_OBJECT_NAME)
        if (blueprint_obj is None or blueprint_obj.data.attributes.get("tile_id") is None) and not scene.get("gla_package_cache"):
            self.report({'ERROR'}, "Generate a Game Blueprint first.")
            return {'CANCELLED'}
        if not hasattr(bpy.ops.export_scene, "gltf"):
            self.report({'ERROR'}, "glTF exporter isn't available -- enable Import-Export: glTF 2.0.")
            return {'CANCELLED'}
        if self.per_floor:
            return self._export_floors(context, os.path.splitext(self.filepath)[0], blueprint_obj)
        base_names = (
            BLUEPRINT_OBJECT_NAME, ROUND_FLOOR_OBJECT_NAME, WALLS_OBJECT_NAME, WALLS_ROUND_OBJECT_NAME,
            STAIRS_OBJECT_NAME, DOORS_OBJECT_NAME, DOORS_ROUND_OBJECT_NAME, PROPS_TORCH_OBJECT_NAME,
            PROPS_DECORATION_OBJECT_NAME, WINDOWS_OBJECT_NAME,
        )
        targets = _gltf_export_targets(base_names, False)
        stem = os.path.splitext(self.filepath)[0]
        glb_path = stem + ".glb"
        scene_binary = scene.wfc_export_binary
        scene.wfc_export_binary = True  # the package always references one self-contained .glb
        try:
            _run_gltf_export(context, glb_path, targets, False)
        finally:
            scene.wfc_export_binary = scene_binary
        package = _build_game_package(scene, blueprint_obj, os.path.basename(glb_path))
        json_path = stem + ".json"
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(package, fh, indent=1)
        self.report({'INFO'}, f"Exported '{glb_path}' and '{json_path}' ({sum(len(f['walk_rects']) for f in package['floors'])} walk rectangles).")
        return {'FINISHED'}


def _castle_walk_cells(width, depth, wall_t, tower_r, gate, keep, step=0.5, apron=8.0, tower_wall=0.55,
                       hall_furniture=True):
    """Walkable ground of a castle (see _build_castle_mesh), in castle-local
    Blender XY, as grid cells of `step` metres centred on multiples of step:
    the courtyard inside the curtain walls minus the corner towers and the
    keep, the gate passage, and an apron of open ground in front of the
    gate. Every cell keeps >= 0.45 m clear of masonry. Returns a set of (i, j)."""
    hx, hy = width / 2.0, depth / 2.0
    m = 0.45
    ks = max(6.0, min(width, depth) * 0.38)
    kt = max(wall_t, 1.0)
    kcx, kcy = 0.0, depth * 0.12
    kb = ks / 2.0 + kt / 2.0 + 0.5
    towers = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]
    furniture = []   # (x, y, half-extent x, half-extent y) incl. a 0.35 m walking margin, axis-aligned boxes
    if keep and hall_furniture:
        for fx, fy, _z, kind, rot in _keep_hall_layout(ks, kt, kcx, kcy):
            xmin, xmax, ymin, ymax = _prop_local_bounds(kind, 2.0)
            c_, s_ = math.cos(rot), math.sin(rot)
            pts = [(fx + lx * c_ - ly * s_, fy + lx * s_ + ly * c_) for lx in (xmin, xmax) for ly in (ymin, ymax)]
            cxm, cym = (min(p_[0] for p_ in pts) + max(p_[0] for p_ in pts)) / 2.0, (min(p_[1] for p_ in pts) + max(p_[1] for p_ in pts)) / 2.0
            furniture.append((cxm, cym, (max(p_[0] for p_ in pts) - min(p_[0] for p_ in pts)) / 2.0 + 0.35,
                              (max(p_[1] for p_ in pts) - min(p_[1] for p_ in pts)) / 2.0 + 0.35))
    cells = set()
    nx, ny = int(math.ceil((hx + apron) / step)) + 1, int(math.ceil((hy + apron) / step)) + 1
    for i in range(-nx, nx + 1):
        for j in range(-ny, ny + 1):
            x, y = i * step, j * step
            inside = abs(x) <= hx - wall_t / 2.0 - m and abs(y) <= hy - wall_t / 2.0 - m
            if inside:
                if any(math.hypot(x - tx, y - ty) < tower_r + m for tx, ty in towers):
                    inside = False
                if keep and abs(x - kcx) <= kb and abs(y - kcy) <= kb:
                    inside = False
            passage = gate and abs(x) <= 1.1 and -hy - apron <= y <= -hy + wall_t / 2.0 + m
            if keep:
                kin = ks / 2.0 - kt / 2.0 - m
                if abs(x - kcx) <= kin and abs(y - kcy) <= kin:
                    passage = not any(abs(x - fx) <= fhx and abs(y - fy) <= fhy for fx, fy, fhx, fhy in furniture)   # inside the keep's hall, clear of furniture
                if abs(x - kcx) <= 0.8 and kcy - ks / 2.0 - kt / 2.0 - m <= y <= kcy - ks / 2.0 + kt / 2.0 + m:
                    passage = True   # through the keep's south door
            outside_apron = gate and abs(x) <= 6.0 and -hy - apron <= y <= -hy - wall_t / 2.0 - m
            if inside or passage or outside_apron:
                cells.add((i, j))
    return cells


def _castle_package_rooms(scene, cells, step, ox, oy):
    """Named open areas a loader can anchor story props to: the yard inside the gate, the ground in front of the keep,
    the west and east yards (snapped to walkable cells; towers and the keep interior are not reachable)."""
    W, D = scene.wfc_castle_width, scene.wfc_castle_depth
    ks = max(6.0, min(W, D) * 0.38)
    kt = max(scene.wfc_castle_wall_thickness, 1.0)
    kcy = D * 0.12
    spots = [("COURTYARD", 0.0, -D / 2.0 + 4.5), ("KEEP_FRONT", 0.0, kcy - ks / 2.0 - kt / 2.0 - 1.1),
             ("WEST_YARD", -W * 0.3, D * 0.12), ("EAST_YARD", W * 0.3, D * 0.12)]
    if not scene.wfc_castle_keep:
        spots[1] = ("KEEP_FRONT", 0.0, 0.0)
    else:
        spots.append(("KEEP_HALL", 0.0, kcy))
    rooms = []
    for i, (name, x, y) in enumerate(spots):
        # cells here are already shifted by (ox, oy); snap in that frame
        gx, gy = round(x / step) + ox, round(y / step) + oy
        near = min(cells, key=lambda c: (c[0] - gx) ** 2 + (c[1] - gy) ** 2)
        cx, cy = near[0] * step, near[1] * step
        rooms.append({"id": i, "shape": name, "floor": 0,
                      "rect": [round(cx - 1.5, 4), round(-cy - 1.5, 4), round(cx + 1.5, 4), round(-cy + 1.5, 4)],
                      "center": [round(cx, 4), round(-cy, 4)]})
    return rooms


def _castle_package_props(scene, loc):
    if not (scene.wfc_castle_keep and scene.wfc_castle_hall_props):
        return []
    W, D = scene.wfc_castle_width, scene.wfc_castle_depth
    ks = max(6.0, min(W, D) * 0.38)
    kt = max(scene.wfc_castle_wall_thickness, 1.0)
    return [{"kind": kind, "pos": _to_engine(loc.x + x, loc.y + y, loc.z + z), "yaw": round(rot, 4)}
            for x, y, z, kind, rot in _keep_hall_layout(ks, kt, 0.0, D * 0.12)]


def _castle_package_lights(scene, loc):
    """Torches beside the gate and in the courtyard corners (the glTF itself carries no lights)."""
    hx, hy = scene.wfc_castle_width / 2.0, scene.wfc_castle_depth / 2.0
    spots = [(-2.2, -hy - 0.9), (2.2, -hy - 0.9)]
    spots += [(sx * (hx - 5.0), sy * (hy - 4.5)) for sx in (-1, 1) for sy in (-1, 1)]
    if scene.wfc_castle_keep:
        spots.append((0.0, hy * 0.24))   # the keep's hall (its centre, as in _build_castle_mesh)
    return [{"pos": _to_engine(loc.x + x, loc.y + y, loc.z + 2.6), "color": [1.0, 0.55, 0.24], "energy_w": 80.0, "radius": 0.25}
            for x, y in spots]


def _build_castle_package(scene, castle_obj, glb_name=""):
    """gla-export/1 description of a castle: walkable rectangles of its
    ground (see _castle_walk_cells), an entrance at the far end of the apron
    (or inside the courtyard when there is no gate), no lights. Positions
    include the object's location, like the exported glTF."""
    step = 0.5
    loc = castle_obj.location
    cells = _castle_walk_cells(
        scene.wfc_castle_width, scene.wfc_castle_depth, scene.wfc_castle_wall_thickness,
        scene.wfc_castle_tower_radius, scene.wfc_castle_gate, scene.wfc_castle_keep, step,
        hall_furniture=scene.wfc_castle_hall_props)
    # the exported cell grid is in the glTF's world space: shift by the object's location (a multiple of step)
    ox, oy = round(loc.x / step), round(loc.y / step)
    cells = {(i + ox, j + oy) for i, j in cells}
    rects = []
    for x0, y0, x1, y1 in _merge_cells_to_rects(cells):
        ex0, ex1 = (x0 - 0.5) * step, (x1 + 0.5) * step
        ey0, ey1 = (y0 - 0.5) * step, (y1 + 0.5) * step
        rects.append([round(ex0, 4), round(-ey1, 4), round(ex1, 4), round(-ey0, 4)])
    hy = scene.wfc_castle_depth / 2.0
    if scene.wfc_castle_gate:
        entrance = (loc.x, loc.y - hy - 7.0)
        exit_pt = (loc.x, loc.y - hy - 7.5)
    else:
        entrance = (loc.x, loc.y - hy / 2.0)
        exit_pt = (loc.x, loc.y - hy / 2.0 - 0.5)
    snap = lambda v: round(v / step) * step
    return {
        "format": GAME_PACKAGE_FORMAT,
        "generator": "Game Level Architect " + ".".join(str(v) for v in bl_info["version"]),
        "kind": "castle",
        "seed": scene.wfc_seed,
        "glb": glb_name,
        "tile_size": step,
        "interior": False,
        "coordinates": "engine: x right, y up, z = -blender_y",
        "floors": [{"z": 0, "y": round(loc.z, 4), "cells": len(cells), "walk_rects": rects}],
        "entrance": {"floor": 0, "pos": _to_engine(snap(entrance[0]), snap(entrance[1]), loc.z)},
        "exit": {"floor": 0, "pos": _to_engine(snap(exit_pt[0]), snap(exit_pt[1]), loc.z)},
        "stairs": [], "rooms": _castle_package_rooms(scene, cells, step, ox, oy), "lights": _castle_package_lights(scene, loc),
        "props": _castle_package_props(scene, loc), "wall_height": scene.wfc_castle_wall_height,
        "castle": {"width": scene.wfc_castle_width, "depth": scene.wfc_castle_depth,
                   "ruin": scene.wfc_castle_ruin, "gate": scene.wfc_castle_gate, "keep": scene.wfc_castle_keep},
    }


class OBJECT_OT_ExportCastlePackage(bpy.types.Operator, ExportHelper):
    """Exports the generated castle as glTF plus its JSON description (walkable
    courtyard, gate passage and apron), the same "gla-export/1" format as a
    level package."""
    bl_idname = "object.export_castle_package"
    bl_label = "Export Castle Package (glb + json)"
    bl_options = {'REGISTER'}

    filename_ext = ".glb"
    filter_glob: StringProperty(default="*.glb", options={'HIDDEN'})

    def execute(self, context):
        scene = context.scene
        castle = bpy.data.objects.get(CASTLE_OBJECT_NAME)
        if castle is None:
            self.report({'ERROR'}, "Generate a Castle first.")
            return {'CANCELLED'}
        if not hasattr(bpy.ops.export_scene, "gltf"):
            self.report({'ERROR'}, "glTF exporter isn't available -- enable Import-Export: glTF 2.0.")
            return {'CANCELLED'}
        stem = os.path.splitext(self.filepath)[0]
        previous = scene.wfc_export_binary
        scene.wfc_export_binary = True
        try:
            _run_gltf_export(context, stem + ".glb", [castle], False)
        finally:
            scene.wfc_export_binary = previous
        package = _build_castle_package(scene, castle, os.path.basename(stem) + ".glb")
        with open(stem + ".json", "w", encoding="utf-8") as fh:
            json.dump(package, fh, indent=1)
        self.report({'INFO'}, f"Exported '{stem}.glb' and '{stem}.json' ({len(package['floors'][0]['walk_rects'])} walk rectangles).")
        return {'FINISHED'}


def _section(layout, idname, title, icon, default_closed=False):
    """A collapsible section with a native disclosure triangle (Blender's
    UILayout.panel(), added in 4.1) that remembers open/closed state on its
    own -- falls back to a plain always-open box on any Blender build where
    that API isn't available or has a different signature, so the panel
    still renders either way.

    Returns the body layout to draw into, or None if the section is
    currently collapsed -- callers must check before adding widgets."""
    panel_func = getattr(layout, 'panel', None)
    if panel_func is not None:
        try:
            header, body = panel_func(idname, default_closed=default_closed)
            header.label(text=title, icon=icon)
            return body
        except TypeError as exc:
            print(f"[Level Architect] layout.panel() unavailable, using a plain box: {exc}")
    box = layout.box()
    box.label(text=title, icon=icon)
    return box


def _color_swatch(layout, color_icon):
    """A small colored square, purely a visual accent with no function --
    reuses Blender's own built-in collection-color icon set (the same
    swatches used for collection/strip color tags, stable since 2.80)
    rather than shipping or generating custom icon images. Wrapped
    defensively: this is cosmetic only, so if a future Blender build ever
    renames these icons, the addon quietly draws a blank space here
    instead of breaking the whole panel."""
    swatch = layout.row(align=True)
    swatch.scale_x = 0.4
    try:
        swatch.label(text="", icon=color_icon)
    except TypeError as exc:
        print(f"[Level Architect] Could not draw color accent '{color_icon}': {exc}")
        swatch.label(text="")


def _step_button(layout, idname, text, icon, color_icon):
    """One of the 3 main generation buttons -- taller than a normal button
    and paired with a color accent so the actions that actually DO
    something stand out from the settings stacked above them. Always
    drawn at full visibility (never inside a collapsible section), so
    collapsing a step's settings to save space never hides its button."""
    row = layout.row(align=True)
    row.scale_y = 1.4
    _color_swatch(row, color_icon)
    row.operator(idname, text=text, icon=icon)


class WFC_FloorProfile(bpy.types.PropertyGroup):
    """One per-floor override breakpoint (see 'Per-Floor Overrides' in the
    Rooms section) -- floor_index is a LOGICAL floor (0-based, same axis as
    the Height field), room_size_min/max and room_shape apply from this
    floor onward until the next breakpoint (room size interpolates
    smoothly between breakpoints, room_shape/style switch at the
    breakpoint since they're not numeric -- see WFC_Level_Solver.
    _room_size_for_floor / _room_shape_for_floor and this file's
    _style_for_logical_floor). An empty list (the default) falls back to
    the flat Rooms-section values everywhere, unchanged from before this
    feature existed. Deliberately no 'Cave' room_shape option here --
    mixing Cave with non-Cave floors in one generation is a separate,
    larger, already-tracked limitation (DEVELOPMENT.md "Cave mode is an
    all-or-nothing setting"), not something this feature attempts."""
    floor_index: IntProperty(name="Floor", min=0, default=0)
    room_size_min: IntProperty(name="Min Size", min=1, max=20, default=2)
    room_size_max: IntProperty(name="Max Size", min=1, max=20, default=4)
    room_shape: EnumProperty(
        name="Shape",
        items=[
            ('RECT', "Rectangular", "Classic rectangular rooms"),
            ('ROUND', "Round", "Circular/oval rooms, approximated on the tile grid"),
            ('MIXED', "Mixed", "Randomly rectangular or round, chosen per room"),
        ],
        default='RECT',
    )
    style: EnumProperty(
        name="Style",
        items=[
            ('0', "Dungeon", "Strict modular grids"),
            ('1', "Cave", "Organic rock layouts"),
            ('2', "Open Area", "Flat layout with barriers"),
        ],
        default='0',
    )


class WFC_UL_FloorProfiles(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, "floor_index", text="Floor")
        row.prop(item, "room_size_min", text="Min")
        row.prop(item, "room_size_max", text="Max")
        row.prop(item, "room_shape", text="")
        row.prop(item, "style", text="")


class OBJECT_OT_FloorProfileAdd(bpy.types.Operator):
    """Adds a new per-floor override breakpoint, seeded from the current
    flat Rooms-section values (and one floor past the highest existing
    breakpoint, or 0 for the first one) so it starts as a no-op until the
    user actually changes something on it."""
    bl_idname = "object.wfc_floor_profile_add"
    bl_label = "Add Floor Override"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        profiles = scene.wfc_floor_profiles
        item = profiles.add()
        item.floor_index = max((p.floor_index for p in profiles[:-1]), default=-1) + 1
        item.room_size_min = min(scene.wfc_room_size_min, scene.wfc_room_size_max)
        item.room_size_max = max(scene.wfc_room_size_min, scene.wfc_room_size_max)
        item.room_shape = scene.wfc_room_shape if scene.wfc_room_shape != 'CAVE' else 'RECT'
        item.style = scene.wfc_style
        scene.wfc_floor_profiles_active_index = len(profiles) - 1
        return {'FINISHED'}


class OBJECT_OT_FloorProfileRemove(bpy.types.Operator):
    bl_idname = "object.wfc_floor_profile_remove"
    bl_label = "Remove Floor Override"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        profiles = scene.wfc_floor_profiles
        index = scene.wfc_floor_profiles_active_index
        if 0 <= index < len(profiles):
            profiles.remove(index)
            scene.wfc_floor_profiles_active_index = min(index, len(profiles) - 1)
        return {'FINISHED'}


def _style_for_logical_floor(floor_profiles, logical_floor, default_style):
    """Step function (style isn't numeric, so no interpolation): the LAST
    floor_profiles breakpoint at or before this logical floor wins; falls
    back to default_style before the first breakpoint or when
    floor_profiles is empty. floor_profiles is a plain list of dicts (see
    OBJECT_OT_GenerateGameBlueprint.execute(), built once per generation
    from scene.wfc_floor_profiles) -- same shape WFC_Level_Solver takes,
    reused here so both the room-shape/size side and the material-style
    side read the identical breakpoint data."""
    chosen = default_style
    for p in sorted(floor_profiles, key=lambda p: p['floor_index']):
        if p['floor_index'] <= logical_floor:
            chosen = p['style']
        else:
            break
    return chosen


PRESETS = {
    'ISOMETRIC': dict(
        # Isometric / top-down: looking down INTO rooms, so no ceiling;
        # moderate size/room count, Mixed shapes for readable variety, a
        # couple of logical floors with light elevation for gentle
        # verticality without needing to look up/down much.
        wfc_width=30, wfc_length=30, wfc_height=2, wfc_rooms_min=15, wfc_rooms_max=25,
        wfc_room_size_min=3, wfc_room_size_max=6, wfc_room_shape='MIXED', wfc_room_shape_sides=12,
        wfc_sub_levels_per_floor=1, wfc_split_level_chance=0.2, wfc_elevation_chance=0.1,
        wfc_elevation_range=0.5, wfc_stairs_per_level=3, wfc_tile_size=2.0, wfc_level_height=3.5,
        wfc_add_ceiling=False, wfc_iso_mode=True, wfc_wall_height=3.0, wfc_wall_thickness=0.25,
        wfc_door_height=2.2, wfc_torch_chance=0.15, wfc_prop_chance=0.12, wfc_organic_amount=0.05,
    ),
    'FPS': dict(
        # FPS / Immersive-Sim: seen from INSIDE, so Add Ceiling is on and
        # Isometric Mode is off; Round rooms read as genuinely interesting
        # geometry walking through them in first-person (unlike a top-down
        # view, where corner-cutting barely registers); more sub-levels/
        # elevation range and more logical floors for real dramatic
        # verticality, taller walls, arched doors.
        wfc_width=26, wfc_length=26, wfc_height=4, wfc_rooms_min=10, wfc_rooms_max=18,
        wfc_room_size_min=4, wfc_room_size_max=8, wfc_room_shape='ROUND', wfc_room_shape_sides=10,
        wfc_sub_levels_per_floor=2, wfc_split_level_chance=0.4, wfc_elevation_chance=0.3,
        wfc_elevation_range=1.5, wfc_stairs_per_level=4, wfc_stair_bend_chance=0.3,
        # Level Height must be >= Sub-Levels per Floor * Wall Height (see
        # the module-level _adjusting_level_geometry cross-consistency
        # system near register()) -- 2 sub-levels * a 4.0m wall needs at
        # least 8.0m of headroom, so this is picked to already satisfy
        # that constraint rather than relying on the auto-grow callback.
        wfc_tile_size=2.2, wfc_level_height=8.0, wfc_add_ceiling=True, wfc_iso_mode=False,
        wfc_wall_height=4.0, wfc_wall_thickness=0.3, wfc_wall_cap_top=True, wfc_door_height=2.4,
        wfc_door_style='ROUND', wfc_torch_chance=0.25, wfc_torch_light_chance=0.6,
        wfc_prop_chance=0.2, wfc_organic_amount=0.1,
    ),
    'ROGUELIKE': dict(
        # Compact Roguelike: small tight Rect rooms, high room count
        # relative to a small map, single floor -- classic dense top-down
        # crawler. Door Merge Distance=0 keeps doorways as many distinct
        # openings rather than merging nearby ones into fewer big gaps;
        # Organic Irregularity off for a clean, deliberate grid look.
        wfc_width=20, wfc_length=20, wfc_height=1, wfc_rooms_min=20, wfc_rooms_max=35,
        wfc_room_size_min=2, wfc_room_size_max=4, wfc_room_shape='RECT', wfc_room_shape_sides=16,
        wfc_sub_levels_per_floor=1, wfc_split_level_chance=0.0, wfc_elevation_chance=0.0,
        wfc_elevation_range=0.0, wfc_stairs_per_level=1, wfc_tile_size=2.0, wfc_level_height=3.0,
        wfc_add_ceiling=False, wfc_iso_mode=True, wfc_wall_height=2.5, wfc_wall_thickness=0.2,
        wfc_door_merge_distance=0, wfc_door_height=2.0, wfc_torch_chance=0.1, wfc_prop_chance=0.15,
        wfc_organic_amount=0.0,
    ),
    'MEGADUNGEON': dict(
        # Megadungeon: large map, big room count, several logical floors
        # grouped Per-Floor (so each story's stairs/walls are easy to
        # isolate on a map this size), Mixed shapes and moderate elevation
        # variety for sprawl rather than any one particular camera style.
        wfc_width=45, wfc_length=45, wfc_height=6, wfc_rooms_min=40, wfc_rooms_max=70,
        wfc_room_size_min=3, wfc_room_size_max=7, wfc_room_shape='MIXED', wfc_room_shape_sides=12,
        wfc_sub_levels_per_floor=2, wfc_split_level_chance=0.3, wfc_elevation_chance=0.15,
        wfc_elevation_range=1.0, wfc_stairs_per_level=6, wfc_stair_grouping='PER_FLOOR',
        # Same headroom constraint as FPS's own preset entry above: 2
        # sub-levels * a 3.5m wall needs at least 7.0m of Level Height.
        wfc_wall_grouping='PER_FLOOR', wfc_tile_size=2.0, wfc_level_height=7.0,
        wfc_add_ceiling=True, wfc_iso_mode=False, wfc_wall_height=3.5, wfc_wall_thickness=0.25,
        wfc_torch_chance=0.15, wfc_prop_chance=0.1, wfc_organic_amount=0.05,
    ),
}

PRESET_LABELS = {
    'ISOMETRIC': "Isometric", 'FPS': "FPS / Immersive-Sim",
    'ROGUELIKE': "Compact Roguelike", 'MEGADUNGEON': "Megadungeon",
}


class OBJECT_OT_ApplyGLAPreset(bpy.types.Operator):
    """Sets every scene property PRESETS[self.preset] names -- does NOT
    generate anything itself, same "one button, one job" precedent every
    other operator here follows (the user still presses Step 1
    afterward). Only ever touches the flat wfc_* scene properties --
    wfc_floor_profiles (Per-Floor Overrides) is left untouched, since an
    empty profile list already falls straight back to those flat values."""
    bl_idname = "object.apply_level_architect_preset"
    bl_label = "Apply Preset"
    bl_description = "Set Width/Rooms/Levels/Walls/etc. to values tuned for a target camera/genre"
    bl_options = {'REGISTER', 'UNDO'}

    preset: StringProperty()

    def execute(self, context):
        settings = PRESETS.get(self.preset)
        if settings is None:
            self.report({'ERROR'}, f"Unknown preset '{self.preset}'.")
            return {'CANCELLED'}
        scene = context.scene
        for key, value in settings.items():
            setattr(scene, key, value)
        self.report({'INFO'}, f"Applied {PRESET_LABELS.get(self.preset, self.preset)} preset.")
        return {'FINISHED'}


class VIEW3D_PT_GameLevelArchitect(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Level Architect'
    bl_label = "Procedural Game Architect"

    def draw(self, context):
        scene = context.scene
        layout = self.layout

        col = layout.column(align=True)
        col.label(text="Presets")
        preset_items = list(PRESET_LABELS.items())
        for k in range(0, len(preset_items), 2):
            row = col.row(align=True)
            for preset_key, label in preset_items[k:k + 2]:
                op = row.operator("object.apply_level_architect_preset", text=label)
                op.preset = preset_key
        layout.separator()

        tabs = layout.row(align=True)
        tabs.prop(scene, "wfc_active_tab", expand=True, icon_only=True)
        layout.separator()

        if scene.wfc_active_tab == 'SETUP':
            self._draw_setup_tab(context, layout)
        elif scene.wfc_active_tab == 'WALLS':
            self._draw_walls_tab(context, layout)
        elif scene.wfc_active_tab == 'STAIRS':
            self._draw_stairs_tab(context, layout)
        elif scene.wfc_active_tab == 'DOORS':
            self._draw_doors_tab(context, layout)
        elif scene.wfc_active_tab == 'PROPS':
            self._draw_props_tab(context, layout)
        elif scene.wfc_active_tab == 'EXPORT':
            self._draw_export_tab(context, layout)
        elif scene.wfc_active_tab == 'TOWER':
            self._draw_tower_tab(context, layout)
        elif scene.wfc_active_tab == 'CASTLE':
            self._draw_castle_tab(context, layout)

        layout.separator()
        section = _section(layout, "LA_debug", "Debug: Last Generation Params", 'CONSOLE', default_closed=True)
        if section:
            if scene.wfc_debug_params:
                box = section.box()
                col = box.column(align=True)
                col.scale_y = 0.75
                for line in scene.wfc_debug_params.split("\n"):
                    col.label(text=line)
            else:
                section.label(text="Run a step below to capture its settings here.")
            section.operator("object.copy_level_architect_params", text="Copy Parameters", icon='COPYDOWN')

    def _draw_setup_tab(self, context, layout):
        scene = context.scene

        section = _section(layout, "LA_map", "Map & Seed", 'MESH_GRID')
        if section:
            col = section.column(align=True)
            row = col.row(align=True)
            row.prop(scene, "wfc_width", text="W")
            row.prop(scene, "wfc_length", text="L")
            col.prop(scene, "wfc_height", text="Height (Z)")
            col.separator()
            row = section.row(align=True)
            seed_row = row.row(align=True)
            seed_row.enabled = not scene.wfc_random_seed
            seed_row.prop(scene, "wfc_seed", text="Seed")
            row.prop(scene, "wfc_random_seed", text="", icon='FILE_REFRESH', toggle=True)

        section = _section(layout, "LA_rooms", "Rooms", 'HOME', default_closed=True)
        if section:
            col = section.column(align=True)
            row = col.row(align=True)
            row.prop(scene, "wfc_rooms_min", text="Min")
            row.prop(scene, "wfc_rooms_max", text="Max")
            row = col.row(align=True)
            row.prop(scene, "wfc_room_size_min", text="Min Size")
            row.prop(scene, "wfc_room_size_max", text="Max Size")
            col.prop(scene, "wfc_room_shape", text="Shape")
            col.prop(scene, "wfc_room_shape_sides", text="Shape Sides")
            col.separator()

            overrides_box = section.box()
            overrides_box.label(text="Per-Floor Overrides", icon='NLA_PUSHDOWN')
            if scene.wfc_room_shape == 'CAVE':
                overrides_box.label(
                    text="Ignored while Room Shape is Cave (whole level is Cave).", icon='INFO'
                )
            else:
                overrides_box.label(
                    text="Size/Shape/Style from this floor on -- size blends between rows, "
                         "Shape/Style switch.",
                )
                list_row = overrides_box.row()
                list_row.template_list(
                    "WFC_UL_FloorProfiles", "", scene, "wfc_floor_profiles",
                    scene, "wfc_floor_profiles_active_index", rows=3,
                )
                button_col = list_row.column(align=True)
                button_col.operator("object.wfc_floor_profile_add", text="", icon='ADD')
                button_col.operator("object.wfc_floor_profile_remove", text="", icon='REMOVE')
            col = section.column(align=True)
            col.separator()
            col.prop(scene, "wfc_sub_levels_per_floor", text="Sub-Levels / Floor")
            split_row = col.column(align=True)
            split_row.enabled = scene.wfc_sub_levels_per_floor > 1
            split_row.prop(scene, "wfc_split_level_chance", text="Split-Level Chance")
            col.separator()
            col.prop(scene, "wfc_elevation_chance", text="Elevation Chance")
            elevation_row = col.row(align=True)
            elevation_row.enabled = scene.wfc_elevation_chance > 0.0
            elevation_row.prop(scene, "wfc_elevation_range", text="Range")
            elevation_row.prop(scene, "wfc_max_ramp_slope", text="Max Angle")

        section = _section(layout, "LA_scale_style", "Scale & Style", 'SETTINGS', default_closed=True)
        if section:
            col = section.column(align=True)
            row = col.row(align=True)
            row.prop(scene, "wfc_tile_size", text="Tile (m)")
            row.prop(scene, "wfc_level_height", text="Floor (m)")
            col.prop(scene, "wfc_floor_thickness", text="Floor Thickness (m)")
            col.prop(scene, "wfc_add_ceiling", text="Add Ceiling")
            ceiling_row = col.column(align=True)
            ceiling_row.enabled = scene.wfc_add_ceiling
            ceiling_row.prop(scene, "wfc_ceiling_thickness", text="Ceiling Thickness (m)")
            col.prop(scene, "wfc_organic_amount", text="Organic Irregularity (m)")
            col.prop(scene, "wfc_uv_tile_size", text="UV Tile Size (m)")
            col.separator()
            col.prop(scene, "wfc_simple_materials", text="Simple Viewport Colors")
            style_col = section.column(align=True)
            style_col.enabled = not scene.wfc_simple_materials
            style_col.prop(scene, "wfc_style", text="Visual Style")
            col = section.column(align=True)
            col.prop(scene, "wfc_iso_mode", text="Isometric Mode (Cull Ceilings)")
            col.prop(scene, "wfc_color_rooms", text="Color Rooms/Corridors")

        layout.separator()
        _step_button(
            layout, "object.generate_game_blueprint", "Step 1: Generate Blueprint",
            'MESH_CUBE', 'COLLECTION_COLOR_05',
        )
        util_row = layout.row(align=True)
        util_row.operator("object.separate_level_by_floor", text="Separate by Floor/Room", icon='MOD_EXPLODE')
        util_row.enabled = context.active_object is not None and context.active_object.type == 'MESH'

        freeze_row = layout.row(align=True)
        freeze_row.operator("object.freeze_level_for_texture_work", text="Freeze for Texture Work", icon='LOCKED')
        freeze_row.enabled = bpy.data.objects.get(BLUEPRINT_OBJECT_NAME) is not None

    def _draw_walls_tab(self, context, layout):
        scene = context.scene
        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(scene, "wfc_wall_height", text="Height")
        row.prop(scene, "wfc_wall_thickness", text="Thick")
        col.prop(scene, "wfc_wall_cap_top", text="Cap Top")
        col.prop(scene, "wfc_wall_grouping", text="Grouping")
        col.separator()
        col.prop(scene, "wfc_wall_corner_rounding", text="Round Corners")
        radius_row = col.row(align=True)
        radius_row.enabled = scene.wfc_wall_corner_rounding
        radius_row.prop(scene, "wfc_wall_corner_radius", text="Radius")
        col.separator()
        col.prop(scene, "wfc_wall_style", text="Wall Style")
        colors_row = col.row(align=True)
        colors_row.enabled = scene.wfc_wall_style == 'MASONRY' or scene.wfc_round_wall_style == 'MASONRY'
        colors_row.prop(scene, "wfc_masonry_room_colors", text="Room Brick Colors")
        wall_ruin_row = col.row(align=True)
        wall_ruin_row.enabled = scene.wfc_wall_style == 'MASONRY'
        wall_ruin_row.prop(scene, "wfc_wall_ruin", text="Wall Ruin")
        col.prop(scene, "wfc_round_wall_style", text="Round Rooms")
        ruin_row = col.row(align=True)
        ruin_row.enabled = scene.wfc_round_wall_style == 'MASONRY'
        ruin_row.prop(scene, "wfc_round_wall_ruin", text="Ruin")
        col.separator()
        col.prop(scene, "wfc_window_chance", text="Window Chance")
        win_col = col.column(align=True)
        win_col.enabled = scene.wfc_window_chance > 0.0
        win_col.prop(scene, "wfc_window_width", text="Window Width")
        win_row = win_col.row(align=True)
        win_row.prop(scene, "wfc_window_sill", text="Sill")
        win_row.prop(scene, "wfc_window_height", text="Height")
        layout.separator()
        _step_button(
            layout, "object.generate_level_walls", "Step 2: Generate Walls",
            'MOD_SOLIDIFY', 'COLLECTION_COLOR_08',
        )

    def _draw_stairs_tab(self, context, layout):
        scene = context.scene
        col = layout.column(align=True)
        col.prop(scene, "wfc_stairs_per_level", text="Stairs / Level")
        col.prop(scene, "wfc_corridor_stairs", text="Corridor Stairs")
        row = col.row(align=True)
        width_col = row.column(align=True)
        width_col.enabled = not scene.wfc_corridor_stairs
        width_col.prop(scene, "wfc_stair_room_width", text="Room W")
        row.prop(scene, "wfc_stair_room_length", text="Room L")
        col.separator()
        col.prop(scene, "wfc_stair_mesh_style", text="Mesh Style")
        steps_col = layout.column(align=True)
        steps_col.enabled = scene.wfc_stair_mesh_style == 'STAIRS'
        steps_col.prop(scene, "wfc_stair_steps", text="Steps per Tile")
        col = layout.column(align=True)
        col.prop(scene, "wfc_stair_grouping", text="Grouping")
        col.separator()
        col.prop(scene, "wfc_stair_bend_chance", text="Bend Chance")
        bend_style_row = col.row(align=True)
        bend_style_row.enabled = scene.wfc_stair_bend_chance > 0.0 and not scene.wfc_corridor_stairs
        bend_style_row.prop(scene, "wfc_stair_bend_style", text="Bend Style")
        if scene.wfc_stair_bend_chance > 0.0 and scene.wfc_corridor_stairs:
            col.label(text="Bending needs a room-based stairwell -- ignored with Corridor Stairs on", icon='INFO')
        layout.separator()
        _step_button(
            layout, "object.generate_level_stairs", "Step 3: Generate Stairs",
            'TRIA_UP', 'COLLECTION_COLOR_02',
        )

    def _draw_doors_tab(self, context, layout):
        scene = context.scene
        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(scene, "wfc_door_height", text="Height")
        row.prop(scene, "wfc_door_frame_thickness", text="Thick")
        col.prop(scene, "wfc_door_merge_distance", text="Merge Distance (tiles)")
        col.prop(scene, "wfc_door_grouping", text="Grouping")
        col.separator()
        col.prop(scene, "wfc_door_style", text="Style")
        arch_row = col.row(align=True)
        arch_row.enabled = scene.wfc_door_style != 'FLAT'
        arch_row.prop(scene, "wfc_door_arch_height", text="Arch Height")
        col.separator()
        col.prop(scene, "wfc_generate_door_panels", text="Generate Door Panels")
        hinge_row = col.row(align=True)
        hinge_row.enabled = scene.wfc_generate_door_panels
        hinge_row.prop(scene, "wfc_upbge_hinge_physics", text="UPBGE Hinge Physics (Experimental)")
        layout.separator()
        _step_button(
            layout, "object.generate_level_doors", "Step 4: Generate Doors",
            'MOD_LATTICE', 'COLLECTION_COLOR_06',
        )

    def _draw_castle_tab(self, context, layout):
        scene = context.scene
        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(scene, "wfc_castle_width", text="Width")
        row.prop(scene, "wfc_castle_depth", text="Depth")
        row = col.row(align=True)
        row.prop(scene, "wfc_castle_wall_height", text="Wall Height")
        row.prop(scene, "wfc_castle_wall_thickness", text="Thick")
        row = col.row(align=True)
        row.prop(scene, "wfc_castle_tower_radius", text="Tower R")
        row.prop(scene, "wfc_castle_tower_height", text="Tower H")
        col.prop(scene, "wfc_tower_detail", text="Brick Detail")
        col.prop(scene, "wfc_castle_brick_color", text="Brick Color")
        col.separator()
        col.prop(scene, "wfc_castle_gate", text="Gate")
        col.prop(scene, "wfc_castle_keep", text="Keep")
        hall_row = col.row(align=True)
        hall_row.enabled = scene.wfc_castle_keep
        hall_row.prop(scene, "wfc_castle_hall_props", text="Hall Furniture")
        col.prop(scene, "wfc_castle_ruin", text="Ruin")
        layout.label(text="Built at the 3D cursor.")
        layout.separator()
        _step_button(layout, "object.generate_level_castle", "Generate Castle", 'HOME', 'COLLECTION_COLOR_05')
        pkg_row = layout.row(align=True)
        pkg_row.operator("object.export_castle_package", text="Export Castle Package (glb + json)", icon='PACKAGE')
        pkg_row.enabled = bpy.data.objects.get(CASTLE_OBJECT_NAME) is not None

    def _draw_tower_tab(self, context, layout):
        scene = context.scene
        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(scene, "wfc_tower_radius", text="Radius")
        row.prop(scene, "wfc_tower_height", text="Height")
        col.prop(scene, "wfc_tower_wall", text="Wall Thickness")
        col.prop(scene, "wfc_tower_detail", text="Brick Detail")
        col.prop(scene, "wfc_tower_brick_color", text="Brick Color")
        col.separator()
        col.prop(scene, "wfc_tower_ruin", text="Ruin")
        battle_row = col.row(align=True)
        battle_row.enabled = scene.wfc_tower_ruin <= 0.0
        battle_row.prop(scene, "wfc_tower_battlements", text="Battlements")
        col.prop(scene, "wfc_tower_door", text="Arched Door")
        door_row = col.row(align=True)
        door_row.enabled = scene.wfc_tower_door
        door_row.prop(scene, "wfc_tower_door_angle", text="Door Angle")
        col.prop(scene, "wfc_tower_windows", text="Windows / Storey")
        col.prop(scene, "wfc_tower_interior", text="Floors + Spiral Stairs")
        stair_row = col.row(align=True)
        stair_row.enabled = scene.wfc_tower_interior
        stair_row.prop(scene, "wfc_tower_stair_width", text="Stair Width")
        rail_row = col.row(align=True)
        rail_row.enabled = scene.wfc_tower_interior
        rail_row.prop(scene, "wfc_tower_stair_rail", text="Stair Railing")
        lamp_row = col.row(align=True)
        lamp_row.enabled = scene.wfc_tower_interior
        lamp_row.prop(scene, "wfc_tower_lights", text="Lanterns")
        furn_row = col.row(align=True)
        furn_row.enabled = scene.wfc_tower_interior
        furn_row.prop(scene, "wfc_tower_props", text="Furniture")
        layout.label(text="Built at the 3D cursor.")
        layout.separator()
        _step_button(
            layout, "object.generate_level_tower", "Generate Round Tower",
            'MESH_CYLINDER', 'COLLECTION_COLOR_04',
        )

    def _draw_props_tab(self, context, layout):
        scene = context.scene
        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(scene, "wfc_torch_chance", text="Torch Chance")
        row.prop(scene, "wfc_torch_height", text="Height")
        row = col.row(align=True)
        row.prop(scene, "wfc_torch_light_chance", text="Light Chance")
        row.prop(scene, "wfc_max_lights", text="Max Lights")
        row = col.row(align=True)
        row.prop(scene, "wfc_torch_light_energy", text="Energy (W)")
        row.prop(scene, "wfc_torch_light_radius", text="Radius")
        col.prop(scene, "wfc_torch_light_color", text="Light Color")
        col.separator()
        col.prop(scene, "wfc_prop_chance", text="Prop Chance")
        col.prop(scene, "wfc_prop_theme", text="Theme")
        layout.separator()
        _step_button(
            layout, "object.generate_level_props", "Step 5: Generate Props",
            'LIGHT', 'COLLECTION_COLOR_03',
        )

    def _draw_export_tab(self, context, layout):
        scene = context.scene
        col = layout.column(align=True)
        col.prop(scene, "wfc_export_binary", text="Binary (.glb)")
        col.prop(scene, "wfc_export_include_lights", text="Include Lights")
        layout.separator()
        export_row = layout.row(align=True)
        export_row.scale_y = 1.4
        _color_swatch(export_row, 'COLLECTION_COLOR_01')
        export_row.operator("object.export_level_gltf", text="Export Level (glTF/GLB)", icon='EXPORT')
        export_row.enabled = bpy.data.objects.get(BLUEPRINT_OBJECT_NAME) is not None

        package_row = layout.row(align=True)
        package_row.scale_y = 1.2
        _color_swatch(package_row, 'COLLECTION_COLOR_05')
        package_row.operator("object.export_game_package", text="Export Game Package (glb + json)", icon='PACKAGE')
        package_row.enabled = bpy.data.objects.get(BLUEPRINT_OBJECT_NAME) is not None or bool(scene.get("gla_package_cache"))
        floors_row = layout.row(align=True)
        floors_op = floors_row.operator("object.export_game_package", text="Export Package per Floor", icon='PACKAGE')
        floors_op.per_floor = True
        floors_row.enabled = package_row.enabled and scene.wfc_wall_grouping == 'PER_FLOOR'

        layout.separator()
        layout.label(text="Collision Mesh -- Floor + Walls + Stairs only")
        collision_row = layout.row(align=True)
        collision_row.scale_y = 1.2
        _color_swatch(collision_row, 'COLLECTION_COLOR_04')
        collision_row.operator(
            "object.export_level_collision_gltf", text="Export Collision Mesh", icon='PHYSICS',
        )
        collision_row.enabled = bpy.data.objects.get(BLUEPRINT_OBJECT_NAME) is not None


# ==============================================================================
# 5. REGISTRATION
# ==============================================================================
classes = (
    OBJECT_OT_ApplyGLAPreset,
    OBJECT_OT_GenerateGameBlueprint,
    OBJECT_OT_SeparateLevelByFloor,
    OBJECT_OT_FreezeForTextureWork,
    OBJECT_OT_GenerateLevelWalls,
    OBJECT_OT_GenerateLevelStairs,
    OBJECT_OT_GenerateLevelDoors,
    OBJECT_OT_GenerateLevelProps,
    OBJECT_OT_GenerateLevelTower,
    OBJECT_OT_GenerateLevelCastle,
    OBJECT_OT_ExportGamePackage,
    OBJECT_OT_ExportCastlePackage,
    OBJECT_OT_ExportLevelGLTF,
    OBJECT_OT_ExportLevelCollisionGLTF,
    OBJECT_OT_CopyLevelArchitectParams,
    WFC_FloorProfile,
    WFC_UL_FloorProfiles,
    OBJECT_OT_FloorProfileAdd,
    OBJECT_OT_FloorProfileRemove,
    VIEW3D_PT_GameLevelArchitect,
)


# Wall Height, Door Height, Level Height, and Sub-Levels per Floor need to
# stay mutually consistent: the real headroom available before something
# pokes into whatever sits directly above (the next sub-level slice, or the
# next floor) is level_height / sub_levels_per_floor, NOT level_height
# alone -- Wall Height and Door Height used to be totally independent
# numbers, so raising Sub-Levels per Floor (which shrinks that headroom) or
# either height (which needs more of it) with no cross-check let walls (and
# door frames -- same bug, same fix, folded in once it came up) visibly
# clip through the floor above. User feedback: "if we change sublevels in
# rooms, heights of walls, vertical distance from floor must be
# connected... walls are generated they [are] visible on upper floor," then
# "there are doors, ok default is 2.2m and if we choose to make floor
# height 1m??" -- same gap, just never asked about walls specifically the
# first time. And specifically asked for properties to adjust each other
# rather than one silently clamping the others down. Whichever property the
# user just changed is treated as their real intent and left alone; Level
# Height is preferred to grow (respecting its own max) before either height
# ever shrinks. A module-level reentrancy guard stops the four update
# callbacks from ping-ponging off each other -- setting one property from
# within another's update callback still fires that property's own
# callback in Blender's RNA system.
_adjusting_level_geometry = False


def _sync_level_geometry(scene, changed):
    global _adjusting_level_geometry
    if _adjusting_level_geometry:
        return
    _adjusting_level_geometry = True
    try:
        sub_levels = max(1, scene.wfc_sub_levels_per_floor)
        if changed == 'level_height':
            # User set Level Height directly -- Wall Height and Door
            # Height are what give way here, since Level Height is the
            # one they just touched.
            max_height = scene.wfc_level_height / sub_levels
            if scene.wfc_wall_height > max_height:
                scene.wfc_wall_height = max_height
            if scene.wfc_door_height > max_height:
                scene.wfc_door_height = max_height
        else:
            # Wall Height, Door Height, or Sub-Levels changed -- grow
            # Level Height to fit both if it still can (respecting its own
            # max=20.0); only if even the max isn't enough does whichever
            # height still doesn't fit also give way, so the invariant
            # holds either way.
            required_level_height = max(scene.wfc_wall_height, scene.wfc_door_height) * sub_levels
            if scene.wfc_level_height < required_level_height:
                scene.wfc_level_height = min(required_level_height, 20.0)
            max_height = scene.wfc_level_height / sub_levels
            if scene.wfc_wall_height > max_height:
                scene.wfc_wall_height = max_height
            if scene.wfc_door_height > max_height:
                scene.wfc_door_height = max_height
    finally:
        _adjusting_level_geometry = False


def _update_wall_height(self, context):
    _sync_level_geometry(self, 'wall_height')


def _update_door_height(self, context):
    _sync_level_geometry(self, 'door_height')


def _update_sub_levels_per_floor(self, context):
    _sync_level_geometry(self, 'sub_levels_per_floor')


def _update_level_height(self, context):
    _sync_level_geometry(self, 'level_height')


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.wfc_width = IntProperty(name="Width", default=10, min=5, max=50)
    bpy.types.Scene.wfc_length = IntProperty(name="Length", default=10, min=5, max=50)
    bpy.types.Scene.wfc_height = IntProperty(name="Height", default=3, min=1, max=10)
    bpy.types.Scene.wfc_seed = IntProperty(
        name="Seed", default=0, min=0, max=999_999,
        description="Random seed for this generation -- with Random Seed off, the same "
                    "seed plus the same settings always reproduces the identical layout"
    )
    bpy.types.Scene.wfc_random_seed = BoolProperty(
        name="Random Seed", default=True,
        description="Pick a fresh random seed every time Generate Blueprint runs. "
                    "Disable to keep reusing the Seed value above"
    )
    bpy.types.Scene.wfc_rooms_min = IntProperty(name="Min Rooms", default=10, min=1, max=200)
    bpy.types.Scene.wfc_rooms_max = IntProperty(name="Max Rooms", default=30, min=1, max=200)
    bpy.types.Scene.wfc_room_size_min = IntProperty(name="Min Room Size", default=2, min=1, max=20)
    bpy.types.Scene.wfc_room_size_max = IntProperty(name="Max Room Size", default=4, min=1, max=20)
    bpy.types.Scene.wfc_room_shape = EnumProperty(
        name="Room Shape",
        items=[
            ('RECT', "Rectangular", "Classic rectangular rooms"),
            ('ROUND', "Round", "Circular/oval rooms -- a real merged n-gon floor disc and a "
                                "matching wall ring hug the actual shape"),
            ('MIXED', "Mixed", "Randomly rectangular or round, chosen per room"),
            ('CAVE', "Cave", "Every floor becomes one organic connected network of winding "
                              "tunnels and round chambers instead of discrete rooms joined by "
                              "straight corridors. Reuses Min/Max Rooms as the chamber count and "
                              "Min/Max Room Size as chamber size. Pairs well with Corridor Stairs"),
        ],
        default='RECT',
    )
    bpy.types.Scene.wfc_room_shape_sides = IntProperty(
        name="Room Shape Sides", default=16, min=3, max=32,
        description="Sides of a Round room's floor disc and wall ring -- 3=triangle, 4=square, "
                    "higher=smoother circle. Only affects rooms resolved to Round (including via "
                    "Mixed and Cave)",
    )
    bpy.types.Scene.wfc_floor_profiles = CollectionProperty(type=WFC_FloorProfile)
    bpy.types.Scene.wfc_floor_profiles_active_index = IntProperty(default=0)
    bpy.types.Scene.wfc_sub_levels_per_floor = IntProperty(
        name="Sub-Levels per Floor", default=1, min=1, max=4,
        description="Subdivide each floor into this many internal height slices so some rooms "
                    "can sit raised or lowered relative to the rest of their floor (split-level), "
                    "still connected by the normal stairwell system. 1 = off, every room on a "
                    "floor sits at the same height. Raising this shrinks the headroom available "
                    "to each slice (Level Height / Sub-Levels) -- Level Height grows to compensate "
                    "automatically so Wall Height and Door Height still fit without clipping into "
                    "the slice above",
        update=_update_sub_levels_per_floor,
    )
    bpy.types.Scene.wfc_split_level_chance = FloatProperty(
        name="Split-Level Chance", default=0.3, min=0.0, max=1.0, subtype='FACTOR',
        description="Only used when Sub-Levels per Floor > 1: chance a given room is placed on "
                    "a raised/lowered slice of its floor instead of the floor's base height"
    )
    bpy.types.Scene.wfc_elevation_chance = FloatProperty(
        name="Elevation Chance", default=0.0, min=0.0, max=1.0, subtype='FACTOR',
        description="Chance a single-doorway room's floor gets a smooth continuous height offset "
                    "instead of sitting flush with its floor -- 0 = off (default, no change from "
                    "before this existed). Only rooms with exactly one doorway and enough corridor "
                    "run leading to it are eligible; others are skipped automatically"
    )
    bpy.types.Scene.wfc_elevation_range = FloatProperty(
        name="Elevation Range (m)", default=0.0, min=0.0, max=3.0, unit='LENGTH',
        description="Maximum world-space height an eligible room's floor can be raised or lowered "
                    "by. The actual offset is clamped further by Max Ramp Angle and however much "
                    "corridor run is actually available to slope down over"
    )
    bpy.types.Scene.wfc_max_ramp_slope = FloatProperty(
        name="Max Ramp Angle (deg)", default=30.0, min=5.0, max=60.0,
        description="Steepest slope a continuous-elevation connector is allowed to use -- an "
                    "eligible room's offset is clamped down to whatever fits this angle over its "
                    "available corridor run, so a short run always yields a gentler rise, never a "
                    "cliff"
    )
    bpy.types.Scene.wfc_stairs_per_level = IntProperty(
        name="Stairs per Level Transition", default=3, min=1, max=50,
        description="How many stairs connect each pair of adjacent Z-slices -- including "
                    "split-level transitions within the same floor, not just between floors. "
                    "Raise this for bigger maps"
    )
    bpy.types.Scene.wfc_stair_room_width = IntProperty(
        name="Stair Room Width", default=3, min=MIN_STAIR_ROOM_WIDTH, max=8,
        description="Tiles across each stairwell room, perpendicular to the climb -- "
                    "3 is the minimum that still leaves a walkway on both sides of the stair"
    )
    bpy.types.Scene.wfc_stair_room_length = IntProperty(
        name="Stair Room Length", default=4, min=MIN_STAIR_ROOM_LENGTH, max=12,
        description="Tiles along each stairwell room, in the direction of the climb -- longer is a gentler "
                    "slope; 4 is the minimum that still leaves a landing before and after the steps. Also "
                    "used as the climb length for Corridor Stairs"
    )
    bpy.types.Scene.wfc_corridor_stairs = BoolProperty(
        name="Corridor Stairs", default=False,
        description="Place stairs as a flush 1-tile-wide strip directly in the corridor network "
                    "instead of a whole buffered stairwell room -- no separate walkway beside the "
                    "climb, but far cheaper on space, so dense layouts should hit the emergency "
                    "bufferless fallback much less often. Stair Room Width is ignored in this mode"
    )
    bpy.types.Scene.wfc_tile_size = FloatProperty(
        name="Tile Size", default=4.0, min=0.5, max=20.0, unit='LENGTH',
        description="Physical size (in meters) of one grid cell / primitive, in X/Y"
    )
    bpy.types.Scene.wfc_level_height = FloatProperty(
        name="Level Height", default=4.0, min=1.0, max=20.0, unit='LENGTH',
        description="Vertical distance (in meters) between floor levels/stories. Shrinking this "
                    "below what Wall Height or Door Height needs (that height x Sub-Levels per "
                    "Floor) reduces them automatically so walls/doors don't clip into the slice "
                    "above",
        update=_update_level_height,
    )
    bpy.types.Scene.wfc_floor_thickness = FloatProperty(
        name="Floor Thickness", default=0.0, min=0.0, max=0.5, unit='LENGTH',
        description="0 = flat plane (merged by distance), otherwise a solid slab"
    )
    bpy.types.Scene.wfc_add_ceiling = BoolProperty(
        name="Add Ceiling", default=False,
        description="Add a ceiling slab above every walkable tile, so no room ever opens onto "
                    "empty space/world background overhead -- needed for a proper FPS view. Live "
                    "GN toggle (no regeneration needed), and automatically hidden by Isometric "
                    "Mode's existing top-down culling, so dollhouse-style editing still works "
                    "with it left on"
    )
    bpy.types.Scene.wfc_ceiling_thickness = FloatProperty(
        name="Ceiling Thickness", default=0.1, min=0.0, max=0.5, unit='LENGTH',
        description="Only visible when Add Ceiling is on -- 0 = flat plane (merged by distance), "
                    "otherwise a solid slab"
    )
    bpy.types.Scene.wfc_style = EnumProperty(
        name="Style",
        items=[
            ('0', "Dungeon", "Strict modular grids"),
            ('1', "Cave", "Organic rock layouts"),
            ('2', "Open Area", "Flat layout with barriers"),
        ],
        default='0',
    )
    bpy.types.Scene.wfc_iso_mode = BoolProperty(name="Isometric Mode", default=False)
    bpy.types.Scene.wfc_color_rooms = BoolProperty(
        name="Color Rooms/Corridors", default=True,
        description="Tint room floors differently from corridor floors"
    )
    bpy.types.Scene.wfc_simple_materials = BoolProperty(
        name="Simple Viewport Colors", default=True,
        description=(
            "Skip the procedural style shaders and use flat Viewport Display "
            "colors instead -- light grey for corridors/structure, a random "
            "color per room. Fast and clear for modeling/layout work"
        )
    )
    bpy.types.Scene.wfc_wall_height = FloatProperty(
        name="Wall Height", default=4.0, min=0.0, max=40.0, unit='LENGTH',
        description="How tall the generated walls stand above each level's floor -- capped to "
                    "Level Height / Sub-Levels per Floor, since anything taller would clip into "
                    "the slice above; Level Height grows automatically to fit instead, up to its "
                    "own max",
        update=_update_wall_height,
    )
    bpy.types.Scene.wfc_wall_thickness = FloatProperty(
        name="Wall Thickness", default=0.3, min=0.0, max=2.0, unit='LENGTH',
        description="How thick the generated walls are"
    )
    bpy.types.Scene.wfc_wall_cap_top = BoolProperty(
        name="Cap Top", default=False,
        description="Keep a ceiling cap at the top of each wall run instead of leaving it open"
    )
    bpy.types.Scene.wfc_wall_grouping = EnumProperty(
        name="Wall Grouping",
        items=[
            ('SINGLE', "Single Object", "One combined walls object for the whole building"),
            ('PER_FLOOR', "Per Floor", "One walls object per logical floor -- easier to isolate or hide a floor"),
        ],
        default='SINGLE',
    )
    bpy.types.Scene.wfc_wall_corner_rounding = BoolProperty(
        name="Round Corners", default=False,
        description="Add a live Bevel modifier to the wall object(s) that rounds every sharp "
                    "vertical edge -- genuine building corners, and wall runs ending at a "
                    "doorway/opening jamb alike (edge angle alone can't tell those apart). Also "
                    "rounds the top rim if Cap Top is on. Live/adjustable -- no regeneration "
                    "needed to change the radius"
    )
    bpy.types.Scene.wfc_wall_corner_radius = FloatProperty(
        name="Corner Radius", default=0.1, min=0.01, max=1.0, unit='LENGTH',
        description="Bevel width for Round Corners -- Blender's own Clamp Overlap keeps an "
                    "oversized radius from self-intersecting on a thin wall"
    )
    bpy.types.Scene.wfc_wall_style = EnumProperty(
        name="Wall Style",
        items=[
            ('BOXES', "Boxes", "Plain merged boxes along every exposed edge (default, unchanged)"),
            ('MASONRY', "Masonry", "Brick-textured walls: one smooth textured wall per straight run, dressed-stone "
                                   "caps and window frames, scattered proud stones, optional ruin. Corners overlap "
                                   "and close; doorway jambs get end caps. Ignores Organic Irregularity"),
        ],
        default='BOXES',
        description="How ordinary room/corridor walls are built"
    )
    bpy.types.Scene.wfc_masonry_room_colors = BoolProperty(
        name="Room Brick Colors", default=True,
        description="Masonry walls (ordinary and Round rooms): every room gets its own brick tint (warm ochre, "
                    "slate, moss, rose, umber, sand) so rooms read apart; corridors keep the plain brick. A wall "
                    "run belongs to the room on its inner side. Off = one brick colour everywhere"
    )
    bpy.types.Scene.wfc_wall_ruin = FloatProperty(
        name="Wall Ruin", default=0.0, min=0.0, max=1.0, subtype='FACTOR',
        description="Masonry walls only: how ruined the walls are (jagged stepped tops, breaches). Doorways stay "
                    "passable. 0 = intact"
    )
    bpy.types.Scene.wfc_window_chance = FloatProperty(
        name="Window Chance", default=0.0, min=0.0, max=1.0, subtype='FACTOR',
        description="Chance that each exposed room-wall edge gets a real window opening (cut "
                    "through the wall, with a frame, mullions and a glass pane). Corridors, Round "
                    "rooms and Corridor-Stairs sides are never windowed; windows on one wall are "
                    "kept at least 2 tiles apart. 0 = no windows (default)"
    )
    bpy.types.Scene.wfc_window_width = FloatProperty(
        name="Window Width", default=1.0, min=0.3, max=4.0, unit='LENGTH',
        description="Opening width in meters (clamped to leave 0.1 m of wall each side of a tile)"
    )
    bpy.types.Scene.wfc_window_sill = FloatProperty(
        name="Window Sill", default=1.0, min=0.0, max=5.0, unit='LENGTH',
        description="Height of the window's bottom edge above the floor"
    )
    bpy.types.Scene.wfc_window_height = FloatProperty(
        name="Window Height", default=1.0, min=0.3, max=5.0, unit='LENGTH',
        description="Height of the opening (clamped so a lintel always remains under the wall top)"
    )
    bpy.types.Scene.wfc_round_wall_style = EnumProperty(
        name="Round Room Walls",
        items=[
            ('MASONRY', "Masonry", "Brick-textured smooth ring on the room's rim with real arched/"
                                   "pointed/flat openings exactly where corridors meet it, stone frames "
                                   "and scattered stones (the Round Tower method). Uses Door Style and "
                                   "Door Height; Round rooms then get no separate RoundDoors object"),
            ('CLASSIC', "Classic", "Plain-box n-gon ring (Room Shape Sides) with whole polygon "
                                   "edges left open, plus separate oriented door frames"),
        ],
        default='MASONRY',
        description="How the walls of Round rooms are built"
    )
    bpy.types.Scene.wfc_round_wall_ruin = FloatProperty(
        name="Ruin", default=0.0, min=0.0, max=1.0, subtype='FACTOR',
        description="Masonry Round-room walls only: how ruined they are. Wall tops break down to a "
                    "jagged edge that steps along whole brick courses, deep breaches open up (an arch "
                    "or window whose top fell away becomes a plain gap), and fallen blocks lie against "
                    "the inside of the wall. Doorways stay passable. 0 = intact (default)"
    )
    bpy.types.Scene.wfc_organic_amount = FloatProperty(
        name="Organic Irregularity", default=0.0, min=0.0, max=0.3, unit='LENGTH',
        description="Jitters wall height/thickness, stair tread width, and ramp edges for a "
                    "hand-carved look -- purely cosmetic, never affects which cells are walkable "
                    "or connectivity. 0 = perfectly regular (default)"
    )
    bpy.types.Scene.wfc_uv_tile_size = FloatProperty(
        name="UV Tile Size", default=1.0, min=0.05, max=20.0, unit='LENGTH',
        description="Meters-per-UV-tile used to box-map every baked mesh (walls/doors/stairs/"
                    "ramps/torches/decoration) -- set this to match a tiling texture or trim "
                    "sheet's real-world size so it repeats correctly instead of stretching across "
                    "a whole wall run. Doesn't affect Simple Viewport Colors (flat swatches read "
                    "the same regardless of UV), only materials that actually sample varying "
                    "texture detail across a face"
    )
    bpy.types.Scene.wfc_stair_mesh_style = EnumProperty(
        name="Mesh Style",
        items=[
            ('STAIRS', "Stairs", "Discrete ascending steps"),
            ('RAMP', "Ramp", "One continuous sloped wedge per run, flush with the floor at both "
                              "ends -- suits caves and open terrain better than boxy steps"),
        ],
        default='STAIRS',
    )
    bpy.types.Scene.wfc_stair_steps = IntProperty(
        name="Steps per Tile", default=4, min=2, max=12,
        description="How many ascending step boxes make up each tile of a stair run's length "
                    "(Stairs mesh style only)"
    )
    bpy.types.Scene.wfc_stair_grouping = EnumProperty(
        name="Stair Grouping",
        items=[
            ('PER_FLOOR', "Per Floor", "One stairs object per floor, combining every stair that starts there"),
            ('PER_STAIR', "Per Stair", "One stairs object per individual stairwell -- move/hide/regenerate any one independently"),
        ],
        default='PER_FLOOR',
    )
    bpy.types.Scene.wfc_stair_bend_chance = FloatProperty(
        name="Bend Chance", default=0.0, min=0.0, max=1.0, subtype='FACTOR',
        description="Chance a given stairwell bends through one landing into two straight "
                    "segments instead of climbing in one straight run. 0 = off (default, no "
                    "change from every stairwell before this existed). Only offered for "
                    "room-based stairwells, never Corridor Stairs (no room for a landing) or "
                    "the emergency connectivity-repair fallback"
    )
    bpy.types.Scene.wfc_stair_bend_style = EnumProperty(
        name="Bend Style",
        items=[
            ('RANDOM', "Random", "Each bent stairwell independently rolls L or U"),
            ('L', "L (90°)", "The second segment turns 90 degrees, left or right at random"),
            ('U', "U (180°)", "The second segment reverses into a second parallel lane -- a \"dog-leg\""),
        ],
        default='RANDOM',
    )
    bpy.types.Scene.wfc_door_height = FloatProperty(
        name="Door Height", default=2.2, min=0.5, max=10.0, unit='LENGTH',
        description="Height of each door frame's opening, from floor to the underside of the "
                    "lintel -- capped to Level Height / Sub-Levels per Floor, since anything "
                    "taller would clip into the slice above; Level Height grows automatically to "
                    "fit instead, up to its own max",
        update=_update_door_height,
    )
    bpy.types.Scene.wfc_door_frame_thickness = FloatProperty(
        name="Door Frame Thickness", default=0.15, min=0.02, max=1.0, unit='LENGTH',
        description="How thick the frame's posts and lintel are"
    )
    bpy.types.Scene.wfc_door_grouping = EnumProperty(
        name="Door Grouping",
        items=[
            ('SINGLE', "Single Object", "One combined doors object for the whole building"),
            ('PER_FLOOR', "Per Floor", "One doors object per logical floor"),
        ],
        default='SINGLE',
    )
    bpy.types.Scene.wfc_door_merge_distance = IntProperty(
        name="Merge Distance", default=2, min=0, max=5,
        description="Two doorways facing each other across a corridor this many tiles long or "
                    "shorter collapse into a single door instead of one at each end. 0 = never merge"
    )
    bpy.types.Scene.wfc_door_style = EnumProperty(
        name="Door Style",
        items=[
            ('FLAT', "Flat", "A flat lintel across the top of the frame (default, unchanged)"),
            ('ROUND', "Round", "A rounded (segmental/elliptical) arch replaces the flat lintel"),
            ('POINTED', "Pointed", "A two-centered pointed (Gothic/lancet) arch replaces the flat lintel"),
        ],
        default='FLAT',
        description="Shape of every ORDINARY doorway's top. Entrance and Exit always get their "
                    "own larger, always-arched Gate regardless of this setting, so they stay "
                    "visually distinct from ordinary doors either way"
    )
    bpy.types.Scene.wfc_door_arch_height = FloatProperty(
        name="Arch Height", default=0.6, min=0.1, max=3.0, unit='LENGTH',
        description="How far a Round/Pointed arch rises above the springline (ignored for Flat). "
                    "Also scales the Entrance/Exit Gate's own (larger) arch"
    )
    bpy.types.Scene.wfc_generate_door_panels = BoolProperty(
        name="Generate Door Panels", default=True,
        description="Also build one real swinging panel object per ordinary doorway (never for "
                    "Entrance/Exit gates), hinged on its span_min side -- see _build_door_panels"
    )
    bpy.types.Scene.wfc_upbge_hinge_physics = BoolProperty(
        name="UPBGE Hinge Physics (Experimental)", default=False,
        description="EXPERIMENTAL, off by default: on UPBGE only (silent no-op on stock Blender), "
                    "best-effort adds a RIGID_BODY + HINGE constraint to each door panel so it can "
                    "swing during play. Confirmed working correctly on UPBGE 0.53-alpha, but on "
                    "UPBGE 0.50 the constraint-setup step was unreliable enough to crash Blender "
                    "under repeated regeneration -- see _try_setup_hinge_physics. Whether UPBGE's "
                    "live game runtime actually simulates the constraint in real time, even when "
                    "setup succeeds, was also not verified -- confirm by pressing Start Game and "
                    "pushing a door before relying on this for anything"
    )
    bpy.types.Scene.wfc_torch_chance = FloatProperty(
        name="Torch Chance", default=0.15, min=0.0, max=1.0, subtype='FACTOR',
        description="Chance any given wall-adjacent tile gets a torch, independent of the "
                    "guarantee that every room with a wall gets at least one regardless"
    )
    bpy.types.Scene.wfc_torch_height = FloatProperty(
        name="Torch Height", default=1.6, min=0.2, max=4.0, unit='LENGTH',
        description="Height above the floor a torch's flame sits at"
    )
    bpy.types.Scene.wfc_torch_light_energy = FloatProperty(
        name="Torch Light Energy", default=60.0, min=1.0, max=1000.0,
        description="Power (Watts) of each torch's Point light"
    )
    bpy.types.Scene.wfc_torch_light_color = FloatVectorProperty(
        name="Torch Light Color", subtype='COLOR', size=3, default=(1.0, 0.55, 0.2), min=0.0, max=1.0,
        description="Color of every torch's Point light"
    )
    bpy.types.Scene.wfc_torch_light_radius = FloatProperty(
        name="Torch Light Radius", default=0.25, min=0.01, max=2.0, unit='LENGTH',
        description="Shadow soft size of each torch's Point light -- larger softens shadows"
    )
    bpy.types.Scene.wfc_torch_light_chance = FloatProperty(
        name="Torch Light Chance", default=0.4, min=0.0, max=1.0, subtype='FACTOR',
        description="Chance any given torch also gets a real Point light, independent of Torch "
                    "Chance (which only controls the mesh). Real-time lights are the expensive "
                    "part in a game engine, not the placeholder mesh -- lower this to keep torches "
                    "visually dense while cutting the actual light count. Every room with a torch "
                    "still gets at least one lit torch regardless of this roll"
    )
    bpy.types.Scene.wfc_max_lights = IntProperty(
        name="Max Lights", default=150, min=1, max=2000,
        description="Hard cap on total torch lights generated -- trims the optional ones "
                    "(from Torch Light Chance) first if there are too many; the one guaranteed "
                    "light per room is never trimmed, so an aggressively low cap on a big map "
                    "can still exceed it slightly rather than leave a room dark"
    )
    bpy.types.Scene.wfc_prop_chance = FloatProperty(
        name="Prop Chance", default=0.1, min=0.0, max=1.0, subtype='FACTOR',
        description="Chance any given non-doorway floor tile in a room gets a crate/barrel/cone "
                    "decoration prop"
    )
    bpy.types.Scene.wfc_prop_theme = EnumProperty(
        name="Prop Theme",
        items=[
            ('GENERIC', "Generic", "Crates, barrels and cones (original look)"),
            ('MIXED', "Mixed Rooms", "Each room randomly gets one of the themes below"),
            ('CRYPT', "Crypt", "Coffins, tombs, columns, candle stands"),
            ('LIBRARY', "Library", "Bookshelves along walls, tables, chairs, chests"),
            ('HALL', "Hall", "Tables, chairs, barrels, chests"),
            ('BEDROOM', "Bedroom", "Beds, chests, chairs, bookshelves"),
            ('STORAGE', "Storage", "Crates, barrels, chests"),
        ],
        default='GENERIC',
        description="What kind of furniture decoration props are. Themed props are stacked "
                    "primitives (tables, chairs, bookshelves, coffins, beds...) placed against "
                    "walls or rotated to quarter turns; all in the one decoration mesh"
    )
    bpy.types.Scene.wfc_tower_radius = FloatProperty(
        name="Tower Radius", default=3.0, min=1.5, max=15.0, unit='LENGTH',
        description="Outer radius of the tower"
    )
    bpy.types.Scene.wfc_tower_height = FloatProperty(
        name="Tower Height", default=9.0, min=3.0, max=40.0, unit='LENGTH',
        description="Total height including battlements"
    )
    bpy.types.Scene.wfc_tower_wall = FloatProperty(
        name="Tower Wall Thickness", default=0.55, min=0.2, max=2.0, unit='LENGTH',
        description="Wall thickness; must stay at least 0.3 m under the radius"
    )
    bpy.types.Scene.wfc_tower_detail = EnumProperty(
        name="Brick Detail",
        items=[
            ('LOW', "Low", "Textured shell + openings + plinth/cornice/battlements only. Fewest vertices"),
            ('MEDIUM', "Medium", "Adds dressed-stone door/window frames and scattered proud stones"),
            ('HIGH', "High", "Medium plus many more proud stones for a rougher, more irregular surface"),
        ],
        default='MEDIUM',
        description="How much real geometry is added on top of the brick-textured shell"
    )
    bpy.types.Scene.wfc_tower_battlements = BoolProperty(
        name="Battlements", default=True, description="Crenellated top (merlons with gaps)"
    )
    bpy.types.Scene.wfc_tower_door = BoolProperty(
        name="Arched Door", default=True, description="Round-headed door at ground level"
    )
    bpy.types.Scene.wfc_tower_door_angle = FloatProperty(
        name="Door Angle", default=270.0, min=0.0, max=360.0,
        description="Compass angle of the door around the tower (270 = facing -Y)"
    )
    bpy.types.Scene.wfc_tower_windows = IntProperty(
        name="Windows per Storey", default=2, min=0, max=8,
        description="Slit windows around each 3 m storey (staggered per storey)"
    )
    bpy.types.Scene.wfc_castle_width = FloatProperty(
        name="Castle Width", default=26.0, min=12.0, max=120.0, unit='LENGTH',
        description="East-west distance between the corner tower centres"
    )
    bpy.types.Scene.wfc_castle_depth = FloatProperty(
        name="Castle Depth", default=20.0, min=12.0, max=120.0, unit='LENGTH',
        description="North-south distance between the corner tower centres (the gate is on the south side)"
    )
    bpy.types.Scene.wfc_castle_wall_height = FloatProperty(
        name="Castle Wall Height", default=7.0, min=3.0, max=25.0, unit='LENGTH',
        description="Curtain wall height including battlements"
    )
    bpy.types.Scene.wfc_castle_wall_thickness = FloatProperty(
        name="Castle Wall Thickness", default=1.5, min=0.8, max=2.5, unit='LENGTH',
        description="Curtain wall thickness: the outer 0.5 m is the parapet, the rest is the walkway"
    )
    bpy.types.Scene.wfc_castle_tower_radius = FloatProperty(
        name="Castle Tower Radius", default=3.2, min=2.0, max=8.0, unit='LENGTH',
        description="Outer radius of the four corner towers"
    )
    bpy.types.Scene.wfc_castle_tower_height = FloatProperty(
        name="Castle Tower Height", default=12.0, min=5.0, max=40.0, unit='LENGTH',
        description="Corner tower height (kept at least 3 m above the curtain walls)"
    )
    bpy.types.Scene.wfc_castle_gate = BoolProperty(
        name="Gate", default=True, description="A large arched gate in the middle of the south wall"
    )
    bpy.types.Scene.wfc_castle_keep = BoolProperty(
        name="Keep", default=True, description="A square keep in the courtyard with a door facing the gate"
    )
    bpy.types.Scene.wfc_castle_hall_props = BoolProperty(
        name="Hall Furniture", default=True,
        description="Furnish the keep's hall: a long table with chairs, bookshelves, chests, a bed and candle stands"
    )
    bpy.types.Scene.wfc_castle_ruin = FloatProperty(
        name="Ruin", default=0.0, min=0.0, max=1.0, subtype='FACTOR',
        description="How ruined every part of the castle is (towers, walls, keep). 0 = intact"
    )
    bpy.types.Scene.wfc_tower_brick_color = EnumProperty(
        name="Brick Color", items=BRICK_COLOR_ITEMS, default='PLAIN',
        description="Tint of the tower's bricks (the same tints as Room Brick Colors); Plain = the original brick"
    )
    bpy.types.Scene.wfc_castle_brick_color = EnumProperty(
        name="Brick Color", items=BRICK_COLOR_ITEMS + [('MIXED', "Mixed", "Walls, keep and each tower get their own tint")],
        default='PLAIN',
        description="Tint of the castle's bricks: one tint for everything, or Mixed (walls ochre, keep umber, towers slate/moss/rose/sand)"
    )
    bpy.types.Scene.wfc_tower_ruin = FloatProperty(
        name="Ruin", default=0.0, min=0.0, max=1.0, subtype='FACTOR',
        description="How ruined the tower is: the top breaks down to a jagged edge that steps along "
                    "brick courses, breaches open, an arch or window whose top fell away becomes a "
                    "gap, rubble lies around the base, and floors above the lowest broken wall top "
                    "are gone. Battlements disappear. 0 = intact"
    )
    bpy.types.Scene.wfc_tower_interior = BoolProperty(
        name="Floors + Spiral Stairs", default=True,
        description="Floor slabs every >= 3 m (the top one is the roof platform behind the "
                    "battlements) joined by one full turn of stone spiral stairs per storey, hugging "
                    "the inner wall. Skipped automatically when the inner radius is under 1.6 m"
    )
    bpy.types.Scene.wfc_tower_props = BoolProperty(
        name="Furniture", default=True,
        description="A few pieces of furniture (chests, barrels, crates, a table, a chair, candle stands) on every "
                    "floor of the tower's interior, inside the disc the stair lane leaves free. Needs Floors + "
                    "Spiral Stairs"
    )
    bpy.types.Scene.wfc_tower_lights = BoolProperty(
        name="Lanterns", default=True,
        description="A hanging lantern and a real Point light under every floor of the tower's interior (needs "
                    "Floors + Spiral Stairs). Light strength/colour follow the Props tab's torch settings"
    )
    bpy.types.Scene.wfc_tower_stair_rail = BoolProperty(
        name="Stair Railing", default=True,
        description="A low stone balustrade along the open inner edge of the spiral stairs and round the "
                    "stairwell opening of every floor"
    )
    bpy.types.Scene.wfc_tower_stair_width = FloatProperty(
        name="Stair Width", default=1.0, min=0.7, max=2.0, unit='LENGTH',
        description="Radial width of the spiral stair lane along the inner wall"
    )
    bpy.types.Scene.wfc_debug_params = StringProperty(
        name="Debug Params", default="",
        description="Internal: snapshot of every wfc_* setting as of the most recent Step "
                    "operator run, for the Debug panel's Copy Parameters button. Not meant to be "
                    "edited directly"
    )
    bpy.types.Scene.wfc_export_binary = BoolProperty(
        name="Binary (.glb)", default=True,
        description="On: one self-contained .glb file with textures embedded. Off: a .gltf text "
                    "file plus a separate .bin and a textures folder -- easier to inspect/version, "
                    "but multiple files to keep together"
    )
    bpy.types.Scene.wfc_export_include_lights = BoolProperty(
        name="Include Lights", default=True,
        description="Export the real Point lights placed by Step 5 (Torch Light Chance) as glTF "
                    "punctual lights. Turn off to export geometry only and light the level by "
                    "hand in-engine instead"
    )
    bpy.types.Scene.wfc_active_tab = EnumProperty(
        name="Active Tab",
        items=[
            ('SETUP', "Setup", "Map, seed, rooms, scale, and style settings, plus Step 1: "
                                "Generate Blueprint", 'MESH_CUBE', 0),
            ('WALLS', "Walls", "Wall settings, plus Step 2: Generate Walls", 'MOD_BUILD', 1),
            ('STAIRS', "Stairs", "Stair settings, plus Step 3: Generate Stairs", 'MOD_BEVEL', 2),
            ('DOORS', "Doors", "Door settings, plus Step 4: Generate Doors", 'MESH_PLANE', 3),
            ('PROPS', "Props", "Torch and decoration settings, plus Step 5: Generate Props",
                      'LIGHT', 4),
            ('EXPORT', "Export", "One-click glTF/GLB export", 'EXPORT', 5),
            ('TOWER', "Tower", "Round tower: brick-textured shell, arched door, slit windows, "
                               "battlements", 'MESH_CYLINDER', 6),
            ('CASTLE', "Castle", "Walled castle: corner towers, curtain walls, gate, keep, ruins",
                                 'HOME', 7),
        ],
        default='SETUP',
        description="Which step's settings the panel below shows",
    )


def unregister():
    del bpy.types.Scene.wfc_width
    del bpy.types.Scene.wfc_length
    del bpy.types.Scene.wfc_height
    del bpy.types.Scene.wfc_seed
    del bpy.types.Scene.wfc_random_seed
    del bpy.types.Scene.wfc_rooms_min
    del bpy.types.Scene.wfc_rooms_max
    del bpy.types.Scene.wfc_room_size_min
    del bpy.types.Scene.wfc_room_size_max
    del bpy.types.Scene.wfc_room_shape
    del bpy.types.Scene.wfc_room_shape_sides
    del bpy.types.Scene.wfc_floor_profiles
    del bpy.types.Scene.wfc_floor_profiles_active_index
    del bpy.types.Scene.wfc_sub_levels_per_floor
    del bpy.types.Scene.wfc_split_level_chance
    del bpy.types.Scene.wfc_elevation_chance
    del bpy.types.Scene.wfc_elevation_range
    del bpy.types.Scene.wfc_max_ramp_slope
    del bpy.types.Scene.wfc_stairs_per_level
    del bpy.types.Scene.wfc_stair_room_width
    del bpy.types.Scene.wfc_stair_room_length
    del bpy.types.Scene.wfc_corridor_stairs
    del bpy.types.Scene.wfc_tile_size
    del bpy.types.Scene.wfc_level_height
    del bpy.types.Scene.wfc_floor_thickness
    del bpy.types.Scene.wfc_add_ceiling
    del bpy.types.Scene.wfc_ceiling_thickness
    del bpy.types.Scene.wfc_style
    del bpy.types.Scene.wfc_iso_mode
    del bpy.types.Scene.wfc_color_rooms
    del bpy.types.Scene.wfc_simple_materials
    del bpy.types.Scene.wfc_wall_height
    del bpy.types.Scene.wfc_wall_thickness
    del bpy.types.Scene.wfc_wall_cap_top
    del bpy.types.Scene.wfc_wall_grouping
    del bpy.types.Scene.wfc_wall_corner_rounding
    del bpy.types.Scene.wfc_wall_corner_radius
    del bpy.types.Scene.wfc_wall_style
    del bpy.types.Scene.wfc_masonry_room_colors
    del bpy.types.Scene.wfc_wall_ruin
    del bpy.types.Scene.wfc_window_chance
    del bpy.types.Scene.wfc_window_width
    del bpy.types.Scene.wfc_window_sill
    del bpy.types.Scene.wfc_window_height
    del bpy.types.Scene.wfc_round_wall_style
    del bpy.types.Scene.wfc_round_wall_ruin
    del bpy.types.Scene.wfc_organic_amount
    del bpy.types.Scene.wfc_uv_tile_size
    del bpy.types.Scene.wfc_stair_mesh_style
    del bpy.types.Scene.wfc_stair_steps
    del bpy.types.Scene.wfc_stair_grouping
    del bpy.types.Scene.wfc_stair_bend_chance
    del bpy.types.Scene.wfc_stair_bend_style
    del bpy.types.Scene.wfc_door_height
    del bpy.types.Scene.wfc_door_frame_thickness
    del bpy.types.Scene.wfc_door_grouping
    del bpy.types.Scene.wfc_door_merge_distance
    del bpy.types.Scene.wfc_door_style
    del bpy.types.Scene.wfc_door_arch_height
    del bpy.types.Scene.wfc_generate_door_panels
    del bpy.types.Scene.wfc_upbge_hinge_physics
    del bpy.types.Scene.wfc_torch_chance
    del bpy.types.Scene.wfc_torch_height
    del bpy.types.Scene.wfc_torch_light_energy
    del bpy.types.Scene.wfc_torch_light_color
    del bpy.types.Scene.wfc_torch_light_radius
    del bpy.types.Scene.wfc_torch_light_chance
    del bpy.types.Scene.wfc_max_lights
    del bpy.types.Scene.wfc_prop_chance
    del bpy.types.Scene.wfc_prop_theme
    del bpy.types.Scene.wfc_tower_radius
    del bpy.types.Scene.wfc_tower_height
    del bpy.types.Scene.wfc_tower_wall
    del bpy.types.Scene.wfc_tower_detail
    del bpy.types.Scene.wfc_tower_battlements
    del bpy.types.Scene.wfc_tower_door
    del bpy.types.Scene.wfc_tower_door_angle
    del bpy.types.Scene.wfc_tower_windows
    del bpy.types.Scene.wfc_castle_width
    del bpy.types.Scene.wfc_castle_depth
    del bpy.types.Scene.wfc_castle_wall_height
    del bpy.types.Scene.wfc_castle_wall_thickness
    del bpy.types.Scene.wfc_castle_tower_radius
    del bpy.types.Scene.wfc_castle_tower_height
    del bpy.types.Scene.wfc_castle_gate
    del bpy.types.Scene.wfc_castle_keep
    del bpy.types.Scene.wfc_castle_hall_props
    del bpy.types.Scene.wfc_castle_ruin
    del bpy.types.Scene.wfc_tower_brick_color
    del bpy.types.Scene.wfc_castle_brick_color
    del bpy.types.Scene.wfc_tower_ruin
    del bpy.types.Scene.wfc_tower_interior
    del bpy.types.Scene.wfc_tower_props
    del bpy.types.Scene.wfc_tower_lights
    del bpy.types.Scene.wfc_tower_stair_rail
    del bpy.types.Scene.wfc_tower_stair_width
    del bpy.types.Scene.wfc_debug_params
    del bpy.types.Scene.wfc_export_binary
    del bpy.types.Scene.wfc_export_include_lights
    del bpy.types.Scene.wfc_active_tab

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
