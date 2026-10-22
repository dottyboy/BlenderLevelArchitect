# Plan format `gla-plan/1` (M0 draft)

A **plan** is plain data describing something to build and where its parts go. Plans nest. The same data is stored inside
the .blend and as `<name>.plan.json`. Nothing here changes generator code yet; this is the spec to review.

## 1. Conventions

* Units: metres. Axes: Blender's (X east, Y north, Z up). Game packages keep converting to engine axes at export, as today.
* A plan's coordinates are **local to its parent**: `transform` places it, rotation is degrees about Z.
* Footprint polygons are lists of `[x, y]`, counter-clockwise, implicitly closed, no self-intersection.
* **Seeds are derived, never shared**: a child's effective seed is `hash(parent_seed, child.id)`. Adding or removing a sibling
  never changes the others. An explicit `seed` on a node overrides.
* Unknown fields are kept and written back unchanged (forward compatibility).

## 2. Plan node

```json
{
  "format": "gla-plan/1",           // root only
  "id": "castle_1",                 // unique among siblings, [a-z0-9_]
  "type": "building",               // building | compound | block | settlement | terrain
  "kind": "castle",                 // building: castle, tower, house, barn, chapel... ; others: free label
  "name": "Keep of Example",
  "style": "medieval",              // style pack name, inherited from parent if omitted
  "seed": null,
  "transform": {"x": 0, "y": 0, "z": 0, "rot": 0},
  "footprint": [[-15,-10],[15,-10],[15,10],[-15,10]],
  "levels": [{"z": 0, "height": 4.0}],   // optional: floors / terraces; footprint may be overridden per level
  "params": {},                      // type/kind specific, see section 4
  "anchors": [],                     // section 3
  "children": []
}
```

* `footprint` is optional for `terrain` and `settlement`; required for `building` and `compound`, except for kinds that derive one from their params (`castle`: width x depth, `tower`: circle of `radius`).
* Building seeds: the builder receives `effective_seed % 1,000,000`, because the existing builders take the scene seed (0-999,999).
* `levels` lets a plan exist at several heights: floors of a building, terraces of a castle, a bridge. A level can carry
  its own `footprint`; otherwise it uses the plan's.
* Children must lie inside the parent's footprint unless the parent's `params.allow_outside` is true (validation warning, not error).

## 3. Anchors

Named connection points other plans or roads snap to.

```json
{"id": "gate", "kind": "gate", "pos": [0,-10,0], "dir": 270, "width": 3.0, "level": 0}
```

`kind`: `door`, `gate`, `road`, `path`, `water`, `stairs`. `dir` is the outward direction in degrees. A road or path plan
connects *anchor to anchor* (`"from": "farm_1/gate"`, `"to": "castle_1/gate"`), addressed by `plan_id/anchor_id`.
Generated buildings add their own anchors (their doors) back into the data, so later plans can use them.

## 4. Type-specific `params`

| type / kind | main params |
|---|---|
| building / castle | today's castle settings: `width`, `depth`, `wall_height`, `wall_thickness`, `tower_radius`, `tower_height`, `gate`, `keep`, `hall_props`, `ruin`, `brick_color` |
| building / tower | `radius`, `height`, `wall`, `door`, `door_angle`, `windows`, `interior`, `stair_width`, `rail`, `lights`, `props`, `battlements`, `ruin`, `brick_color` |
| building / house, chapel, stable, barn | `width`, `depth`, `wall_height`, `floors`, `wall_thickness`, `roof` (GABLE / FLAT / NONE), `roof_pitch`, `door` (S/E/N/W/NONE), `door_style`, `door_width/height`, `windows`, `window_kind/width/height/sill`, `brick_color`, `ruin`, `detail` (defaults per kind in `PLAN_HOUSE_DEFAULTS`) |
| compound | `fence` (`none` / `stone` / `wood`), `fence_height`, `fence_thickness`, `gate_height`, `layout` rules: list of `{ "kind": "barn", "count": [1,2], "near": "free" / "wall" / "ring" (with `"ring": [inner, outer]`), "at": "corners", "min_gap": 3, "params": {} }`, `layout_target` (child id, default: the first castle), `layout_margin`, `corridor_width` |
| block | `road_graph` (`{nodes: {id: [x, y]}, edges: [[a, b], [a, b, {width}]]}`), `road_width`, `lot_width`, `lot_depth`, `setback`, `lot_gap`, `skip_chance`, `fill` rules (`kind`, `weight`, `params`, `size` ranges); or `from` / `to` anchor references for a straight connecting road |
| settlement | `blocks`, `squares`, `walls`, `main_roads`, `density` |
| terrain | section 5 |

Parameter names deliberately match the current `wfc_castle_*` / `wfc_tower_*` scene properties (prefix dropped), so the first
building plans are a thin wrapper over the existing builders.

## 5. Terrain and biomes (Geometry Nodes)

Implemented in 0.48.0. A `terrain` node is a rectangular ground sheet centred on its transform; the plans below it are
placed on it and the ground is flattened under them.

```json
{
  "type": "terrain", "id": "land", "kind": "terrain",
  "params": {
    "biome": "forest",            // meadow | forest | desert | tundra | mountain | island
    "width": 240.0, "depth": 240.0, "resolution": 2.0,   // metres; grid cell size 0.5..10 (max 250 000 cells)
    "pad_margin": 10.0,           // metres over which the ground eases into a pad (never less than 0.9 x amplitude)
    "scatter": 1.0,               // vegetation / rock density multiplier, 0 = none
    // optional overrides of the biome's own numbers:
    "amplitude": 6.0, "feature_size": 55.0, "detail": 4.0, "roughness": 0.5,
    "base": 0.0, "sea_level": -4.5, "island": 0.0, "water": true
  },
  "children": [ ... plans placed on the terrain ... ]
}
```

* **Heights.** Python lays the grid and writes four per-vertex attributes (`pad_h`, `pad_w`, `edge`, `skirt`); a **Geometry Nodes**
  modifier (`GLA_Terrain_<id>`) makes the relief from 4D noise (inputs *Amplitude, Feature Size, Detail, Roughness, Seed, Base,
  Sea Level, Island, Skirt Depth* stay editable in the modifier panel), blends the pads in, drops the rim for islands and adds a skirt
  so the sheet is a solid slab. The same tree writes the biome colours to a `Col` attribute (altitude ramp, rock on steep slopes,
  trodden earth under plans, dark skirt) that the terrain material reads.
* **Pads.** Every top-level building or compound below the terrain (and every road of a block) flattens the ground to the plan's own
  world `z`, 1.2 m + 0.75 cells beyond its outline, then eases back into the relief over `pad_margin`. Overlapping pads blend by weight.
  A path between plans on different heights (`from` / `to` anchors) slopes: the pad and the road follow the line between the anchor heights
  (`road_graph.z` holds the two end heights, filled in by the layout step).
* **Water.** If any ground lies below `sea_level` a translucent water plane is added at that height (lakes, or the sea around an island).
* **Scatter.** Each biome lists vegetation rules (`tree` with crown/leaf/height, `bush`, `rock`, `cactus`; per hectare, slope and altitude
  limits, a noise-based cluster mask). Points are tested against the evaluated terrain, kept away from pads and each other, and merged
  into one mesh per rule (`PB_<id>.scatter`).
* `"fill": []` on a block means "a bare road, no lots" (the default fill still makes houses when the key is absent).
* **Rivers.** `"rivers": "auto" | "none" | [{"path": [[x, y], ...], "width": 6.0}]` (terrain coordinates; auto = one river in meadow, forest and
  mountains, the best of several meanders by distance from the plans). The bed follows the terrain but never rises downstream (it runs from the
  low-y end to the high-y end), is cut as a flat channel with banks easing over 8 m, and gets a water ribbon 0.75 m above the bed. Plan pads win over rivers.
* **Regions.** `"region_biome": "mountain"` (+ `region_scale` 30..600 m, `region_bias` -0.35..0.35, `region_blend` 0.02..0.5) lets a second biome
  take over where a noise mask is high. The mask is written as the `region` point attribute; the tree blends amplitude, feature size, base, palette
  and rock/earth colours, floors the second biome at the first one's water line, and scatter uses each biome's rules in proportion.
* **Bridges.** Roads of blocks give way to a river (their pad weight fades inside the river's bank); each crossing gets a stone bridge along the road.
* **Ridged.** `"ridged": 0..1` turns the noise into crest lines (desert 0.85, mountains 0.5, others 0).
* **Polygon regions.** `"region_polygons": [[[x, y], ...], {"polygon": [...], "blend": 12.0}]` (needs `region_biome`): the second biome rules inside the
  polygons and fades out over `blend` metres; `"region_noise": true` combines them with the noise mask.
* **Import.** `plan_import_file(path)` turns an `.svg` or `.dxf` into a `settlement` (or, with biome-labelled shapes, a `terrain`) tree — see the User Guide.
* **Several region biomes.** `"regions": [{"biome": "desert", "polygon": [[x, y], ...], "blend": 12}, {"biome": "tundra", "noise": {"scale": 140, "bias": 0, "blend": 0.15}}]`
  — at most three distinct biomes besides `biome`; entries of the same biome join; a later biome overrides an earlier one where they overlap. The masks are the point
  attributes `region`, `region_2`, `region_3`; the tree blends relief, palette and rock/earth colours, scatter draws each biome's vegetation by weight.
* **Heightmap.** `"heightmap": {"file": "terrain.png" | "image": "name", "height": 40.0, "mix": 1.0, "invert": false}` — the image (greyscale or the mean of RGB, normalised to
  its own darkest/brightest) is stretched over the terrain (top = +y). `mix` blends it with the noise relief; the heights feed pads, rivers, bridges, colours and scatter.
* **Pad mode.** `"pad_mode": "plan"` (default) cuts the ground to each plan's world `z`; `"terrain"` lifts each plan (and its descendants) to the natural ground height at its
  centre instead, streets flat at the mean height under their roads, from/to paths sloping between their ends.
* Not yet: heightmaps tiled or larger than one terrain, region biomes with their own water level blended across one terrain, terrain from a heightmap image, roads that curve with the ground.

### Block extras

`"infill": 1.0` (default 0) adds a second pass: random spots inside the block outline, up to `infill_reach` (24 m) from a road, turned toward the nearest road,
kept clear of roads and lots. `"fill": []` means a bare road.

## 6. Storage

**In the .blend:** one *Collection* per plan, named `Plan_<path>` (ids from the root joined by `.`, e.g. `Plan_farm.barn.silo`), nested like the plan tree.
The root of each collection is an Empty `PlanRoot_<id>` with custom property `gla_plan` (the node's JSON, children
excluded; children live in the nested collections). Optional helper objects:
a footprint mesh/curve (`PlanFootprint_<id>`) the user can edit by hand, anchor empties (`PlanAnchor_<id>_<anchor>`).
Generated geometry goes in a sibling collection `Built_<id>` so rebuilding can remove it cleanly.

**On disk:** `<blend name>.plan.json` (or any path the user picks): the full tree with `format`, plus `revision` (integer,
+1 on every save) and `saved_with` (add-on version).

**Sync rules:** the .blend is the source of truth while open. *Save Plan* writes JSON; *Load Plan* replaces the tree
(asks if the scene already has one). *Sync from Objects* reads edited footprint meshes / anchor empties back into the JSON.
Nothing syncs silently.

## 7. Build pipeline

1. Validate the tree (section 8). Errors stop the build; warnings are reported.
2. Resolve inheritance (style, seed) top-down.
3. Build **bottom-up per level of scope**: terrain pads first, then buildings, compounds, blocks, roads.
4. Each plan's builder returns its objects, its anchors and its **walk areas** (so a built plan can export a game package).
5. Rebuild of one subtree removes only that subtree's `Built_` objects.

## 8. Validation

* Unique ids among siblings; `type`/`kind` known; footprint is a simple CCW polygon with area > 0.
* Children inside parent (warning); siblings overlapping beyond a tolerance (warning).
* Anchor references resolve; a connection joins two anchors that exist.
* Numeric params within the same ranges as the matching scene properties.
* `levels` strictly increasing in z.

## 9. Example: castle with extras

```json
{
  "format": "gla-plan/1", "id": "site", "type": "compound", "kind": "castle_grounds", "style": "medieval",
  "footprint": [[-30,-25],[30,-25],[30,25],[-30,25]],
  "params": {"fence": "stone", "gate_side": "south"},
  "anchors": [{"id": "gate", "kind": "gate", "pos": [0,-25,0], "dir": 270, "width": 4}],
  "children": [
    {"id": "castle", "type": "building", "kind": "castle", "footprint": [[-15,-10],[15,-10],[15,10],[-15,10]],
     "params": {"width": 30, "depth": 20, "keep": true, "brick_color": "MIXED"}},
    {"id": "chapel", "type": "building", "kind": "chapel", "transform": {"x": 22, "y": 14, "z": 0, "rot": 90},
     "footprint": [[-3,-5],[3,-5],[3,5],[-3,5]], "params": {"floors": 1, "roof": "gable"}},
    {"id": "stable", "type": "building", "kind": "barn", "transform": {"x": -22, "y": -14, "z": 0, "rot": 0},
     "footprint": [[-5,-3],[5,-3],[5,3],[-5,3]], "params": {"floors": 1, "roof": "gable"}}
  ]
}
```

## 10. Decisions (closed 2026-10-22)

1. **`block` and `settlement` stay two separate types** (may be revisited later).
2. **Levels come later.** In M1 a building has a single footprint; the `levels` field is part of the format and is read and
   written back unchanged, but the builders ignore it until a plan type needs it.
3. **Anchors are addressed as `plan_id/anchor_id`.** Possible extensions to keep in mind (not built): a `tags` list on anchors
   for queries such as "any `gate` anchor of this compound"; wildcard references; nested paths across more than one level
   (`site/castle/gate`); anchors that carry a capacity (how many roads may join); and anchors on terrain (water, ford, pass).
   The reference syntax is parsed in one function so these can be added without changing stored data.

## 11. Reference added after M2-M4

**Styles.** `style` on any node: `medieval`, `egyptian`, `mexican`, `chinese`, `inca`, `futuristic`, `alpine`, or `mixed` (every building,
fence and road picks a pack from its own seed). A pack is data (`PLAN_STYLES`): wall, trim, wood and roof materials plus per-kind
parameter defaults; explicit `params` win. Huts use *construction* packs (`PLAN_CONSTRUCTIONS`: straw, branch, timber, earth, earthbag,
aircrete) selected by `params.construction`.

**Shapes.** `params.shape` = `{"kind": "rect" | "circle" | "ellipse" | "blob" | "lshape", "width", "depth", "irregularity", "seed"}` gives a
compound or block its footprint when it has none. Gates snap to the nearest edge.

**Road generators.** `params.road_generator` = `{"kind": "grid" | "organic" | "ring", ...}` fills `road_graph` at expansion time
(grid: `cols`, `rows`, `cell`, `jitter`; organic: adds `amplitude`, `segment`; ring: `radius`, `rings`, `spokes`, `segments`, `wobble`).

**Building kinds.** `tower`, `castle`, `keep`, `house`, `chapel`, `stable`, `barn`, `well`, `hut`, `tree`, `barrel`, `crate`, `haystack`.
House-like parameters: `width`, `depth`, `wall_height`, `floors`, `basement`, `stilts`, `wall_thickness`, `roof` (`GABLE`, `HIP`, `CURVED`, `FLAT`,
`NONE`), `roof_pitch`, `roof_overhang`, `roof_lift`, `parapet`, `roof_color`, `door`, `doors` (extra sides), `door_style`, `door_width`,
`door_height`, `door_leaf`, `windows`, `window_*`, `chimney`, `stairs`, `use`, `brick_color`, `ruin`, `detail`.
Hut parameters: `construction`, `form` (`BOX`, `DOME`, `TUNNEL`, `SILO`, `AFRAME`), `levels`, `level_height` plus the house-like ones.

**Layout rules** (`params.layout`): `kind`, `count`, `near` (`free`, `wall`, `ring`, `attach`), `ring`, `at: "corners"`, `every`, `min_gap`,
`params`, `vary` (parameter -> list of choices; brick and roof colours are ignored under a non-medieval style).
