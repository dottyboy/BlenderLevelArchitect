# World generator plan (draft, 2026-10-22)

Direction: Game Level Architect grows from dungeons/towers/castles into a general generator, scaling from one building to a
city. Not tied to one game. Cultures (style packs) come after the first small result; scope grows step by step.

## Scope ladder (each rung reuses the one below)

| Rung | Result | New ideas it forces |
|---|---|---|
| 1 | Castle with extras (gatehouse, chapel, stables, well, outer wall) | Plan format, parts placed on a footprint, anchors |
| 2 | Farm: a few buildings + fence | Compound plan: a boundary with building plans inside |
| 3 | A few houses clustered | Lots, orientation toward a shared point or road |
| 4 | A street / one block | Road graph, lots along edges, doors facing the road |
| 5 | District | Several blocks, squares, mixed building types |
| 6 | Small settlement | Terrain, paths between plans, edge of settlement |
| 7 | Small town | Walls/gates, main street, market |
| 8 | Larger city | Instancing, per-district budgets, LOD |
| 9+ | Regions, roads between towns, biomes | Terrain + biome layer, rivers |

## Core idea: nested plans

A **Plan** is data: a type, parameters, a seed, and children. Plans nest; a bigger plan only decides *where* smaller
plans go and what parameters they get.

* **Building plan** — footprint (closed polygon at some height), floors, roof, parts (door, windows, tower, chimney),
  style pack name. The current Tower and Castle become building plan types.
* **Compound plan** — a boundary polygon plus rules: which building plans, how many, fence along the boundary, gate.
  (Farm, castle grounds, monastery.)
* **Block / street plan** — a road graph; lots along its edges; each lot gets a building plan facing the road.
* **Settlement plan** — blocks, squares, walls, main roads; later a whole city.
* **Terrain plan** — heightmap, water, vegetation per biome; plans are placed on it and flatten a foundation.

Plans exist on **several heights** (floors, terraces, bridges): a plan has a Z, and a footprint may sit on several levels.
Each plan exports a small JSON (the same "gla-export" family as today) so a built plan can be reused.

### Anchors ("ports")
Every plan declares anchor points: doors, gates, road connections. Roads and paths snap to anchors, so connecting
buildings, farms and streets, and generating terrain around them, works the same at every scale.

### Manual plans as base
A plan can be written by hand and used as the base for parameters (e.g. a castle outline with marked towers), then the
generator fills the rest. Three input routes, easiest first:
1. Parameters (as today): width, depth, towers, style.
2. Drawn in Blender: a closed curve or mesh outline plus empties for parts (type + params as custom properties).
3. Imported vector/CAD (SVG, DXF) after 2 works; images last (needs wall recognition, research task).

## Milestones

**M0 — spec.** Plan JSON v1 (fields, nesting, anchors, heights) and how a plan is stored in a Blender file
(collection + root empty with custom properties). No generator changes. Review together.

**M1 — Plan core + building plans.** Plan classes, validation, JSON round trip, "Build from Plan" operator. Wrap the existing
tower and castle builders as building plans *without changing their output* (existing ~670 tests stay the safety net).

**M2 — Rung 1.** Castle with extras: gatehouse, chapel, stables, well, outer wall, placed by the plan on the castle
footprint. First shared footprint/part placement code. First GIF for the README.

**M3 — Rung 2/3.** Compound plans: farm (barn, house, fence, gate), cluster of houses. A simple house building plan
(footprint, roof, door, windows). Fence builder.

**M4 — Rung 4.** Road graph and lots; a street with houses facing it. Anchors and snapping.

**M5 — Style packs.** Extract today's medieval look into the first pack (data, not code), then a second, very different
one (e.g. Egyptian) to learn how general the building plan must be (roof forms, columns, terraces). More cultures after.

**M6 — Terrain.** *Done in 0.48.0:* Geometry Nodes heightfield around plans, flattening pads, sloped paths between plans, lakes/sea, six biomes with vegetation. Rivers done in 0.49.0, noise-based biome regions in 0.50.0. Later: polygon regions on one terrain, heightmap import, curved roads.

**M7+ — Rungs 5-8.** *Districts and a city example done in 0.53.0 (blocks avoid each other); still to do: per-district budgets and instancing for very large cities.* Districts, settlements, town walls, instancing and per-district budgets, biomes.

## Rules for the work
* Existing output must not change until a plan type replaces it and passes the same tests.
* Every new builder gets a headless test (ray casts for passability, vertex budget, normals), as now.
* Big scenes use instancing from the start (one mesh per house type, instanced), not per-house geometry.
* Style = data. New cultures should not need new generator code unless a new architectural form is needed.

## Decisions (2026-10-22)
* **Plans live in both places**: inside the .blend (editable, source of truth while editing) and as a `.plan.json` next to it
  (exchange, version control, reuse). See [PLAN_FORMAT.md](PLAN_FORMAT.md).
* **Terrain is generated with Geometry Nodes**, fed by the terrain plan (heightfield, flatten pads, water, rivers).
* **Biomes are part of Level Architect**, not a separate add-on: a biome layer of the terrain plan.
* **BrickSpitter** stays the simpler 3D-platformer / side-scroller generator and is upgraded *from* Level Architect: pieces
  (plan core, terrain, biomes, style packs) are taken over selectively. So the plan core, terrain and biome code is written
  as self-contained sections with no dependence on dungeon-solver internals, to make that extraction cheap.
