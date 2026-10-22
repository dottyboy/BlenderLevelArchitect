# Game Level Architect — Development Notes

Internal dev-facing doc: what's built, what's known-broken, what's next. Not for end users
(see `dist/README.md` for that). Source of truth for the addon's actual behavior is always
`levelArchitect_v2.py` — this file can drift out of date; the code can't.

Current version: **0.43.0** (see `bl_info` in the source file).

§2 (Development tree) was condensed 2026-08-21 — dropped the blow-by-blow investigation
narrative and per-run stress-test numbers from older, fully-resolved entries, kept every
decision, bug mechanism, and design rationale. Nothing was removed for being wrong or
obsolete; the full uncondensed version lives in `DEVELOPMENT_OFFLINE.md` (gitignored, local
only, not on GitHub) if you need the full narrative behind an entry.

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
      Fixed a real bug along the way: "Per Floor" grouping was bucketing by *fine* Z-slice
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
      exactly where the wall silhouette already leaves a gap, so a doorway can only ever land
      where a wall gap already exists.
  - [x] **Merge Distance** — two rooms connected by a short corridor used to get a doorway at
        each end, standing on top of each other. Doorways within `Merge Distance` tiles of each
        other collapse to a single frame (`Merge Distance = 0` restores the old behavior).
  - [x] **Merge Distance fix: wide openings.** The first pass only compared doorways on the
        *same* grid line, so a wide corridor or long shared room edge still produced several
        doors side by side (each on its own line). `_cluster_nearby_points` replaces the
        per-line scan with a 2D (Chebyshev) union-find cluster over both axes.
- [x] **Stairwell placement: reduce bufferless emergency fallback.** `_find_stair_footprint`'s
      fallback tiers all required a full 1-tile empty *margin* around the footprint, not just the
      footprint itself — in dense layouts that margin was usually what wasn't available, pushing
      placement to `_ensure_connectivity`'s absolute-last-resort single tile (no room, no buffer
      — a stair that visibly clips into/opens straight at a wall). Added one more fallback tier
      at the minimum footprint size with `margin=0` (flush against a neighboring room is fine;
      overlapping one never is). Cut the bufferless-fallback rate from 34% to 6.7% in a stress
      config, zero connectivity regressions.
- [x] **True continuous room elevation — middle-ground V1** (`_apply_continuous_elevation`).
      A room becomes an elevation candidate only if every doorway can grow a usable ramp back to
      flat ground (so no unramped entrance can ever meet its raised/lowered floor as a cliff);
      its offset is clamped to whatever fits `Max Ramp Angle` over the shortest available run. A
      cell's world-Z offset is a baked `z_offset` point attribute that Walls and Doors read too,
      so wall boxes and door frames follow the sloped floor instead of floating/clipping.
      One real bug fixed during verification: a ramp corridor could run past a doorway into an
      unrelated third room without ramping it, leaving a cliff exactly at that door — fixed by
      rejecting any corridor cell that is itself a doorway into another room.
      First-pass scope only: single elevated room per opt-in, one flat neighbor, no chained
      multi-room gradients, no multi-doorway rooms. Off by default (`Elevation Chance` = 0).
  - [x] **Multi-doorway rooms.** `_room_elevation_paths` grows one ramp per doorway instead of
        requiring exactly one; if even one doorway can't grow a usable ramp, the whole room stays
        flat. A second real bug surfaced here: two independently-grown ramps could pass each
        individually but still end up running side by side with very different offsets — fixed
        by giving every ramp a 1-cell buffer against any other already-committed ramp cell, the
        same margin rooms already keep from each other.
- [x] **Corridor Stairs** (`wfc_corridor_stairs`, off by default). Alternative to the room-based
      stairwell: a flush 1-tile-wide strip directly in the corridor network instead of a buffered
      room, so walls form on both sides exactly like an ordinary corridor — no separate walkway.
      `_carve_stair_room` already degrades correctly at width 1 with no changes needed; a new
      `_stair_footprint_chain` helper picks the placement chain (room-based or corridor-based)
      shared by both `_connect_levels_with_stairs` and `_ensure_connectivity`'s repair pass.
      **A real interaction bug with continuous elevation was caught during review, before ever
      running a test**: a corridor stair's climb cells carry `room_id == -1`, identically to an
      ordinary corridor cell, but the stair mesh never reads `z_offset` — so an elevation ramp's
      walk-outward pass could have treated a real staircase as flat corridor to slope through, or
      run directly beside one. Fixed by requiring `TILE_FLOOR` specifically (not just any
      walkable tile) for ramp candidates, and rejecting any cell adjacent to a `TILE_STAIR` tile.
- [x] **Ceiling** (`wfc_add_ceiling` + `wfc_ceiling_thickness`, off by default). For FPS-style
      play, an open-top level reads as looking at the sky from inside any room — adds a ceiling
      slab above every walkable tile, GN-driven exactly like the floor (same Instance on Points →
      Realize Instances pipeline, joined in before the existing Merge Distance/material-index
      steps). Skips any point whose upper neighbor is a stairwell's `floor_opening`, via a new
      `ceiling_opening` point attribute, so a stairwell hole can't be silently sealed from above.
      Isometric Mode's existing "strip the top slice" cull step hides the new ceiling
      automatically with no extra wiring — very likely built in anticipation of this feature.
      Verified against live Blender (`tests/blender_headless_test.py`): the GN graph builds and
      evaluates correctly, Add Ceiling adds real geometry, Isometric Mode culls it back down.
- [x] **Props / decoration scattering (Step 5)** — wall-mounted torches (baked-mesh bracket +
      flame cap) each paired with a REAL `bpy.data.lights` Point light at the flame position, so
      they actually illuminate the level; plus floor decoration (crate/barrel/cone placeholders)
      scattered per room. Fully-baked Python mesh, no GN involvement. Everything lands in a
      `Procedural Level Props` collection tree (Torches / Lights / Decoration sub-collections)
      instead of loose objects, so the whole prop layer can be hidden/isolated/deleted
      independently of the structural geometry.
      "Rooms need lights" is a hard guarantee, not just a density knob: every room with a wall
      gets ≥1 torch regardless of the random roll (a forced top-up pass covers any room the first
      pass missed). Decoration placement excludes doorway threshold tiles so nothing blocks a
      passage. Torch/decoration Z follows per-cell `z_offset` exactly like Walls/Doors.
      `_remove_objects_by_prefix` needed generalizing to branch on the object's own `.type`
      (Mesh vs. Light data-block) before cleanup — getting this wrong would have errored or
      silently leaked light data-blocks on every regeneration.
- [x] **Optimization pass: generation speed, runtime light count, wall polycount.**
  - [x] **Generation speed** — Walls/Doors/Stairs/Props each used to read the blueprint back
        per-vertex through Blender's Python/RNA wrapper. New shared `_read_blueprint_points` (plus
        an inlined equivalent in `_read_stair_runs`) switches to `foreach_get`, the standard
        bulk-array-copy pattern for this case. Behavior-preserving refactor only.
  - [x] **Runtime light count** — torch MESH density (Torch Chance, cheap, purely visual) decoupled
        from actual Point light count (Torch Light Chance + Max Lights, the expensive part in a
        real game engine). One light per room stays a hard guarantee, just moved from the mesh
        stage to the light stage — Max Lights only ever trims the *optional* lights, never that
        guaranteed one.
  - [x] **Wall polycount** — `_build_wall_mesh` used one fully-closed box per exposed tile-edge;
        with Organic Irregularity off, adjacent boxes along a straight run are already perfectly
        flush, so merging them changes nothing about the visible surface. New run-merging path
        (gated on `organic_amount <= 0`) groups same-direction exposed edges into contiguous runs,
        broken wherever `z_offset` differs between adjacent cells (a sloped run can't be one flat
        box). Cut wall box count by 56% in a stress sample with zero coverage regressions.
        Doors/Stairs/Props were left untouched — comparatively small object counts already.
- [x] **Real-Blender headless test harness** (`tests/blender_headless_test.py` +
      `run_blender_tests.sh`) — every verification up to this point was `stub_bpy` (a Python-level
      mock, structurally unable to construct or evaluate a Geometry Nodes graph) or manual
      in-viewport testing. This runs the addon inside a real headless Blender process and
      exercises the full pipeline through real `bpy.ops` calls: Blueprint → live Add
      Ceiling/Isometric Mode toggling on the evaluated depsgraph mesh → Walls → Stairs → Doors →
      Props → apply modifier → Separate by Floor. Exits non-zero on any failed check.
      The full pipeline passed end to end against real Blender 5.2.0 LTS — the biggest open
      question hanging over this project (whether any of the GN code actually works) is resolved.
      Discovered a genuine Blender 5.2 API change worth remembering: GN modifier inputs are no
      longer accessible via the old `modifier["Socket_N"]` IDProperty pattern — the working form
      is `modifier.properties.inputs.Socket_N.value`.
  - [x] **Found and fixed a real mesh-winding bug on the very first winding-aware check** — every
        `add_box`-style helper in the file (walls, doors, stairs, ramps, torches, decoration — six
        separate copies of the identical convention) had every face wound backwards: a box's
        bottom face pointed +Z (into itself) and its top face pointed -Z. Invisible for the whole
        project up to now because Blender's Solid shading doesn't cull backfaces by default — it
        would only show up as inside-out geometry in a renderer/game engine that does. Fixed by
        reversing every face's vertex order in all six `add_box` copies.
- [x] **Two real bugs found by actually opening `test_blends/` files** — geometrically valid
      (non-empty, no-exception) meshes are not the same as CORRECTLY POSITIONED meshes; both of
      these passed every prior check and were only caught by a human looking at the output.
  - [x] **Doors placed on/beside the stairs themselves.** `_build_door_mesh` treated any
        same-Z boundary where `room_id` differs as a doorway — correct for "corridor enters
        room," but a stairwell's climb column carries `room_id == -1` too, so the WALKWAY-to-
        climb-column boundary *inside* a stairwell room read as a doorway as well. Fixed by
        threading a `stair_cells` set into `_build_door_mesh` and excluding any boundary that
        touches one.
  - [x] **Stair runs frequently anchored at the wrong end.** `_read_stair_runs` picks a run's
        start tile via an EXACT dict lookup keyed by the `tile_rotation` float, but that value is
        read back from a baked mesh attribute stored as a 32-bit float — a rotation written as the
        exact Python float64 constant `3.1415` can round-trip back as `3.1414999961853027`. The
        exact-equality lookup silently fell through to a wrong-but-valid default direction,
        translating the whole stair mesh to the wrong end of the run (overlapping walls, opening
        away from the solver's actual exit). Simulating the real float32 round-trip showed 78% of
        stair runs got the wrong direction under the old lookup. Fixed with
        `_direction_for_rotation(rot, tolerance=0.01)`, which finds the nearest of the 4 known
        rotation constants instead of requiring exact equality. Added a permanent AABB-overlap
        regression check between every stair tread box and every wall box.
- [x] **GUI reorganized to cut vertical space in the sidebar tab.** User feedback: "low on screen
      space." Merged two separate stair-settings sections into one, and stopped the Rooms section
      (9 properties) from defaulting to open on every panel draw. Paired several previously
      one-per-row properties onto shared rows. No property removed or renamed.
- [x] **"Round" rooms didn't read as round.** User feedback: "there are no round rooms."
      `_carve_room`'s ellipse test was mathematically correct (the exact inscribed circle) but at
      the room sizes this generator actually produces, an exactly-inscribed circle only ever clips
      the 4 extreme-corner tiles no matter how big the room gets — a "round" 3x3 room was
      pixel-identical to a rect one. Fixed by tightening the membership threshold from `<= 1.0` to
      `<= 0.8` — a deliberately smaller circle, so the tile-grid approximation actually carves a
      visible notch at every supported size.
- [x] **New: "Debug: Last Generation Params" panel section + Copy Parameters button.** User
      request: a way to grab the exact settings behind a generated level for a bug report, rather
      than re-describing slider positions from memory. `_update_debug_snapshot` runs at the end of
      every Step operator and writes every current `wfc_*` scene property into a `wfc_debug_params`
      StringProperty, formatted as a `dict(wfc_foo=..., ...)` literal — the same override-dict
      style `tests/generate_test_blends.py`'s `SCENARIOS` list already uses, so a pasted snapshot
      is directly reusable there too. Property names are discovered from `scene.bl_rna.properties`
      rather than hardcoded, so it can't drift out of sync with `register()`.
- [x] **New: Room Shape = CAVE — whole-floor organic cave generation.** User provided a hand-built
      reference file, analyzed headlessly rather than guessed from description: one floor was 113
      floor tiles with **zero** wall tiles — one connected meandering shape, not discrete rooms.
      Reframed this from "a new room shape" to "a new floor-generation mode."
      `_carve_cave_floors` replaces `_scatter_rooms` when `room_shape == 'CAVE'`. A handful of
      "drunkard's walks" (`_carve_cave_tunnel`) wander the grid carving 1-tile tunnel (`room_id
      -1`, identical to an ordinary corridor cell); every walk after the first starts from an
      already-placed chamber, so the network is connected by construction. Each walk ends by
      carving a round chamber — reusing `_carve_room`'s ROUND ellipse verbatim — which gets a real
      `room_id`, exactly like a scattered room. That single choice is what keeps walls/doors/
      stairs/entrance-exit/elevation all working completely unmodified: a door appears wherever a
      chamber meets a tunnel, the same rule that already governs a normal room/corridor boundary.
      Three real bugs surfaced, all found via full BFS-reachability checks (not geometry/overlap
      checks — every one produced a perfectly valid, non-crashing mesh with just an unreachable
      pocket): (1) a walk's own movement bound used the NEXT chamber's margin instead of a fixed
      one, permanently trapping walks that started near a map edge — fixed by reverting to a fixed
      1-tile margin and clamping chamber placement afterward instead; (2) the fixed entrance/exit
      corners are routinely nowhere near a purely-random walk network, and the existing
      last-resort repair filled the gap with one dead-straight corridor spanning most of the map —
      fixed by anchoring chamber 0 at the entrance directly and reaching the exit via a
      target-biased walk; (3) that first anchored-exit fix still looked like a straight line —
      replaced with a genuinely winding target-biased variant of the tunnel walk.
      Known limitations, documented rather than chased further: ignores `sub_levels_per_floor`/
      `split_level_chance`; a floor that's simultaneously entrance and exit only anchors the
      entrance; a rare stray unreachable tile from the ROUND ellipse at extreme aspect ratios
      (pre-existing, equally present in ordinary ROUND rooms). Currently global (every floor
      becomes Cave, not assignable per floor).
- [x] **Cave + Corridor Stairs: stairwells missing a wall on one side.** User feedback: "few
      stairs on lower floor are not good... not enough space around them to walk." Root cause:
      `_find_stair_footprint`'s `margin=0` for Corridor Stairs was uniform in all directions —
      correct for the two travel-axis ends (a corridor is meant to attach flush there), wrong for
      the perpendicular sides (must stay clear, no walkway to absorb an adjacent cell). Rare on
      RECT/ROUND floors, routine on Cave floors where chambers are densely surrounded by their own
      tunnels — confirmed 48% of stair cells exposed before the fix. Two-part fix: a new
      `_corridor_stair_fits` check adds real perpendicular clearance at placement time, and a new
      `_would_expose_stair_side` guard stops the organic tunnel-connector from grazing an existing
      stair's side afterward. Cut the exposure rate to ~7-10% (an accepted residual — two
      independently-placed stairwells occasionally land adjacent to each other, each one's own
      fits-check only validating against what existed at ITS OWN placement time).
- [x] **Major: "Color Rooms/Corridors" (and "Add Ceiling") silently never took effect on a fresh
      generation, regardless of the addon's own default.** Found while building a showcase render
      for the README — it came out flat grey with zero per-room color variation, despite
      `wfc_color_rooms` defaulting to True. Root cause: `create_geometry_nodes_modifier` assigned
      `mod.node_group = node_group` immediately after creating the node group but **before** any
      of its Bool/Float interface sockets existed. Blender initializes a modifier's own per-input
      override at the moment each interface socket is added to a node group already assigned to
      that modifier — using the socket type's built-in zero value, not whatever `.default_value` a
      later line of Python sets. Every property whose intended default matched the type's zero
      value was unaffected; the two that default to something else — Color Rooms/Corridors = True,
      Add Ceiling once toggled on before ever regenerating — silently did nothing. Fixed by
      deferring `mod.node_group = node_group` to the very end of the function, once every
      interface socket's real default already exists.
- [x] **"Separate by Floor" → "Separate by Floor/Room".** User idea: organize the blueprint mesh
      into per-room objects (plus one combined corridor object per floor) inside a real collection
      tree, instead of one flat mesh per floor. Reused the exact `_read_polygon_values` technique
      `OBJECT_OT_SeparateLevelByFloor` already used for `logical_floor` — `room_id` is baked the
      same way, so no new attribute plumbing was needed. New `BLUEPRINT_SPLIT_COLLECTION_NAME`
      collection tree (`Procedural Level Blueprint (Split) > Floor N > Rooms` / `> Corridors`),
      built lazily so an all-corridor or all-room floor doesn't leave an empty collection behind.
- [x] **"Separate by Floor/Room" still showed flat, un-colored rooms after applying the modifier
      first.** User feedback: applying the GN modifier before splitting (the old documented
      precondition) left every floor tile as one object. Root cause: this addon's GN material
      system only ever writes a numeric `material_index` via Set Material Index — it never
      attaches real material references to the geometry, so the actual palette lives entirely on
      the object's pre-existing material slot list. Blender's Convert-to-Mesh/Apply Modifier
      replaces the object's mesh datablock with evaluated geometry that has no slot list of its
      own to inherit, so the previous 30+-material palette silently disappeared the moment a user
      followed the README's own documented steps. Fixed by having the operator do its own
      depsgraph evaluation and explicitly re-attach the ORIGINAL object's material list — removing
      the manual "apply first" step from the workflow entirely, since it was actively the bug.
- [x] **Major: `room_id`/`level_z` were silently corrupted at room/corridor boundaries by Merge By
      Distance — the actual root cause behind "one room made from smaller room pieces."** User
      feedback led to a stress check showing 28 of 39 rooms on one level "fragmented," most into
      pieces scattered across the entire map. The solver's own ground-truth `room_id` grid was
      completely clean — the corruption was downstream, in the mesh: 484 of 1,402 faces (35%) had
      inconsistent `room_id` across their own 4 corner vertices. Root cause: `room_id`/`level_z`
      are POINT-domain attributes broadcast uniformly across a tile's cube instance — fine on
      their own, but `GeometryNodeMergeByDistance` (welding seams between adjacent tile
      primitives) welds a shared corner between TWO DIFFERENT tiles' cubes into ONE vertex, and
      for a non-blendable INT attribute keeps only one of the colliding source values, arbitrarily.
      Fixed at the source: `room_id`, `logical_floor`, and `level_z` are now snapshotted to real
      FACE domain immediately after the floor+ceiling geometry is joined, BEFORE the merge ever
      runs, so every face still only has its own tile's point broadcast across its corners.
  - [x] **Round rooms: a real, narrower bug found on the way to the above.** The ellipse threshold
        could leave a lone corner tile disconnected from the main shape at extreme aspect ratios —
        fixed by keeping only the largest 4-connected group of carved cells.
  - [x] **Stairwell landing pairs: confirmed legitimate, rerouted to Corridors per user request.**
        A room-based stairwell's two landing tiles genuinely share no vertex with each other
        (the stair itself sits between them as a separate tile_id) — now detected and folded into
        that floor's shared Corridors bucket instead of reading as a fragmented "Room" object.
  - [x] **Ceilings double-counted as "fragmentation" once Add Ceiling is on** — caught before it
        shipped. A room's ceiling patch shares its room_id but sits a full `level_height` above its
        floor patch with zero shared geometry, sweeping essentially every room into Corridors under
        the reroute logic above. Fixed with a Z-band check pulling ceiling faces into their own
        per-floor Ceilings bucket before the room/corridor split ever runs.
- [x] **Major: Floor Thickness = 0.0 made every single floor face wind backwards.** User feedback
      with exact repro settings from the Debug Params panel. At Floor Thickness 0.0, all 684 of
      684 floor faces in the repro level pointed -Z, zero pointed +Z. Root cause: at
      floor_thickness=0 the floor cube's top and bottom faces become fully coincident, Merge By
      Distance welds every one of their vertices together, and Blender's own cleanup of the
      resulting fully-overlapping duplicate faces silently keeps only one — consistently the
      downward-facing one. Renders fine with backface culling off (the project's default so far),
      reads as fully transparent from directly above with it on. Fixed by clamping the floor (and
      ceiling) cube's actual thickness to stay at least 3x the live Merge Distance value, so top
      and bottom can never truly coincide while remaining visually flat at any normal distance.
- [x] **New: Wall Height / Level Height / Sub-Levels per Floor now stay mutually consistent.**
      User feedback: raising Sub-Levels per Floor (shrinking per-slice headroom) or Wall Height
      (needing more of it) with no cross-check let walls clip through the floor above. User
      requested the properties themselves stay mutually consistent in the UI rather than silently
      clamping behind the scenes. Implemented via `update=` callbacks on all three properties,
      routed through one `_sync_level_geometry`: whichever property the user just changed is
      treated as their real intent; Level Height is preferred to grow (up to its own max) to make
      room, and Wall Height only shrinks as a last resort. A module-level reentrancy guard stops
      the callbacks from ping-ponging off each other.
  - [x] **Door Height folded into the same sync** — identical bug, spotted by the user immediately
        after the wall fix, generalized to `max(wall_height, door_height)` throughout.
- [x] **`tests/stub_bpy.py` committed** — see the now-checked §3 entry.
- [x] **Style mode gained real per-floor/per-room coloring**, matching what Simple Viewport Colors
      already had. Previously a flat 2-slot system — every corridor on every floor was the exact
      same material, and so was every room. Fixed by generalizing the existing `tint` mechanism
      into three functions mirroring Simple mode's own material-building functions:
      `get_or_create_style_floor_level_materials`, `get_or_create_style_room_materials`, and
      per-style entrance/exit variants. No changes needed to the GN graph's material-index switch,
      since it was already generic over slot count.
- [x] **GUI reorganized into tabs.** User feedback: "izs a lot of dropdowns, maybe tabs??" — the
      panel had grown to 8 stacked collapsible sections. Added a `wfc_active_tab` EnumProperty
      (SETUP/WALLS/STAIRS/DOORS/PROPS) drawn as an icon-only button row at the top; `draw()`
      dispatches to one of five `_draw_*_tab` methods, each ending in that step's own Generate
      button. Debug stays outside the tab system, persistent at the bottom. Behavior-preserving —
      every existing property reference, row grouping, and enabled-state condition moved verbatim.
- [x] **`generate_test_blends.py`'s SCENARIOS expanded from 13 to 20** — covering everything this
      session had added that didn't yet have a scenario to look at: Style materials on Cave
      Rock/Open Area, Floor Thickness 0.0, Cave + Add Ceiling together, Sub-Levels=3 with default
      heights (to show Level Height auto-growing), a stress/showcase-scale map, and one scenario
      that also runs Separate by Floor/Room afterward.
- [x] **Room/material display saga — a chain of increasingly deep fixes for "rooms don't show
      distinct colors," each one real and necessary, none of them alone sufficient.** Traced across
      several rounds of user feedback on the same underlying symptom:
  - [x] **UV map missing entirely.** Solid Shading's "Texture" color mode (unlike "Material," which
        reads `diffuse_color` directly) samples an Image Texture node via a real UV map, with no
        Generated-coordinates fallback the way EEVEE has — the addon never generated one anywhere.
        Fixed with a `GeometryNodeStoreNamedAttribute` UV store (flat constant `(0.5, 0.5)`, since
        every Simple Viewport Colors swatch is a single flat color, so the actual UV value doesn't
        matter for correctness). Two real bugs found verifying this: `mesh.uv_layers.active` reads
        None for a GN-baked UV attribute (fixed by indexing `uv_layers[0]` directly), and
        `_mesh_from_faces` (every Separate by Floor/Room split) never carried UV data over at all
        (`from_pydata()` doesn't preserve it).
  - [x] **Same gap in every other baked mesh.** The fix above only touched the Blueprint's GN
        graph and `_mesh_from_faces` — Walls/Doors/Stairs/Ramps/Torches/Decoration each build
        their own hand-rolled mesh with no UV at all. New shared `_add_flat_uv_map` called in all
        6 builder functions.
  - [x] **The actual root cause: `mesh.materials.clear()` silently resets every polygon's
        `material_index` to 0.** Both UV fixes were real and necessary but not this bug — every
        material_index/diffuse_color check kept coming back correct right up until the moment
        `OBJECT_OT_SeparateLevelByFloor` rebuilt the evaluated mesh's material slot list. Traced
        via real viewport screenshots down to a minimal repro: `.clear()` resets material_index as
        an undocumented side effect of emptying the slot list, and re-appending the same materials
        afterward does not restore it. Every split room object then inherited material_index 0
        uniformly. Fixed by saving each polygon's material_index into a plain list before touching
        `mesh.materials`, restoring it afterward.
  - [x] **`viewport_color` Color Attribute — an attribute-based alternative to material-slot
        coloring.** User's own idea, after the fix above: Solid Shading's "Attribute" color mode
        reads a mesh's active Color Attribute directly, with no dependency on UV, material slots,
        or material_index at all. New shared `_add_viewport_color_attribute` fills a
        `FLOAT_COLOR`/`CORNER` attribute from each polygon's resolved material's `diffuse_color`,
        wired into every split object and all 6 baked-mesh types. Surfaced one real gap: style
        materials never set `diffuse_color` at all (their look comes purely from the node tree) —
        fixed at the source in `_finish_material`.
  - [x] **`_mesh_from_faces` was copying every split object's ENTIRE source material list**, not
        just what that object's own faces use — a Room object's Properties panel showed a
        floor-level color instead of its own, even though it rendered correctly (Blender always
        shows the object's ACTIVE slot, index 0, which was always `LA_Floor_Level_0` with the full
        list copied). Fixed by compacting the copied list to only the materials the object's own
        faces actually reference, remapping material_index into the new local slot space.
  - [x] **Separate by Floor/Room now refuses to run if its GN modifier was already applied**,
        instead of silently producing empty material slots — a manual pre-apply (the old,
        no-longer-needed precondition) puts the object in exactly the state the compaction fix
        above can't recover from. Refuses with a clear, actionable error instead of degrading
        silently.
  - [x] **Real crash running the workflow a second time** — `RuntimeError: Collection '...'
        already in collection '...'`. Blender leaves the outliner's active collection sitting
        inside a previous run's own nested tree; running the operator again tried to link that
        same top-level collection as a child of its own descendant. Fixed at
        `_get_or_create_collection`: checks whether linking would create a cycle and, if so,
        leaves the collection wherever it already is instead of attempting the relink.
  - [x] **Corridor Stairs residual wall gap, fixed for real at wall-generation time** — the
        remaining ~7-10% exposure (see the Cave + Corridor Stairs entry above) came from a
        corridor pathfound AFTER a stairwell's own placement-time check ran. Rather than chase
        this further at placement time, a new `forced_wall_edges` parameter on `_build_wall_mesh`
        forces a wall on a stair cell's two perpendicular sides regardless of neighbor walkability,
        derived from the already-baked `tile_id`/`tile_rotation` attributes with no solver changes.
  - [x] **Hidden-face removal for Walls/Doors, then Stairs/Ramps/Decoration.** Every wall box's
        bottom face, every stair tread/ramp segment's bottom, and every decoration prop's base is
        always coincident with the floor beneath it — genuinely never visible — so each is now
        skipped unconditionally (a door's lintel keeps its bottom face, since that one actually is
        visible from underneath). Torches were investigated and deliberately left untouched — both
        boxes are wall-mounted, floating above the floor, not floor-touching at all.
  - [x] **Per-Floor Overrides.** User picked "breakpoints with gradients": a short list of
        (floor_index, room_size_min/max, room_shape, style) rows where numeric values (room size)
        interpolate smoothly between rows and discrete values (shape, style) switch at the row's
        floor. New `WFC_FloorProfile` PropertyGroup + UIList + Add/Remove operators. An empty list
        (the default) falls back to the flat Rooms-section values everywhere, byte-identical to
        every generation before this feature existed. Deliberately excludes 'Cave' from per-floor
        options — per-floor profiles are ignored entirely whenever the global Room Shape is Cave.
        Style-mode materials generalized the same way (`style_for_slot`/`style_for_room`
        resolvers), so different floor-level ramp slots and rooms can each use a different
        procedural shader, still tinted by that slot/room's own palette color. Also caught and
        fixed a real gap in `tests/stub_bpy.py`: it never defined `CollectionProperty`,
        `PropertyGroup`, or `UIList` at all, so the addon failed to even import under it once this
        feature's classes were added.
- [x] **Trim-sheet-ready UVs.** Every baked mesh used to write a flat constant `(0.5, 0.5)` UV —
      correct for a flat-color swatch, but meant any texture with real detail (a trim sheet, a
      tiling brick/rock material) sampled one pixel across an entire wall run. Replaced with real
      box-mapped UVs (`_add_planar_uv_map`), projecting each quad onto whichever of XY/XZ/YZ its
      face normal is most aligned with, using its actual world-space position. New `wfc_uv_tile_size`
      scene property controls meters-per-UV-tile. Deliberately does not touch the Blueprint floor's
      own GN-driven UV — GN changes are the exact "uncertain live-API behavior" category this addon
      has avoided since the walls/stairs pivot.
- [x] **Rounded / filleted wall corners (v1, Bevel-modifier based).** New opt-in `wfc_wall_corner_
      rounding` + `wfc_wall_corner_radius` adds a live, angle-limited Bevel modifier to the wall
      object(s) rather than hand-deriving per-corner fillet geometry — chosen because Bevel is a
      long-stable ordinary mesh modifier, not Geometry Nodes, the same risk category this addon has
      deliberately avoided elsewhere. Known limitation: angle-limited selection can't distinguish a
      true building corner from a wall run simply ending at a doorway jamb, so it rounds both.
- [x] **Freeze for Texture Work.** Every Step operator deletes-and-rebuilds its objects by fixed
      name each time it runs, so any material/texture work done by hand on the live objects gets
      silently wiped the moment Generate is clicked again. New `OBJECT_OT_FreezeForTextureWork`
      renames every currently-generated Blueprint/Walls/Stairs/Doors/Torches/Decoration/Light
      object into a new `Frozen - Seed{n}` collection, with a copy of `scene.wfc_debug_params`
      stashed on the collection (the live property gets overwritten by the next generation).
      Deliberately a rename, not a duplicate — no new datablocks, so freezing is nearly free.
      **Real bug caught by this feature's own headless test:** the first version appended the
      frozen tag to the end of each object's name, but `_objects_matching_prefix`'s match is
      front-anchored (`startswith(base_name + "_")`), so a Per Floor/Per Stair grouped object
      (already named e.g. `Procedural_Level_Stairs_Floor2_02`) kept matching regardless of
      anything appended — a frozen grouped object would have been silently deleted on the next
      regeneration. Fixed by prepending the tag instead, which changes what the name STARTS WITH.
- [x] **Arched doors + Entrance/Exit Gates.** New `wfc_door_style` (Flat/Round/Pointed) replaces
      an ordinary doorway's flat lintel with a stepped arch silhouette when set; Entrance and Exit
      each get their own fixed, larger, always-arched "Gate" regardless of `wfc_door_style`,
      reusing the existing Entrance/Exit marker materials (green/red) so the two read as landmarks
      distinct from ordinary doors in every configuration. The arch is built as
      `DOOR_ARCH_SEGMENTS` small axis-aligned boxes stepping up to a curve profile (a half-ellipse
      for Round; a generalized two-centered/Gothic construction for Pointed, solved for an
      arbitrary apex height rather than the classic fixed equilateral proportion) — deliberately
      reusing the same already-verified `add_box` winding instead of hand-deriving new winding for
      a smoothly curved surface. Entrance/Exit gates are a separate placement pass keyed off the
      cell's own exposed side (same exposure check `_build_wall_mesh` uses), not the ordinary
      room_id-boundary doorway logic — the entrance/exit cell's own room_id is -1 like any corridor
      cell, so it usually wouldn't get an ordinary doorway there at all. Verified against real
      Blender 5.2.0 LTS (new material-index/geometry regression checks) and visually via rendered
      close-ups: confirmed a real, correctly-shaped stepped arch (not flat, not degenerate) for
      both styles, and confirmed Round vs. Pointed are genuinely different curves (Pointed climbs
      measurably steeper and has a real tangent discontinuity at the apex, not just a cosmetic
      label) via direct numeric comparison of the two profile functions.
- [x] **Bent stairwells (L/U switchback with one landing).** New `wfc_stair_bend_chance` (0 =
      off, byte-identical to every generation before this feature existed) and
      `wfc_stair_bend_style` (Random/L/U). Confirmed the scoping simplification held: room
      RESERVATION is untouched — `_find_stair_footprint`/`_room_fits` still just search for and
      reserve one rectangle exactly as before; only what gets carved inside it changed. New
      `_carve_bent_stair_path` carves two straight segments joined by one flat landing tile (a
      plain floor cell, not a stair cell) instead of one straight center line; a 90° turn (L)
      just changes direction at the landing, a 180° turn (U) offsets sideways by
      `BENT_STAIR_LANE_OFFSET` into a second parallel lane (reversing straight back would walk
      through the first segment's own already-carved tiles). The landing's world-Z is baked into
      `cell_z_offset` proportionally to how much of the total climb the first segment alone
      covers — the same mechanism `_apply_continuous_elevation` already uses for elevated rooms,
      so Walls/Doors pick up the landing's correct height for free. Run data changed shape from a
      flat `(x,y,z,rot,length)` tuple to `{'z': z, 'segments': [...]}` — a straight run is just the
      1-segment case, unchanged behavior; `_read_stair_runs`, `_build_stair_mesh`, and
      `_build_ramp_mesh` all generalized to walk a list of segments, carrying height/step count
      cumulatively across the join. **Three real bugs found and fixed during this build, in
      increasing order of subtlety:**
      1. `WFC_Level_Solver.__init__` accepted a `level_height` constructor argument but never
         actually stored it (`self.level_height` didn't exist) — harmless until the landing's
         proportional-height math needed to read it back, at which point it would have been an
         `AttributeError`. Separately, the Blueprint operator was passing `scene.wfc_level_height`
         (the full logical floor height) to that same constructor argument instead of
         `_fine_level_height(scene)` (the real per-fine-slice height) — again harmless while
         unused, but would have made every landing's height wrong by a factor of
         `sub_levels_per_floor` once it became load-bearing. Both fixed together.
      2. The very first version of `_carve_bent_stair_path`'s ceiling-hole placement only added
         the tile adjacent to segment 2's final step to `floor_openings`, not the final step's own
         tile — unlike the straight-run convention, which always includes both. The climb would
         have dead-ended into a solid ceiling.
      3. **The subtle one, caught by the automated wall-overlap regression test, not by eye:**
         segment 1 is centered on its own perpendicular axis by construction
         (`stair_perp_idx = size_perp // 2`), so it always has a free walkway tile on both sides
         within the reserved rectangle — exactly the guarantee a straight run already gets for
         free. Segment 2's perpendicular axis is the ORIGINAL along-axis, and its position on that
         axis is just wherever the landing happened to land (`entry_offset + climb1_len`), with no
         such guarantee — a segment 2 tread could end up flush against the rectangle's own edge,
         and the wall built along that edge would land right on top of the tread instead of past
         it. Fixed by requiring every cell in both segments to have a free tile on both
         perpendicular sides within the rectangle (`_has_perp_buffer`), bailing out to an ordinary
         straight run instead of carving a bent path that overlaps a wall.
      Verified against real Blender 5.2.0 LTS: seeded solver-level stress trials (BFS
      reachability with bending forced on, landing z-offset range), a real pipeline pass (AABB
      overlap check between stair tread boxes and wall boxes), and visually — a rendered top-down
      close-up (floor geometry hidden to avoid z-fighting with the tread boxes at the same base Z)
      showing a real L-shaped run: two 4-tread flights meeting exactly at their shared corner, one
      climbing along X and the other along Y, continuous rise from the floor to the next level.
- [x] **One-click glTF/GLB export.** New `OBJECT_OT_ExportLevelGLTF` (new Export tab, 6th
      alongside Setup/Walls/Stairs/Doors/Props) selects every currently-generated object
      (Blueprint/Walls/Stairs/Doors/Torches/Decoration, and optionally Lights) via the exact same
      `_objects_matching_prefix` helper `OBJECT_OT_FreezeForTextureWork` already relies on — so
      export always agrees with the rest of the addon about what "the level" is, regardless of
      Per Floor/Per Stair grouping mode — and hands them straight to Blender's own
      `bpy.ops.export_scene.gltf` with `use_selection=True, export_apply=True`. `export_apply`
      bakes the Blueprint's live Geometry Nodes modifier (and Walls' optional Round Corners Bevel
      modifier) into real exported mesh data; glTF's own exporter handles the Blender-Z-up →
      glTF-Y-up axis conversion and Principled BSDF → PBR material mapping itself, so there's zero
      addon-side geometry or material translation code at all — the whole feature is selection
      logic plus one well-established Blender operator call.

      Deliberately **glTF/GLB only, not FBX** — glTF's axis convention is standardized and
      engine-agnostic (no per-engine "-Z Forward/Y Up" fiddling the way FBX needs), and it maps
      Principled BSDF straight to its own PBR spec, which is exactly what this addon's materials
      already are. FBX would be a reasonable follow-up but carries meaningfully more surface area
      to get subtly wrong for a first pass. Two settings: **Binary (.glb)** (default on — one
      self-contained file) vs. off (`.gltf` + `.bin` + a textures folder), and **Include Lights**
      (default on — exports the real Point lights from Step 5 as glTF `KHR_lights_punctual`).

      Every real operator property used (`use_selection`, `export_apply`, `export_lights`,
      `export_format`'s `'GLB'`/`'GLTF_SEPARATE'` values) was confirmed by introspecting the
      actual installed Blender 5.2.0's `bpy.ops.export_scene.gltf` operator RNA directly, not
      assumed from memory — this project's standing rule about not guessing Blender API shape.
      `io_scene_gltf2` is core-bundled and enabled by default, confirmed via `addon_utils.check`;
      the operator still checks `hasattr(bpy.ops.export_scene, "gltf")` at runtime and refuses
      with a clear message if it's ever been disabled by hand, rather than crashing.

      Verified against real Blender 5.2.0 LTS: not just "operator returned FINISHED" but a real
      round-trip — the exported `.glb` is immediately re-imported via Blender's own
      `bpy.ops.import_scene.gltf` and checked for actual non-empty mesh geometry and (with
      Include Lights on) real light objects, confirming the file contains a real level, not an
      empty shell. Also verified: the refusal path with nothing generated reports a clear error
      instead of a silent no-op, and Include Lights off round-trips with zero lights. All checks
      passed on the first real-Blender run.
- [x] **Collision mesh export.** Follow-up to glTF export above: without collision geometry, an
      exported level looks right in-engine but can't be walked on unless the target engine happens
      to auto-generate collision from complex static geometry. New
      `OBJECT_OT_ExportLevelCollisionGLTF` (second button, same Export tab) — deliberately **a
      filtered re-export of already-built geometry**, not a freshly-built simplified/merged mesh:
      there's no existing floor-region box-merging code anywhere in this file (confirmed by
      reading it directly), and it would be a materially harder 2D problem than
      `_build_wall_mesh`'s existing 1D per-line wall run-merge. Re-exporting the already-verified
      visual meshes carries zero new geometry-correctness risk, and for static level architecture
      (not moving physics props) using the real level mesh directly as collision is standard
      practice in Unity/Unreal/Godot alike.

      Exports Blueprint (floor) + Walls + Stairs only — deliberately excludes Doors, Torches,
      Decoration, and Lights. Doors are a walk-through frame overlaid on an already-open gap
      (`_build_wall_mesh`'s `is_exposed` never places a wall box between two walkable cells), so
      leaving them out of collision doesn't reopen anything — it just avoids the door posts
      themselves becoming a minor physical snag at every doorway, matching a doorway's own
      "walk-through by design" intent. Torches/Decoration are cosmetic and shouldn't block
      movement; Lights obviously don't belong in a collision mesh. Stairwell holes
      (`floor_openings`) are handled correctly for free, with zero new code, since the Blueprint's
      own GN graph already skips floor/ceiling geometry there (the same mechanism the Add Ceiling
      feature's own hole-skipping already relies on).

      Deliberately **no hand-baked navmesh** — once collision geometry is exported, Unity/Unreal/
      Godot can all auto-bake their own navmesh from it at import/edit time, so a hand-rolled one
      here would duplicate something the target engine already does for free, for a narrower
      audience (only matters with AI/NPCs).

      Shares `_gltf_export_targets`/`_run_gltf_export`, two small helpers factored out of the main
      export operator during this feature (object-gathering and the select-and-call-exporter
      plumbing) so both operators can never disagree about what "the level" or "how to export it"
      means. The main export operator's own behavior is unchanged by the refactor — confirmed by
      its existing round-trip test still passing unmodified. `invoke()` suggests a
      `<blend-name>_collision.glb` default filename (distinct from the main export's own default)
      so the two buttons don't tempt an accidental overwrite of one export with the other.

      Verified against real Blender 5.2.0 LTS: the same round-trip discipline as the main export
      (re-import via `bpy.ops.import_scene.gltf`, confirm real non-empty mesh geometry) plus two
      checks specific to this feature — confirming the exclusion actually took effect, not just
      "some geometry exists": zero light objects come back, and none of the round-tripped objects'
      names match the Doors/Torches/Decoration prefixes. All checks passed on the first
      real-Blender run.

- [x] **Real Round-room shape (n-gon floor + wall ring) + Presets.** Ported back from a sibling
      addon, BrickSpitter, which itself originally ported `_carve_room`'s ellipse-carving
      technique FROM this file — BrickSpitter later upgraded its own Round rooms to a real merged
      n-gon shape and asked "level architect could use this feature too."

      The floor is Geometry-Nodes-driven here (one small cube instanced per point in the
      Blueprint's own shared point cloud, which every later step — Walls, Doors, Stairs, Torches,
      Decoration, Separate by Floor/Room, both exports — reads back from as its ground truth), a
      meaningfully different architecture from BrickSpitter's plain-mesh-everything approach.
      Removing/hiding a Round room's floor points from that cloud would silently break every one
      of those downstream readers. Chosen design instead **never touches the Blueprint or its GN
      graph at all**: a new `_build_round_room_floor_mesh` draws a real n-gon disc as a separate,
      purely cosmetic overlay (`ROUND_FLOOR_OBJECT_NAME`, `Procedural_Level_RoundFloors`) that
      fully covers the existing blocky floor cubes from a hair above (the disc's radius always
      uses the room's FULL bounding-box ellipse, larger than `_carve_room`'s own tightened `<=0.8`
      carving threshold, so it's guaranteed to cover every carved tile with no visible gap at the
      edge). `WFC_Level_Solver` gained `self.room_shapes`/`self.room_cells` (small, additive) to
      track this.

      Walls were ALREADY a separate baked-Python object here (same architecture BrickSpitter
      itself uses), so the wall-ring half is a much more direct port: new `_build_round_room_walls_mesh`
      builds one oriented `add_wall_segment` per polygon edge of a Round room's rim, skipping
      whichever edge(s) sit where a corridor/doorway actually connects (a room cell bordering a
      walkable cell belonging to a different room is a real doorway; its angle around the room's
      own ellipse picks which edge to open) — same technique BrickSpitter's own fix used.
      `_build_wall_mesh` gained one new optional `skip_cells` param so a Round room's cells still
      count as walkable for a NEIGHBORING room's own exposed-edge check, they just don't get their
      own blocky box built (that's what `_build_round_room_walls_mesh` builds instead). Room
      bounding-box + shape metadata is baked onto the Blueprint object as a `gla_room_meta` JSON
      custom property at Step 1 time, since `OBJECT_OT_GenerateLevelWalls` deliberately never
      re-runs the solver.

      **A real naming-collision bug found and fixed during verification**: the new wall-ring
      object was first named `Procedural_Level_Walls_Round`, which — since `_objects_matching_prefix`
      matches on `startswith(base_name + "_")` — accidentally ALSO matched `WALLS_OBJECT_NAME`'s
      own prefix, causing it to be picked up (and renamed/frozen) TWICE by anything iterating both
      names, including `OBJECT_OT_FreezeForTextureWork`. Caught by the existing Freeze test's own
      exact-name-set assertion, not a new check written for this feature. Renamed to
      `Procedural_Level_RoundWalls`, which shares no prefix with any existing base name.

      Also new: **Presets** (`PRESETS` dict + `OBJECT_OT_ApplyGLAPreset`, mirroring BrickSpitter's
      own `OBJECT_OT_ApplyPreset` pattern exactly) — four one-click buttons (Isometric, FPS /
      Immersive-Sim, Compact Roguelike, Megadungeon) bundling Width/Rooms/Room Shape/Sub-Levels/
      Elevation/Stairs/Wall/Door/Torch settings tuned per target camera/genre. Only ever sets flat
      `wfc_*` properties; Per-Floor Overrides (`wfc_floor_profiles`) are left untouched. **A real
      preset-design bug found via the same test suite**: the FPS and Megadungeon presets'
      originally-chosen `wfc_level_height` values were too small for their own
      `wfc_sub_levels_per_floor` × `wfc_wall_height` combination, so the existing Wall/Door/Level
      Height cross-consistency system (see §2's own entry on that feature) correctly auto-grew
      Level Height to compensate — caught because the test asserted the EXACT value each preset
      requested, not what it turned out to need. Fixed by picking preset values already consistent
      with that constraint (`level_height >= sub_levels_per_floor * wall_height`) instead of
      relying on the auto-grow.

      Verified: offline (`stub_bpy`, extended with a `bpy_extras.io_utils.ExportHelper` mock and a
      fuller mesh-loop/UV-layer mock — both latent gaps this was the first attempt to offline-test
      `_build_wall_mesh`/the new functions directly, not pre-existing bugs) — 800 seeded solver
      trials confirming `room_shapes`/`room_cells` populated for every real room, 400 trials
      confirming `skip_cells` never affects a non-skipped cell's own exposed-edge wall, 400 trials
      confirming the floor/wall-ring builders produce sane geometry with real openings. Real
      Blender 5.2.0 LTS: the FULL pre-existing 1700+-line suite still passes completely unmodified
      (this suite's own baseline has used `wfc_room_shape='MIXED'` throughout from the start, so
      Round rooms were already exercised end-to-end against every other system before this feature
      even added its own dedicated checks) plus new checks — exact RoundFloors face count/vertices-
      per-face, RoundWalls has fewer faces than a fully-sealed ring (real openings), all 4 Presets
      apply then run the complete pipeline to real geometry. Visual: 6 new `generate_test_blends.py`
      scenarios — Round at 4 and 24 `wfc_room_shape_sides` (visibly diamond vs. smooth circle,
      floor and wall ring matching exactly) and one per Preset.

      Known limitation (fixed next, see below): door frames stay straight/axis-aligned even
      against a now-curved wall.

- [x] **Curved door frames for Round rooms.** Closes the known limitation the Round-shape pass
      above left open, by request right after it shipped.

      `_build_door_mesh`'s existing doorway detection (a `room_id` boundary crossing between two
      walkable cells) is independent of wall shape, so it already places doors at the CORRECT
      locations against a curved wall — only the frame's own geometry was wrong (always a straight
      axis-aligned box). New `_build_round_room_doors_mesh` recomputes each Round room's open rim
      edges the exact same way `_build_round_room_walls_mesh` already does (so a door always lands
      exactly where the wall ring's own gap is, by construction), then builds a frame ORIENTED
      along that edge's own tangent direction — new `add_oriented_box` generalizes
      `_build_door_mesh`'s own `add_box` from an axis-aligned footprint to an arbitrarily-rotated
      one (same winding, just a rotated footprint quad), reused for both posts and the flat
      lintel. The stepped arch silhouette (Round/Pointed Door Style) needed the same treatment:
      new `add_arch_silhouette_oriented` expresses the existing profile-stepping technique in the
      doorway's own local (tangent, normal) basis instead of a hardcoded world X/Y axis --
      `add_oriented_box` already derives the perpendicular/normal from whichever two tangent-
      direction points it's given, so no separate normal-vector plumbing was needed.

      `_build_door_mesh` gained one new optional `skip_room_ids` param (mirrors `_build_wall_mesh`'s
      own `skip_cells`) so a boundary touching a Round room on either side is skipped by the
      straight-axis pass entirely — otherwise a Round room's real doorway would get BOTH a straight
      frame (old pass, wrong shape) and an angled one (new pass) stacked on top of each other.
      Entrance/Exit Gates are untouched — they're fixed, always-arched, map-corner landmarks
      unrelated to per-room doorway shape, so they stay on `_build_door_mesh`'s existing pass
      regardless of which room type they're near.

      Verified: offline (`stub_bpy`) — 400 more seeded trials (reusing the same 8-Round-room setup
      the floor/wall-ring trials already use) confirming the builder never crashes and every
      resulting vertex sits close to SOME Round room's own ellipse rim (a normalized radial-
      distance check, loose enough to allow for post/lintel thickness) — the same check, run again
      with Door Style Round/Pointed, confirms the oriented arch path specifically. Real Blender
      5.2.0 LTS: the full pre-existing suite still passes unmodified; new checks add the same
      rim-distance verification against real evaluated geometry, plus Round/Pointed Door Style
      exercised specifically against Round rooms (the arch-silhouette path the FLAT-only check
      above doesn't reach), plus RoundDoors added to the export-target check. Visual: a close-up
      render (not one of the regular `generate_test_blends.py` scenarios, whose top-down framing is
      too zoomed-out to show doorway-level detail) confirmed the frame visibly follows the wall's
      curve right at the opening, not standing at a mismatched straight angle against it.

- [x] **Panel reorganisation (0.43.0).** Setup/Walls split into sections (Floors & Elevation, Advanced, Tools, Shape/Masonry/Windows); tab enum is now SETUP/WALLS/CONNECTIONS/PROPS/EXPORT/STRUCTURES plus `wfc_structure_kind` (Tower/Castle); `OBJECT_OT_GenerateAllSteps` runs Steps 1-5 (confirm via `invoke_confirm` when `_level_step_done` finds output, Step 3 skipped when a level has no stairs); Step buttons show a check mark. `tests/blender_headless_test.py` draws every tab on a stub layout.
- [x] **Furniture, tints, sub-levels (0.42.0).** `room_tint_map`: greedy colouring of rooms by adjacency (any two cells of
      different rooms within 2 tiles, same level), each room trying tints from its own preferred slot. Sub-level packages:
      `_band_copy` keeps the faces whose CENTRE lies in [z*fh-0.15, (z+1)*fh-0.15) -- a stair run straddling the boundary
      goes to the lower level, so the upper level's geometry can start up to ~0.4 m below its floor (the test allows
      0.45). Furniture layouts are pure functions (`_tower_interior_props`, `_keep_hall_layout`) reused by the mesh
      operator, the package and the walk-cell exclusion; names avoid the `Procedural_Level_Tower`/`_Castle` prefixes that
      `_remove_objects_by_prefix` and the tests' prefix counts match on. Chest bounds (lid 0.37) are wider than the body:
      the first layout poked 7 cm through the hall wall. Not done: tower furniture for castle towers, prop-aware stairs.
- [x] **Interior finishing (0.41.0).** `step_blocks_at(deg, width)` mirrors `_stairs` (same step count/rise/start) and
      returns the (bottom, top) of every step in front of a wall point; `add_window` searches sill shifts of +-0.1 m
      steps inside the storey with a 0.12 m margin each side. Railing: a 0.12 m wide wedge at the lane's inner radius per
      step, plus wedges round each slab hole's inner arc. Lanterns hang from the slab underside on the axis (chain
      and body as four wedge quadrants); the Point lights are separate objects named `Procedural_Level_LanternLight_*`
      (NOT the Props prefix, so regenerating props neither deletes them nor lists them in a level package; the
      first name `...TowerLight...` shared the tower object's prefix, and `_remove_objects_by_prefix` and the tests'
      prefix counts swallowed them). Keep hall: floor quad plus ceiling slab (two quads) at kh - 1.0, the same height
      the wall caps use. Tests that probe the empty tower axis must switch the lanterns off. Not done: props inside
      tower storeys, stairs to the keep roof, hall furniture.
- [x] **Tower / castle brick colour (0.40.0).** `_remap_soup_materials` for a single soup (tower), `mat_map` per part for the
      castle (`part_map`: one tint, or Mixed = walls 1, keep 5, towers 2/3/4/6 by index). Any direct `poly(..., mat)` call
      outside the builders (the courtyard slab) must use the stone slot of the list in use -- slot 1 means "tint 1" once the
      8-slot list is active.
- [x] **Room brick colours + stone door frames (0.39.0).** `_TowerMesh.append(..., mat_map)` remaps the builders' slot 0
      (brick) / 1 (stone) per room: slot = `brick_tint_slot(room_id)` (0 for corridors, 1 + rid % (N-1) for rooms), stone
      is slot N. Material list = `masonry_material_list(room_colors)`. The first idea, multiplying the albedo by an RGB
      tint, barely changed the red-brown brick (blue-grey times red is still brown); Hue/Saturation/Value works, with
      Blender's hue convention (0.5 = no shift; brick hue is ~0.05, so parameter h shifts it by h - 0.5). The Mix node's
      A/B/Result sockets exist once per data type (pick by `.type`, not by name) -- no longer needed after the switch.
      Door frames: with Masonry walls slot 0 of the door object becomes the stone material and the UV tile size
      TOWER_TILE_W; panels keep `LA_Door`. Not done: per-room tint for tower/castle, tint cycling that avoids two
      neighbouring rooms sharing a colour, brick colour from a user palette.
- [x] **Masonry level walls (0.38.0).** `_build_masonry_wall_mesh` reuses `_WallRunBuilder` per merged run of exposed edges
      (same merge rule as the boxes path: consecutive cells, equal elevation offset, same direction and line). Local frame
      -> world: rotation theta = atan2(dx, -dy) so local -y points outward; start point from the run's low/high cell
      depending on the sign of u. Corner detection from a map of half-tile corner points to the axes of the exposed edge
      segments meeting there. The first version extended BOTH runs at a corner by half a thickness: the overlapping
      coplanar caps self-shadowed to black squares in Cycles (and would z-fight anywhere); now only the horizontal-axis
      run extends and the vertical one is trimmed. Windows: `add_opening` may reject an opening that does not fit under
      the wall top, so the builder returns the accepted window edges and the frame/glass object is built for those only.
      Not done: masonry for stair/corridor-stair forced walls beyond the same path, per-room brick colour, doors set
      into masonry with stone frames (door frames are still the old boxes), props placed against the textured walls
      are unchanged.
- [x] **Per-floor packages (0.37.0).** Floors are separate locations on the engine side, which avoids a y-aware walker,
      occlusion of upper floors and picking planes: each floor's glb holds only its objects (`_Floor<k>` name match;
      torch mesh left out, lights/props come from the JSON), stairs become fade links. Stair geometry used: a stair
      cell (x, y, z) with direction d climbs to the landing (x+d, z+1); the landing room is open above the stair cell
      itself, so the way back down is the cell (x, y, z+1) arriving at (x-d, z). Stairs whose landing is not walkable are
      skipped. Pitfalls: Separate by Floor/Room deletes the Blueprint (hence the cache on the scene); sub-levels > 1 are
      refused; one floor of the first seed tried had no usable stair (seed 9), so generate and check `stair_links`. Vampire
      side: the importer wires `stairs_out`/`arrivals`; a trigger arms only after the player has stepped 2 m away from
      every trigger (an arrival one tile from the trigger must not bounce back); door panels need the hinge-origin
      transform composed by hand when the scene is not in the tree yet (global_transform is identity there).
- [x] **Castle areas (0.36.0).** `_castle_package_rooms`: four anchor points computed from the same keep geometry as
      the mesh builder, snapped to the nearest walkable cell. Lesson from the Vampire side: a story prop standing in
      the one-cell-wide strip in front of the keep wall blocked the only route between the yards (A* ignores
      blockers, the actor then steers into them) -- props that belong to a wall must be 0.25 m radius (no blocker)
      and pushed into the wall, not left on the walkable cell.
- [x] **Props in the package (0.35.0).** Props op stores `gla_props` on the decoration object; the package turns it into
      `props` (engine axes). Architect props face +X; Vampire models face +Z, so a loader rotates by yaw + 90 deg.
      Vampire blockers only for the big ones (a table, coffin, tomb...), none for chairs/candelabra, and `--dungeontest`
      still reaches every room centre.
- [x] **Castle package + story hooks (0.34.0).** `_castle_walk_cells` samples a 0.5 m grid against the same footprints
      `_build_castle_mesh` uses (curtain-wall inset, tower circles + margin, keep box + margin, gate corridor |x| <= 1.1,
      apron |x| <= 6); the keep/tower constants are duplicated from the mesh builder on purpose (change both).
      Vampire side: `Dungeon.inject` adds a door prop to a STORY location at build time from the dungeon json's
      `entrance_from`, so world.json and the story validator never see it (the validator rejects unknown `go`
      targets); `links.exit_to` for the level's exit tile; walking back onto the entrance tile after leaving a 4 m
      radius returns to the story location. Verified in the engine: `--dungeonlinktest` (chapel_crypt -> dungeon_crypt
      -> back), `--dungeontest` on the castle (7 goals) and all story/arc replays still pass.
      Open: castle interior (keep), tower floors in the walk data, several floors, props as Vampire assets, doors that
      open, a story reason for each generated place.

- [x] **Game package export + Vampire loader (0.33.0).** `_merge_cells_to_rects` (rows of runs, equal runs on
      consecutive rows stacked; exact), `_build_game_package` (pure data; engine axes via `_to_engine`),
      `OBJECT_OT_ExportGamePackage` (forces a self-contained .glb, restores the user's Binary setting).
      Vampire side, in the other project: `scripts/dungeon.gd`, `Location.build_dungeon` on top of the region
      machinery, `shaders/cutaway.gdshader`, `pipeline/import_dungeon.py`, `--dungeontest`. Lessons: (a) the
      region pathfinder routes through the CENTRE of rectangle overlaps, which for adjacent corridor/room
      rectangles lies on a wall edge and the clamp then traps the player in a corner (1 of 6 goals failed);
      the dungeon routes A* over tile centres (8 directions, no corner cutting) with string pulling instead,
      accepting a straight leg only when five points 0.4 m around every sample are walkable. (b) A camera
      that looks in from one side needs walls above head height removed between camera and player: done in a
      shader (discard in a box around the player on the camera side), not by hiding objects. (c) Architect's
      debug-colour swatches are mapped to the game's own materials by the material NAMES the exporter keeps
      (LA_Floor_*, LA_Simple_Wall, LA_Door...). Verified: `--dungeontest` walks entrance->exit and to every room
      centre on 4 different seeds (round rooms included), screenshots checked.
      Open: castle/tower packages, multi-floor use (stairs between rooms), doors that open, props as Vampire
      assets, story hooks (exits to other locations), saving/loading inside a dungeon seed.

- [x] **Polish pass (0.32.0).** (1) Torch bug: `wall_adjacent` tested `(x+dx, y+dy)` against a set of `(x, y, z)` cells, so
      every direction passed; fixed with the z component. (2) `_round_ring_inner_ellipse`,
      `_ring_torch_mount`, `_prop_inside_ring`: torches hang on the masonry ring's inner skin (7-tuple torch
      entries, `_build_torch_mesh.add_oriented`), props are tested against the inner ellipse and lose their
      wall kinds in ring rooms. (3) `_TowerBuilder.floor_levels` replaces the even storey split; `seam` now
      applies to `add_opening` and the stair start (world angles), so a castle tower can rotate its seam away
      from its doors. The wall-walk doors sit on the wall axes (corner diagonals are exactly 45 deg
      multiples, NOT the direction to the courtyard centre, which differs on non-square courtyards -- the
      first version was off by 7 deg and the doors opened onto the parapet), the ground door sits ~170 deg
      into the climb (steps well above head height) and the upper slab's open stretch stays clear of the
      wall-walk doors. (4) `_masonry_images` is the one texture generator (brick, stone): tileable weathering
      blotches from a coarse grid blurred with wrap-around. Open: tower windows vs steps, interior
      props/lights, stair railing, keep interior, ordinary level walls as wall runs, collision export
      for castles/towers.

- [x] **Castle + straight masonry walls (0.31.0).** `_WallRunBuilder` mirrors `_TowerBuilder` in a flat frame (x along
      the run, outer face at y = -t/2): columns carrying every opening that contains them, the same ruin
      profile (lattice noise over x, notches, brick-course snapping) and gap conversion, caps/steps, frames
      on both faces, plinth on the outer face, merlons with crenel caps, stones, rubble. `_arch_h` and
      `_arch_curve` became static methods so both builders share them. `_build_castle_mesh` composes it:
      towers at the corners (door angle = direction to the centre), curtain runs placed with
      rot = 0, pi/2, pi, 3pi/2 so local -y is the outward side, run ends buried at xe =
      sqrt((R - wall/2)^2 - (t/2)^2) from the tower centre (the point where the run's outer corner lies
      inside the tower's masonry band, so no end cap is needed), keep walls extended by t/2 each end so
      their corners close by overlap (end caps there were coplanar with the neighbouring wall and rendered
      black). Verified with ray casts (south wall, gate, joints, towers, courtyard). Open: connect tower
      floors to wall tops, keep interior, wall runs as ordinary level walls (rect rooms) and ruined rect
      rooms, a moat/ground skirt, castle exports with collision, gatehouse towers and a portcullis.

- [x] **Ruins (0.30.0).** `_TowerBuilder` got `ruin` and `rubble_outside`. Columns (`_build_columns`) are now built
      once and shared by both skins, the caps and the end faces; each carries every opening that contains it
      (`ops`, lowest sill first -- stacked windows used to be dropped because only the first matching opening
      owned a column), its `gap` (an opening that became a breach) and `top`. `_ruin_top(t)` = smooth lattice
      noise (48 + 12 point octaves, cosine interpolated, periodic in the WORLD angle so it survives the seam
      rotation) plus notches, snapped down to whole brick courses (0.26 m) and clamped to >= 0.5 m. An opening
      survives only if apex + 0.4 m fits under the local top, else it becomes a 'gap' whose height is the lower of
      its two neighbouring column tops (so jambs never stand above the wall beside them); openings whose sill is
      above the local top are dropped. `_caps_and_steps` draws the flat caps (stone, UV across the thickness)
      and the vertical faces between columns of different height, facing the lower side. Pitfalls found: a
      cap/step must be emitted per column, not per skin; stones must test the STANDING top (`_standing_top`), not
      the raw noise, or they float across a breach; rubble must stay below 0.25 m or a 0.3 m passability ray hits
      it. Open: ruins for plain rectangular walls (needs the masonry wall segment generalisation), partial
      slab collapse inside ruined towers, moss/weathering in the texture, castles/fortresses as assemblies of
      these parts.

- [x] **Round rooms as masonry (0.29.0).** `_build_round_room_masonry_mesh` reuses `_TowerBuilder` per Round room:
      a circle of radius max(rx, ry) is built, rotated by a seam angle (middle of the widest solid stretch,
      so no opening straddles the shell's 0/2pi sweep) and stretched by (rx/R, ry/R); both maps have a positive
      determinant so `_TowerMesh.poly`'s outward orientation survives. Openings come from
      `_round_room_opening_ranges`: 1440 ring samples tested against the cell grid (CENTERED convention, cell i
      spans i-0.5..i+0.5 tiles -- NOT the corner convention the older ring code's dead-corner pass used) -- a sample
      is marked when it lies in a non-room walkable cell, or inside one of the room's own cells in the half facing
      a non-room walkable neighbour (this second rule catches a corridor that only touches the rim tangentially:
      the first version missed it and the ray test found 19/3012 sealed passages). Runs are widened to >= 1.4 m and
      merged when closer than 1 m so frames never overlap. Placement falls back arch/pointed/flat -> flat ->
      'gap' (full height, no frame) -> leave the room's wall out; a corridor is never sealed. Outer skin is ON the
      rim and the wall grows inward. UV columns come from the Ramanujan perimeter. In Masonry mode the Doors step
      skips RoundDoors and the Walls step skips the Bevel modifier for ring objects (custom property
      `gla_masonry_ring`). Tests: ray cast along every adjacent walkable pair at 0.3 m and 1.2 m heights, five seeds,
      three door styles, wall heights 0.61 and 3.0, plus BVH overlap against stairs. Legacy Round-room tests now
      pin `wfc_round_wall_style = 'CLASSIC'`. Fixed in 0.29.1: the stair clipping at 3 m wall height was a sill stone sinking below a floor-level
      doorway plus proud stones on the rim; ring now inset by ROUND_RING_INSET. Classic still clips in 1/5 seeds. Open: reuse for non-round rooms, ruins, torch brackets on the ring,
      props against curved walls (decoration still assumes straight tile walls).

- [x] **Round Tower interior (0.28.0).** `_TowerBuilder._slab/_stairs`. Storey height = shell height / int(shell
      height / 3), so the top slab is the roof platform. One full turn of stairs per storey, a wedge block per
      step (0.3 m thick so consecutive steps overlap into a solid soffit), starting at door angle + 60 deg
      snapped to the 64-segment slab grid. Each slab is a polar mesh: solid inner disc, outer stair lane open
      over the last 2.2 m of climb (angles computed from the step index, hole edges get their own faces
      pointing into the hole). Everything stays shared-vertex per group; verified with ray casts (step tops,
      headroom, slab heights). Decision on the stairs' start angle: a step above the door's inner face
      is fine because 2.5 m of headroom > 2 m player height, so no special-casing is needed.
      Open: step vs. slit-window overlap, a railing/newel, interior props/lights, doors between storeys,
      the same masonry method for ruins/castles/fortresses and for Round rooms in generated levels.

- [x] **Round Tower (0.27.0).** Replaces the "brick-by-brick + modifier" idea after a prototype showed
      it costs ~8 400 vertices for one 9 m tower. Section 7 of `levelArchitect_v2.py`: `_TowerBuilder`
      builds a smooth shell (outer/inner skins in cylindrical UVs, one tall quad per plain column,
      finer columns only over openings, vertical rings only where an opening needs them -- T-junctions
      are collinear so they don't crack) with a numpy-generated brick albedo+normal image
      (`_tower_brick_images`, 1024 px tile, rows tile horizontally, packed into the .blend). Openings are
      cut by arch-shaped column boundaries (round arch = half ellipse; slit = rect) with reveal quads;
      frames/voussoirs/plinth/cornice/merlons are wedge solids in cylindrical coordinates. Faces are
      oriented by construction (`_TowerMesh.poly` flips a face to point at a given direction), so the
      outward-normal check in the headless suite passes without per-builder winding tables.
      Gotchas found: (1) changing `colorspace_settings` AFTER writing a generated image's pixels
      regenerates it to blank black -- set it first; (2) `image.pixels` is linear, so the display-space
      palette is raised to 2.2 for the sRGB image; (3) `bpy.ops` raises RuntimeError (not CANCELLED) when
      an operator reports an ERROR. Verified by ray casts through the door, outward/inward normals,
      vertex budgets per detail level, and a glb round-trip. Open: interior floors + spiral stairs,
      tower as a room type inside a generated level (needs room reservation like Round rooms),
      taper, per-detail LOD measured in an engine rather than in vertices, an actual dedicated
      brick texture shipped in Textures/ instead of the generated one.

- [x] **Windows + themed props (0.26.0).** Cross-pollination from the Vampire Adventure project.
      Windows: see §4 entry. Props: `_composite_prop_parts` defines each new kind as box/cylinder
      parts in a local frame (front = +X); `_prop_local_bounds`/`_prop_fits` keep a placed prop
      inside its tile and clear of walls (checked for every wall side and all open sides, so nothing
      pokes into a distant wall); wall kinds are pushed back against the wall's inner face. Themes
      live in `PROP_THEMES`; the Generic theme keeps the original code path and RNG use exactly, so
      existing seeds reproduce. Raised parts (table tops etc.) get bottom faces — the usual
      hidden-bottom culling only holds for floor-touching boxes. Not done: per-prop materials
      (still one slot), props on floors above 1 sub-level are placed like any other, windows in Round
      room rings.

- [x] **Round rooms could clip stairs, or wall off a corridor that should be walkable (0.25.1).**
      User-reported, reproduced from a pasted debug-snapshot dict (Round room shape, multiple
      Sub-Levels per Floor): stairs sometimes visibly clipped through a nearby Round room's own
      wall ring, and some corridors dead-ended at a low wall (0.61m — jumpable) instead of a real
      opening. **Confirmed via a real Blender repro of the exact snapshot before touching any
      code** (this project's own established discipline) — a stair tread box genuinely overlapped
      a `WALLS_ROUND` box. Three separate, real bugs, all in the 0.23.0/0.24.0 Round-room wall
      ring/floor disc/door-frame machinery:

      1. **Placement never reserved a Round room's full rectangle.** `_carve_room`'s docstring
         already claimed `_room_fits` "reserves the FULL bounding box... same as a rect one" — but
         `_room_fits` only ever checked the GRID (`TILE_AIR`), and a Round room only carves cells
         inside its inscribed ellipse (`<= 0.8` threshold), leaving its own bounding-box corners
         genuinely `TILE_AIR`. A new stairwell (or any room) could get placed straight into that
         "empty" corner — which the wall ring, an ellipse spanning the room's FULL rectangle, still
         cuts straight through. Fixed: `_room_fits` now also rejects any candidate overlapping an
         existing ROUND room's full rectangle, not just its carved cells (covers every caller —
         room scattering AND stairwell placement — since both funnel through the one function).
      2. **A corridor can still legitimately reach that same dead corner.** `_carve_corridor` is a
         straight Manhattan line with no alternate routing "used in places where connectivity must
         not be allowed to fail" (its own docstring) — it can't be made to skip a cell there without
         risking a genuinely disconnected floor, so placement-blocking alone (bug 1's fix) isn't
         enough. Fixed at the RENDERING end instead: `_build_round_room_walls_mesh` and
         `_build_round_room_doors_mesh` now also scan the room's full rectangle for any walkable
         cell that ISN'T the room's own floor, and force that ring edge open — covering both a
         cell fully inside one polygon sector (checked via all 4 grid-corners' angle bucket) and
         the reverse case on a minimum-size 3×3 Round room, where a whole rim edge can land inside
         ONE grid cell without touching any of ITS corners either (checked via whether either of
         the edge's own two rim vertices falls inside the cell's rectangle).
      3. **The actual root cause of the real clipping (bugs 1+2 alone weren't enough — a multi-seed
         regression test still caught one residual case):** all three Round-room mesh builders
         computed a room's WORLD-SPACE ellipse center as `(x + rw/2.0) * tile_size` — ported
         verbatim from the sibling project, which uses a CORNER-based grid convention (`_build_
         walls_mesh` there: `cx0 = x*tile_size, cx1 = (x+rw)*tile_size`). This project's own grid
         is CENTERED instead (`_build_wall_mesh` here: `left = (x-0.5)*tile_size`), matching
         `_carve_room`'s own grid-space ellipse test (`cx = x + (rw-1)/2.0`) — so the ported
         formula was half a tile off in both X and Y here specifically. Confirmed by hand before
         fixing: a genuinely-carved corner cell fell just OUTSIDE the old formula's disc on one
         side, while the ring overreached a whole half-tile into empty space on the opposite side
         — which is exactly what let an otherwise-correctly-placed stairwell still get clipped.
         Fixed to `(x + (rw-1)/2.0) * tile_size`, matching the ellipse test exactly. BrickSpitter
         itself needed no equivalent fix — its own formula is correct for its own (corner-based)
         convention.

      Added a new dedicated regression test (Round rooms + multi-Sub-Level Stairs together, 5
      seeds): the existing Round rooms test pins `wfc_height=1` so Stairs never even runs there,
      and the suite's `MIXED`-shape baseline only randomly rolls Round per room — this exact
      combination had no guaranteed coverage before, which is how this shipped unnoticed.

---

## 3. Known issues / things that need fixing

- [ ] **`docs/palette_downgraded-32.hex` (the master palette source) has 32 colors, but only 31 made it into
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
- [x] **A Round room's door frame used to stay straight/axis-aligned against its curved wall** —
      see §2, now fixed.

---

## 4. Ideas for future work (not started)

Roughly ordered by how directly they build on what already exists:

- [x] **Bent stairwells/ramps (L or U switchback with one landing) — done, see §2.** Shipped as
      `wfc_stair_bend_chance`/`wfc_stair_bend_style`. Deliberately NOT a true continuous curve
      (spiral stairs) — that stays the "biggest lift, don't start casually" item. The scoped-out
      simplification held: room reservation is untouched, only what's carved inside the rectangle
      changed.
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
- [x] **Windows — done (0.26.0).** Shipped differently from the sketch below: `_pick_window_edges` chooses
      exposed room-wall edges (seeded, shared by wall and window builders), `_build_wall_mesh` cuts a real
      opening (piers + sill + lintel boxes; window edges never join merged runs), `_build_window_mesh`
      adds frame/mullions/glass as a separate object. Verified by ray-cast through the opening in the
      headless suite. Original sketch: would reuse most of `_build_door_mesh`'s same-Z boundary-detection logic
      (frame at a wall-facing edge instead of only room-to-room boundaries), sized/positioned
      differently (mid-wall-height opening, not floor-to-lintel) and gated by its own placement
      rule (e.g. only on true exterior walls) rather than "wherever a doorway already is."
- [x] **Collision mesh export — done, see §2.** Shipped as `OBJECT_OT_ExportLevelCollisionGLTF`.
      Scoped down from the original note's "simplified box set" to a filtered re-export of
      already-built geometry (no new floor-region merging code); no hand-baked navmesh — engines
      already auto-bake their own from imported collision geometry.
- [x] **One-click glTF/GLB export — done, see §2.** Shipped as `OBJECT_OT_ExportLevelGLTF`
      (new Export tab). glTF only for now, not FBX — deliberately scoped down (see §2) for a
      standardized, engine-agnostic axis convention with zero addon-side conversion math.
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
