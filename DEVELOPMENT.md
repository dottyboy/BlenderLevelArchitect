# Game Level Architect — Development Notes

Internal dev-facing doc: what's built, what's known-broken, what's next. Not for end users
(see `dist/README.md` for that). Source of truth for the addon's actual behavior is always
`levelArchitect_v2.py` — this file can drift out of date; the code can't.

Current version: **0.19.0** (see `bl_info` in the source file).

---

## 1. Architecture overview

```
WFC_Level_Solver (pure Python, no bpy)
  └─ produces a 3D grid: room/corridor/stair layout + connectivity guarantee
        │
        ▼
OBJECT_OT_GenerateGameBlueprint  (Step 1)
  └─ bakes the grid into a sparse mesh (1 vertex per tile) + point attributes
     (tile_id, room_id, level_z, logical_floor, z_offset, ...) -- z_offset is
     continuous room elevation (see §2), folded into the point's Z too
  └─ builds a Geometry Nodes modifier that instances floor/marker geometry
     per point, live-adjustable (Isometric Mode, Color Rooms/Corridors, etc.)
        │
        ▼
OBJECT_OT_GenerateLevelWalls (Step 2)         OBJECT_OT_GenerateLevelStairs (Step 3)
  └─ reads tile_id off the blueprint            └─ reads tile_id/rotation/stair_run_id
  └─ fully-baked Python mesh (no GN)                └─ fully-baked Python mesh (no GN)
  └─ Single Object / Per Floor grouping             └─ Stairs or Ramp mesh style
                                                      └─ Per Floor / Per Stair grouping

OBJECT_OT_GenerateLevelDoors (Step 4)
  └─ reads tile_id + room_id off the blueprint
  └─ fully-baked Python mesh (no GN); walk-through frame (2 posts + lintel,
     no panel) at every boundary where room_id differs across a walkable
     gap -- i.e. every point a corridor enters a room
  └─ Single Object / Per Floor grouping

OBJECT_OT_GenerateLevelProps (Step 5)
  └─ reads tile_id + room_id off the blueprint
  └─ fully-baked Python mesh (no GN) for torches + decoration, plus REAL
     bpy.data.lights Point light objects (one per torch)
  └─ lands in a "Procedural Level Props" collection tree, not loose objects

OBJECT_OT_SeparateLevelByFloor (utility, next to Step 1)
  └─ splits the blueprint mesh into per-floor objects using logical_floor,
     AFTER its GN modifier has been applied -- doesn't rely on Select Linked
```

**Why walls/stairs are baked Python mesh, not Geometry Nodes:** two consecutive GN-based
implementations failed in real testing (uncertain `GeometryNodeExtrudeMesh` Selection-socket
defaults). Deliberate pivot to deterministic `mesh.from_pydata()` construction, verified offline
against a `stub_bpy` mock harness before ever touching real Blender. This trade-off (no live GN
slider adjustability for wall/stair dimensions post-generation) was made on purpose and should
stay that way unless there's a strong reason to revisit it.

**Why the floor stays Geometry-Nodes-driven:** it needs live toggles (Isometric Mode, Color
Rooms/Corridors, Floor Thickness, Merge Distance) that don't require regeneration — worth the
GN complexity there specifically.

---

## 2. Development tree (how this got built, roughly chronological)

- [x] **Foundation** — WFC-style solver (room scatter, MST corridors, BFS connectivity +
      repair pass), Geometry Nodes floor renderer, procedural style materials (dungeon/cave/open
      area), basic N-panel UI.
- [x] **Walls as their own object** — pivoted from GN extrude to baked Python mesh after GN
      reliability issues.
- [x] **Stairs, take 1 → take 2** — GN-based stairs also hit reliability issues; rebuilt as
      baked Python mesh. Multi-tile runs (self-scaling with level_height:tile_size ratio) to
      avoid steep single-tile stairs.
- [x] **Room-based stairwell system** — replaced "grow a stair from a room's center" with a
      fully reserved, buffered rectangular room per stairwell (`_carve_stair_room` /
      `_find_stair_footprint`). Fixed a long tail of bugs this surfaced: stair orientation not
      matching the actual approach direction, emergency-fallback stairs merging into one bogus
      run across the whole map, walls clipping through stair geometry, stairs opening into
      "thin air," repair-pass stairs stacking on the exit corner.
  - [x] Minimum room size enforcement (`MIN_STAIR_ROOM_WIDTH/LENGTH`, `FALLBACK_STAIR_ROOM_LENGTH`)
        so a buffer around the stair is *always* possible, no more bare unenclosed stairs in
        the middle of a corridor.
- [x] **Materials pass 1** — fixed root cause of "colors not visible" (Solid shading reads
      `diffuse_color`, not the shader node tree). Simple Viewport Colors mode (flat materials,
      per-room random color, light-grey corridors).
- [x] **Seed + reproducibility** — deterministic generation, Random Seed toggle.
- [x] **Round rooms** — RECT / ROUND / MIXED room shapes.
- [x] **Perf pass** — Prim's MST O(n³) → O(n²), cached rooms-by-level instead of re-filtering
      `self.rooms` repeatedly.
- [x] **GUI reorganization** — collapsible sections, paired-row layouts, colored step buttons,
      settings separated from always-visible action buttons.
- [x] **Per-floor / per-stair object grouping** — walls and stairs can each split into multiple
      objects instead of one combined mesh.
- [x] **Sub-Levels per Floor / Split-Level Chance** — rooms can sit raised/lowered within their
      own logical floor, still connected via the same stairwell system, just a shorter climb.
      Surfaced (and fixed) a real bug: "Per Floor" grouping was bucketing by *fine* Z-slice
      instead of *logical* floor, producing more stair/wall objects than actual floors.
- [x] **Separate by Floor** — post-GN-apply utility to split the blueprint mesh by floor without
      relying on Blender's Select Linked (which can't tell split-level rooms apart, since they
      aren't vertex-connected to the rest of their floor).
- [x] **Texture/palette system** — 32-color palette mapped to floor-level ramp (8 colors,
      cycles), room pool (18 colors), walls, stairs, entrance, exit, doors. Loads real `.png`
      files from `Textures/`, falls back to hex constants if a file's missing.
- [x] **Publishing prep** — GPL-3.0-or-later, restructured into an installable
      `game_level_architect/__init__.py` + `Textures/` + `LICENSE` package, `build_package.sh`.
- [x] **Ramp mesh style** — alternative to stepped stairs: one continuous sloped wedge per run,
      flush with the floor at both ends. Same room/buffer/orientation guarantees as stairs, just
      a different mesh on top of the same run data.
- [x] **Organic Irregularity** — cosmetic jitter (wall height/thickness, stair tread width,
      ramp edge waviness), seeded for reproducibility, zero effect on connectivity or room
      placement.
- [x] **Doors (Step 4)** — walk-through frames (two posts + a lintel, deliberately no panel),
      placed at every same-Z boundary between two walkable cells whose `room_id` differs — i.e.
      exactly where the wall silhouette already leaves a gap. Reads `tile_id` + `room_id` off the
      blueprint (same data walls already use, plus room_id), so a doorway can only ever land
      where a wall gap already exists, and can't miss one either. Verified against 1,478
      generated doorways across 50 randomized levels: every walkable opening stays genuinely
      clear of wall geometry.
  - [x] **Merge Distance** — two rooms connected by a short (1-2 tile, configurable) corridor
        used to get a doorway at each end, standing right on top of each other. Doorways are now
        collected per straight line first, then any run within `Merge Distance` tiles of the
        previous one collapses down to a single frame. Verified: 1-2 tile gaps → 1 door, 3+ tile
        gaps → 2 doors, `Merge Distance = 0` restores the old always-two-doors behavior; across
        60 randomized levels this cut total door count by ~27% with zero newly-blocked openings.
  - [x] **Merge Distance fix: wide openings** — the pass above only compared doorways on the
        *same* grid line, so a wide corridor or a long shared room edge (adjacent boundary cells,
        each on its own line) still produced several doors side by side in the same room —
        exactly the "multiple doors next to each other" symptom. `_cluster_nearby_points`
        replaces the per-line scan with a 2D (Chebyshev, both axes) union-find cluster over every
        boundary in a given axis+Z, keeping one frame per cluster. Verified across 60 randomized
        levels: zero surviving door pairs closer than `Merge Distance` afterward (was previously
        possible), raw→kept reduction rose from ~27% to ~52% at the default distance.
- [x] **Stairwell placement: reduce bufferless emergency fallback** — `_find_stair_footprint`
      tries progressively smaller room sizes before giving up, but every tier required a full
      1-tile empty *margin* around the footprint too; in dense layouts that margin — not the
      footprint itself — was usually what wasn't available, so placement fell through to
      `_ensure_connectivity`'s absolute-last-resort single tile (no room, no buffer — the stair
      that visibly clips into/opens straight at a wall). Added one more tier at the minimum
      footprint size with `margin=0` (flush against a neighboring room is fine; overlapping one
      never is — `_room_fits` still checks the footprint itself is empty) before falling through.
      Verified against a deliberately oversaturated stress config (small map, high room count,
      split-levels): the bufferless-fallback rate among all placed stairs dropped from 34% to
      6.7%, with zero connectivity regressions (BFS start→end still succeeds on every test level);
      normal-density layouts stayed at 0% either way.
- [x] **True continuous room elevation — middle-ground V1** (`_apply_continuous_elevation`).
      Implements the sketch below: the grid/BFS/room-fit/stairs are untouched, a room becomes an
      elevation candidate only if it has exactly one doorway (so no other, unramped entrance can
      ever meet its raised/lowered floor as a cliff), its offset is clamped to whatever fits `Max
      Ramp Angle` over the actual corridor run available, and that run's cells get the offset
      linearly interpolated back to flat. A cell's world-Z offset is a new baked `z_offset` point
      attribute (plus folded directly into the point's Z) that Walls and Doors now read so wall
      boxes and door frames follow the sloped floor instead of floating/clipping.
      Two real bugs surfaced and were fixed during verification (not just theoretical edge cases
      — both reproduced in stress tests before the fix): (1) a ramp corridor could run past a
      doorway into an unrelated third room without ramping it, leaving a cliff exactly at that
      door — fixed by rejecting any corridor cell that is itself a doorway into another room
      (`_is_clean_corridor_cell`); (2) none, the initial "adjacent cells more than Max Ramp Angle
      apart" and "adjacent cells belong to different unmerged ramps" failure modes were checked
      for but never found to occur, across 150 stress-tested levels (varied room shapes/sizes,
      sub-levels, split-level chance). Verified end-to-end through the real
      Blueprint → Walls → Doors operators (not just solver-level checks): 0 mismatched wall
      vertices out of 669,216 and 0 mismatched door vertices out of 146,280 across that same
      150-level stress run; 0 cliffs (a room's own floor always stays uniformly flat) and 0
      slope violations at the solver level.
      First-pass scope only, per the sketch: single elevated room per opt-in, one flat neighbor,
      no chained multi-room gradients, no multi-doorway rooms. Off by default (`Elevation
      Chance` = 0).
  - [x] **Multi-doorway rooms.** `_room_elevation_paths` grows one ramp per doorway (adjacent
        boundary cells cluster into a single doorway first, same idea as the door-merge pass, so
        a wide corridor mouth doesn't spawn several redundant near-parallel ramps) instead of
        requiring exactly one; if EVEN ONE of a room's doorways can't grow a usable ramp, the
        whole room stays flat rather than partially ramping it, same reasoning as before but
        applied per-doorway instead of per-room. The offset is clamped by whichever doorway's
        run is shortest, so every ramp individually respects Max Ramp Angle.
        A second real bug surfaced here and was fixed: two independently-grown ramps (whether
        from the same room's different doorways, or from two different elevated rooms) can pass
        each individually but still end up running geometrically side by side with very
        different offsets, since nothing stopped them from ever getting adjacent to begin with
        (only cell *reuse* was blocked). Fixed by giving every ramp a 1-cell buffer against any
        other already-committed ramp cell, the same margin rooms already keep from each other
        (`is_clean`, refactored to take the current path's own visited cells so a path doesn't
        buffer against itself). Verified across 300 stress-tested levels: 618 rooms elevated
        (up from 159 when only single-doorway rooms qualified), 318 of them genuinely
        multi-doorway, 0 cliffs, 0 slope violations, 0 connectivity regressions — and the same
        150-level Blueprint → Walls → Doors round-trip check as V1 stayed at 0 mismatched
        vertices (669,216 wall + 146,280 door) with 141/150 levels now getting at least one
        elevated room (up from 109/150).
- [x] **Corridor Stairs** (`wfc_corridor_stairs`, off by default). Alternative to the
      room-based stairwell system: instead of reserving a buffered `stair_room_width`-wide room
      (margin=1) around the climb, the stair is placed as a flush `CORRIDOR_STAIR_WIDTH`-wide
      (1 tile, margin=0) strip directly in the corridor network -- no separate walkway, walls
      form on both sides exactly like an ordinary corridor. `_carve_stair_room` already degrades
      correctly at width 1 with no changes needed (the walkway and stair-column indices collapse
      to the same cell, and the ceiling opening shrinks from 2 tiles to 1 to match); the new
      `_stair_footprint_chain` helper picks which placement chain (room-based, 4 fallback tiers,
      or corridor-based, 2 tiers) `_connect_levels_with_stairs` and `_ensure_connectivity`'s
      repair pass both call, replacing the duplicated inline chains at each site. Verified: in
      the same dense stress config used for the earlier stair-placement fix, corridor mode's
      stair-placement attempts failed 0/757 times vs room mode's 36/757 (4.8%) -- the whole
      point, since a 1-wide strip needs far less free space than a buffered room.
      **A real interaction bug with continuous elevation was caught during review, before ever
      running a test**: a corridor stair's climb cells carry `room_id == -1`, identically to an
      ordinary corridor cell, but the stair mesh is built with fixed geometry that never reads
      `z_offset` -- so an elevation ramp's walk-outward pass could have treated a real staircase
      as just more flat corridor to slope through, or run directly beside one, desyncing the
      stair from a sloped floor next to it. Fixed in `_room_elevation_paths`: doorway thresholds
      and ramp candidates now require `TILE_FLOOR` specifically (not just any walkable tile), and
      `is_clean` rejects any cell adjacent to a `TILE_STAIR` tile outright. Verified across 300
      stress-tested levels with both features on together: 463 rooms elevated, 0 cliffs, 0 slope
      violations, 0 ramp cells touching or bordering a stair tile, 0 connectivity regressions;
      re-ran the room-mode-only elevation stress suite afterward too, to confirm the tightened
      filter changed nothing there (still exactly 618/0/0/0, byte-identical to before the fix).
- [x] **Ceiling** (`wfc_add_ceiling` + `wfc_ceiling_thickness`, off by default). For FPS-style
      play, an open-top level reads as "looking at the sky/world background" from inside any
      room -- this adds a ceiling slab above every walkable tile, GN-driven exactly like the
      floor (mirrors the floor cube's own node chain: same Instance on Points → Realize
      Instances pipeline, off the same point cloud, joined in with `GeometryNodeJoinGeometry`
      before the existing Merge Distance/material-index steps, so it needs zero changes to
      material assignment or Isometric Mode). Placed one whole `level_height` above each point,
      i.e. flush with the floor of the point directly above it, for a seamless sandwich between
      stories. Skips any point whose upper neighbor is a stairwell's `floor_opening`, via a new
      baked `ceiling_opening` point attribute (mirrors `floor_opening`'s own skip logic exactly),
      so Add Ceiling can't silently seal a stairwell hole shut from above -- verified in Python
      against 21,769 points across 60 randomized levels (corridor/room stairs and elevation both
      mixed in): 0 mismatches between `ceiling_opening` and the actual floor_opening state of
      the point above.
      Isometric Mode already had a "strip the top slice of every level" cull step wired up from
      before this feature existed (labelled "Cull Ceilings" in the UI at the time) -- turning
      Isometric Mode on hides the new ceiling automatically, no extra wiring needed; this was
      very likely built in anticipation of exactly this feature.
      **Now verified against live Blender** (see `tests/blender_headless_test.py`, added later
      this session) -- the GN graph builds and evaluates correctly, Add Ceiling adds real geometry
      to the evaluated mesh, and Isometric Mode culls it back down, all confirmed in an actual
      Blender 5.2.0 LTS process. Not fully exhaustive (seam quality/visual correctness still
      wants an eyeballed look), but the "does this even work" risk this bullet used to flag is
      resolved.
- [x] **Props / decoration scattering (Step 5)** — wall-mounted torches (baked-mesh bracket +
      flame cap, two material slots via per-polygon `material_index`, same pattern
      `OBJECT_OT_SeparateLevelByFloor` already uses) each paired with a REAL `bpy.data.lights`
      Point light at the flame position, so they actually illuminate the level rather than just
      resembling a light source; plus floor decoration (crate/barrel/cone placeholders,
      `_build_decoration_mesh`) scattered per room. Fully-baked Python mesh, no GN involvement at
      all, so (unlike Ceiling above) this one WAS fully exercisable through `stub_bpy` end-to-end.
      Everything lands in a `Procedural Level Props` collection tree (Torches / Lights /
      Decoration sub-collections, via new `_get_or_create_collection` helper) instead of loose
      objects in the scene collection, so the whole prop layer can be hidden/isolated/deleted
      independently of the structural geometry.
      "Rooms need lights" is a hard guarantee, not just a density knob: every room with at least
      one wall-adjacent tile gets ≥1 torch regardless of how the random `Torch Chance` roll goes
      (a forced second pass tops up any room the first pass missed) — verified across 100
      stress-tested levels (corridor/room stairs and elevation both mixed in): 0 rooms missing a
      torch out of 2,277 checked. Decoration placement excludes any tile that's itself a doorway
      threshold, so nothing can block a passage — verified across 40 high-density trials
      (`Prop Chance` = 0.6): 0 violations across 5,306+ placed props. Torch/decoration Z follows
      per-cell `z_offset` exactly like Walls/Doors, so wall-mounted torches stay flush against a
      sloped-floor wall too (96,832 torch vertices checked, 0 out of the expected range).
      `_remove_objects_by_prefix` needed generalizing to branch on the object's own `.type`
      before deciding whether to clean up a Mesh or a Light data-block — the two aren't
      interchangeable, and getting this wrong would have errored (or silently leaked light
      data-blocks) on every regeneration; verified light objects clean up correctly and don't
      duplicate across repeated Step 5 runs.
      Deliberately out of scope for v1: only 3 of the primitive kinds mentioned (crate=box,
      barrel=cylinder, cone) — a true low-poly sphere was skipped as extra geometry-building code
      for comparatively little placeholder value; adding one later is a straightforward
      `add_sphere` alongside the existing `add_cylinder`/`add_cone` helpers in
      `_build_decoration_mesh`, not a design change.
- [x] **Optimization pass: generation speed, runtime light count, wall polycount.**
  - [x] **Generation speed** — Walls/Doors/Stairs (`_read_stair_runs`)/Props each used to read the
        blueprint back with `for i, vert in enumerate(mesh.vertices): vert.co.x, attr.data[i].value`
        -- per-item access through Blender's Python/RNA wrapper, once per vertex per attribute.
        New shared `_read_blueprint_points` (Walls/Doors/Props) plus an inlined equivalent in
        `_read_stair_runs` switch to `foreach_get`, the standard bulk-array-copy pattern for this
        exact case (mirrors the `foreach_set` already used to write these same attributes at
        generation time). Behavior-preserving refactor only, no logic changed — reverified with
        the full 150-level Blueprint → Walls → Doors round-trip check (still 0 mismatched
        vertices) plus the 100-level Props stress suite (still 0/2,277 rooms missing a torch).
  - [x] **Runtime light count** — torch MESH density (Torch Chance, cheap, purely visual) is now
        decoupled from actual Point light count (new Torch Light Chance + Max Lights, the
        expensive part in a real game engine). One light per room is still a hard guarantee, just
        moved from the mesh stage to the light stage — `must_light` picks one of a room's torches
        before the probabilistic pass runs, and Max Lights only ever trims the *optional* lights,
        never that guaranteed one (so an aggressively low cap on a big map exceeds it slightly
        rather than leave a room dark). Verified: 0/2,277 rooms missing a light across the normal
        stress suite, and separately stress-tested with `Max Lights = 3` against ~20-room levels
        (30 trials): still 0 rooms without a light, confirming the guarantee holds even when it
        must override the cap.
  - [x] **Wall polycount** — `_build_wall_mesh` used one fully-closed box per exposed tile-edge;
        with Organic Irregularity off, every box along a straight run has identical
        thickness/height, so adjacent boxes are already perfectly flush/coplanar at their shared
        seam and merging them changes nothing about the visible surface. New run-merging path
        (gated on `organic_amount <= 0`, since jitter needs per-tile granularity to still read as
        hand-built) groups same-direction exposed edges into contiguous runs — broken wherever
        `z_offset` differs between adjacent cells too, since a sloped run genuinely can't be one
        flat box. Verified two ways: (1) an independently-computed ground-truth coverage check
        (built without reusing the merge code at all) showed 0 mismatches across 1,150 wall-line
        checks over 30 levels, confirming byte-identical exterior surface coverage; (2) box count
        dropped 56.2% (9,890 → 4,334) over those same levels. Also directly verified the
        elevation-aware run-breaking on a synthetic 5-cell run with one differently-offset middle
        cell: correctly split into 3+3+1+1 = 8 boxes instead of merging straight through it.
        Doors/Stairs/Props were left untouched — they're comparatively small object counts already
        (a handful of boxes each vs. potentially hundreds of wall edges), so the same rewrite
        there wasn't judged worth the added risk for this pass.
- [x] **Real-Blender headless test harness** (`tests/blender_headless_test.py` +
      `run_blender_tests.sh`) — every verification described throughout this file up to this
      point was `stub_bpy` (a Python-level mock good enough for solver/mesh-math logic, but
      structurally unable to construct or evaluate a Geometry Nodes graph at all) or manual
      in-viewport testing. This runs the actual addon inside a real headless Blender process
      (`blender --background --factory-startup --python ...`) and exercises the full pipeline
      through real `bpy.ops` calls: Blueprint → live Add Ceiling/Isometric Mode toggling on the
      evaluated depsgraph mesh → Walls → Stairs → Doors → Props (collections, real Light
      objects) → apply modifier → Separate by Floor. Exits non-zero on any failed check, so it's
      usable as a script/CI gate, not just an interactive tool.
      The full pipeline (Blueprint through Separate by Floor) passed end to end against real
      Blender 5.2.0 LTS — the biggest open question hanging over this whole project (whether any
      of the GN code actually works at all) is resolved. Along the way, discovered a genuine
      Blender 5.2 API change worth remembering: GN modifier inputs are no longer accessible via
      the old `modifier["Socket_N"]` IDProperty pattern (raises "id properties not supported for
      this type" on 5.2) — the working form is `modifier.properties.inputs.Socket_N.value`, via a
      `GeometryNodesModifierInterface` wrapper that didn't exist in older Blender versions.
      Documented inline in the test script since nothing else in this codebase pokes a live GN
      modifier's inputs today.
  - [x] **Found and fixed a real mesh-winding bug on the very first winding-aware check** — every
        `add_box`-style helper in the file (walls, doors, stairs, ramps, torches, decoration —
        six separate copies of the identical convention, all deliberately kept in sync with each
        other per the note in §5) had every face wound backwards: a box's bottom face pointed
        +Z (into itself) and its top face pointed -Z (into itself), confirmed by direct cross-
        product computation and reproduced live against real evaluated geometry. This was
        invisible for the entire project up to now because Blender's Solid shading doesn't cull
        backfaces by default, so it silently looked fine in every manual viewport check anyone
        (including the user) had done — it would only have shown up as inside-out geometry in a
        renderer or game engine that DOES cull backfaces, which is most of them. Confirmed the
        bug was systemic (not a one-off) by computing the actual cross product for three faces
        of one box (bottom, top, one side) by hand — all three came out backwards, consistent
        with the whole convention being flipped from day one, not a partial mistake. Fixed by
        reversing every face's vertex order in all six `add_box` copies (verified this is the
        correct, sufficient fix: reversing a planar polygon's vertex order exactly negates its
        computed normal, and rotation -- used by the stair/ramp/decoration variants -- preserves
        that relationship since it's a proper orthogonal transform). Re-ran
        `tests/blender_headless_test.py` afterward: both winding checks now pass. The
        `add_cylinder`/`add_cone` helpers added this session for decoration barrels/cones were
        NOT part of this bug — they were derived independently (not copied from `add_box`) and
        checked out correct by the same by-hand cross-product method before ever touching them.
        Also re-ran the full `stub_bpy` regression suite (position/count-based, so blind to pure
        winding changes) to confirm nothing else regressed: unchanged.
- [x] **Two real bugs found by actually opening `test_blends/` files** — geometrically valid
      (non-empty, no-exception) meshes are not the same as CORRECTLY POSITIONED meshes; both of
      these passed every prior check (including `tests/blender_headless_test.py` at the time) and
      were only caught by a human looking at the generated levels.
  - [x] **Doors placed on/beside the stairs themselves.** `_build_door_mesh` treated any
        same-Z boundary where `room_id` differs as a doorway -- correct for "corridor enters
        room," but a stairwell's climb column carries `room_id == -1` too (reset to match
        ordinary corridor cells, for BFS/connectivity uniformity -- see `_carve_stair_room`), so
        the WALKWAY-to-climb-column boundary *inside* a stairwell room read as a doorway as well,
        planting a frame on the stairs. Fixed by threading a `stair_cells` set (from the
        blueprint's own `tile_id` attribute) into `_build_door_mesh` and excluding any boundary
        that touches one -- a stairwell's real, legitimate doorway (corridor entering its
        walkway) is unaffected, since that boundary never touches a stair tile. Verified via the
        `stub_bpy` harness across 60 stress-tested levels: 54 doors previously landed on/beside
        stairs (about 1 per level on average); an independent, precise check (not reusing the fix
        code) confirmed 0 of the 1,620 doors generated after the fix have a boundary touching a
        stair cell.
  - [x] **Stair runs frequently anchored at the wrong end — the more serious of the two.**
        `_read_stair_runs` picks a run's "start" (climb origin) tile via
        `DIRECTION_FOR_ROTATION.get(rot, (0, 1))`, an EXACT dict lookup keyed by the
        `tile_rotation` float. But that value is read back from a baked mesh attribute Blender
        stores as a 32-bit float -- so a rotation written as the exact Python float64 constant
        `3.1415` can round-trip back as `3.1414999961853027`. The dict lookup silently missed
        that and fell through to the `(0, 1)` default -- not a "close enough" answer, a
        different, wrong direction -- which picks the wrong end of the run as its anchor,
        translating the whole stair mesh by up to a full run's length in the wrong place
        (overlapping walls, opening away from where the solver actually carved its exit). Found
        by hand-tracing one real overlap in `test_blends` output back to its source run, then
        confirmed systemic: simulating the real float32 round-trip against 213 stair runs across
        60 stress-tested levels showed **166 (78%) got the wrong direction** under the old exact
        lookup. Fixed with a new `_direction_for_rotation(rot, tolerance=0.01)` that finds the
        nearest of the 4 known rotation constants instead of requiring exact equality, falling
        back to `(0, 1)` only if truly nothing is within tolerance (i.e. actually unrecognized
        data, not just float32-rounded) -- 0/213 wrong afterward. Solver-internal call sites
        (`_carve_stair_room`, the emergency-fallback rotation in `_ensure_connectivity`) were
        never at risk: they pass the exact float64 constant directly, never round-tripping
        through a mesh attribute, so `DIRECTION_FOR_ROTATION`'s plain dict lookup stays safe
        there. Added a permanent regression check to `tests/blender_headless_test.py` (AABB
        overlap between every stair tread box and every wall box) so this class of bug can't
        silently return -- tuned with a Corridor-Stairs-aware tolerance, since a corridor
        stair's treads are *supposed* to sit flush against a wall on their open sides (no side
        walkway there, by design), which looks identical in shape to a real bug at a glance (both
        are a shallow, wall-thickness-scale overlap) -- only a room-based stairwell (which always
        has a walkway buffer) can assume zero wall contact means correct and vice versa.
- [x] **GUI reorganized to cut vertical space in the sidebar tab.** User feedback: "low on screen
      space." Two changes: (1) stair settings were split across two separate collapsible sections
      (`LA_stair_layout` near the top of the panel, and a second `Step 3: Stairs` section further
      down for mesh style/steps/grouping) -- merged into one `Step 3: Stairs` section, removing a
      whole extra header+box. (2) the `Rooms` section (9 properties) defaulted to open on every
      panel draw; now `default_closed=True` like every other settings section except `Map & Seed`.
      Also paired several previously one-per-row properties onto shared rows to shrink each
      section when it IS expanded: Elevation Range/Max Angle, Torch Chance/Height, Light
      Chance/Max Lights, Light Energy/Radius. No property was removed or renamed (same
      `scene.wfc_*` identifiers throughout), so no user-facing settings break; verified via
      `./run_blender_tests.sh` (full pipeline, ALL CHECKS PASSED) since `register()` runs through
      the same scene-property block either way.
- [x] **"Round" rooms didn't read as round.** User feedback after opening the regenerated
      `test_02.blend` (Room Shape = ROUND): "there are no round rooms." `_carve_room`'s ellipse
      test was mathematically correct (`((xi-cx)/rx)**2 + ((yi-cy)/ry)**2 <= 1.0`, the exact
      inscribed circle) but at the room sizes this generator actually produces (roughly 3-6
      tiles), an exactly-inscribed circle only ever clips the 4 single extreme-corner tiles no
      matter how big the room gets within that range -- confirmed via `stub_bpy`: all 12 rooms in
      a seed-424242 ROUND-mode generation carved exactly 4 tiles regardless of room size (a 6x5
      room carved the same 4 tiles as a 3x5 one), and at the minimum supported size (3x3) the
      exact circle carves *zero* tiles (every corner cell's distance ratio is ~0.94, under the
      1.0 threshold) -- a "round" 3x3 room was pixel-identical to a rect one. Both are invisible
      or near-invisible at a glance, especially with straight tile-grid walls following the cut.
      Fixed by tightening the membership threshold from `<= 1.0` to `<= 0.8` -- not a truer
      circle, a deliberately smaller one, so the tile-grid approximation actually carves a
      visible notch at every supported size: a minimum 3x3 room now carves into a plus/diamond
      (5/9 tiles), scaling up to a proper stepped octagon by 6x6 (24/36). Verified the new shapes
      are fully connected and symmetric at all room-size combinations 3x3 through 6x6 (plus
      non-square cases like 6x3, 3x4) by hand-rendering the cut pattern as ASCII grids. Re-ran the
      full `run_blender_tests.sh` suite (MIXED-room scenario, so ROUND rooms are exercised) and a
      150-trial `stub_bpy` stress regression (`e2e_stress.py`, wall/door vertex-count assertions)
      after the change -- both clean, 0 mismatches.
- [x] **New: "Debug: Last Generation Params" panel section + Copy Parameters button.** User
      request: a way to grab the exact settings behind a specific generated level to paste into a
      bug report, rather than re-describing slider positions from memory. `_update_debug_snapshot`
      (new) runs at the end of every Step operator (Blueprint/Walls/Stairs/Doors/Props, all five,
      since a bug can hinge on a Props-only setting just as easily as a layout one) and writes
      every current `wfc_*` scene property into a new `wfc_debug_params` StringProperty, formatted
      as a `dict(wfc_foo=..., ...)` literal -- deliberately the same override-dict style already
      used by `tests/generate_test_blends.py`'s `SCENARIOS` list, so a pasted snapshot is directly
      reusable there too, not just human-readable. Property names are discovered from
      `scene.bl_rna.properties` rather than hardcoded, so the snapshot can never drift out of sync
      with `register()` as properties are added or removed. New collapsed-by-default GUI section
      (`LA_debug`, bottom of the panel) displays it as read-only label rows plus a
      `object.copy_level_architect_params` button that copies the full text (header comment
      included) to the OS clipboard via `window_manager.clipboard`. Verified via a real-Blender
      run: generated a Blueprint + Walls with non-default settings, dumped `wfc_debug_params`,
      confirmed valid, sorted, correctly-typed Python syntax (bools/ints/floats/quoted
      enum-strings/color tuple) and the right captured step label.
- [x] **New: Room Shape = CAVE -- whole-floor organic cave generation.** User provided a
      hand-built reference file (`REQUEST_SAMPLE.blend`, not committed) with two floors sculpted
      by hand; analyzed it headlessly (bucketed polygon centers into a 2.03m tile grid, matching
      `wfc_tile_size`) rather than guessing from a description. Findings: one floor was 113 floor
      tiles with **zero** wall tiles, one connected meandering shape spanning nearly the whole
      map -- not discrete rooms, a single organic network. That reframed this from "a new room
      shape" to "a new floor-generation mode": one sprawling connected region replacing the
      room-scatter + MST-corridor solver entirely for a floor, confirmed with the user via
      `AskUserQuestion` (whole-floor mode vs. a smaller per-room shape option; the user picked
      whole-floor, but asked that some chambers still get doors "like the STAIRS looks like a
      corridor" -- i.e. Corridor Stairs pairs with this).

      Implementation reuses the existing data model completely rather than adding a parallel one:
      `_carve_cave_floors` (new) replaces `_scatter_rooms` when `room_shape == 'CAVE'`
      (`_connect_rooms_per_level`'s MST pass early-returns for Cave too, since chambers are
      already connected by construction). A handful of "drunkard's walks"
      (`_carve_cave_tunnel`, new) wander the grid carving 1-tile tunnel (`room_id -1`, identical
      to an ordinary corridor cell); every walk after the first starts from an already-placed
      chamber, so the network is connected by construction. Each walk ends by carving a round
      chamber -- reusing `_carve_room`'s ROUND ellipse verbatim -- which gets a real `room_id`,
      exactly like a scattered room. That single choice is what makes walls/doors/stairs/
      entrance-exit/elevation all keep working completely unmodified: a door appears wherever a
      chamber meets a tunnel (`room_id` differs either side), never between two tunnel cells,
      the exact same rule that already governs a normal room/corridor boundary. Chamber count
      reuses `_rooms_per_level`'s existing per-floor distribution and chamber size reuses
      Room Size Min/Max, so the feature needed zero new user-facing settings -- just a 4th
      `wfc_room_shape` enum value.

      Three real bugs surfaced by this feature, all found the same way as the stair-orientation
      bug earlier in this doc -- a full BFS reachability check (every `WALKABLE` cell on a floor,
      not just start-to-end), not a geometry/overlap check, since all three produced perfectly
      valid, non-crashing meshes with just an unreachable pocket:
      1. **Trapped walker.** The walk's own movement bound originally used the NEXT chamber's
         margin (so it would never need reclamping) -- but the walk's start point only satisfies
         some EARLIER, usually smaller chamber's margin; if that start already sits inside the
         new, bigger excluded zone near a map edge, every step toward the interior fails the very
         check meant to let it out, permanently trapping the walk. A trapped walk's "endpoint"
         (still the unchanged start) could be far enough outside the new chamber's bounds that
         `_carve_room`'s box literally went negative (`y=-2`), which Python's negative-index
         wraparound silently turned into phantom floor cells at the wrong end of the grid instead
         of erroring. Fixed by reverting the walk's own bound to a fixed 1-tile margin (matching
         every other grid walk in this file) and clamping the CHAMBER placement afterward instead,
         with a short corridor bridging the clamp shift when one actually occurs.
      2. **Entrance/exit corners unreachable from the network.** The fixed corners `_wire_
         entrance_and_exit` always uses ((1,1) and (w-2,l-2), same for every room_shape) are
         routinely nowhere near a purely-random walk network that only covers a fraction of the
         map. `_ensure_connectivity`'s existing last-resort repair still guarantees a path (that's
         its whole job), but for Cave specifically that repair is one dead-straight corridor
         spanning most of the empty map -- geometrically fine, but exactly the un-organic look
         this feature exists to avoid, and it showed up on nearly every test render. Fixed with
         two targeted anchors instead of leaving it to chance: chamber 0 starts AT the entrance
         directly (free -- nothing to bridge from yet), and the last chamber of the exit's floor
         reaches the exit via a target-biased walk (see next point) rather than a plain random one.
      3. **The anchored exit still looked like a straight line.** The first fix for #2 forced the
         last chamber's center directly onto the exit corner and bridged the gap with
         `_carve_corridor` (a straight L-shape) -- correctness was fine, but visually
         indistinguishable from the bug it was fixing (confirmed by rendering it: still one long
         diagonal highway). Replaced with a target-biased variant of the same walk
         (`_carve_cave_tunnel(..., target=(ex, ey))`): direction has a 60% pull toward whichever
         axis closes the most distance to the target rather than continuing straight, and the
         step budget is sized off the real Manhattan distance plus slack -- reads as a winding
         tunnel that happens to reach the corner, confirmed by re-rendering (a jagged
         diagonal staircase path, not a straight line). Starts from whichever existing chamber is
         actually closest to the exit (not a random one), keeping the biased distance as short as
         the network's own layout allows.

      Verified with a 300-trial `stub_bpy` full-BFS-reachability regression (0 disconnected
      floor-instances) and a new permanent check in `tests/blender_headless_test.py` (20 seeded
      trials solver-only, plus one real end-to-end Blueprint/Walls/Stairs/Doors pass through
      actual Blender) -- both added specifically because this bug class doesn't show up in any
      other existing check. Visually verified against the reference file by rendering the actual
      generated output (orthographic top-down + isometric, real Blender) and comparing side by
      side: winding 1-tile tunnels between round chambers, walls tracing the irregular boundary,
      doors at chamber openings -- matches the reference's character. Known limitations, left as
      documented trade-offs rather than blocking scope creep: ignores `sub_levels_per_floor`/
      `split_level_chance` (every cave floor sits at its logical floor's base slice); a single-
      chamber floor that's simultaneously the entrance and exit floor only gets the entrance
      anchored (degenerate edge case); a rare (~1.7% of floor-instances in the 300-trial stress
      run) single stray unreachable tile from `_carve_room`'s ROUND ellipse at extreme aspect
      ratios, pre-existing and equally present in ordinary ROUND rooms, just never visible there.
      Currently global (every floor becomes Cave, not assignable per floor) -- ties directly into
      the not-yet-started "Per-floor variation profiles" idea below, which is the natural next
      step once per-floor overrides exist.
- [x] **Cave + Corridor Stairs: stairwells missing a wall on one side.** User feedback after
      opening a generated Cave level: "few stairs on lower floor are not good, wrong orientation
      and unaccesable, not enough space around them to walk." Investigated with a new check
      (perpendicular-neighbor walkability per stair cell) that nothing existing tested for --
      confirmed 48% of stair cells across a 40-trial stress run had a WALKABLE cell on their
      perpendicular side, meaning the wall that's supposed to enclose a 1-wide Corridor Stairs run
      (no side walkway, by design) was simply missing. Root cause: `_find_stair_footprint`'s
      `margin=0` for Corridor Stairs was uniform in all directions -- correct for the two
      TRAVEL-axis ends (that's deliberately where a corridor is meant to attach flush), wrong for
      the PERPENDICULAR sides (which must stay clear, there's no walkway to absorb an adjacent
      cell there). Rare on RECT/ROUND floors (corridors are sparse, so a stairwell's nearby empty
      space is unlikely to already border one) but routine on Cave floors, where chambers are
      densely surrounded by their own tunnels. Two-part fix:
      1. **Placement time**: new `_corridor_stair_fits` replaces the plain uniform-margin
         `_room_fits` for Corridor Stairs specifically -- keeps margin=0 at the travel-axis ends,
         adds a real clearance requirement on the perpendicular sides.
      2. **After placement**: new `_would_expose_stair_side` guards the one remaining source --
         the organic connector (`_connect_room_to_point`'s Cave-mode target-biased walk, added
         alongside this same Cave feature) wandering close enough to graze an existing stair's
         side after the fact. Applied inside `_carve_cave_tunnel`'s own movement check (safe: it
         already retries a different direction on rejection, so guarding it can't break
         connectivity) -- deliberately NOT applied inside `_carve_corridor` (tried first, then
         reverted: a straight line has no alternate routing, so skipping one cell there left a
         real hole in what's supposed to be an unbroken corridor -- confirmed as a regression by
         the connectivity stress test immediately catching it, 0 -> up to 29 disconnected
         floor-instances out of 300). A first version of the walk-side fix also nearly-eliminated
         the bug (2/363 cells, down from 175/363) by additionally letting the walk stop the
         instant a targeted walk arrives instead of burning its whole (deliberately generous)
         step budget wandering right around the thing it just reached -- but that version turned
         out to be measuring against a mixed corridor/room-stairs sample without filtering, which
         had separately made the fix look far weaker than it is (see next point).
      3. **Test-methodology bug found in the process of writing the regression check itself**:
         the first version of both the ad-hoc stress script and the permanent check counted a
         ROOM-based stairwell's real walkway (a WALKABLE perpendicular neighbor, correct and
         expected there -- only Corridor Stairs has no walkway) as "exposed," inflating the
         measured rate back up to ~48% and briefly making the fix look like it hadn't worked at
         all. Filtering to `solver.corridor_stairs` runs only, the true rate is ~7-10% (down from
         the real 48% baseline) -- the residual is two independently-placed stairwells
         occasionally landing adjacent to each other (each one's own fits-check only validates
         against what existed at ITS OWN placement time), an accepted rare tradeoff rather than a
         further-chased bug, consistent with "most practical way." Added as a permanent regression
         check (`tests/blender_headless_test.py`, 20 seeded trials, asserts the rate stays well
         below the 48% pre-fix baseline rather than requiring exactly 0%, so it catches a real
         regression without being flaky over the accepted residual) alongside the existing Cave
         connectivity check.
- [x] **Major: "Color Rooms/Corridors" (and "Add Ceiling") silently never took effect on a fresh
      generation, regardless of the addon's own default.** Found while building a showcase render
      for the README, not from a user report — the render came out flat grey with zero per-room
      color variation. Traced through the material node graph, the per-face `material_index`
      output, and finally the live GN modifier's own per-input storage
      (`mod.properties.inputs.Socket_3.value`), which read **False** even though
      `wfc_color_rooms` defaults to **True** and the node group's own interface item correctly
      showed `default_value = True`. Root cause: `create_geometry_nodes_modifier` assigned
      `mod.node_group = node_group` immediately after creating the node group but **before** any
      of its Bool/Float interface sockets (Isometric Mode, Color Rooms/Corridors, Floor Thickness,
      Add Ceiling, Ceiling Thickness) existed. Blender initializes a modifier's own per-input
      override at the moment each interface socket is added to a node group already assigned to
      that modifier — using the socket type's built-in zero value (`False` / `0.0`), not whatever
      `.default_value` a later line of Python sets on the interface. That later write only updates
      the node group's own stored default (relevant for a *different*, future modifier instance);
      it never reaches back and re-syncs this already-linked modifier. Every property whose
      intended default matched the type's zero value (Isometric Mode = False, Floor Thickness =
      0.0 in the common case) was unaffected and never exposed the bug; the two that default to
      something else — **Color Rooms/Corridors = True**, **Add Ceiling** when a user turns it on
      before ever regenerating — silently did nothing on the very first generation. A user could
      only get the intended behavior by manually re-toggling the corresponding checkbox in
      Blender's own Modifier Properties tab after the fact (the addon's sidebar checkbox looks
      like it controls this but, on a fresh generation, never actually reaches the modifier) —
      which is very likely why this went unnoticed through the whole Cave/stairs investigation
      earlier: `tests/blender_headless_test.py`'s Ceiling check already worked around this exact
      bug by construction, calling `set_input(gn_mod, "Add Ceiling", True)` to flip it live
      *after* generation, rather than relying on the generation-time default — which happened to
      test the toggle mechanism but never the default-value path this bug actually broke.
      Fixed by deferring `mod.node_group = node_group` to the very end of the function, once every
      interface socket (and its real default) already exists — the modifier's own per-input
      storage then initializes from the correct values from the start, for every current and
      future GN input, not just these two. Verified directly: read
      `mod.properties.inputs.Socket_3.value` before/after (False → True) and the evaluated mesh's
      `material_index` histogram before/after (only floor-level/entrance/exit indices ever
      appeared before the fix, zero room-pool indices out of 2,070 room-floor faces in one repro
      case; genuine room-pool indices covering all 17 rooms afterward). Re-ran the full
      `run_blender_tests.sh` suite (unchanged, all pass — nothing in it happened to probe this
      path) and added a permanent regression check that does: reads the modifier's own Color
      Rooms/Corridors input value directly (not just the interface default) and confirms at least
      one generated face actually lands on a room-pool material index, not just floor-level ones.
- [x] **"Separate by Floor" -> "Separate by Floor/Room".** User idea: organize the blueprint mesh
      into per-room objects (plus one combined corridor object per floor) inside a real collection
      tree, instead of one flat mesh per floor loose in the scene collection. Scoped down from a
      broader ask (also splitting Walls/Doors/Stairs/Props the same way, and giving every
      individual corridor *segment* its own object) to just the blueprint floor mesh, with
      corridors staying one combined object per floor — corridors have no existing per-connection
      identity (`room_id == -1` uniformly for every corridor cell on a floor), so splitting them
      further would need new bookkeeping during generation, not just a splitting pass afterward;
      left as a possible future step, not attempted here.
      Reused the exact technique `OBJECT_OT_SeparateLevelByFloor` already used for
      `logical_floor` (`_read_polygon_values`, which transparently handles a baked attribute
      landing on either the POINT or FACE domain after Geometry Nodes' Instance-on-Points ->
      Realize-Instances, depending on Blender version) — `room_id` is baked exactly the same way,
      so no new attribute plumbing was needed, only a second `_read_polygon_values` call and a
      nested floor -> room_id -> [face indices] bucketing instead of a flat floor -> [face indices]
      one. Extracted the shared vertex-dedup/material-index-copy logic (previously inlined once)
      into `_mesh_from_faces`, since building one object per room now calls it many times per run
      instead of once per floor. New `BLUEPRINT_SPLIT_COLLECTION_NAME` collection tree
      (`Procedural Level Blueprint (Split) > Floor N > Rooms` / `> Corridors`), built lazily with
      the existing `_get_or_create_collection` helper (same one Props already uses for its
      Torches/Lights/Decoration sub-collections) — a floor's Rooms or Corridors sub-collection is
      only created if that floor actually has faces for it, so an all-corridor or all-room floor
      (edge case, but possible) doesn't leave an empty collection behind. Entrance/exit cells
      carry `room_id == -1` same as ordinary corridor cells, so they fall into the same per-floor
      Corridors object rather than getting their own one-tile object — reasonable, not a design
      the user asked to change.
      The old bail-out ("only one floor found, nothing to separate") no longer made sense once a
      *single*-floor level also benefits from per-room splitting, so it was replaced with a total
      room+corridor bucket count check instead. Verified end to end through
      `tests/blender_headless_test.py` against the real 3-floor MIXED scenario: 52 objects created
      (rooms + 1 corridor object per floor, across all 3 floors), every floor index 0-2 present,
      the collection tree exists with exactly one sub-collection per floor, and every floor's
      collection has both a Rooms and a Corridors child.
- [x] **"Separate by Floor/Room" still showed flat, un-colored rooms after applying the modifier
      first.** User feedback, one message after the feature above shipped: "Per-room coloring was
      still bit buggy, because we applied geo modifier and all floor tiles were same object."
      Reproduced directly rather than guessing: generated a Blueprint, read the material_index
      histogram off the live evaluated geometry (correct, matches the earlier Color Rooms/Corridors
      fix), then ran the exact documented precondition -- `bpy.ops.object.convert(target='MESH')`,
      i.e. Blender's own "Object > Apply > Visual Geometry to Mesh" -- and read the histogram again.
      Every face's `material_index` survived byte-for-byte, but `len(obj.data.materials)` collapsed
      from 33 down to 1. Root cause: this addon's GN material system only ever writes a numeric
      `material_index` via Set Material Index -- it never attaches real material references to the
      geometry itself (no Material-typed GN socket is used anywhere here), so the actual palette of
      materials lives entirely on the *object's* pre-existing material slot list, not in anything
      the modifier's output geometry carries. Blender's Convert-to-Mesh/Apply Modifier replaces the
      object's mesh datablock with the evaluated geometry, which has no slot list of its own to
      inherit, and Blender doesn't reconstruct one from what the object used to have -- so the
      previous 33-material palette silently disappears the moment a user does exactly what the
      README told them to do, and every face resolves to whatever grey default fills an empty slot.
      This is the same root mechanism as the Color Rooms/Corridors bug fixed earlier in this same
      session, one layer further down the pipeline: that fix made material_index correct at
      generation time; this one made it survive the very next step a user was told to take.
      Fixed by having `OBJECT_OT_SeparateLevelByFloor` do its own depsgraph evaluation
      (`obj.evaluated_get(depsgraph).to_mesh()`) instead of requiring a pre-applied mesh, and
      explicitly re-attaching the ORIGINAL object's material list to the evaluated mesh before
      reading anything off it -- removing the manual "apply the modifier first" step from the
      workflow entirely (it's no longer just unnecessary, it was actively the bug), while also
      fixing the underlying cause. Cleanup was adjusted to match: the temporary evaluated mesh is
      freed with `to_mesh_clear()` (not `bpy.data.meshes.remove()`), and the original object's real
      source mesh + its GN modifier's node group are freed only once orphaned by removing the
      object, mirroring the same old-node-group cleanup pattern `create_geometry_nodes_modifier`
      already uses elsewhere. Verified via `tests/blender_headless_test.py`: removed the now-wrong
      pre-apply step from the test itself, and added a direct regression check that every split
      room/corridor object kept a >1-entry material slot list and that a real face resolves to an
      actually-named `LA_Room_*`/`LA_Floor_Level_*` material rather than a default.
- [x] **Major: `room_id`/`level_z` were silently corrupted at room/corridor boundaries by Merge
      By Distance -- the actual root cause behind "one room made from smaller room pieces."** User
      feedback, casual aside after the fix above shipped: "when we separate rooms and flatten all,
      we get one room made from smaller rooms pieces." Chased it hands-on with the user's own
      "it is square" clarification pointing at a real, narrower cause first (ROUND's ellipse
      carving can leave a lone stray tile at extreme aspect ratios -- fixed on its own merits, see
      `_largest_connected_group` below), but a stress check revealed something far bigger once
      Separate by Floor/Room ran against a real scenario: 28 of 39 rooms on one level showed up as
      "fragmented," most into scattered pieces flung across the ENTIRE MAP, nothing like a stray
      corner tile. Cross-checked against the SOLVER's own ground-truth `room_id` grid directly
      (bypassing the mesh/GN pipeline entirely) -- the solver's data was completely clean, one
      tight contiguous blob per room, no collisions. The corruption was downstream, in the mesh:
      **484 of 1,402 faces (35%) had inconsistent `room_id` values across their own 4 corner
      vertices** -- one single quad face read `[9, 6, 4, 9]`, three different rooms' worth of
      corner data on what should be one room's own floor tile.
      Root cause: `room_id`/`level_z` are POINT-domain attributes, broadcast uniformly across a
      tile's own cube instance by Instance on Points -- fine on their own, but `GeometryNode
      MergeByDistance` (used to weld the seams between adjacent tile primitives) welds a shared
      corner between TWO DIFFERENT tiles' cubes -- e.g. a room and its neighboring corridor, or
      two adjacent rooms -- into ONE vertex. For a non-blendable INT attribute, Blender keeps only
      ONE of the colliding source values at that merged vertex, effectively arbitrarily. Any code
      reading room_id/level_z per-vertex AFTER that point -- both the Color Rooms/Corridors
      material switch (fixed earlier this session for a DIFFERENT bug, the modifier-input-default
      issue, but never audited for THIS one) and Separate by Floor/Room's Python-side per-face
      read -- could silently pick up a face's NEIGHBOR's value instead of its own. This means the
      Color Rooms/Corridors fix earlier in this session was real and correct, but incomplete: some
      boundary faces were very likely still getting the wrong room's color, just never measured
      directly until this investigation built a check precise enough to catch it (this class of
      bug produces no crash, no missing geometry, nothing `tests/blender_headless_test.py`'s
      existing checks were built to notice -- only "does the DATA make internal sense" catches it).
      Fixed at the actual source, not by working around it downstream: `room_id`, `logical_floor`,
      and `level_z` are now snapshotted to genuine FACE domain (`GeometryNodeStoreNamedAttribute`)
      immediately after the floor+ceiling geometry is joined, BEFORE `GeometryNodeMergeByDistance`
      ever runs -- at that point every face still only has ITS OWN tile's point broadcast across
      its corners, so the snapshot is unambiguous by construction, and merging afterward can't
      touch face-domain data the same way. Every existing downstream reader (the material switch,
      Python's `_read_polygon_values`, which already preferred a FACE-domain branch when present)
      picks up the protected value automatically -- nothing else needed to change. Verified
      directly: the same stress scenario went from 39 distinct rooms / 28 fragmented (many
      scattered, multi-piece) to 23 distinct rooms / 12 fragmented (every single one now exactly
      the small, 2-piece stairwell-landing pattern below) -- 23 matches `len(solver.rooms)` for
      that exact seed/config precisely, confirming the room COUNT itself was being inflated by
      this bug too, not just individual rooms' shapes.
  - [x] **Round rooms: a real, narrower bug found on the way to the above.** `_carve_room`'s
        ellipse threshold can leave a lone corner tile disconnected from the main shape at extreme
        aspect ratios -- confirmed the stray piece is always exactly one tile, never larger. Fixed
        by keeping only the largest 4-connected group of carved cells (`_largest_connected_group`,
        new) -- a room is now one contiguous blob by construction, the rare stray tile is dropped
        rather than kept as a disconnected "part of the room" no player could ever read as
        connected to anything.
  - [x] **Stairwell landing pairs: confirmed legitimate, not a bug -- rerouted to Corridors per
        user request.** A room-based stairwell's buffer tile before the first step and the one
        after the last step share one room_id, but the stair itself (built separately in Step 3,
        a different tile_id) runs between them -- so the two landings genuinely share no vertex
        with each other, unlike the ROUND case above. User confirmed wanting these treated as
        corridor-like rather than kept as a visibly two-piece "Room" object; `OBJECT_OT_
        SeparateLevelByFloor` now detects any room_id whose faces aren't one topologically
        connected group (`_face_connected_components`, new) and folds it into that floor's shared
        Corridors bucket instead.
  - [x] **Ceilings double-counted as "fragmentation" once Add Ceiling is on -- caught by the
        reroute logic immediately above being too broad, before it shipped.** Add Ceiling
        instances a second cube per point, flush with the floor of the point directly above --
        every room's ceiling patch shares that room's room_id but sits a full `level_height` above
        its floor patch with zero shared geometry, which the reroute-to-Corridors logic couldn't
        tell apart from a genuine stairwell landing pair, sweeping essentially every room on a
        floor into Corridors and defeating the whole point of splitting by room. Confirmed with
        the user this needed its own bucket rather than either prior option. Fixed with a Z-band
        check (reusing the same "local Z within a level" idea Isometric Mode's own culling already
        uses) that pulls ceiling faces (room_id >= 0 only -- a corridor's own ceiling stays bundled
        into its single combined Corridors object, never meant to read as one cohesive shape
        anyway) into their own per-floor Ceilings bucket BEFORE the room/corridor split and its
        fragmentation check ever run, so Rooms only ever sees actual floor tiles again.
      Verified end to end with a 25-trial real-Blender stress run (varied room shape, corridor
      stairs, sub-levels, split-level chance, elevation, and Add Ceiling on/off, generation +
      Separate by Floor/Room + fragmentation/material-slot checks every trial): 0 bad trials.
      Added matching permanent checks to `tests/blender_headless_test.py` (which already has Add
      Ceiling on in its scenario): Ceilings objects are produced, room objects aren't swept away by
      the ceiling case, and every floor's collection now has Rooms + Corridors + Ceilings.
- [x] **Major: Floor Thickness = 0.0 made every single floor face wind backwards.** User feedback,
      with the exact repro settings pasted from the Debug Params panel: "we applied modifier and
      split floor blueprint, then opened Procedural Level Blueprint (Split) and did flip normals,
      because backface culling is on, then from top view floors were transparent." The pasted
      params had `wfc_floor_thickness=0.0` -- a case none of this session's earlier normals
      verification had actually tried (everything up to this point used the nonzero default).
      Reproduced exactly, then measured directly rather than guessing: at Floor Thickness 0.0,
      **all 684 of 684 floor faces in the repro level pointed -Z, zero pointed +Z**. Root cause was
      exactly what an existing code comment already predicted, just not verified: "at 0.0 it's a
      flat plane (with Merge Distance cleaning up the resulting coincident top/bottom faces)" --
      at floor_thickness=0 the floor cube's top and bottom faces become fully coincident, Merge By
      Distance welds every one of their vertices together, and Blender's own cleanup of the
      resulting fully-overlapping duplicate faces silently keeps only ONE of the two -- confirmed
      to consistently be the downward-facing one, never the upward one. That renders completely
      normally with backface culling off (Blender's default, and every render/screenshot taken
      this whole project), but reads as fully transparent from directly above with it on, exactly
      matching the report. Fixed by clamping the floor cube's actual thickness (and applied the
      identical fix to the ceiling cube, same latent risk, just never hit since Add Ceiling was
      off in the reported scenario) to stay at least 3x the live Merge Distance value, so top and
      bottom can never truly coincide regardless of how thin Floor/Ceiling Thickness or how
      generous Merge Distance are set, while remaining visually flat at any normal viewing
      distance (a few centimeters at most, against meter-scale tiles). Verified directly: the same
      684-face repro level now shows exactly 684 up + 684 down -- both faces surviving per tile,
      matching the already-independently-verified nonzero-thickness case. Added a permanent
      regression check to `tests/blender_headless_test.py` (temporarily sets Floor Thickness to
      0.0, confirms equal up/down face counts, restores the scenario's normal thickness
      afterward) so this can't silently return.
- [x] **New: Wall Height / Level Height / Sub-Levels per Floor now stay mutually consistent.**
      User feedback: "if we change sublevels in rooms, heights of walls, vertical distance from
      floor must be connected, because when walls are generated they [are] visible on upper
      floor." Real gap, not a misunderstanding -- a wall's actual available headroom before it
      pokes into whatever sits directly above is `level_height / sub_levels_per_floor` (see
      `_fine_level_height`), but `Wall Height` was a totally independent number with zero
      awareness of that, so raising Sub-Levels per Floor (which shrinks the per-slice headroom)
      or Wall Height (which needs more of it) with no cross-check let walls clip straight through
      the floor above.
      First proposed a generation-time clamp (cap the actually-built wall height to fit, silently,
      per the earlier Floor Thickness fix's pattern); user pushed back with a better idea instead:
      "why not if we change one height, others make adjustments" -- i.e. keep the properties
      themselves mutually consistent in the UI, rather than silently shrinking whatever the user
      asked for behind the scenes. Implemented via `update=` callbacks on all three properties
      (`_update_wall_height`, `_update_sub_levels_per_floor`, `_update_level_height`, all routed
      through one `_sync_level_geometry` so the invariant lives in exactly one place): whichever
      property the user just changed is treated as their real intent and left alone; Level Height
      is preferred to grow (up to its own max=20.0) to make room, and Wall Height only ever
      shrinks as a last resort if even Level Height's max can't fit it. A module-level reentrancy
      guard (`_adjusting_level_geometry`) stops the three callbacks from ping-ponging off each
      other, since setting one property from inside another's callback still fires that property's
      own callback under Blender's RNA system.
      Verified directly, three cases: raising Sub-Levels per Floor 1->2 grew Level Height 4.0->8.0
      and left Wall Height untouched at 4.0 (fine_level_height now exactly 4.0, matching); directly
      shrinking Level Height to 3.0 afterward correctly shrank Wall Height 4.0->1.5 to fit instead
      (Level Height is what the user just touched, so it's Wall Height's turn to give way); and the
      extreme edge case (Wall Height requested at 30 with Sub-Levels=4, needing Level Height=120,
      far past its own max=20) correctly fell back to capping Wall Height too (down to 5.0) rather
      than leaving the invariant violated. Added a permanent regression check to
      `tests/blender_headless_test.py` covering the first two cases against the real scenario's own
      values, then restores its baseline before Step 1 runs.
  - [x] **Door Height folded into the same sync -- identical bug, spotted by the user immediately
        after the wall fix.** "there are doors, ok default is 2.2m and if we choose to make floor
        height 1m??" -- `wfc_door_height` (default 2.2) had exactly the same gap as Wall Height:
        totally independent of Level Height / Sub-Levels, so a door frame's lintel could clip
        through the floor above the same way a wall could. `_sync_level_geometry` generalized from
        one height to `max(wall_height, door_height)` throughout, with a fourth `update=` callback
        (`_update_door_height`) added alongside the existing three. Verified with the user's exact
        numbers: Level Height dropped to 1.0 correctly shrank both Wall Height and Door Height to
        1.0 each, invariant held for both simultaneously. Existing regression check extended to
        assert both heights, not just Wall Height.
- [x] **`tests/stub_bpy.py` committed** — see the now-checked §3 entry.
- [x] **Style mode gained real per-floor/per-room coloring**, matching what Simple Viewport
      Colors already had. Previously a flat 2-slot system (`get_or_create_style_material`, one
      corridor look + one uniform "room" tint, `room_variant=True`) — every corridor on every
      floor was the exact same material, and so was every room regardless of which one. Fixed by
      generalizing the existing `tint` mechanism (`_finish_material`'s literal RGBA multiply,
      already used for the single flat room variant) into three new functions that mirror Simple
      mode's own material-building functions almost exactly:
      `get_or_create_style_floor_level_materials` (one tinted variant per `FLOOR_RAMP_HEX` ramp
      position, cached/reused across generations like Simple mode's floor materials),
      `get_or_create_style_room_materials` (one tinted variant per actual room, freshly created
      and shuffled each generation via the same orphaned-material-purge pattern
      `create_simple_room_materials` uses, not name-reuse), and `get_or_create_style_entrance_
      material`/`get_or_create_style_exit_material`. The Blueprint operator's Style-mode branch now
      builds the exact same `floor_level_materials + room_materials + [entrance, exit]` list shape
      Simple mode does and passes it through the identical `floor_level_count` plumbing — no
      changes needed to the GN graph's material-index switch at all, since it was already generic
      over slot count. `room_variant`/`ROOM_TINT` (now unused, only ever called with
      `room_variant=True` from the code path just replaced) deleted rather than left dead; Walls
      and Stairs keep calling the now-simplified single-argument `get_or_create_style_material`
      unchanged, since neither mode gives walls/stairs per-room coloring (matches Simple mode's
      own `LA_Simple_Wall`/`LA_Simple_Stair` — one flat material each, by design, not part of this
      fix's scope).
      Verified directly (Dungeon style, MIXED shape, 2 floors, 8 rooms): 24 material slots created
      (8 floor-level + 14 room + entrance + exit), and the evaluated mesh's material_index
      histogram showed real, nonzero face counts on ALL 14 room-pool indices plus both floor
      levels plus entrance and exit -- nothing collapsed onto one shared slot the way the old
      2-slot system did. Stress-tested 15 trials across all three style keys (Dungeon/Cave/Open
      Area), varied room shape, height, and Add Ceiling: 0 bad trials. Added permanent checks to
      `tests/blender_headless_test.py` (which had never exercised Style mode — Simple Viewport
      Colors was the only path any existing check ran) confirming more than one floor-level index
      and more than one room-pool index are actually used, and that a room face resolves to a
      real per-room `*_Room_NNNN` material rather than any shared default.
- [x] **GUI reorganized into tabs.** User feedback: "izs a lot of dropdowns, maybe tabs??" — the
      panel had grown to 8 collapsible `_section()` boxes stacked in one long scroll (Map & Seed,
      Rooms, Scale & Style, then one settings section per generation step, then Debug). Added a
      `wfc_active_tab` EnumProperty (SETUP/WALLS/STAIRS/DOORS/PROPS) drawn as an icon-only expanded
      button row (`layout.row(align=True).prop(scene, "wfc_active_tab", expand=True, icon_only=
      True)` — the standard Blender idiom for faking tabs inside a single Panel, since the API has
      no native tab widget within one panel) at the very top of the panel; `draw()` now dispatches
      to one of five new `_draw_setup_tab`/`_draw_walls_tab`/`_draw_stairs_tab`/`_draw_doors_tab`/
      `_draw_props_tab` methods based on the active tab, each ending in that step's own Generate
      button (and Setup's also has the Separate by Floor/Room utility button) so the button most
      relevant to whatever's currently open is never more than one scroll away.
      Setup keeps its three `_section()` sub-groups (Map & Seed / Rooms / Scale & Style are still
      a lot of properties for one step) since it bundles what used to be 3 separate top-level
      sections; Walls/Stairs/Doors/Props dropped their `_section()` wrapper entirely, since each
      now has a whole tab already scoped to just its own ~4-8 properties, and Debug stays outside
      the tab system altogether (persistent, collapsed, at the very bottom, since it's about
      "whatever you just generated" and useful regardless of which tab happens to be open) rather
      than becoming a 6th tab.
      Every existing `scene.wfc_*` property reference, row/column grouping, and enabled-state
      condition was moved verbatim into its new tab method — behavior-preserving reorganization,
      no widget removed, renamed, or changed. Verified three ways, since headless Blender
      (`--background`) has no real UI region to actually render into: (1) `register()` succeeds
      with the new `wfc_active_tab` property with no exception; (2) the full real-Blender
      operator/generation test suite still passes unchanged (proves nothing about the actual
      generation pipeline was disturbed); (3) a duck-typed mock layout (`unittest.mock.MagicMock`,
      configured so `.row()`/`.column()`/`.box()` return fresh mocks and `.panel()` returns a
      `(header, body)` pair matching `_section()`'s real Blender 4.1+ contract) fed directly into
      `draw()` for all 5 tab values -- 0 exceptions, every property/operator reference resolved
      correctly. A real pixel screenshot (`bpy.ops.screen.screenshot` under Xvfb, both immediately
      and after several forced-redraw ticks) came back solid black both times -- a known category
      of headless-GL/Xvfb capture issue in this environment, not evidence of anything wrong with
      the panel itself; not chased further given the exhaustive draw-logic verification above
      already covers what a screenshot would have.
- [x] **`generate_test_blends.py`'s SCENARIOS expanded from 13 to 20** — hadn't been touched in
      a while, and this session added/fixed enough (Style mode per-room/floor coloring, the
      zero-thickness floor winding fix, Ceilings-bucket separation, Wall/Door/Level Height sync)
      that none of it had a scenario to actually look at. New ones: Style materials on Cave Rock
      and Open Area (test_12 already covered Dungeon), Floor Thickness 0.0, Cave + Add Ceiling
      together (the trickiest case for the Ceilings fix), Sub-Levels=3 with default heights (to
      visibly show Level Height auto-growing), a stress/showcase-scale map, and one scenario that
      also runs Separate by Floor/Room afterward so the saved file shows the actual split
      collection tree rather than one combined object (`_run_separate`, a new non-`wfc_*`
      scenario-runner directive `apply_settings` strips before calling `setattr`, handled by
      `run_pipeline` re-selecting the Blueprint object and calling the operator once Steps 1-5
      finish). Verified test_18 (Sub-Levels=3) directly: saved `wfc_level_height` is 7.5, exactly
      `wall_height (2.5) x sub_levels (3)`, confirming the sync actually ran and was captured.
      All 20 generated cleanly in one pass.
- [x] **New: a UV map, so Solid Shading's "Texture" color mode actually works.** User feedback
      after the Cave gallery file, once split by room: "only when random is chosen is there a
      color difference between rooms" -- confirmed via direct data inspection (material_index
      histogram, resolved material names, real per-room diffuse_color values) that the underlying
      color data was completely correct; the actual gap was in HOW Solid Shading's "Material"
      color mode was being compared against, once the user's own answer clarified they'd also
      tried "Texture" mode (their known-working manual pattern elsewhere: "in manual way we
      unwrap level to image representing the color, and in shading we turn on textures"). "Texture"
      is a genuinely separate, simpler display path from "Material" -- it samples an Image Texture
      node directly rather than reading a material's Viewport Display Color, and unlike EEVEE
      (which falls back to Generated coordinates when no UV map exists) it has no fallback at all,
      so it shows nothing useful without one. The addon never generated a UV map anywhere.
      Fixed with a `GeometryNodeStoreNamedAttribute` (domain='CORNER', data_type='FLOAT2', name
      "UVMap") in the GN graph, storing a flat constant `(0.5, 0.5)` for every corner -- every
      Simple Viewport Colors swatch (Room1-18/Floor1-8/Wall0/Stairs/Doors/Entrance/Exit .png) is a
      single flat color across the whole image, so the actual UV value genuinely doesn't matter
      for correctness, only that one exists at all. Placed in the same pre-merge spot as the
      room_id/logical_floor/level_z snapshots (no contamination risk here either way, since every
      corner gets the identical value regardless of which side of a weld it's on).
      Found and fixed two real bugs verifying this, neither of which the constant-value choice
      alone would have caught: (1) `mesh.uv_layers.active` reads **None** for a UV attribute baked
      by Geometry Nodes -- Blender never auto-flags it "active" the way a manually-created UV map
      would be -- so the first attempt at reading it back came up empty; fixed by indexing
      `uv_layers[0]` directly instead of relying on `.active`. (2) `_mesh_from_faces()` (used by
      every Separate by Floor/Room split) never carried UV data over at all -- `from_pydata()`
      doesn't preserve it -- so a split object, exactly what the user was actually looking at when
      they reported this, had no UV map regardless of the GN-graph fix; fixed by copying each
      face's loop UVs from the source mesh into the new one, keyed off the SAME per-face loop
      ordering `_mesh_from_faces` already relies on for material_index. Along the way, `_set_input`
      was only catching `KeyError`/`TypeError` around `default_value` assignment, not the
      `ValueError` a wrong-shape tuple raises (a plain 2-tuple where a FLOAT2 socket's Value input
      actually expects a 3-component Vector, Z ignored) -- would have crashed the whole operator
      instead of degrading gracefully like every other defensive wrapper in this file; added
      `ValueError` to the caught exceptions.
      Verified directly: the live evaluated mesh's UV loop count exactly matches its total loop
      count (full coverage, no gaps) at `(0.5, 0.5)` throughout; a split room object shows the
      same. Added permanent checks to `tests/blender_headless_test.py` for both the live Blueprint
      and Separate by Floor/Room's split objects.
  - [x] **Same gap, found immediately after, in every OTHER mesh the addon builds.** User: "i
        think it did not unwrap, and had no textures assigned" -- the fix above only ever touched
        the Blueprint's GN graph and `_mesh_from_faces` (Separate by Floor/Room's splitter).
        Walls/Doors/Stairs/Ramps/Torches/Decoration are each built by their own hand-rolled
        `add_box`-style Python mesh function, none of which go through the GN graph or
        `_mesh_from_faces` at all -- every one of them had exactly the same "no UV map, Texture
        color mode shows nothing" gap, just never touched by the first pass. New shared
        `_add_flat_uv_map(mesh)` (same flat `(0.5, 0.5)` constant, same reasoning -- every one of
        these materials' swatches is a single flat color too) called right after `mesh.update()`
        in all 6 builder functions. Verified directly: generated a full level (Blueprint, Walls,
        Ramp-style Stairs, Doors, Torches, Decoration) and confirmed full UV loop coverage on
        every one of the 5 baked-mesh object types. Added a permanent check to
        `tests/blender_headless_test.py` covering all of them in one pass.
  - [x] **The actual root cause, found right after: `mesh.materials.clear()` silently resets
        every polygon's material_index to 0.** User, after both UV fixes still didn't resolve it:
        "did try, but floors are still only distinct when in random." The UV work was real and
        necessary, but not the actual bug here -- this was always about material_index, not UV,
        and every earlier data-level check (material_index histograms, resolved material names,
        diffuse_color values) kept coming back correct, which is what made this genuinely hard to
        find: the data WAS correct right up until the exact moment `OBJECT_OT_SeparateLevelByFloor`
        rebuilt the evaluated mesh's material slot list.
        Chased it by finally getting real viewport screenshots working (`bpy.ops.render.opengl`
        under Xvfb, after `bpy.ops.screen.screenshot` kept coming back solid black -- a capture
        method difference, not a scene problem) and building up from a minimal reproduction: a
        hand-built 2-face mesh with the addon's own real materials displayed correctly distinct
        colors in Solid Shading every time, including at full room-count/material-count scale (100
        faces, 25 materials) -- ruling out material count, Image Texture nodes, and UV entirely.
        The one variable that mattered was rebuilding the SAME mesh coordinates via a fresh
        `from_pydata()` call vs using `to_mesh()`'s result directly: a full-blueprint rebuild via
        `from_pydata()` displayed correctly, but the ACTUAL split room objects (built through
        `_mesh_from_faces`, which already rebuilds via `from_pydata()` too) still didn't -- which
        narrowed it to something specific to the SOURCE mesh those splits read from, not the
        splitting logic itself. Traced it checkpoint by checkpoint through the operator's own code
        and found it immediately: reading `material_index` right after `OBJECT_OT_
        SeparateLevelByFloor`'s own `mesh.materials.clear()` + re-append (added in the 0.13.1 fix,
        to rebuild the evaluated mesh's material slot list) showed **every single polygon on the
        whole mesh reading material_index 0**, before any per-room splitting logic even ran.
        `.clear()` resets material_index as an undocumented side effect of emptying the slot list;
        re-appending the same materials afterward does not restore it -- that data is already gone.
        Every split room object then inherited material_index 0 uniformly (`LA_Floor_Level_0`), so
        "Material"/"Texture" viewport color modes showed every room identically, and only "Random"
        (which colors by object identity, not material) showed any difference at all -- exactly
        matching the report, across every message in this whole exchange.
        Fixed by saving each polygon's material_index into a plain list BEFORE touching
        `mesh.materials` at all, then restoring it onto the (now correctly repopulated) mesh
        afterward -- 4 lines, once the actual mechanism was understood.
        This also retroactively explains why the earlier "room object's face resolves to a real
        room-pool/floor material" regression check never caught it: it accepted `LA_Floor_Level_*`
        as a passing result for a ROOM object, not just `LA_Room_*` -- room_objs[0] resolving to
        slot 0 (a real, validly-named floor-level material) passed that check even though it was
        wrong. Tightened to require `LA_Room_*` specifically for a room object, and added a second,
        stronger check that compares TWO different rooms' resolved materials against each other --
        the actual shape of this bug (every room silently identical) is invisible to any check that
        only ever looks at one room in isolation.
        Verified directly: the exact reported scenario, re-screenshotted the same way, now shows
        every room a genuinely distinct color. Full suite green on 4.2.21 LTS and 5.2.0 LTS.
  - [x] **0.17.0: "viewport_color" Color Attribute -- an attribute-based alternative to material-
        slot coloring.** User's follow-up, after the 0.16.3 fix: "could attributes be good
        alternative to color rooms?? because uv-s are not unwraped, textures not connected, maybe
        if in room attributes could be viewport color/texture?? it only shows when random is
        chosen." Correct instinct -- Solid Shading's "Attribute" color mode (Python enum `VERTEX`
        on `space.shading.color_type`, label "Attribute" in the UI) reads a mesh's active Color
        Attribute directly, with **no dependency on UV data, material slots, or material_index at
        all** -- sidesteps every failure mode both UV fixes and the material_index fix above were
        chasing, in one step.
        New shared helper `_add_viewport_color_attribute(mesh)`: fills a `FLOAT_COLOR`/`CORNER`
        Color Attribute named "viewport_color" from each polygon's already-resolved material's
        `diffuse_color` (per-face, so it's correct even for multi-material meshes like Torches),
        and marks it active via `mesh.color_attributes.active_color_index`. Wired into
        `_mesh_from_faces` (so every Separate by Floor/Room room/corridor/ceiling object gets one
        automatically) and into all 6 baked-mesh call sites (Walls x2, Stairs, Doors x2, Torches,
        Decoration), right after each one's `.materials.append(...)` call -- same scope as the
        0.16.2 UV fix, same reasoning for why every baked-mesh type needed it, not just the
        Blueprint mesh.
        One real gap this surfaced: style materials (`create_dungeon_material`/`create_cave_
        material`/`create_open_area_material`) never set `diffuse_color` at all -- their look
        comes purely from the node tree, so every style room/floor material read as the same
        default gray to anything (Solid Shading's "Material" mode too, not just this new
        attribute) that reads `diffuse_color` directly. Fixed at the source: `_finish_material`
        now also sets `mat.diffuse_color = tint` whenever a tint is given (needed passing `mat`
        through from the 3 factory functions) -- a genuine, permanent improvement to Style mode's
        Solid+Material display, not just a workaround for the new attribute.
        Deliberately scoped to Separate-by-Floor/Room split objects and the 6 baked-mesh types,
        not the live, unsplit Blueprint object still carrying its GN modifier -- same precedent as
        the UV work: a GN-baked attribute on a live modifier-preview mesh doesn't reliably pick up
        Blender's "active" flag the way a real, code-created datablock does, so building the
        GN-side palette-lookup machinery (an image-texture-based index-to-color sample, keyed off
        the same `final_index_socket` already driving Set Material Index) wasn't worth the added
        complexity for a case Separate by Floor/Room already solves reliably.
        Verified with real checks (color attribute present + full loop coverage + active on every
        target object type, two different rooms' colors compared against each other rather than
        checked in isolation -- same "two rooms, not one" shape as the 0.16.3 regression check,
        for the same reason) and a real `bpy.ops.render.opengl` screenshot in Solid Shading with
        Color set to Attribute: every room shows a genuinely distinct color, no material/UV setup
        needed at all. Full suite green on 4.2.21 LTS and 5.2.0 LTS.
  - [x] **0.17.1: `_mesh_from_faces` was copying every split object's ENTIRE source material
        list, not just what that object's own faces use.** Found from user feedback right after
        0.17.0 shipped: "we get Procedural_Level_Blueprint_Floor2_Room04 but material field is
        empty on this object, material should be LA_Room_0004... when we add it manually, it is
        all there." Diagnosed directly (`obj.active_material_index`, `obj.material_slots`,
        `obj.active_material` on a real split Room object): every Room/Corridor/Ceiling object
        WAS getting the correct per-face `material_index` all along (rendering was already
        correct, confirmed by every earlier screenshot), but `_mesh_from_faces` copied the FULL
        source material list onto every single split object regardless -- for a real level, all
        30-50+ floor-level + room-pool + entrance/exit materials, even though a Room object only
        ever uses ONE of them. Blender's Properties > Material tab always shows the OBJECT's
        ACTIVE slot (index 0, never touched by this operator) as "the material" -- with the full
        list copied, slot 0 was always `LA_Floor_Level_0`, so a Room object's Material field
        showed a floor-level color instead of its own room color, even though the object rendered
        correctly in the viewport. Explains "when we add it manually, it is all there" exactly:
        manually assigning a material sets the active slot to the new one, which then correctly
        shows.
        Fixed by compacting `_mesh_from_faces`'s copied material list to only the materials the
        given `face_indices` subset actually references, remapping each face's `material_index`
        from the source mesh's global index space into the new, densely-packed local one. A Room
        object now typically has exactly 1 material slot -- its own room material -- so the
        default active slot is always correct with no extra step needed. Corridor/Ceiling objects
        (which can span more than one underlying material, e.g. a floor-level color plus an
        entrance/exit marker) keep exactly as many slots as they actually use, no more.
        Replaced the old "kept the full material slot list (not collapsed to 1)" regression check
        (written against the 0.13.1 bug, where a real Blender Apply Modifier collapsed everything
        down to ONE SHARED slot across the whole mesh -- a different failure shape than a
        correctly-sized per-object list) with a check that every split object's slot count exactly
        matches the number of distinct materials its own faces reference, plus a new check
        matching the exact reported symptom: a Room object's `active_material` is its own real
        `LA_Room_*` material. The 0.13.1-style collapse-to-one-shared-list failure mode is still
        caught, more robustly, by the existing "different rooms actually resolve to different
        materials" check just below it. Full suite green on 4.2.21 LTS and 5.2.0 LTS.
  - [x] **0.17.2: Separate by Floor/Room now refuses to run at all if its GN modifier was
        already applied, instead of silently producing empty material slots.** Direct follow-up
        to 0.17.1, from the user's own reported repro steps: their test workflow's step 3 was
        "APPLY GN_Game_Renderer MODIFIER" -- a manual pre-apply, done BEFORE step 4 ("Separate by
        Floor/Room") -- which is exactly the old, no-longer-needed, actively-harmful precondition
        the 0.13.1 fix and this operator's own docstring already warn about. Doing it anyway
        (old habit, or documentation not being read/found) puts the object in exactly the state
        0.17.1's compaction fix couldn't recover from: Blender's own Apply Modifier already
        collapsed `obj.data.materials` down to whatever few slots survive a real Convert-to-Mesh
        (per-face `material_index` values survive bit for bit, the SLOT LIST does not), so
        `original_materials = list(obj.data.materials)` captured at the top of `execute()` is
        already the collapsed list by the time the operator runs -- no different from what would
        happen for ANY user hitting this operator's real precondition violation, just previously
        undetected. 0.17.1's compaction correctly appends `None` for any `material_index` beyond
        that collapsed list's range, which is exactly right for the case it was built for (a
        legitimately-run split needing only the materials actually used) but silently produces an
        empty material slot for THIS case instead of surfacing the real problem.
        Fixed by checking for the live `NODES` modifier immediately, before any of the eval/
        material work runs, and refusing with a clear, actionable error ({'ERROR'}, cancels)
        explaining exactly what happened and what to do instead (regenerate the Blueprint, run
        this directly on it, skip the manual apply step) rather than degrading silently. New test:
        duplicates the blueprint object, applies its modifier via `bpy.ops.object.convert(target=
        'MESH')` (reproducing the user's exact step 3), confirms the operator now cancels with a
        RuntimeError explaining why (calling an operator that reports {'ERROR'} from Python raises
        rather than just returning {'CANCELLED'} the way a plain WARNING/INFO cancellation would --
        the test's first attempt at this check crashed the whole suite before that was accounted
        for with a try/except). Full suite green on 4.2.21 LTS and 5.2.0 LTS.
  - [x] **0.17.3: real crash found running the now-correct direct workflow a second time --
        `RuntimeError: Collection '...' already in collection '...'`.** User tried the fixed
        workflow from 0.17.2 (regenerate, Separate by Floor/Room directly, no manual apply) and
        hit a traceback at `_get_or_create_collection`'s `parent.children.link(existing)`.
        Root cause: Blender moves the outliner's ACTIVE collection
        (`context.collection` / `view_layer.active_layer_collection`) to the last one an operator
        run created or linked into, and never moves it back on its own. After one Separate by
        Floor/Room run, the active collection was left sitting inside that run's own nested
        "Floor 0 - Rooms". Running the operator again looked up the existing top-level
        "Procedural Level Blueprint (Split)" collection by name (found the one from the FIRST
        run) and tried to link it as a child of `context.collection` -- now a descendant of
        itself. Blender correctly refuses to create that cycle and raises. `Generate Props`
        builds an equally nested tree (Level Props > Torches/Lights/Decoration) through the same
        helper and was equally exposed, just not yet hit by a report.
        Fixed at the helper, not the call sites: `_get_or_create_collection` now checks whether
        linking the existing collection under the requested parent would create a cycle (parent
        IS that collection, or already lives somewhere inside it via a new `_collection_contains`
        recursive check) and, if so, leaves the collection wherever it currently is instead of
        attempting the relink -- correct behavior for the common case too (a previous run's tree
        is still exactly where it should be, nothing needs to move). No call site changed; this
        protects every current and future use of the helper, including Props.
        New test reproduces the exact scenario: run Separate by Floor/Room once, point the active
        collection at a real leftover "- Rooms" sub-collection from that run (found by walking
        `view_layer.layer_collection` recursively), regenerate the Blueprint fresh, and run the
        operator again -- confirmed it no longer raises. Full suite green on 4.2.21 LTS and
        5.2.0 LTS.
  - [x] **0.17.4: two picked-from-the-backlog items -- the Corridor Stairs residual wall gap
        (Known Issues) and hidden-face removal for Walls/Doors (Ideas for future work).**
        - **Corridor Stairs wall gap, fixed for real this time.** The residual ~7-10% (see the
          Cave + Corridor Stairs entry above) came from a corridor pathfound AFTER a stairwell's
          own placement-time clearance check ran, which can end up alongside its perpendicular
          side with nothing to stop a player stepping on from the side. Rather than chase this
          further at PLACEMENT time (risky -- `_carve_corridor`'s straight-line path has no
          alternate routing, and DEVELOPMENT.md already documents that guarding it there caused
          real disconnections in testing), fixed it at WALL-GENERATION time instead: `tile_id` and
          `tile_rotation` are already baked mesh attributes, and `wfc_corridor_stairs` is a single
          scene-wide toggle, so Generate Level Walls can identify every TILE_STAIR cell and its
          travel direction without touching the solver at all. New `forced_wall_edges` parameter
          on `_build_wall_mesh` (a set of `(cell, (ddx,ddy))` pairs) makes a side "exposed" (gets a
          wall) even when the neighbor IS walkable; wired up only when Corridor Stairs is on, for
          exactly a stair cell's two perpendicular sides (derived via the existing
          `_direction_for_rotation` float-tolerant lookup, rotated 90°) -- room-based stairs are
          untouched, since that same neighbor cell there is the room's own real walkway, not a gap.
          New regression check verifies actual GEOMETRY, not solver-level grid walkability like the
          existing Cave check does (which can't observe a wall-generation-time fix at all): for
          every stair cell in a real Corridor-Stairs generation, a wall box AABB genuinely covers
          both perpendicular boundary lines, confirmed via the same `per_box_aabbs` helper already
          used for stair/wall overlap checks.
        - **Hidden-face removal, scoped to Walls + Doors** (the two the idea specifically named,
          not Stairs/Ramps/Torches/Decoration -- kept to what's actually verified rather than
          extending scope unprompted). Every wall box's bottom face is always coincident with, and
          hidden behind, the floor tile it stands on -- genuinely never visible in any normal
          view -- so `_build_wall_mesh`'s `add_box` now skips it unconditionally: roughly a sixth
          to a fifth fewer faces per wall box (5 instead of 6 with Cap Top on, 4 instead of 5 off),
          on what's usually a level's single biggest geometry contributor. Doors needed more care:
          a door frame's two POSTS are floor-touching exactly like a wall (bottom safely droppable),
          but the LINTEL spanning between them is suspended at door_height -- its underside is
          genuinely visible to anyone standing underneath it, so unconditionally dropping the
          bottom there would leave a real visible hole. `add_box` gained a `floor_touching=True`
          default parameter (kept for both post calls, passed `False` only for the lintel), rather
          than blindly mirroring the wall change. The existing "bottom face winding points -Z"
          regression check (there specifically to verify the add_box winding convention against a
          real evaluated mesh) no longer has a bottom face to check on Walls -- replaced with a
          check confirming the exact expected reduced face count, so the optimization itself is
          verified as having actually happened, not just assumed safe. Full suite green on 4.2.21
          LTS and 5.2.0 LTS.
  - [x] **0.17.4b / 0.18.0: hidden-face cleanup extended to Stairs/Ramps/Decoration, and Per-Floor
        Overrides (room size/shape and material style, breakpoints with size interpolation).**
        - **Hidden-face cleanup, extended.** Every stair tread box and ramp segment box's z0 is the
          run's own entry floor level regardless of position along the run, and the room floor
          under a stair/ramp run sits at that exact same level -- same reasoning as Walls, so their
          bottom faces are gone too. Decoration (crates/barrels/cones) always rests directly on the
          floor its own z0 already encodes, so its base/bottom caps are gone as well -- verified by
          checking no downward-facing polygon remains at all (three mixed primitive shapes per
          generation, in random proportions, made an exact expected face count impractical, unlike
          the box-counting checks used for Walls/Stairs/Ramps). Torches were investigated and
          deliberately left untouched: both boxes a torch builds (haft and flame) are wall-mounted,
          floating at roughly torch_height above the actual floor, not floor-touching at all -- the
          haft's underside in particular is genuinely visible to anyone standing beneath it, so
          there's no always-hidden face to remove there.
        - **Per-Floor Overrides.** User picked "Both" (room size/shape AND material style vary per
          floor) and, for the config shape, "breakpoints with gradients" -- a short list of
          (floor_index, room_size_min/max, room_shape, style) rows where NUMERIC values (room size)
          interpolate smoothly between rows and DISCRETE values (shape, style) switch at the row's
          floor (no way to blend RECT into ROUND, or one procedural shader into another, as a
          literal interpolation). New `WFC_FloorProfile` PropertyGroup + `WFC_UL_FloorProfiles`
          UIList + Add/Remove operators, a "Per-Floor Overrides" box in the Rooms section (disabled
          with an explanatory label when Room Shape is Cave -- see below). An empty list (the
          default) falls back to the flat Rooms-section values everywhere, byte-identical to every
          generation before this feature existed -- confirmed directly, full existing suite stayed
          green with zero changes needed.
          Solver side: `WFC_Level_Solver` gained `floor_profiles` (a plain list of dicts, not the
          PropertyGroup directly -- keeps the solver decoupled from bpy types, same as every other
          constructor arg) and two resolvers, `_room_size_for_floor` (linear interpolation between
          the two nearest breakpoints, clamped to the nearest end outside their range) and
          `_room_shape_for_floor` (step function: the last breakpoint at or before this floor
          wins). `_scatter_rooms` now calls these per logical floor instead of reading the flat
          `self.room_size_min/max`/`self.room_shape` directly. Deliberately excludes 'Cave' from
          the per-floor room_shape options, and per-floor profiles are ignored entirely whenever
          the GLOBAL Room Shape is Cave (the whole level stays Cave, `_scatter_rooms`'s existing
          early-return to `_carve_cave_floors` never even reaches the new resolvers) -- mixing Cave
          and non-Cave floors in one generation is the separate, larger, already-tracked "Cave mode
          is an all-or-nothing setting" limitation, not something this feature attempts to solve.
          Material side (Style/procedural mode only -- Simple Viewport Colors doesn't have a
          "style" concept to vary): `get_or_create_style_floor_level_materials`/
          `get_or_create_style_room_materials` changed from taking a single style_key to taking a
          `style_for_slot`/`style_for_room` resolver callable, so different floor-level ramp slots
          and different rooms can now each use a DIFFERENT style's shader (still tinted by that
          slot/room's own palette color, same as before -- a style room still has its brick/rock/
          noise pattern, just with per-floor variety on top now). New `_style_for_logical_floor`
          helper (same step-function shape as `_room_shape_for_floor`) resolves both: floor-level
          ramp slot i is treated as logical floor i directly (exactly correct whenever Sub-Levels
          per Floor is 1, the common case; an accepted approximation otherwise, same granularity
          Simple mode's own floor-level coloring already has), rooms resolve by their own actual
          `room['z'] // solver.sub_levels` (no slot-cycling ambiguity there -- every room already
          gets its own individual material regardless). Entrance/Exit materials stay on the single
          global `scene.wfc_style` -- level-wide landmarks, not tied to one floor. Room material
          naming/orphan-purge updated to handle multiple styles' prefixes coexisting in one
          generation (previously assumed a single shared prefix).
          Deliberately NOT extended to Walls/Doors/Stairs/Props in this pass -- those use a single
          shared material (or, for Simple mode floors/rooms, the existing per-room system already
          unaffected by style) regardless of Wall/Stair Grouping; making them per-floor-style-aware
          would need each grouped-by-floor object to pick its own material, a real but separable
          follow-up, not attempted here to keep this pass to a deliverable size.
          Verified at three layers: direct resolver unit checks (interpolation lands strictly
          between two breakpoints' values, step function doesn't blend, empty list falls back
          exactly); a real end-to-end generation through the actual Add operator + regenerate,
          confirming ACTUAL carved floor tiles differ per room between a 2x2-room floor and a
          7x7-room floor (not just the solver's own room list); and that floor-level slot 0 vs
          slot 3 and every room on the 7x7 floor resolve to genuinely different style-material
          name prefixes (Dungeon vs Cave Rock). Also caught and fixed a real gap in
          `tests/stub_bpy.py` (the offline mock): it never defined `CollectionProperty`,
          `PropertyGroup`, or `UIList` at all, so the addon failed to even import under it the
          moment this feature's new import/classes were added -- fixed by adding all three (the
          latter two as plain `object`, matching how `Panel` was already stubbed, since the mock
          never needs to model actual UI drawing). Full suite green on 4.2.21 LTS and 5.2.0 LTS,
          plus 50 seeded solver trials with floor_profiles set, under the offline mock.
- [x] **Freeze for Texture Work.** Every Step operator deletes-and-rebuilds its objects by fixed
      name each time it runs (`_remove_objects_by_prefix`), so any material/texture work done by
      hand on the live objects gets silently wiped the moment Generate is clicked again. New
      `OBJECT_OT_FreezeForTextureWork` (Setup tab, next to Separate by Floor/Room) renames every
      currently-generated Blueprint/Walls/Stairs/Doors/Torches/Decoration/Light object and moves
      them into a new `Frozen - Seed{n}` collection, with a copy of `scene.wfc_debug_params`
      (exact settings/seed) stashed on the collection as a custom property, since the live
      property itself gets overwritten by the next generation. Deliberately a rename, not a
      duplicate -- no new datablocks, so freezing costs nothing beyond string renames + one
      collection, and independence from a future generation falls out of the rename alone (every
      Step operator only ever looks up objects by their fixed name).
      **Real bug caught by this feature's own headless test, not found by inspection:** the first
      version appended the frozen tag to the end of each object's name
      (`f"{obj.name}_Frozen_{label}"`). `_objects_matching_prefix`'s match is
      `startswith(base_name + "_")` -- front-anchored -- so a Per Floor/Per Stair grouped object
      (already named e.g. `Procedural_Level_Stairs_Floor2_02`) kept matching
      `Procedural_Level_Stairs_` regardless of anything appended after it. A frozen grouped object
      would have been silently deleted the next time Stairs got regenerated -- the exact opposite
      of what the feature promises. Caught immediately by the new regression test's "freeze twice
      in a row" check (the second freeze found the same 62 objects again instead of reporting
      nothing to freeze) and confirmed directly with a targeted check that regenerates Walls (not
      just Blueprint) after a freeze and asserts the frozen collection is untouched -- Blueprint's
      own cleanup is an exact-name lookup, not a prefix match, so regenerating only Blueprint would
      NOT have caught this. Fixed by prepending the tag instead
      (`f"Frozen_{label}_{obj.name}"`), which changes what the name STARTS WITH and so can never
      satisfy any base_name's prefix match again, for every grouping mode at once -- also improves
      Outliner grouping as a side effect, since every object from one freeze now sorts together.
      Verified against real Blender 5.2.0 LTS via `run_blender_tests.sh`, full suite green.

---

## 3. Known issues / things that need fixing

- [ ] **`downgraded-32.hex` (the master palette source) has 32 colors, but only 31 made it into
      `levelArchitect_v2.py`.** `b8b4b2` (line 13) isn't `FLOOR_RAMP_HEX`, `ROOM_POOL_HEX`,
      `WALL_HEX`, `STAIR_HEX`, `DOOR_HEX`, `ENTRANCE_HEX`, `EXIT_HEX`, `TORCH_HEX`, `TORCH_FLAME_HEX`,
      or `PROP_HEX` -- it never got assigned to anything. Every other line in the hex file maps 1:1
      to a constant. Need to decide what `b8b4b2` was meant for (an unused slot? a second wall
      variant, given `WALL_HEX`'s neighbor `WALL_FILE`/`Wall1.png` already exists unreferenced in
      `Textures/`?) and wire it in, or drop it from the palette file if it's genuinely spare.
- [x] **`Room17.png` / `Room18.png` were duplicate colors** (both `fcef8d`) in the shipped
      Textures set — `658d78` (dark sage), `ROOM_POOL_HEX`'s actual entry for Room18, never made
      it into the shipped swatch. Fixed by regenerating `Room18.png` as a flat `658d78` PNG to
      match its intended palette entry; was always a texture-asset bug, not a code bug.
- [x] **Style (procedural) materials didn't get per-floor/per-room coloring** — see §2, now fixed.
- [x] **The `stub_bpy` mock harness itself wasn't committed** — every mock-based verification
      described throughout §2 up to this point was run from a scratch directory outside the repo.
      Committed as `tests/stub_bpy.py`, unchanged from the scratch copy (re-verified working
      against the current addon file first: 50 seeded `WFC_Level_Solver` trials, no exceptions).
      `tests/blender_headless_test.py` covers the "does this actually work in real Blender"
      question (including everything GN-related, which this mock deliberately doesn't model at
      all), but the mock is still the faster path for iterating on solver/connectivity/mesh-math
      logic — hundreds of seeded trials in seconds, no Blender process needed. Usage documented in
      the file's own header comment.
- [ ] **Defensive wrappers (`_set_prop`, `_set_input`, the `layout.panel()` fallback in
      `_section`) were never individually re-audited** after `tests/blender_headless_test.py`
      confirmed the addon actually works end to end on real Blender 5.2.0 LTS. They're almost
      certainly still fine (nothing in the full run needed them to silently swallow an error to
      pass), just never went through a "prove each one is still necessary" pass — low priority
      since they're cheap insurance, not a proven problem.
- [x] **`bl_info["blender"]` only declared `(5, 2, 0)`, untested on earlier versions.** Actually
      ran the full real-Blender pipeline test (`run_blender_tests.sh`) against both Blender 4.2.21
      LTS and 4.5.2 LTS: **passed clean on both, zero addon-code changes needed.** The 5.2-only
      concern turned out to only ever apply to `tests/blender_headless_test.py`'s own helper for
      poking a *live* GN modifier input from outside the addon (`modifier.properties.inputs` is
      5.2+; older versions need the `modifier["Socket_N"]` IDProperty form instead) — the addon's
      own code never touches either API, it only sets defaults via `node_group.interface` at
      *creation* time, which has been stable since Blender 4.0. Fixed the test helper to branch on
      `hasattr(mod, "properties")` so it works on both, and lowered `bl_info["blender"]` to
      `(4, 2, 0)` to match what's now actually verified, not just assumed. Not chased further back
      than 4.2 LTS (pre-4.0's `node_group.inputs.new()` node-tree API is meaningfully different, so
      3.x is a real, not just unverified, incompatibility — not worth chasing for an early testing
      release).

---

## 4. Ideas for future work (not started)

Roughly ordered by how directly they build on what already exists:

- [ ] **Bent / curved ramps and stairwells.** The natural next step after the plain ramp
      feature — the run data model (one straight direction per run) would need to grow into a
      multi-segment path, and the room reservation (`_carve_stair_room`) would need to support
      L-shaped or multi-segment footprints instead of a single rectangle. This is the biggest
      lift on this list; don't start it casually.
- [ ] **Actual door leaves/panels**, as an option alongside the current always-open frame — the
      frame deliberately has no panel today (walk-through by design). A closable-looking panel
      would need its own geometry and probably its own material, plus a decision on whether it
      should ever visually block the opening (it shouldn't block *pathing* — connectivity must
      stay frame-based) or just sit ajar for looks.
- [x] **Props / decoration scattering — done, see §2.** Shipped as `OBJECT_OT_GenerateLevelProps`
      (Step 5): wall-mounted torches (baked mesh + real Point lights) and per-room crate/barrel/
      cone decoration. This entry was stale — left unchecked after the feature actually landed.
- [x] **Trim-sheet-ready UVs — done.** Every baked-mesh builder (walls/doors/stairs/ramps/torches/
      decoration) used to write a flat constant `(0.5, 0.5)` UV on every corner
      (`_add_flat_uv_map`) — correct for a flat-color Simple Viewport Colors swatch, but it meant
      any texture with real detail (a trim sheet, a tiling brick/rock material) sampled one single
      pixel across an entire wall run instead of repeating. Replaced with `_add_planar_uv_map`:
      real box-mapped UVs (project each quad onto whichever of XY/XZ/YZ its face normal is most
      aligned with, using its actual world-space position in meters) — needs no separate unwrap
      step, and every box this file builds is axis-aligned in world space EXCEPT
      `_build_decoration_mesh`'s CRATE prop (rotated by an arbitrary angle, not the cardinal
      0/90/180/270 stair/ramp rotations), which still gets a valid, fully-covered UV, just with a
      slight per-face shear — imperceptible on a small placeholder prop. New `wfc_uv_tile_size`
      scene property (Setup tab, Scale & Style section) controls meters-per-UV-tile so a texture's
      real-world size can be matched.
      Deliberately does NOT touch the Blueprint floor's own UV (still the GN graph's constant
      `(0.5, 0.5)` `GeometryNodeStoreNamedAttribute` — see `create_geometry_nodes_modifier`) — GN
      changes are the exact category of "uncertain live-API behavior" this addon has deliberately
      avoided (§1), so that stays a separate, deliberately-not-attempted follow-up, not scope creep
      onto this change. **Verified against real Blender 5.2.0 LTS** (this project's primary
      target — see §5 for how to point `run_blender_tests.sh` at a local install) via
      `run_blender_tests.sh`, including the new regression check asserting the UVs are no longer a
      single constant tuple across a mesh — full suite green.
- [x] **Rounded / filleted wall corners — done (v1, Bevel-modifier based).** `_build_wall_mesh`
      still emits one merged box per straight run, meeting at hard 90° corners in the base mesh —
      unchanged. New opt-in `wfc_wall_corner_rounding` + `wfc_wall_corner_radius` (Walls tab) adds
      a live `BEVEL` modifier (`_add_corner_rounding_modifier`) to the wall object(s), angle-limited
      (`limit_method='ANGLE'`, ~35°) so it only catches genuinely sharp edges, not the near-flat
      edges running along a straight wall. Chose this over hand-derived per-corner quarter-cylinder
      fillet geometry specifically because Bevel is a long-stable, ordinary mesh modifier — not
      Geometry Nodes, the exact "uncertain live-API behavior" category §1 already flags as the
      reason walls/stairs are baked Python in the first place — so it's verifiable and low-risk.
      **Verified against real Blender 5.2.0 LTS** via `run_blender_tests.sh` (new checks: exactly
      one Bevel modifier added, width matches Corner Radius, `limit_method == 'ANGLE'`) — full
      suite green. Still only confirms the modifier is wired up correctly, not that the rounded
      result looks good at a glance — worth an actual visual look in the viewport before relying
      on the default radius/angle-limit values for a real level.
      **Known, disclosed limitation (not a bug):** angle-limited selection can't distinguish a true
      building corner from a wall run simply ending at a doorway/opening jamb — both read as ~90°
      edges — so it rounds both, and also rounds the top rim whenever Cap Top is on. Reads as a
      reasonable, broader-than-strictly-"corners" softened look in practice.
      **v2, if the broader effect above turns out to matter:** hand-derived fillet geometry
      directly in `_build_wall_mesh`, built only at cells where a run's endpoint coincides with
      another perpendicular run's endpoint (a real corner) — composes correctly with Organic
      Irregularity and continuous-elevation z_offsets the way a blind modifier can't, but needs
      that corner-vs-jamb classification logic first. **v2-alt:** a `WEIGHT`-limited Bevel marking
      only true corner edges via each box's own known vertical-edge vertex pairs — much less new
      geometry code than v2, but Blender 4.0 moved Bevel Weight onto the generic attribute system,
      so the exact attribute name/API needs live-Blender verification before attempting it, not a
      blind guess.
- [ ] **Alternative layout-generation algorithms (Voronoi / Perlin-Simplex noise).** Two genuinely
      different approaches from what exists today (grid scatter+MST for RECT/ROUND/MIXED,
      drunkard's-walk tunnels for CAVE — see §1's pipeline and `_carve_cave_floors`):
      - **Voronoi room partitioning.** Scatter N seed points per floor, assign every grid cell to
        its nearest seed (a rasterized Voronoi diagram) instead of carving discrete rectangles —
        rooms become irregular polygonal cells with naturally organic, non-axis-aligned boundaries.
        The big appeal: almost everything downstream is already keyed off `room_id` differing
        across a walkable boundary (doors, per-room materials, wall silhouette) — a Voronoi cell is
        just a different way to *fill* `room_id`/`grid`, so doors/walls/materials would need zero
        changes. The real work is corridor connectivity: adjacent Voronoi cells sharing a border
        need an explicit opening carved through it (a "portal" a few cells wide), then the existing
        MST-over-adjacency-graph idea (§1) still applies, just over Voronoi-cell adjacency instead
        of room-rect adjacency.
      - **Perlin/simplex noise-thresholded caves**, as an alternative to `_carve_cave_tunnel`'s
        drunkard's-walk: threshold a noise field per Z-level (walkable where noise > cutoff) for
        naturally winding caverns without an explicit random walk. Needs its own connectivity
        story — noise thresholding doesn't guarantee traversability the way a walk that always
        starts from an already-connected chamber does — but `_ensure_connectivity`/
        `_bfs_reachable`'s generic BFS-and-repair pass is already agnostic to how a grid got
        carved, so that part is reusable as-is, not a new subsystem.
      - Both are self-contained alternative `room_shape` values (like `'CAVE'` today), not changes
        to the existing modes — same reasoning §4's Cave-mode-is-all-or-nothing note already gives
        for why per-floor mixing is a separate, larger concern than adding the mode itself.
- [ ] **Windows.** Would reuse most of `_build_door_mesh`'s same-Z boundary-detection logic
      (frame at a wall-facing edge instead of only room-to-room boundaries), sized/positioned
      differently (mid-wall-height opening, not floor-to-lintel) and gated by its own placement
      rule (e.g. only on true exterior walls) rather than "wherever a doorway already is."
- [ ] **Collision mesh / navmesh export.** The solver already has the full walkable-cell graph
      (`WFC_Level_Solver.grid` / `room_id` / connectivity) — nothing downstream currently emits
      anything beyond visual mesh. A simplified collision box set (reuse `_build_wall_mesh`'s
      run-merging, just without the cosmetic jitter path) or a baked nav-polygon mesh from the
      same walkable cells would mostly be "read data already computed, emit different geometry,"
      not a new subsystem.
- [ ] **One-click game-engine export operator** (FBX/glTF), aware of the addon's own split object
      structure (Walls/Doors/Stairs/Props per floor, see `_remove_objects_by_prefix`'s naming
      convention) so a user doesn't have to know to reach for Blender's generic exporter and
      manually select the right object set.
- [x] **Delete interior/hidden faces for faster rendering — done for Walls/Doors/Stairs/Ramps/
      Decoration, see §2 (0.17.4, extended in 0.17.4b/0.18.0).** Every wall box's, stair tread
      box's, and ramp segment box's bottom face (always hidden behind the floor beneath it) is
      gone unconditionally; every door post's and decoration prop's base is gone the same way.
      Two exceptions kept on purpose: a door's lintel (elevated, underside genuinely visible) and
      Torches (both boxes are wall-mounted/floating, never floor-touching at all -- investigated
      and explicitly left as full 6-face boxes, not an oversight). The "two adjacent wall boxes
      along a straight run touch face-to-face" case from the original wording turned out to
      already be moot: the existing run-merging optimization (Organic Irregularity off, no
      per-tile z_offset variation) already emits ONE box per merged run instead of one per tile,
      so that specific interior-seam duplication was never really separate geometry to remove.
- [ ] **Organic Irregularity for floor tiles.** Currently only walls/stairs/ramps get jitter,
      since floors are GN-driven and adding noise there means touching the GN graph — the exact
      category of "uncertain live-API behavior" this addon has deliberately avoided. Worth doing
      eventually, but budget for a real live-Blender testing pass, not a blind attempt.
    - **Alternative if this needs Blender-based iteration:** the AI Blender MCP server
      (`github.com/ahujasid/blender-mcp`, MIT license — check compatibility before wiring it
      into a GPL codebase, not a blocker for using it as a dev tool) can drive Blender directly
      by connecting Claude to it, letting Claude test GN node graphs and other live-Blender
      behavior interactively instead of guessing blind. If GN work resumes, standing this up
      first would remove most of the risk that pushed walls/stairs to baked Python in the first
      place.
- [ ] **True continuous room elevation — beyond multi-doorway V1.1** (see §2 for what's already
      shipped: `_apply_continuous_elevation` / `_room_elevation_paths`, any number of doorways per
      room, grid-locked XY, smooth world-Z, a 1-cell buffer between unrelated ramps). Remaining
      scope:
      - **Chained / multi-room elevation gradients** (room A elevated relative to flat ground,
        room B elevated further relative to A, connected corridor sloping the whole way) — the
        `claimed`/buffer machinery actively prevents this today (a cell already spent on, or
        adjacent to, one room's ramp can't be reused by another), by design, to keep each room's
        slope reasoning independent. Lifting that restriction means reasoning about a whole
        chain's cumulative slope, not just one hop against flat ground.
      - **Full freeform XYZ room placement** (pack rooms anywhere in space, pathfind
        slope-constrained connectors between them) was considered and rejected as a first step —
        it throws away the grid-adjacency guarantees (connectivity, no-overlap, clean walls) that
        make the solver reliable, replacing them with real 3D bin-packing + constrained
        pathfinding. That's a new subsystem, not an extension of this one. Worth revisiting only
        if the grid-locked-XY approach (everything above) turns out to feel too limited in
        practice.
- [x] **Per-floor variation profiles — done, see §2 (0.18.0).** Shipped as "breakpoints with
      gradients" (user's chosen shape): a short `WFC_FloorProfile` list, numeric room size
      interpolates between rows, room_shape/style switch at each row. Room size/shape AND
      material style both covered ("Both", user's chosen scope). **Still open / deliberately not
      attempted**: a true organic "cave" *room shape* option per floor (distinct from `wfc_style`'s
      Cave *material* look) — the existing Cave *room shape* is a structurally different whole-
      level generation path (`_carve_cave_floors`), not a per-room carving mode, so mixing it with
      normal floors per-floor is still the separate "Cave mode is an all-or-nothing setting" known
      issue below, unaffected by this feature. Walls/Doors/Stairs/Props still use a single global
      material regardless of which floor they're grouped by — extending those to be per-floor-
      style-aware (when Wall/Stair Grouping is Per Floor) is a real, separable follow-up.
- [ ] **Extensions Platform submission** (extensions.blender.org) — needs a `blender_manifest.toml`
      and goes through review. Not needed for informal testing distribution (current `dist/`
      zip + README is sufficient for that).

---

## 5. Notes for whoever (including future-me) picks this up

- **The locked backup** (`Desktop/levelArchitect_v2.py`, one level up from this folder) is a
  frozen snapshot from when the addon first reached a stable, workable state. Never edit it —
  it's the rollback point. All active work happens in `BlenderLevelArchitect/levelArchitect_v2.py`.
- **Every generation is seeded and reproducible** — when debugging a reported issue, always ask
  for (or reproduce with) the exact seed + settings rather than "regenerate and see."
- **Offline testing pattern**: `tests/stub_bpy.py` (mesh/material/object stand-ins good enough
  to exercise real solver + operator code without a live Blender) has caught most bugs in this
  project faster than guessing from code review alone. `import stub_bpy` before loading the
  addon module via `importlib` — see the file's own header comment for the exact pattern. Doesn't
  model Geometry Nodes at all, so anything GN-related still needs real-Blender verification below.
- **Real-Blender verification**: `./run_blender_tests.sh [path-to-blender]` (see §2) runs
  `tests/blender_headless_test.py` inside an actual headless Blender process. Use the mock for
  fast solver/mesh-math iteration, but run this before considering ANY GN-graph change, live GN
  modifier interaction, or mesh-winding change actually done — it's the only thing in this
  project that can catch what the mock structurally can't (it already found one real,
  project-wide winding bug the mock had no way to see).
- **This project's primary target is Blender 5.2.0 LTS** — prefer that version's binary for the
  `[path-to-blender]` argument above when more than one Blender install is available locally.
  Exact install paths are machine-specific and deliberately not recorded here; confirm whichever
  binary you point at with `[binary] --version` before trusting it.
- **Visual spot-checking**: `./generate_test_blends.sh [path-to-blender]` runs the full pipeline
  once per scenario in `tests/generate_test_blends.py`'s `SCENARIOS` list, all on the same fixed
  seed (so the toggled option is the only thing that varies between files, not layout too), and
  saves each as `test_blends/test_NN.blend` — open one directly to actually look at a feature
  instead of only checking it evaluates without erroring. Filenames are deliberately generic;
  `test_blends/testfiles.txt` (regenerated each run) is the real index of which file has which
  settings. Add a new tuple to `SCENARIOS` (and bump `NUM_SCENARIOS` in the `.sh` wrapper) for
  any new toggle worth a look. `test_blends/` isn't swept into the distributed package by
  `build_package.sh` (which only ever copies specific named files/folders), same as `tests/`.
  Each scenario also gets a top-down Workbench render (cavity shading on, so edge/corner
  geometry actually reads) saved to `test_blends/Renders/test_NN.png`
  (`render_top_down_preview`, framed to every `WALLS_OBJECT_NAME`-prefixed object's combined
  bounding box) — lets a scenario be glanced at without opening Blender at all, though a render
  can still miss something an interactive look wouldn't (occlusion between stacked floors from
  directly above, wrong-looking materials that only show under a different shading mode, etc.) —
  it's a faster first pass, not a full replacement for opening the file when something looks off.
- **Before touching wall/stair/ramp/torch/decoration mesh math**: re-derive the vertex/face
  winding by comparing against `_build_wall_mesh`'s `add_box` — every other `add_box`-style
  builder in this file was deliberately kept in sync with its exact winding convention (bottom
  face `(i+3,i+2,i+1,i+0)`, top `(i+4,i+5,i+6,i+7)`, sides following the same reversed pattern —
  see the comment on `_build_wall_mesh`'s own `add_box`). This convention WAS wrong for most of
  the project (every face pointed inward) until `tests/blender_headless_test.py` caught it via a
  direct normal-direction check and it got fixed across all six copies at once (see §2) — trust
  the current code, not any memory of "the original convention," and re-run the headless test's
  winding checks after any further changes here rather than eyeballing it in Solid shading, which
  won't show a backwards normal at all.
