# Game Level Architect — User Guide

The add-on lives in the 3D Viewport sidebar (**N** > **Level Architect**). The panel is organised into tabs, one per
job, each with its own settings and its own Generate button, so only one step's settings show at a time. A persistent
**Debug** section at the bottom holds a *Copy Parameters* button that grabs the exact settings behind the last generation.

**Presets** (above the tab row) set a bundle of settings tuned for a target camera or genre — *Isometric*,
*FPS / Immersive-Sim*, *Compact Roguelike*, *Megadungeon*. Step 1 still has to be pressed afterwards.

**Generate All Steps** (under the tab row on the Setup, Walls, Stairs & Doors and Props tabs) runs Step 1–5 in one go with the
current settings. If any step's output already exists it asks first, since regenerating replaces it. A check mark on a Step
button means its output is already in the file.

Contents: [Building a level](#building-a-level) · [Walls and materials](#walls-and-materials) ·
[Towers and castles](#towers-and-castles) · [Ruins](#ruins) · [Plans: sites, villages, towns](#plans-sites-villages-towns) ·
[Exporting](#exporting) · [Tips](#tips)

---

## Building a level

The steps build on each other's output, in order. Steps 2–5 can each be re-run on their own after tweaking their
settings without regenerating the blueprint; regenerating Step 1 rebuilds everything (new seed unless *Random Seed* is off).

| Step | Tab | What it builds |
|---|---|---|
| 1. **Generate Blueprint** | Setup | The room/corridor/stair layout and the floor mesh (a Geometry Nodes modifier). Map size, room count and size, room shape (Rect / Round / Mixed / Cave), floors, sub-levels per floor, continuous elevation, Corridor Stairs. |
| 2. **Generate Walls** | Walls | Walls from the blueprint's exposed edges (plain boxes or **Masonry**), Round-room rings, windows. |
| 3. **Generate Stairs** | Stairs & Doors | Stepped stairs or smooth ramps; straight, L-bent or U-bent stairwells. |
| 4. **Generate Doors** | Stairs & Doors | Frames wherever a corridor enters a room (Flat / Round / Pointed arch), real swinging panels, Entrance and Exit gates. |
| 5. **Generate Props** | Props | Wall torches (a mesh plus a real Point light each) and decoration: crates/barrels/cones or themed furniture. |

**Seeds.** Every generation is seeded and reproducible. Turn *Random Seed* off and note the seed to get the same level back.

**Separate by Floor/Room** (next to Step 1) splits the blueprint into one object per room plus a combined corridor
object per floor, in a collection tree (Floor N > Rooms / Corridors). Run it directly on the Step 1 object; it reads the
live Geometry Nodes modifier itself, so do not apply the modifier first (that drops the per-room materials).

**Add Ceiling** closes every room's ceiling for first-person play; **Isometric Mode** hides it again for a dollhouse view.

### Room shapes

*Rectangular*, *Round* (every Round room is a merged n-gon disc with a wall that follows the curve and a real opening
wherever a corridor connects — **Room Shape Sides** sets the smoothness), *Mixed*, and *Cave* (organic tunnel networks).
Round-room walls can be **Masonry** (default) or the older **Classic** plain-box ring.

### Props

The **Theme** setting picks the decoration: *Generic* (crates, barrels, cones), *Mixed Rooms* (each room gets a theme), or a
theme — *Crypt* (coffins, tombs, columns), *Library* (bookshelves, tables, chairs), *Hall*, *Bedroom*, *Storage*.
Wall-type pieces stand against a wall facing into the room, and in Round rooms torches hang on the curved wall itself.

---

## Walls and materials

**Wall Style** (Walls tab)

* **Boxes** — the original merged boxes (supports Organic Irregularity and corner rounding).
* **Masonry** — one smooth brick-textured wall per straight run with a dressed-stone cap, scattered proud stones, stone
  door frames and stone-framed windows. Corners close without overlapping, doorway jambs get end caps. Brick and stone
  textures are generated procedurally (normal-mapped), so the walls carry real detail at a few thousand vertices.

**Room Brick Colors** gives every room its own brick tint (ochre, slate, moss, rose, umber, sand); corridors keep the plain
brick and rooms near each other never share a tint. **Wall Ruin** breaks masonry walls down (see [Ruins](#ruins)).

**Windows** (**Window Chance**, width, sill, height) cut real openings through room walls with a frame, mullions and a glass
pane. Corridors, Round rooms and Corridor-Stairs sides are never windowed.

Materials: *Simple Viewport Colors* gives every room and floor a flat swatch from the bundled `Textures/` folder; *Style*
mode uses procedural dungeon/cave/open-area shaders; *Per-Floor Overrides* blend room size, shape and style per floor.

---

## Towers and castles

Both are standalone and built at the **3D cursor**, independent of the level blueprint.

**Structures tab, Tower** — a round tower with a brick-textured shell, a real arched door, slit windows (kept clear of the stairs),
stone frames, plinth, cornice and battlements. **Brick Detail** (Low / Medium / High) sets how much real geometry is added to
the textured shell. Inside: floors and **spiral stairs** with an optional **Stair Railing**, hanging **Lanterns** with real
lights, and **Furniture** on every floor. **Brick Color** tints the bricks.

**Structures tab, Castle** — four corner towers (with the same interiors), curtain walls with a parapet and a walkway behind it,
arrow slits, an arched gate, a keep with a furnished hall (**Hall Furniture**), and a courtyard. Each tower has a floor at
the wall-walk height with doors out onto both walls, so ground door → spiral stairs → wall walk is one continuous path.
**Brick Color** is one tint for everything, or **Mixed** (walls, keep and each tower get their own).

---

## Ruins

The **Ruin** slider (Structures tab, and *Wall Ruin* / the Round-room ruin on the Walls tab) breaks masonry down: wall
tops become a jagged edge that steps along whole brick courses, deep breaches open up, an arch or window whose top fell away
becomes a plain gap, battlements disappear, rubble lies around the base, and upper floors above the lowest broken wall are
gone. Doorways stay passable. The result is seeded, so a ruin is reproducible.

---

## Plans: sites, villages, towns

*Experimental.* A **plan** describes a whole site as nested data — a fortress with a keep and corner towers, a farm, a hamlet,
a street, a district, a cluster of huts — and builds it for you. Open **Level Architect > Plans (experimental)** in the sidebar.

1. Pick a **Style** (the look of the buildings), a **Shape** (regular, round or organic outlines and streets) and, for terrain, a **Biome**.
2. Press one of the buttons — **Tower, Castle, Grounds, Fortress, Farm, Hamlet, Street, Block, House, Chapel, Stable, Hut, Huts, Town, Terrain**.
   A plan is created at the 3D cursor and listed below the buttons with a one-line summary.
3. Press **Build** on the plan. Everything the plan describes appears in a `Built_<name>` collection; **Build** again after any
   change replaces it. **Freeze** writes the automatically laid-out buildings into the plan as ordinary entries (so you can
   move them); **Save** writes the plan to a `.plan.json` file, **Load Plan...** reads one back, the bin removes the plan and
   what it built.

The plan itself is plain data — see [PLAN_FORMAT.md](PLAN_FORMAT.md) for every field. In the .blend it lives in `Plan_<name>`
collections (one Empty per node, with the node's JSON as a custom property), so it survives saving and can be inspected or edited
by script.

### Styles

| Style | Look |
|---|---|
| **Medieval** | Brick and dressed stone (tintable per building), terracotta or slate tiles, chimneys |
| **Egyptian** | Sandstone blocks, flat roofs with parapets, narrow openings, a broad temple in place of the chapel |
| **Mexican adobe** | Plastered adobe, arched doors and windows, low hipped terracotta roofs |
| **Chinese** | Red timber walls, sweeping curved roofs with upturned eaves in grey tile, wooden fences |
| **Inca** | Fitted grey stone, steep thatched gables, small rectangular openings |
| **Futuristic** | White panel walls with dark seams, flat metal roofs, big windows, two-storey houses |
| **Alpine chalet** | Log walls, low shingled roofs with wide overhangs, two storeys, chimneys, wooden fences |
| **Mixed** | Every building, fence and road picks its own pack (deterministic from its seed) |

A child plan can override its parent's style (`"style": "chinese"` on one house in a medieval village). Parameters you set explicitly
always win over what the style would choose.

### Shapes

* **Regular** — rectangular enclosures, straight street grids.
* **Round** — circular enclosures (the gate snaps to the outline), ring-and-spoke streets; a round Fortress gets about six towers.
* **Organic** — free-form (noise-based) outlines for fences and districts, and winding streets whose segments bend with Perlin-like noise.
  Everything is seeded, so the same plan always gives the same shape.

### Buildings

House, chapel, stable, barn: masonry walls on a rectangular footprint with doors (arched, pointed, rectangular; an open leaf stands
beside the doorway), windows, floors with a straight stair, a stone floor, and a roof — gable, hip, curved, flat (with a parapet) or none;
overhang, pitch, chimney, ruin and brick colour are parameters. A house can have **floors + basement up to five levels** and stand on **stilts**.
Also available: **well**, **keep** (a free-standing keep), **tower** and **castle** (the existing builders), **trees** (cone or round
crown, several leaf colours) and small props (**barrel, crate, haystack**).

### Huts

A **hut** is a small modular building, 3-5 × 4-8 m by default, in a *construction method*:

| `construction` | Walls | Roof |
|---|---|---|
| `straw` | straw bales | thatch |
| `branch` | woven branches | thatch |
| `timber` | logs | shingles |
| `earth` | cob / rammed earth | sod, flat |
| `earthbag` | earthbag courses | sod, flat |
| `aircrete` | smooth aircrete | aircrete, flat |

and a `form`: **BOX** (gable or flat), **DOME**, **TUNNEL** (barrel vault), **SILO** (round, up to three levels with a spiral stair)
or **AFRAME**. BOX huts can have `levels` (1-3) and a `basement` (0-2); every form can stand on `stilts` (up to 2.5 m, with steps up to
the door); `use` is `dwelling` or `storage` (storage has no windows). Use a layout rule with `"near": "attach"` to join huts wall to wall:
each new module touches one already placed and the shared wall gets a passage (`doors`), so huts grow into larger buildings.

### Automatic layout

A compound (a farm, a hamlet, castle grounds...) can place buildings for you with `layout` rules, for example *one chapel on the wall,
one or two stables on the wall, three houses anywhere*. Rule fields: `kind`, `count` (a number or `[min, max]`), `near` (`free`, `wall`,
`ring` with `ring: [inner, outer]`, or `attach`), `at: "corners"` (one on every vertex, e.g. corner towers; `every: N` for every Nth),
`min_gap`, `params`, and `vary` (a list of choices per parameter — brick colour, roof colour, width, construction...). Buildings keep a
margin from the fence, never overlap, leave a corridor from each gate to the castle or keep free, and turn their doors toward it (or toward
the middle of the compound). What does not fit is skipped with a warning in the report.

### Streets and blocks

A **block** has a road graph (nodes and straight edges, or a generator: `grid`, `organic`, `ring`) and builds the stone roads with kerbs.
Buildings are generated along both sides of every road — `fill` rules choose the kind with a weight, with random size ranges, colours
and roofs — with their doors toward the road; lots that would touch a road, another building or the block's outline are skipped.
A block with only `from` and `to` anchor references (for example `"farm/gate"` to `"castle/gate"`) becomes a straight road between those
two anchors, wherever the plans are placed or turned. Such a block gets houses along it unless it says `"fill": []` (a bare road).

### Terrain and biomes

A **terrain** plan is a ground sheet with the other plans standing on it. The **Terrain** button makes a 240 x 240 m meadow (or whichever
**Biome** you chose) with a hamlet, a farm, a watchtower and a path between the farm and the hamlet; put any plan inside a terrain
(as its child) and the ground is flattened under it, at the plan's own height (`z`), easing back into the relief over a few metres.
A path between two plans on different heights slopes from one to the other.

| Biome | Look |
|---|---|
| Meadow | rolling grass, lakes in the hollows, scattered trees, bushes and stones |
| Forest | dense dark conifers and round trees, bushes, small lakes |
| Desert | dunes of sand, cacti and stones, no water |
| Tundra | snow and moss, a few small conifers, many stones, ponds |
| Mountains | tall relief, forest in the valleys, rock and snow above |
| Island | land in the middle, sea all around, beach, trees and bushes |

Roads that cross a river get a **bridge** automatically; `ridged` (0..1) gives the relief crest lines — dunes in the desert, sharp ridges in the mountains.

Set `region_biome` (for example `"mountain"` on a meadow) to mix two biomes on one terrain: hills and plains, forest edges, an oasis in a desert.
`region_scale` sets the size of the patches, `region_bias` how much of the terrain each biome gets and `region_blend` how soft the border is.

Meadow, forest and mountain terrains get a **river** by default (`rivers`: `"auto"`, `"none"`, or your own paths with a width); it meanders
around your plans, always runs downhill and keeps trees off its banks.

The relief is made by a **Geometry Nodes** modifier on the terrain object (`GLA Terrain`): change *Amplitude, Feature Size, Detail,
Roughness, Seed, Base, Sea Level* or *Island* in the modifier panel and the ground, colours and water-line react at once (the water plane
and the vegetation are placed at build time, so press **Build** again after big changes). In the plan itself you can set `biome`, `width`,
`depth`, `resolution` (grid cell, smaller = finer and slower), `scatter` (vegetation density, 0 = none), and override the biome's numbers
(`amplitude`, `feature_size`, `sea_level`, `island`, ...) — see [PLAN_FORMAT.md](PLAN_FORMAT.md).

### Importing a floor plan (SVG / DXF)

Draw the site in Inkscape (or any CAD that exports DXF) and press **Import SVG/DXF...** in the Plans panel; set *Metres per unit* so one drawing unit is
the right size. Give each shape a label — in Inkscape the *Object ID* or *Label*, in DXF the layer name:

| Shape | Label | Becomes |
|---|---|---|
| closed outline | `house`, `chapel`, `stable`, `barn`, `hut`, `keep`, `well`, `tower` (default `house`) | a building of that kind, sized and turned like the outline |
| closed outline | `yard`, `farm`, `fence`, `ward`, `wall`, `compound` (+ `wood` / `stone` / `none`) | a compound with a fence and a gate that adopts the buildings inside |
| closed outline | a biome: `desert`, `forest`, `tundra`, `mountain`, `island`, `meadow` | a terrain region of that biome (the plan becomes a terrain) |
| open line / polyline | anything | roads (one bare-road block; crossing lines join) |
| circle | `tree`, `tower` (small circles default to trees) | a tree or a tower |

Then press **Build**. Edit the stored plan like any other (the *Edit a parameter* box), pick a **Style**, or add a terrain around it.

### Biome regions

Besides the noise mask, `region_polygons` puts the second biome exactly where you want it: a list of polygons (terrain coordinates, metres) or
`{"polygon": [[x, y], ...], "blend": 12}` entries; the border fades over `blend` metres. Use it for a desert patch, a forest around a village or a
mountain range along an edge.

### Cities and districts

The **City** button makes a walled city: a ring-and-spoke market centre, a grid craft quarter, an organic old town, gardens and a harbour road, joined by two
avenues, inside a 250 m wall with four gates. Every district is a block of its own — give it another `road_generator`, `fill` rules, `style` or `infill` —
and blocks keep their houses clear of each other's streets and houses, so you can add a district anywhere in the plan.

### Walled towns

The **Town** button makes a round town: a stone wall with towers (none in the gateway) and a gate with an approach road, and inside
it a ring-and-spoke street pattern lined with houses, chapels and stables. Put it inside a terrain to see it on the ground. Use the
**Style** dropdown for another culture, or change `params.shape` / the block's `road_generator` for another layout.

### Editing a plan from the panel

Under the plan list there is an **Edit a parameter** box: type the node (leave empty for the plan itself, or `farm`, `land/hamlet`), the key
(`biome`, `scatter`, `fence_height`, `floors`, `style`, `seed`, `transform.z` ...) and the value (a number, a word, `true`/`false`, or JSON like `[1, 2]`),
press **Set on <plan>**, then **Build**. A value that would break the plan is refused with the reason.

A block's `infill` (for example `"infill": 2.0`) places extra houses between the streets, not only along them — the Town example uses it.

### Tips for plans

* Change a parameter in the saved JSON (or in the plan's custom property), then press **Build** — rebuilds are cheap and exact.
* Press **Freeze** once a layout is right; from then on the buildings are fixed and can be moved by hand in the plan.
* Seeds are derived per node from the parent's seed and the node's id, so adding a building never reshuffles the others.
* Large plans: heavy parts (towers with interiors, many windows) cost vertices; set `detail` to `LOW` and drop interiors for big sites.

## Exporting

**Export tab**

* **Export Level (glTF/GLB)** — everything generated, as one binary `.glb` or `.gltf` + textures, optionally with the real lights.
* **Export Collision Mesh** — Floor + Walls + Stairs only, ready to use as a level's collision geometry.
* **Export Game Package (glb + json)** — the glTF plus a JSON ("gla-export/1") with what an engine has to know: walkable tiles
  merged into a few rectangles, entrance and exit, rooms, stairs, torch lights and decoration placements, in engine
  coordinates (x right, y up, z = −Blender y).
* **Export Package per Floor** — one `<name>_f0`, `_f1`… package per floor (or per sub-level), each with floor-relative
  positions and stair links to its neighbours. Needs Wall/Door/Stair grouping = Per Floor and *Separate by Floor/Room* run first.
* **Export Castle Package** (Structures tab, Castle) — the same format for a castle: walkable courtyard, gate passage, apron, the furnished
  keep hall and its props.

Worked example: the sibling game project *Vampire Adventure* loads these packages as playable locations (rectangle-based
walking, torches as real lights, doors that swing open as the player approaches, stairs that fade between floors).

---

## Tips

* **Reproduce a bug:** *Debug: Last Generation Params* > *Copy Parameters* copies every setting behind the last generation.
* **Polycount:** Masonry walls and towers are cheap thanks to the textured shell; *Brick Detail: Low* and switching off
  *Stair Railing* trim a tower further.
* **Collision and navigation:** export the collision mesh and let the engine bake its own navmesh; the game package's walk
  rectangles are for engines with rectangle-based navigation.
* **Ruins and rooms:** doorways never get blocked by ruin or rubble — passages are checked by ray casts in the test suite.
* **Regenerating:** towers and castles replace their previous version; their lights and furniture are rebuilt with them.
