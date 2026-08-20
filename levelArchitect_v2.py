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

import math
import os
import random
from collections import deque

import bpy
from bpy.props import (
    BoolProperty, CollectionProperty, EnumProperty, FloatProperty, FloatVectorProperty,
    IntProperty, StringProperty,
)

bl_info = {
    "name": "Game Level Architect",
    "author": "Ivica Sršan",
    "version": (0, 18, 0),
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
WALLS_OBJECT_NAME = "Procedural_Level_Walls"
STAIRS_OBJECT_NAME = "Procedural_Level_Stairs"
DOORS_OBJECT_NAME = "Procedural_Level_Doors"
PROPS_TORCH_OBJECT_NAME = "Procedural_Level_Torches"
PROPS_DECORATION_OBJECT_NAME = "Procedural_Level_Decoration"
PROPS_LIGHT_NAME_PREFIX = "Procedural_Level_Light"
PROPS_COLLECTION_NAME = "Procedural Level Props"
PROPS_TORCH_COLLECTION_NAME = "Procedural Level Props - Torches"
PROPS_LIGHT_COLLECTION_NAME = "Procedural Level Props - Lights"
PROPS_DECORATION_COLLECTION_NAME = "Procedural Level Props - Decoration"
BLUEPRINT_SPLIT_COLLECTION_NAME = "Procedural Level Blueprint (Split)"

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
        floor_profiles=None,
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

        # Continuous room elevation (see DEVELOPMENT.md "Middle-ground
        # sketch"): purely a rendering-layer feature on top of the
        # unchanged discrete grid -- elevation_chance/elevation_range
        # default to 0, which is byte-identical to no elevation at all.
        # See _apply_continuous_elevation for the actual logic.
        self.elevation_chance = max(0.0, min(1.0, elevation_chance))
        self.elevation_range = max(0.0, elevation_range)
        self.max_ramp_slope_deg = max(1.0, min(89.0, max_ramp_slope_deg))
        self.tile_size = tile_size

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
        # (x, y, z) cells that are a stairwell's ceiling opening -- the floor
        # renderer skips these so climbing a stair doesn't dead-end into a
        # solid slab.
        self.floor_openings = set()
        self.rooms = []  # each: {'x','y','z','w','l','cx','cy'}
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
        bounds."""
        for xi in range(x - margin, x + rw + margin):
            for yi in range(y - margin, y + rl + margin):
                if not self.in_bounds(xi, yi, z):
                    return False
                if self.grid[xi][yi][z] != TILE_AIR:
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
        else:
            cells = [(xi, yi) for xi in range(x, x + rw) for yi in range(y, y + rl)]

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

    def _carve_stair_room(self, x, y, fw, fl, rotation, z):
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

    def _stair_footprint_chain(self, z, center_x, center_y):
        """Tries progressively smaller/more permissive stairwell footprints
        around (center_x, center_y) on level z, room-based or
        corridor-based depending on self.corridor_stairs. Returns whatever
        _find_stair_footprint returns: (x, y, fw, fl, rotation), or None
        if nothing fit anywhere.

        Corridor mode needs far fewer fallback tiers than room mode --
        CORRIDOR_STAIR_WIDTH plus margin=0 is already close to the
        cheapest possible placement (no buffered ring, no separate
        walkway), so there's little room left to relax further before
        the length itself has to shrink."""
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
        return (
            self._find_stair_footprint(
                z, self.stair_room_width, self.stair_room_length,
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

                placement = self._stair_footprint_chain(z, upper['cx'], upper['cy'])
                if placement is None:
                    continue  # no room anywhere for a stairwell -- skip this connection

                x, y, fw, fl, rotation = placement
                lower_room, upper_room = self._carve_stair_room(x, y, fw, fl, rotation, z)
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

    join_geo = nodes.new(type="GeometryNodeJoinGeometry")
    join_geo.location = (700, -280)
    links.new(realize_node.outputs['Geometry'], join_geo.inputs['Geometry'])
    links.new(ceiling_realize_node.outputs['Geometry'], join_geo.inputs['Geometry'])

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

    # 5. Isometric Mode: strip the top slice of every level's walls so a
    #    top-down camera can see into the rooms below, on every story at once
    #    (modulo against level height, not a single global Z threshold).
    ceiling_band = level_height * 0.95  # local Z within a level above which geometry is culled

    pos_node = nodes.new(type="GeometryNodeInputPosition")
    pos_node.location = (780, -220)
    sep_xyz = nodes.new(type="ShaderNodeSeparateXYZ")
    sep_xyz.location = (960, -220)
    links.new(pos_node.outputs['Position'], sep_xyz.inputs['Vector'])

    mod_z = nodes.new(type="ShaderNodeMath")
    _set_prop(mod_z, 'operation', 'MODULO')
    mod_z.location = (1120, -220)
    links.new(sep_xyz.outputs['Z'], mod_z.inputs[0])
    mod_z.inputs[1].default_value = level_height

    compare_band = nodes.new(type="FunctionNodeCompare")
    compare_band.data_type = 'FLOAT'
    compare_band.operation = 'GREATER_THAN'
    compare_band.location = (1280, -220)
    links.new(mod_z.outputs['Value'], compare_band.inputs['A'])
    _set_input(compare_band, 'B', ceiling_band)

    delete_geom = nodes.new(type="GeometryNodeDeleteGeometry")
    delete_geom.location = (1280, -60)
    _set_prop(delete_geom, 'domain', 'FACE')
    _set_prop(delete_geom, 'mode', 'ALL')
    links.new(merge_node.outputs['Geometry'], delete_geom.inputs['Geometry'])
    links.new(compare_band.outputs['Result'], delete_geom.inputs['Selection'])

    # Live toggle: pick full geometry or the ceiling-culled variant.
    iso_switch = nodes.new(type="GeometryNodeSwitch")
    iso_switch.input_type = 'GEOMETRY'
    iso_switch.location = (1460, 0)
    links.new(input_node.outputs['Isometric Mode'], iso_switch.inputs[0])
    links.new(merge_node.outputs['Geometry'], iso_switch.inputs[1])  # False -> untouched
    links.new(delete_geom.outputs['Geometry'], iso_switch.inputs[2])  # True  -> culled

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
    links.new(iso_switch.outputs[0], set_material_index.inputs['Geometry'])
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

        solver = WFC_Level_Solver(
            width=scene.wfc_width,
            length=scene.wfc_length,
            height=scene.wfc_height,
            room_count=room_count,
            room_size_min=size_min,
            room_size_max=size_max,
            stairs_per_level=scene.wfc_stairs_per_level,
            tile_size=scene.wfc_tile_size,
            level_height=scene.wfc_level_height,
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
        level_zs = []
        logical_floors = []
        z_offsets = []
        ceiling_openings = []

        scale_factor = scene.wfc_tile_size
        fine_level_height = _fine_level_height(scene)
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


def _add_flat_uv_map(mesh):
    """Every baked-mesh builder below (walls/doors/stairs/ramps/torches/
    decoration) builds its own geometry directly via from_pydata(), which
    never carries UV data -- same gap the Blueprint's GN graph and
    Separate by Floor/Room's _mesh_from_faces() had, fixed the same way:
    a flat constant (0.5, 0.5) UV on every corner, since every Simple
    Viewport Colors swatch (Wall0/Stairs/Doors/Torch/Prop .png) is a
    single flat color across the whole image, so the actual UV value
    doesn't matter for correctness, only that Solid Shading's "Texture"
    color mode (a separate, simpler display path from "Material" that
    needs a real UV map and has no Generated-coordinates fallback the way
    EEVEE does) has one to sample at all."""
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for loop_uv in uv_layer.data:
        loop_uv.uv = (0.5, 0.5)


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


def _build_wall_mesh(
    walkable_cells, tile_size, level_height, wall_height, wall_thickness, cap_top, name,
    organic_amount=0.0, z_offsets=None, forced_wall_edges=None,
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

    def is_exposed(x, y, z, ddx, ddy):
        return (x + ddx, y + ddy, z) not in walkable or ((x, y, z), (ddx, ddy)) in forced_wall_edges

    verts = []
    faces = []

    def jitter(amount):
        return random.uniform(-amount, amount) if amount > 0 else 0.0

    def add_box(cx0, cy0, cx1, cy1, z0, z1):
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
        if cap_top:
            faces.append((i + 4, i + 5, i + 6, i + 7))  # top
        faces.append((i + 5, i + 4, i + 0, i + 1))  # -Y side
        faces.append((i + 6, i + 5, i + 1, i + 2))  # +X side
        faces.append((i + 7, i + 6, i + 2, i + 3))  # +Y side
        faces.append((i + 4, i + 7, i + 3, i + 0))  # -X side

    if organic_amount > 0:
        for x, y, z in walkable_cells:
            z0 = z * level_height + z_offsets.get((x, y, z), 0.0)
            left = (x - 0.5) * tile_size
            right = (x + 0.5) * tile_size
            bottom = (y - 0.5) * tile_size
            top = (y + 0.5) * tile_size

            if is_exposed(x, y, z, -1, 0):
                ht = max(0.02, half_thick + jitter(organic_amount * 0.3))
                add_box(left - ht, bottom, left + ht, top, z0, z0 + wall_height + jitter(organic_amount))
            if is_exposed(x, y, z, 1, 0):
                ht = max(0.02, half_thick + jitter(organic_amount * 0.3))
                add_box(right - ht, bottom, right + ht, top, z0, z0 + wall_height + jitter(organic_amount))
            if is_exposed(x, y, z, 0, -1):
                ht = max(0.02, half_thick + jitter(organic_amount * 0.3))
                add_box(left, bottom - ht, right, bottom + ht, z0, z0 + wall_height + jitter(organic_amount))
            if is_exposed(x, y, z, 0, 1):
                ht = max(0.02, half_thick + jitter(organic_amount * 0.3))
                add_box(left, top - ht, right, top + ht, z0, z0 + wall_height + jitter(organic_amount))
    else:
        z1_top = wall_height  # relative rise, added to each run's own z0 below

        # -X / +X facing runs extend along Y at a fixed X boundary;
        # -Y / +Y facing runs extend along X at a fixed Y boundary. Each
        # direction is grouped independently -- a cell can start a run in
        # more than one direction at once (e.g. an outward corner).
        for dx in (-1, 1):
            lines = {}  # (x, z) -> sorted [(y, z_offset), ...]
            for (x, y, z) in walkable_cells:
                if is_exposed(x, y, z, dx, 0):
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
                if is_exposed(x, y, z, 0, dy):
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
    _add_flat_uv_map(mesh)
    return mesh


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


def _build_door_mesh(
    walkable_cells, room_ids, tile_size, level_height, door_height, frame_thickness, name,
    merge_distance=2, z_offsets=None, stair_cells=None,
):
    """A walk-through frame (two side posts + a top lintel, deliberately no
    panel filling the gap) at every same-Z boundary between two walkable
    cells whose room_id differs -- i.e. every point a corridor enters a
    room, or two rooms directly meet. That's exactly where _build_wall_mesh
    already leaves a gap (both cells are walkable, so no wall forms), so
    this never needs to reason about walls directly -- it can't place a
    frame anywhere a wall would actually be, and can't miss a real doorway
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
    a stair tile on either side."""
    walkable = set(walkable_cells)
    verts = []
    faces = []
    half_frame = frame_thickness / 2.0
    z_offsets = z_offsets or {}
    stair_cells = stair_cells or set()

    def add_box(cx0, cy0, cx1, cy1, z0, z1, floor_touching=True):
        # See the matching comment in _build_wall_mesh's add_box -- this
        # winding was verified correct against real evaluated Blender
        # geometry; the naive per-corner order pointed every normal inward.
        #
        # floor_touching (default True, matches every post box) drops the
        # bottom face -- always coincident with/hidden behind the floor
        # tile it stands on, same reasoning as walls. A door's LINTEL is
        # the one box here that ISN'T floor-touching (it's suspended at
        # door_height, spanning between the two posts); its underside IS
        # genuinely visible to anyone standing underneath it, so
        # add_frame_facing_x/y pass floor_touching=False for that call
        # specifically to keep it.
        i = len(verts)
        verts.extend([
            (cx0, cy0, z0), (cx1, cy0, z0), (cx1, cy1, z0), (cx0, cy1, z0),
            (cx0, cy0, z1), (cx1, cy0, z1), (cx1, cy1, z1), (cx0, cy1, z1),
        ])
        if not floor_touching:
            faces.append((i + 3, i + 2, i + 1, i + 0))  # bottom
        faces.append((i + 4, i + 5, i + 6, i + 7))  # top
        faces.append((i + 5, i + 4, i + 0, i + 1))
        faces.append((i + 6, i + 5, i + 1, i + 2))
        faces.append((i + 7, i + 6, i + 2, i + 3))
        faces.append((i + 4, i + 7, i + 3, i + 0))

    def add_frame_facing_x(center_x, y_min, y_max, z0):
        """Doorway replacing a north-south wall (found via a +X neighbor
        check) -- opening spans Y, walked through east-west. Posts at the
        Y ends, lintel spanning the full Y width at the top."""
        z1 = z0 + door_height
        add_box(center_x - half_frame, y_min, center_x + half_frame, y_min + frame_thickness, z0, z1)
        add_box(center_x - half_frame, y_max - frame_thickness, center_x + half_frame, y_max, z0, z1)
        add_box(
            center_x - half_frame, y_min, center_x + half_frame, y_max, z1, z1 + frame_thickness,
            floor_touching=False,
        )

    def add_frame_facing_y(center_y, x_min, x_max, z0):
        """Doorway replacing an east-west wall (found via a +Y neighbor
        check) -- opening spans X, walked through north-south."""
        z1 = z0 + door_height
        add_box(x_min, center_y - half_frame, x_min + frame_thickness, center_y + half_frame, z0, z1)
        add_box(x_max - frame_thickness, center_y - half_frame, x_max, center_y + half_frame, z0, z1)
        add_box(
            x_min, center_y - half_frame, x_max, center_y + half_frame, z1, z1 + frame_thickness,
            floor_touching=False,
        )

    # Pass 1: find every doorway boundary, grouped by (axis, z) as (line, b)
    # pairs -- "line" is the perpendicular grid coordinate (which row/column
    # the boundary runs along), "b" is the LOWER cell's index on the axis
    # the doorway crosses (e.g. an X-facing doorway found between cell x
    # and x+1 is keyed by x). Both are kept, rather than only b within a
    # fixed line, so Pass 2 can catch doorways that sit on ADJACENT lines
    # too (a wide corridor/shared edge), not just ones stacked on the exact
    # same line.
    groups = {}
    for x, y, z in walkable_cells:
        if (x, y, z) in stair_cells:
            continue
        rid = room_ids.get((x, y, z), -1)

        east = (x + 1, y, z)
        if east in walkable and east not in stair_cells and room_ids.get(east, -1) != rid:
            groups.setdefault(('X', z), []).append((y, x))

        north = (x, y + 1, z)
        if north in walkable and north not in stair_cells and room_ids.get(north, -1) != rid:
            groups.setdefault(('Y', z), []).append((x, y))

    # Pass 2: cluster every (line, b) pair within merge_distance tiles (on
    # both axes) of one another and keep one frame per cluster.
    for (axis, z), points in groups.items():
        kept = _cluster_nearby_points(points, merge_distance)

        for line, b in kept:
            if axis == 'X':
                offset = (z_offsets.get((b, line, z), 0.0) + z_offsets.get((b + 1, line, z), 0.0)) / 2.0
                z0 = z * level_height + offset
                center_x = (b + 0.5) * tile_size
                y_min = (line - 0.5) * tile_size
                y_max = (line + 0.5) * tile_size
                add_frame_facing_x(center_x, y_min, y_max, z0)
            else:
                offset = (z_offsets.get((line, b, z), 0.0) + z_offsets.get((line, b + 1, z), 0.0)) / 2.0
                z0 = z * level_height + offset
                center_y = (b + 0.5) * tile_size
                x_min = (line - 0.5) * tile_size
                x_max = (line + 0.5) * tile_size
                add_frame_facing_y(center_y, x_min, x_max, z0)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    _add_flat_uv_map(mesh)
    return mesh


def _build_stair_mesh(stair_runs, tile_size, level_height, steps_per_tile, name, organic_amount=0.0):
    """Fully-baked ascending stair geometry, same reasoning as
    _build_wall_mesh: plain Python boxes rather than a Geometry Nodes
    instancing pass. stair_runs is a list of (x, y, z, rotation, length)
    tuples -- (x, y, z) is the run's lowest/starting tile, rotation is one
    of the four cardinal values baked into tile_rotation, and length is how
    many tiles long the run is (see WFC_Level_Solver.stair_length). The
    climb is spread across the whole run -- steps_per_tile * length boxes
    total, each one step taller than the last -- rather than always cramming
    a full level's rise into a single tile, which is what made stairs steep.

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

    for x, y, z, rot, length in stair_runs:
        total_steps = max(1, steps_per_tile * length)
        run_span = tile_size * length
        step_depth = run_span / total_steps
        step_height = level_height / total_steps
        cx = x * tile_size
        cy = y * tile_size
        z0 = z * level_height
        for i in range(total_steps):
            rise = step_height * (i + 1)
            y0 = -half + step_depth * i
            y1 = y0 + step_depth
            hw = half + (random.uniform(-organic_amount, organic_amount) if organic_amount > 0 else 0.0)
            corners = [(-hw, y0), (hw, y0), (hw, y1), (-hw, y1)]
            add_box(corners, z0, z0 + rise, cx, cy, rot)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    _add_flat_uv_map(mesh)
    return mesh


def _build_ramp_mesh(stair_runs, tile_size, level_height, name, organic_amount=0.0):
    """One continuous sloped ramp per run instead of discrete steps -- same
    stair_runs data as _build_stair_mesh (same rooms, same buffer, same
    orientation fix; this only swaps the mesh representation), better
    suited to caves/open terrain than a boxy staircase. The ramp tapers to
    a flush zero-height edge at the entry (matching the lower floor
    exactly, no lip to trip on) and reaches full level_height at the exit
    edge (matching the upper floor).

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

    for x, y, z, rot, length in stair_runs:
        cx = x * tile_size
        cy = y * tile_size
        z0 = z * level_height
        run_span = tile_size * length
        seg_span = run_span / segments

        heights = [level_height * (k / segments) for k in range(segments + 1)]
        widths = [half for _ in range(segments + 1)]
        for k in range(1, segments):  # leave the two ends at exactly tile width
            widths[k] = half + random.uniform(-organic_amount, organic_amount)

        for k in range(segments):
            y0 = -half + seg_span * k
            y1 = y0 + seg_span
            add_segment(cx, cy, rot, y0, y1, heights[k], heights[k + 1], widths[k], widths[k + 1], z0)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    _add_flat_uv_map(mesh)
    return mesh


def _read_stair_runs(blueprint_obj, tile_size, level_height):
    """Reads tile_id/tile_rotation/stair_run_id off the blueprint mesh and
    groups stair cells back into continuous runs, for the stairs operator
    (which needs one run per stairwell instead of one per tile, to build
    a single continuous stair/ramp mesh rather than len(run) disconnected
    single-tile ones). Returns a list of (start_x, start_y, z, rotation,
    length) tuples, or None if the blueprint predates these attributes."""
    mesh = blueprint_obj.data
    tile_id_layer = mesh.attributes.get("tile_id")
    tile_rot_layer = mesh.attributes.get("tile_rotation")
    run_id_layer = mesh.attributes.get("stair_run_id")
    if tile_id_layer is None or tile_rot_layer is None or run_id_layer is None:
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

    # Stairwell cells are never continuous-elevation candidates (see
    # WFC_Level_Solver._apply_continuous_elevation), so their world-Z is
    # always an exact z * level_height with no offset -- rounding it back
    # to a grid index here stays exact regardless of what other cells in
    # the blueprint might carry.
    runs_by_id = {}
    for i in range(n):
        if tile_ids[i] != TILE_STAIR:
            continue
        gx = round(coords[i * 3] / tile_size)
        gy = round(coords[i * 3 + 1] / tile_size)
        gz = round(coords[i * 3 + 2] / level_height)
        rot = rotations[i]
        run_id = run_ids[i]
        runs_by_id.setdefault(run_id, []).append((gx, gy, gz, rot))

    stair_runs = []
    for cells in runs_by_id.values():
        _, _, gz0, rot = cells[0]
        dx, dy = _direction_for_rotation(rot)
        if dx or dy:
            start = min(cells, key=lambda c: c[0] * dx + c[1] * dy)
        else:
            start = cells[0]
        stair_runs.append((start[0], start[1], gz0, rot, len(cells)))
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


def _remove_objects_by_prefix(base_name):
    """Removes the exact single base_name object from an older generation,
    plus any grouped variant (base_name + "_...") from a previous run --
    grouping mode and floor/stair count can both change between
    generations, so matching by prefix is what actually clears everything
    a prior run could have created, not just today's object names.

    Data-block cleanup follows the object's own type -- LIGHT objects
    (see PROPS_LIGHT_NAME_PREFIX) own a Light data-block, not a Mesh, and
    removing the wrong one would either error or silently leak."""
    for obj in list(bpy.data.objects):
        if obj.name == base_name or obj.name.startswith(base_name + "_"):
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


def _build_torch_mesh(torches, tile_size, torch_height, name):
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

    for x, y, z0, dx, dy in torches:
        top_z = z0 + torch_height
        haft_z0 = top_z - haft_half_w * 2.0
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
    _add_flat_uv_map(mesh)
    for poly, mat_idx in zip(mesh.polygons, material_indices):
        poly.material_index = mat_idx
    return mesh


def _build_decoration_mesh(props, tile_size, name):
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
    since barrel/cone are rotationally symmetric about Z)."""
    verts = []
    faces = []

    def add_box(cx, cy, z0, half_w, half_d, height, angle):
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
        faces.append((i + 5, i + 4, i + 0, i + 1))
        faces.append((i + 6, i + 5, i + 1, i + 2))
        faces.append((i + 7, i + 6, i + 2, i + 3))
        faces.append((i + 4, i + 7, i + 3, i + 0))

    def add_cylinder(cx, cy, z0, radius, height, sides=10):
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

    for cx, cy, z0, kind, rot in props:
        if kind == 'CRATE':
            add_box(cx, cy, z0, tile_size * 0.22, tile_size * 0.22, tile_size * 0.4, rot)
        elif kind == 'BARREL':
            add_cylinder(cx, cy, z0, tile_size * 0.18, tile_size * 0.45)
        else:  # 'CONE'
            add_cone(cx, cy, z0, tile_size * 0.2, tile_size * 0.5)

    mesh = bpy.data.meshes.new(name + "_Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    _add_flat_uv_map(mesh)
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
            blueprint_obj, tile_size, level_height, ("z_offset", "tile_id", "tile_rotation")
        )
        z_offsets = extra["z_offset"]

        if not walkable_cells:
            self.report({'WARNING'}, "No walkable tiles found in the blueprint.")
            return {'CANCELLED'}

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

        created = []
        if per_floor:
            cells_by_floor = {}
            for cell in walkable_cells:
                cells_by_floor.setdefault(cell[2] // sub_levels, set()).add(cell)
            for floor_idx in sorted(cells_by_floor):
                name = f"{WALLS_OBJECT_NAME}_Floor{floor_idx}"
                wall_mesh_data = _build_wall_mesh(
                    cells_by_floor[floor_idx], tile_size, level_height,
                    scene.wfc_wall_height, scene.wfc_wall_thickness, scene.wfc_wall_cap_top,
                    name, organic_amount=organic_amount, z_offsets=z_offsets,
                    forced_wall_edges=forced_wall_edges,
                )
                if not wall_mesh_data.vertices:
                    bpy.data.meshes.remove(wall_mesh_data)
                    continue
                obj = bpy.data.objects.new(name, wall_mesh_data)
                context.collection.objects.link(obj)
                wall_mesh_data.materials.append(wall_material)
                _add_viewport_color_attribute(wall_mesh_data)
                created.append(obj)
        else:
            wall_mesh_data = _build_wall_mesh(
                walkable_cells, tile_size, level_height,
                scene.wfc_wall_height, scene.wfc_wall_thickness, scene.wfc_wall_cap_top,
                WALLS_OBJECT_NAME, organic_amount=organic_amount, z_offsets=z_offsets,
                forced_wall_edges=forced_wall_edges,
            )
            obj = bpy.data.objects.new(WALLS_OBJECT_NAME, wall_mesh_data)
            context.collection.objects.link(obj)
            wall_mesh_data.materials.append(wall_material)
            _add_viewport_color_attribute(wall_mesh_data)
            created.append(obj)

        for obj in created:
            obj.select_set(True)
        if created:
            context.view_layer.objects.active = created[-1]

        self.report(
            {'INFO'},
            f"Walls generated from {len(walkable_cells)} exposed edges, in {len(created)} object(s)."
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
            runs_by_floor.setdefault(run[2] // sub_levels, []).append(run)

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
                    mesh_data = _build_ramp_mesh(group, tile_size, level_height, name, organic_amount=organic_amount)
                else:
                    mesh_data = _build_stair_mesh(
                        group, tile_size, level_height, scene.wfc_stair_steps, name,
                        organic_amount=organic_amount,
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

        total_tiles = sum(length for *_, length in stair_runs)
        self.report(
            {'INFO'},
            f"Stairs generated: {len(stair_runs)} runs across {total_tiles} tiles, in {len(created)} object(s)."
        )
        _update_debug_snapshot(context, "Step 3: Generate Stairs")
        return {'FINISHED'}


class OBJECT_OT_GenerateLevelDoors(bpy.types.Operator):
    """Builds walk-through door frame object(s) from the already-generated
    blueprint's tile_id/room_id data -- run "Generate Game Blueprint"
    first. A frame (two posts + a lintel, deliberately no panel) is placed
    at every point a corridor enters a room or two rooms directly meet --
    exactly wherever the wall silhouette already leaves a gap, so this
    never conflicts with or duplicates wall geometry."""
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

        if not walkable_cells:
            self.report({'WARNING'}, "No walkable tiles found in the blueprint.")
            return {'CANCELLED'}

        _remove_objects_by_prefix(DOORS_OBJECT_NAME)

        door_material = get_or_create_door_material()

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
                    stair_cells=stair_cells,
                )
                if not door_mesh_data.vertices:
                    bpy.data.meshes.remove(door_mesh_data)
                    continue
                obj = bpy.data.objects.new(name, door_mesh_data)
                context.collection.objects.link(obj)
                door_mesh_data.materials.append(door_material)
                _add_viewport_color_attribute(door_mesh_data)
                created.append(obj)
        else:
            door_mesh_data = _build_door_mesh(
                walkable_cells, room_ids, tile_size, level_height,
                scene.wfc_door_height, scene.wfc_door_frame_thickness, DOORS_OBJECT_NAME,
                merge_distance=scene.wfc_door_merge_distance, z_offsets=z_offsets,
                stair_cells=stair_cells,
            )
            if door_mesh_data.vertices:
                obj = bpy.data.objects.new(DOORS_OBJECT_NAME, door_mesh_data)
                context.collection.objects.link(obj)
                door_mesh_data.materials.append(door_material)
                _add_viewport_color_attribute(door_mesh_data)
                created.append(obj)
            else:
                bpy.data.meshes.remove(door_mesh_data)

        if not created:
            self.report({'WARNING'}, "No doorways found -- every walkable boundary shares a room_id.")
            return {'CANCELLED'}

        for obj in created:
            obj.select_set(True)
        context.view_layer.objects.active = created[-1]

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
                if (x + dx, y + dy) not in walkable_cells
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
        torches = []  # (x, y, z0, dx, dy)
        torch_room_id = []  # parallel: this torch's room_id, -1 for corridor
        rooms_with_mesh = set()
        for cell, options in wall_adjacent.items():
            if random.random() >= scene.wfc_torch_chance:
                continue
            dx, dy = random.choice(options)
            x, y, z = cell
            rid = room_ids.get(cell, -1)
            torches.append((x, y, cell_z0(cell), dx, dy))
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
            cell = random.choice(cells)
            x, y, z = cell
            dx, dy = random.choice(wall_adjacent[cell])
            torches.append((x, y, cell_z0(cell), dx, dy))
            torch_room_id.append(rid)
            rooms_with_mesh.add(rid)

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
            for cell in random.sample(candidates, prop_count):
                x, y, z = cell
                kind = random.choice(prop_kinds)
                rot = random.uniform(0.0, 2.0 * math.pi)
                decorations.append((x * tile_size, y * tile_size, cell_z0(cell), kind, rot))

        created = []

        if torches:
            torch_mesh = _build_torch_mesh(torches, tile_size, scene.wfc_torch_height, PROPS_TORCH_OBJECT_NAME)
            torch_obj = bpy.data.objects.new(PROPS_TORCH_OBJECT_NAME, torch_mesh)
            torch_collection.objects.link(torch_obj)
            torch_mesh.materials.append(get_or_create_torch_material())
            torch_mesh.materials.append(get_or_create_torch_flame_material())
            _add_viewport_color_attribute(torch_mesh)
            created.append(torch_obj)

            flame_color = tuple(scene.wfc_torch_light_color)
            for idx in lit_indices:
                x, y, z0, dx, dy = torches[idx]
                top_z = z0 + scene.wfc_torch_height
                if dx != 0:
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
            decoration_mesh = _build_decoration_mesh(decorations, tile_size, PROPS_DECORATION_OBJECT_NAME)
            decoration_obj = bpy.data.objects.new(PROPS_DECORATION_OBJECT_NAME, decoration_mesh)
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


class VIEW3D_PT_GameLevelArchitect(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Level Architect'
    bl_label = "Procedural Game Architect"

    def draw(self, context):
        scene = context.scene
        layout = self.layout

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

    def _draw_walls_tab(self, context, layout):
        scene = context.scene
        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(scene, "wfc_wall_height", text="Height")
        row.prop(scene, "wfc_wall_thickness", text="Thick")
        col.prop(scene, "wfc_wall_cap_top", text="Cap Top")
        col.prop(scene, "wfc_wall_grouping", text="Grouping")
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
        layout.separator()
        _step_button(
            layout, "object.generate_level_doors", "Step 4: Generate Doors",
            'MOD_LATTICE', 'COLLECTION_COLOR_06',
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
        layout.separator()
        _step_button(
            layout, "object.generate_level_props", "Step 5: Generate Props",
            'LIGHT', 'COLLECTION_COLOR_03',
        )


# ==============================================================================
# 5. REGISTRATION
# ==============================================================================
classes = (
    OBJECT_OT_GenerateGameBlueprint,
    OBJECT_OT_SeparateLevelByFloor,
    OBJECT_OT_GenerateLevelWalls,
    OBJECT_OT_GenerateLevelStairs,
    OBJECT_OT_GenerateLevelDoors,
    OBJECT_OT_GenerateLevelProps,
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
            ('ROUND', "Round", "Circular/oval rooms, approximated on the tile grid"),
            ('MIXED', "Mixed", "Randomly rectangular or round, chosen per room"),
            ('CAVE', "Cave", "Every floor becomes one organic connected network of winding "
                              "tunnels and round chambers instead of discrete rooms joined by "
                              "straight corridors. Reuses Min/Max Rooms as the chamber count and "
                              "Min/Max Room Size as chamber size. Pairs well with Corridor Stairs"),
        ],
        default='RECT',
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
    bpy.types.Scene.wfc_organic_amount = FloatProperty(
        name="Organic Irregularity", default=0.0, min=0.0, max=0.3, unit='LENGTH',
        description="Jitters wall height/thickness, stair tread width, and ramp edges for a "
                    "hand-carved look -- purely cosmetic, never affects which cells are walkable "
                    "or connectivity. 0 = perfectly regular (default)"
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
    bpy.types.Scene.wfc_debug_params = StringProperty(
        name="Debug Params", default="",
        description="Internal: snapshot of every wfc_* setting as of the most recent Step "
                    "operator run, for the Debug panel's Copy Parameters button. Not meant to be "
                    "edited directly"
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
    del bpy.types.Scene.wfc_organic_amount
    del bpy.types.Scene.wfc_stair_mesh_style
    del bpy.types.Scene.wfc_stair_steps
    del bpy.types.Scene.wfc_stair_grouping
    del bpy.types.Scene.wfc_door_height
    del bpy.types.Scene.wfc_door_frame_thickness
    del bpy.types.Scene.wfc_door_grouping
    del bpy.types.Scene.wfc_door_merge_distance
    del bpy.types.Scene.wfc_torch_chance
    del bpy.types.Scene.wfc_torch_height
    del bpy.types.Scene.wfc_torch_light_energy
    del bpy.types.Scene.wfc_torch_light_color
    del bpy.types.Scene.wfc_torch_light_radius
    del bpy.types.Scene.wfc_torch_light_chance
    del bpy.types.Scene.wfc_max_lights
    del bpy.types.Scene.wfc_prop_chance
    del bpy.types.Scene.wfc_debug_params
    del bpy.types.Scene.wfc_active_tab

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
