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
| building / house, chapel, stable | `width`, `depth`, `wall_height`, `floors`, `wall_thickness`, `roof` (GABLE / FLAT / NONE), `roof_pitch`, `door` (S/E/N/W/NONE), `door_style`, `door_width/height`, `windows`, `window_kind/width/height/sill`, `brick_color`, `ruin`, `detail` (defaults per kind in `PLAN_HOUSE_DEFAULTS`) |
| compound | `fence` (none/wood/stone), `gate_side`, `layout` rules: list of `{ "kind": "barn", "count": [1,2], "min_gap": 3 }` |
| block | `road_graph` (nodes + edges with width), `lot_depth`, `lot_width`, `fill` rules per building kind |
| settlement | `blocks`, `squares`, `walls`, `main_roads`, `density` |
| terrain | section 5 |

Parameter names deliberately match the current `wfc_castle_*` / `wfc_tower_*` scene properties (prefix dropped), so the first
building plans are a thin wrapper over the existing builders.

## 5. Terrain and biomes (Geometry Nodes)

```json
{
  "type": "terrain", "id": "land", "footprint": [[-200,-200],[200,-200],[200,200],[-200,200]],
  "params": {
    "heightfield": {"base": 0.0, "noise_scale": 80.0, "amplitude": 12.0, "seed": null},
    "water_level": -1.0,
    "rivers": [{"path": [[-200,40],[0,10],[200,60]], "width": 6.0, "depth": 1.5}],
    "pads": "auto",                    // flatten a pad under every plan; auto = from footprints
    "pad_blend": 6.0,                  // metres over which terrain blends into a pad
    "biomes": [{"id": "meadow", "region": "noise", "weight": 1.0}, {"id": "forest", "region": [[...]]}]
  }
}
```

* One Geometry Nodes group builds the heightfield from these values; pads and rivers come in as point/curve inputs,
  so changing a building moves its pad.
* A **biome** is a named parameter set: ground materials, vegetation kinds and density, rock density, allowed building
  kinds, default style pack. Regions are polygons or noise masks; transitions blend.
* Biome list for later: meadow, forest, desert, tundra, mountain, valley, wetland, urban.

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
