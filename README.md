<meta property="og:title" content="Game Level Architect">
<meta property="og:description" content="Procedural game-level generator for Blender — a WFC-style room/corridor/stair solver with automatic Geometry Nodes + Python mesh generation.">
<meta property="og:image" content="https://raw.githubusercontent.com/dottyboy/BlenderLevelArchitect/main/screenshot.png">
<meta property="og:url" content="https://github.com/dottyboy/BlenderLevelArchitect">
<meta property="og:type" content="website">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Game Level Architect">
<meta name="twitter:description" content="Procedural game-level generator for Blender — a WFC-style room/corridor/stair solver with automatic Geometry Nodes + Python mesh generation.">
<meta name="twitter:image" content="https://raw.githubusercontent.com/dottyboy/BlenderLevelArchitect/main/screenshot.png">

# Game Level Architect

[![License: GPL v3](https://img.shields.io/github/license/dottyboy/BlenderLevelArchitect)](LICENSE)
[![Blender 4.2+](https://img.shields.io/badge/blender-4.2%20LTS%20%E2%86%92%205.2-orange)](https://www.blender.org/)
[![Latest release](https://img.shields.io/github/v/release/dottyboy/BlenderLevelArchitect)](https://github.com/dottyboy/BlenderLevelArchitect/releases/latest)
[![Automated checks](https://img.shields.io/badge/automated%20checks-1400%2B-brightgreen)](tests/blender_headless_test.py)

**Generate whole game worlds in Blender — dungeons, castles, villages, hill cities, cities carved into mountains and houses traced from a floor-plan picture.**
Everything is procedural, seeded and reproducible, comes with real doors, windows, stairs and furniture, and is **checked to be walkable** before you export it as an engine-ready glTF or game package.

<p align="center"><img src="docs/img/hero_castle.gif" alt="A castle with a different brick tint per tower, turning" width="720"></p>

<p align="center">
<a href="https://github.com/dottyboy/BlenderLevelArchitect/releases/latest"><b>Download</b></a> ·
<a href="#install">Install</a> ·
<a href="#quick-start">Quick start</a> ·
<a href="docs/USER_GUIDE.md">User guide</a> ·
<a href="CHANGELOG.md">Changelog</a>
</p>

## Highlights

<table>
<tr>
<td width="33%"><a href="#a-house-from-a-picture-of-its-floor-plan"><img src="docs/img/house_open.png" alt="A house built from a floor-plan picture"></a><br><b>House from a picture</b><br><sub>Walls, windows, doors with swing arcs and storeys traced from a floor-plan image</sub></td>
<td width="33%"><a href="#a-city-carved-into-a-mountain"><img src="docs/img/rock_city.png" alt="A city carved into a mountain"></a><br><b>City in the rock</b><br><sub>Ledges, carved facades, rooms behind them, caves, a serpentine road</sub></td>
<td width="33%"><a href="#a-terraced-hill-city"><img src="docs/img/terrace_city.png" alt="A terraced hill city"></a><br><b>Terraced hill city</b><br><sub>Terraces joined by steps, walls, waterfalls, a palace on the summit</sub></td>
</tr>
<tr>
<td><a href="#the-swan-castle"><img src="docs/img/swan_castle.png" alt="The Swan castle"></a><br><b>Swan castle</b><br><sub>A tall castle with a stair tower and a banquet hall on every floor</sub></td>
<td><a href="#a-mansion-and-generated-villas"><img src="docs/img/mansion.png" alt="A country house"></a><br><b>Mansion and villas</b><br><sub>A house from a floor plan, or generated plans: bar, L, U, T, ring</sub></td>
<td><a href="#terrain-and-biomes"><img src="docs/img/townland.png" alt="A walled town on a terrain"></a><br><b>Terrain, biomes, towns</b><br><sub>Geometry Nodes ground, six biomes, seven style packs</sub></td>
</tr>
</table>

## Install

1. Download `game_level_architect.zip` from the [Releases page](https://github.com/dottyboy/BlenderLevelArchitect/releases/latest) (don't unzip it).
2. In Blender: **Edit > Preferences > Add-ons > Install from Disk…** and pick the zip. Enable **Game Level Architect**.
3. Open the 3D Viewport sidebar (**N**) and find the **Level Architect** tab.

Requires **Blender 4.2 LTS or newer** (tested on 4.2.21, 5.2.1 and 5.2.2). The bundled `Textures/` folder must stay next to the add-on file.

## Quick start

1. **Setup** tab → pick a Preset or set a map size.
2. **Walls** tab → Wall Style *Masonry*.
3. Press **Generate All Steps** (or run Step 1–5 one by one: Blueprint, Walls, Stairs, Doors, Props).
4. **Structures** tab (choose Tower or Castle) → move the 3D cursor → **Generate**.
5. **Export** tab → **Export Level (glTF/GLB)** or **Export Game Package**.

**A whole site instead?** Open the **Plans** tab, pick a **Style** and **Biome**, choose something from **Add a plan at the 3D cursor** (a village, a terrace city, a rock city, a villa...) and press **Build**.
**A house from a drawing?** Plans tab → **House from Floor-Plan Picture...**, pick the picture, set its width in metres.

The full walkthrough is the **[User Guide](docs/USER_GUIDE.md)**.

## What you get

| | |
|---|---|
| **Dungeons and levels** | Rooms, corridors, stairs over several floors and sub-levels. Rectangular, Round, Mixed and Cave rooms, bent stairwells, Corridor Stairs, continuous elevation. Fully seeded and reproducible. |
| **Masonry** | Brick- and stone-textured walls (procedural normal maps, a few thousand vertices instead of thousands of modelled bricks), stone door frames and framed windows, a different brick colour per room. |
| **Towers, castles, ruins** | A round **Tower** (spiral stairs, railing, lanterns, furniture) and a walled **Castle**; one **Ruin** slider breaks them down with jagged tops, breaches and rubble, and doorways stay passable. |
| **Plans: whole sites** | A site described as nested data — fortress, farm, hamlet, street, district, walled town, huts, terrace city, rock city — in one of **seven style packs** (or a mix), with regular, round or organic shapes, on a **Geometry Nodes terrain** in six biomes. Stored in the .blend and as JSON. |
| **Buildings from plans** | **Mansion** from a room plan, **Villa** generator (random plans), **Swan castle**, and a **house traced from a picture** of its floor plan (several pictures for several floors). |
| **Import** | SVG, DXF or a painted PNG for a whole village; a greyscale **heightmap** for the ground; a floor-plan picture for a house; a **tile-map picture** (a level drawn from square tiles) for a 3D level that keeps its pixel look. |
| **Engine export** | glTF/GLB, collision mesh, and **game packages**: glb + JSON of walkable areas, rooms, stairs, lights and props — per floor if you like. |
| **Tested** | 1400+ automated checks (ray-cast passability, grid walk checks, normals, vertex budgets, round-trips) on Blender 4.2 LTS and 5.2. |

## Gallery

<table>
<tr>
<td width="50%"><img src="docs/img/generated_level.png" alt="A generated level: rooms with their own brick colours, windows, doors, torches and furniture"><br><sub>A generated level — every room its own brick tint, windows, doors, torches, themed furniture</sub></td>
<td width="50%"><img src="docs/img/round_rooms.png" alt="Round rooms with masonry rings and furniture"><br><sub>Round rooms with masonry rings and arched openings</sub></td>
</tr>
<tr>
<td><img src="docs/img/castle_intact.png" alt="The castle with mixed brick colours"><br><sub>The Castle, <i>Mixed</i> brick colours</sub></td>
<td><img src="docs/img/castle_ruin.png" alt="The castle as a ruin"><br><sub>The same generator with the <i>Ruin</i> slider up</sub></td>
</tr>
<tr>
<td><img src="docs/img/tower_ruins.png" alt="Three towers at increasing ruin"><br><sub>Towers at Ruin 0.3 / 0.6 / 1.0</sub></td>
<td><img src="docs/img/tower_interior.png" alt="A tower cut open to show floors, spiral stairs and furniture"><br><sub>A tower cut open: floors, spiral stairs with railing, furniture</sub></td>
</tr>
</table>

<table>
<tr>
<td width="33%"><img src="docs/img/ruin_slider.gif" alt="The Ruin slider from 0 to 1"><br><sub>The <b>Ruin</b> slider, 0 → 1</sub></td>
<td width="33%"><img src="docs/img/tint_cycle.gif" alt="The brick colour options"><br><sub>The brick colours</sub></td>
<td width="33%"><img src="docs/img/seeds.gif" alt="Eight different seeds"><br><sub>Eight seeds, one click each</sub></td>
</tr>
</table>

### In a game

The *Game Package* export feeds a real engine: the sibling project *Vampire Adventure* (Godot) loads packages as playable
locations — walkable by rectangles, torches as real lights, doors that swing open, stairs that fade between floors.

<table>
<tr>
<td width="50%"><img src="docs/img/game_crypt.png" alt="Harker in a generated round room"><br><sub>A generated catacomb in the game</sub></td>
<td width="50%"><img src="docs/img/game_castle.png" alt="The generated castle's gate in the game"><br><sub>The generated castle's gate</sub></td>
</tr>
</table>

## Plans: from one building to a whole site

A **plan** describes a whole site as nested data — a fortress, a farm, a hamlet, a street, a district, a cluster of huts — and the
generator builds it. Plans live in the .blend and as `.plan.json`, are fully seeded, and can place buildings for you.

<table>
<tr>
<td width="50%"><img src="docs/img/plans_fortress.gif" alt="A fortress turning: outer ward with corner towers and a gate, the keep inside"><br><sub><b>Fortress</b> — outer ward, corner towers, gate, keep</sub></td>
<td width="50%"><img src="docs/img/plans_block.png" alt="A district: a grid of streets with varied houses facing the road"><br><sub><b>Block</b> — streets with kerbs, houses facing the road in varied colours</sub></td>
</tr>
<tr>
<td><img src="docs/img/plans_organic.png" alt="An organic district with winding streets and a free-form outline"><br><sub><b>Organic</b> — winding, noise-based streets inside a free-form outline</sub></td>
<td><img src="docs/img/plans_roundtown.png" alt="A round town in Chinese style: ring road, spokes, curved roofs"><br><sub><b>Round</b> — ring-and-spoke streets (here in the Chinese style)</sub></td>
</tr>
</table>

### Terrain and biomes

<p align="center"><img src="docs/img/townland.png" alt="A walled round town on a meadow terrain with lakes, trees and a trodden-earth pad under the town" width="900"></p>

A **terrain** plan is a ground sheet made by a **Geometry Nodes** modifier (noise relief, island fall-off, colours by altitude and slope).
Everything planned on it stands on a flattened pad at its own height, and paths between plans on different heights slope. Six biomes —
meadow, forest, desert, tundra, mountains, island — bring their own palette, relief, lakes or sea, and trees, bushes, rocks and cacti.

<p align="center"><img src="docs/img/biomes_sheet.png" alt="The same hamlet, farm and watchtower in the meadow, forest, desert, tundra, mountains and island biomes" width="900"></p>

### A world generator

<p align="center"><img src="docs/img/worldgen_overview.png" alt="A generated 2 km island seen from above: biomes from tundra in the north to desert in the south, rivers running to the sea, a crater lake, roads (brown) joining the monuments (dark squares)" width="720"></p>

`generate_world(size, res, seed)` makes a whole island as **maps and data** in a couple of seconds: height, **rivers by flow** (from the high ground down to the sea), lakes, biomes by latitude and altitude, **monuments** — the add-on's towns, castles, fortresses, farms, hamlets, huts, towers and rock cities placed by rules (biome, slope, height, distance to water, spacing) on levelled ground — and **roads** between them (a spanning tree plus a ring road, cheapest over gentle ground, bridges over rivers).
`world_build` then builds it in Blender chunk by chunk (seamless ground, lakes, rivers, roads, every monument as its plan on levelled ground; about 30 s for 2 km) and `world_export_chunks` writes one .glb per chunk plus the manifest:

<p align="center"><img src="docs/img/worldgen_aerial.png" alt="The generated island built in Blender: biomes, lakes, roads and monuments" width="900"></p>

`tools/generate_world.py` writes `world.json`, a 16-bit height map, a biome map and the overview above (`--build` also builds and exports the chunks). It is the first stage of a game framework (see the *World Runtime* Godot project).

### Big worlds

<p align="center"><img src="docs/img/world_chunks.png" alt="A mountain world of 4 x 3 terrain chunks, 640 by 480 metres, snow on the ridges and lakes in the valleys, no seams between the chunks" width="900"></p>

*Add a plan > World* builds a grid of terrain **chunks** (up to 16 x 16, 160 m each by default). Every chunk reads the same noise at its place in the world, so ridges, valleys and the water line **continue exactly across the seams**; each chunk is also an ordinary terrain node
you can put villages and towns under. **Export World Chunks** writes one .glb per chunk plus a `gla-world/1` manifest, so an engine can stream the pieces. The picture is 640 x 480 m of the Mountains biome ([tools/render_world.py](tools/render_world.py)).

### Heightmaps and mixed biomes

<p align="center"><img src="docs/img/heightmap_terrain.png" alt="A terrain shaped by a greyscale heightmap, with desert, mountain and forest regions and a hamlet standing on the ground" width="900"></p>

A greyscale picture can shape the ground (`heightmap`, see [docs/examples/heightmap.png](docs/examples/heightmap.png)), `pad_mode: "terrain"` lifts the plans onto it,
and up to three more biomes can take over inside polygons or noise-made patches (`regions`).

### A village from a drawing

<p align="center"><img src="docs/img/svgplan.png" alt="A village built from an SVG floor plan: houses, a chapel, a walled farm, roads and a tower, with a desert region marked in the drawing" width="900"></p>

Draw the site in Inkscape (or export a DXF from CAD — or paint a PNG with the colour legend), label the shapes (`house`, `chapel`, `farm_yard_wood`, `road_main`, `desert_dunes` ...) and import it —
closed outlines become buildings or fenced yards, lines become roads, circles trees and towers, and a shape labelled with a biome becomes a terrain region.
Try [docs/examples/village_plan.svg](docs/examples/village_plan.svg) with *Metres per unit* = 0.12.
The same village painted as a picture with the colour legend ([docs/examples/village_plan.png](docs/examples/village_plan.png), 0.15 m per pixel):

<p align="center"><img src="docs/img/picplan.png" alt="A village imported from a coloured PNG: houses, a barn, a wooden yard, a tower, roads with rounded ends and a desert region" width="900"></p>

### A terraced hill city

<p align="center"><img src="docs/img/terrace_city.png" alt="A walled terraced hill city: round, polygonal and rectangular terraces joined by flights of steps, domed houses, village houses, arcades, fountains, trees and a domed palace on the summit" width="900"></p>

The **Terraces** button builds a stepped hill city you can walk through: irregular, off-centre terraces (rectangles with cut corners and bays, ellipses, six to twelve sided polygons, capsules), one to three flights of
real steps up to each, a crenellated wall with towers and a gate across a pool, waterfalls, fountains, trees, and buildings of many kinds — domed houses with furnished rooms and doors that swing (separate `..._Panel_NNN` objects with their
origin on the hinge), ruins, arcades, belfries, and houses, chapels and huts from the village generator in the textures of the plan's style — with a domed palace on each summit. **Twin** gives two summits joined by an arched
viaduct, **Land** puts the city in a heightmap terrain. A built-in height-grid walk proves you can get from the gate to every palace and room. See the [user guide](docs/USER_GUIDE.md).

<p align="center"><img src="docs/img/terrace_twin.png" alt="Two summits in the Egyptian style joined by a viaduct" width="445"> <img src="docs/img/terrace_land.png" alt="The city in a heightmap valley with mountains behind" width="445"></p>

### A city carved into a mountain

<p align="center"><img src="docs/img/rock_city.png" alt="A city carved into a mountain: ledges one above the other with carved facades, a serpentine road, trees and a summit" width="900"></p>

The **Rock city** button makes **the mountain first** — a ridge that follows the stepped profile of the city and climbs on to a summit — and cuts the ledges into it. Each ledge is uneven and curved, has a cliff wall with
**carved facades** (temple fronts, house fronts, tombs), a **real furnished room behind every facade** with a door that opens, columned porticos, lanterns, fountains, stairs up the side of each cliff, and **caves** with stalactites and a pool.
A serpentine road zigzags up to the first ledge. The rock is procedural (stretched-noise strata, no image tiles). A grid walk proves the road, every ledge, the stairs, every room and the caves can be reached.

<p align="center"><img src="docs/img/rock_city_close.png" alt="Close view of carved facades and porticos" width="445"> <img src="docs/img/rock_city_cave.png" alt="Inside a cave with stalactites" width="445"></p>

### The Swan castle

<p align="center"><img src="docs/img/swan_castle.png" alt="A tall castle with a round stair tower in the middle, pointed windows on every floor, an arched front door, gable roofs and four corner turrets with spires" width="430"> <img src="docs/img/swan_hall.png" alt="The banquet hall inside: long tables with chairs, gold chandeliers, pointed windows" width="640"></p>

The **Swan** button builds a tall castle in the manner of a "Swan Lake" cutaway out of the plugin's own parts: a **round stair tower** in the middle (the round tower builder: a floor and a turn of spiral stairs per storey), **outer walls** with tall pointed
windows from the village houses' wall-run builder, **gable roofs** from the house roof builder, a **dome** over the stair tower and four **corner turrets** with spires. Behind the arched front door is a lobby with a fountain, and every floor has
a great hall on each side of the stair tower — banquet hall, ballroom, throne room, library, treasury, salon, gallery, then bedrooms — furnished and lit. A built-in walk check proves every hall can be reached from the stair tower. `palace: "castle"` puts it on
the summit of a terrace city (the **Land** example does), which is how the picture above the Land section was made:

<p align="center"><img src="docs/img/terrace_land.png" alt="A walled terraced city with the Swan castle on its summit, in a valley of forested hills with mountains behind" width="900"></p>

### A mansion and generated villas

<p align="center"><img src="docs/img/mansion.png" alt="A long Victorian country house with two round stair towers, a servants' wing, pointed windows, gable roofs and chimneys" width="640"> <img src="docs/img/mansion_gallery.png" alt="The two-storey picture gallery inside: a ring of clerestory windows, chandeliers, busts and frames" width="400"></p>

The **Mansion** button builds a country house from a **floor plan given as data** — rooms with a name, a floor, a rectangle and a kind. The built-in plan `bearwood` follows the arrangement of a real Victorian house:
public rooms round a two-storey picture gallery, a stair hall with a tower, bedrooms and nurseries upstairs and a long servants' wing — 48 rooms on three floors. Doors are found from the plan, the stair towers come from the plugin's round
tower builder, rooms are furnished by kind and lit, and a built-in check proves every room can be reached from the front door. Pass your own plan (a dict of rooms) to build any other house.

The **Villa** button builds a house from a **generated plan** instead (`plan: "random"`): square junction halls joined by wings, laid out as a bar, an L, a U, a T or a ring round a courtyard (`plan_shape`, `plan_seed`, `floors`, `wing`, `depth`),
with stair towers and entrances found by the generator and the same walk check. The Swan castle likewise takes `shuffle`, `roof_pitch`, `turret_r` and `top` (`dome` / `spire` / `lantern`) for different silhouettes.

<p align="center"><img src="docs/img/villa.png" alt="A generated U-shaped villa" width="640"></p>

### A house from a picture of its floor plan

<p align="center"><img src="docs/examples/house_floorplan.png" alt="A drawn floor plan: three bedrooms, a living room and a kitchen, doors drawn as swing arcs" width="440"> <img src="docs/img/house_open.png" alt="The house built from that picture, roof off" width="440"></p>

Press **House from Floor-Plan Picture...** and pick a picture of an architect's plan — black walls on a light background, furniture and text as thin lines, doors as swing arcs. Tell it how wide the drawing is in metres and the house is built:
**walls** from the thick strokes, **windows** from the gaps in outside walls, **doors** from their swing arcs (each with a leaf that opens), a floor, a roof and lights; the opening lowest in the picture is the front entrance.
**Several pictures give several floors**, joined by stairs, and a built-in walk check proves every room can be reached. Try [docs/examples/house_floorplan.png](docs/examples/house_floorplan.png) at 13 m wide
(made by [tools/make_house_example.py](tools/make_house_example.py)). Limits: walls must be axis-aligned, a door whose arc touches other lines stays an open doorway, rooms are not named and furniture is not built.

### A level from a tile map

<p align="center"><img src="docs/img/tilemap_demo.png" alt="A 3D level built from a tile-map picture: rounded forest mounds, a lake with sloping banks, brick walls with bevelled tops, a dirt path" width="900"></p>

<p align="center"><img src="docs/examples/tilemap_demo.png" alt="The 2D tile map" width="440"> <img src="docs/examples/tileset_demo.png" alt="The tileset" width="440"></p>

The **Level from Tile Map** button turns a picture of a whole level made of square tiles — the kind 16-bit action games used — into a 3D level that keeps the pixel look. The ground is one smooth surface: **forest tiles swell into rounded mounds**,
**water sits lower and the banks slope into it**, and **stone tiles stand up as walls** in bands one tile high with a bevelled top. The picture itself is the texture, read with nearest filtering. With a **tileset** (a sheet of tiles and a small JSON that names each tile's role: floor, canopy, stone or water)
every tile is matched exactly; without one the roles are read from colour and texture. The pictures above are an original demo tileset with **autotiles** (coasts, forest edges and paths pick rounded edge tiles from their neighbours) and a generated map ([tools/make_tileset.py](tools/make_tileset.py)); [tools/reskin_map.py](tools/reskin_map.py) re-skins any tile map with such a tileset.
Use pictures you may use; none from commercial games is shipped.

**A dungeon from scratch, in an ink style**: [tools/make_ink_tileset.py](tools/make_ink_tileset.py) draws an original *ink on paper* tileset (pale floors with a dotted grid, brick walls in black outline, stippled rock with small stones, round pillars, a chasm) and generates a dungeon map from nothing: rooms and corridors carved out of rock, a pillared hall, a ring of pillars and a chasm.
Walls are the rock tiles next to floor, pillars come from the tileset's `prop` role and become real cylinders:

<p align="center"><img src="docs/img/ink_dungeon.png" alt="A generated ink-style dungeon built in 3D: brick-lined walls rising from stippled rock, pillared halls, a chasm" width="900"></p>

**Walk it in a game**: **Export Tile Map Package (glb + json)** writes the level as glTF plus a `gla-export/1` JSON (exact walk rectangles, entrance, exit, props, trees),
and [examples/godot_tilemap_demo](examples/godot_tilemap_demo) is a small Godot 4 project that loads such a package and lets you walk through it:

<p align="center"><img src="docs/img/godot_tilemap_demo.png" alt="The tile map level in Godot: a figure standing on grass among 3D trees, a lake and a brick wall" width="900"></p>

The same project also plays the **ink dungeon** (`godot --path . -- --level ink`), including its raised platform: the walk rectangles of a second floor can only be entered over the stairs, and the height rises smoothly on them.

<p align="center"><img src="docs/img/godot_ink_demo.png" alt="The ink-on-paper dungeon in Godot: a figure in a brick-walled room, solid stippled rock around it" width="900"></p>

### Ink on paper, as a style

<p align="center"><img src="docs/img/ink_papers.png" alt="The same village in the ink style on white, old and grey paper: pale blocks outlined in black, stippled grass tinted green, a river drawn in wave lines" width="900"></p>

**Ink on paper** is a style pack like the others (it is not part of *Mixed*): walls, trim, roofs and wood are pale blocks outlined in black, and while a plan of this style is built the **whole scene** wears the same look — the ground is stippled paper
(denser on grass, which tints the paper green), leaves are stippled and greenish, water is drawn in wave lines on bluish paper, rock in cracks. Choose the **paper** in the Plans panel when the style is Ink: white, old (yellowed), grey or cream; the plan stores it
as its `paper` field. It makes a quick **blockout** look and a clean base for hand-inked art. The tile-map tools draw their ink tileset on any of the papers too (`INK_PAPER=old python3 tools/make_ink_tileset.py`).

### Seven style packs and a mix

<p align="center"><img src="docs/img/styles_sheet.png" alt="The same village in Medieval, Egyptian, Mexican, Chinese, Inca, Modern and Alpine styles, and a mixed street" width="900"></p>

Medieval, Egyptian, Mexican adobe, Chinese (curved roofs), Inca, Modern (the `futuristic` pack) and Alpine chalet — each is data (materials plus building
proportions), so the same plan can be built in any of them, or in **Mixed**, where every building picks its own pack.

### Huts: straw, branches, timber, cob, earthbag, aircrete

<p align="center"><img src="docs/img/plans_hutforms.png" alt="Huts in several forms: dome, dome on stilts, tunnel, A-frame, silo, two-storey box, box on stilts, three levels over a basement" width="900"></p>

Small modular buildings (3-5 × 4-8 m) in six construction methods and five forms (box, dome, tunnel, silo, A-frame), up to three
levels above a basement, on stilts, as dwelling or storage — and they can be **attached wall to wall** with passages, so they grow into bigger structures:

<p align="center"><img src="docs/img/plans_hutcluster.png" alt="A cluster of attached huts with passages between them" width="640"></p>

### What a plan can contain

* **Buildings**: tower, castle, keep, house (stairs, basement, stilts, chimney, open door leaf), chapel, stable, barn, well, hut, trees,
  barrels, crates, haystacks — gable, hip, curved or flat roofs, ruin.
* **Compounds**: any footprint — rectangle, circle or free-form blob — with a stone or wooden enclosure and gates, and `layout` rules
  ("1 chapel on the wall, 1-2 stables, 3 houses, trees on a ring, huts attached to each other") that place buildings without overlap,
  keep the way from the gate to the castle free and turn doors toward it.
* **Blocks**: a road graph (hand-made or generated: grid, organic, ring) with kerbed stone roads and buildings along both sides; a block can
  also be a road between two anchors, e.g. farm gate to castle gate.
* In Blender: sidebar **Level Architect > Plans** — choose **Style**, **Shape** and **Biome**, open **Add a plan at the 3D cursor** (plans are grouped: buildings, places, cities on hills and in rock, ground), press **Build**.
  Full guide: [docs/USER_GUIDE.md](docs/USER_GUIDE.md#plans-sites-villages-towns); format: [docs/PLAN_FORMAT.md](docs/PLAN_FORMAT.md);
  roadmap towards bigger settlements, rivers and regions: [docs/WORLD_GENERATOR_PLAN.md](docs/WORLD_GENERATOR_PLAN.md).

## The panel at a glance

| Tab | What it does |
|---|---|
| **Setup** | Map & seed, rooms, room shape, floors and sub-levels, elevation, scale, style, **Step 1** |
| **Walls** | Wall Style (Boxes / Masonry), Room Brick Colors, Wall Ruin, windows, Round-room walls, **Step 2** |
| **Stairs & Doors** | Stair style, bends, grouping (**Step 3**); door style, height, frames, swinging panels (**Step 4**) |
| **Props** | Torches and lights, decoration, themes, **Step 5** |
| **Export** | glTF/GLB, collision mesh, game packages (whole level or per floor) |
| **Structures** | Switch between **Tower** (size, door, windows, interior stairs/railing/lanterns/furniture, Brick Color, Ruin) and **Castle** (size, towers, gate, keep, hall furniture, Brick Color, Ruin, castle package export) |

## Tutorials

Short screen recordings of the level generator (they predate towers, castles and plans, but the core workflow is unchanged):

- **Showcase** — [docs/showcase.mp4](docs/showcase.mp4), ~19 s
- **Getting Started** — [docs/tutorial_getting_started.mp4](docs/tutorial_getting_started.mp4), 2:23 — all five steps in order
- **Room Shapes & Corridor Stairs** — [docs/tutorial_room_shapes.mp4](docs/tutorial_room_shapes.mp4), 2:07
- **Materials & Per-Floor Overrides** — [docs/tutorial_materials.mp4](docs/tutorial_materials.mp4), 2:02
- **Props & Lighting** — [docs/tutorial_props_lighting.mp4](docs/tutorial_props_lighting.mp4), 2:03

## More documentation

| | |
|---|---|
| [User Guide](docs/USER_GUIDE.md) | How to use every tab, with tips |
| [CHANGELOG.md](CHANGELOG.md) | Version history and known issues |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Architecture, design decisions, how things are tested |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Reporting bugs and contributing |
| `tools/` | Scripts that render the pictures and animations on this page |

## Known limitations

* A tower's interior is one floor per storey connected by one spiral stair; the castle's tower floors are not yet part of the
  game package's walkable ground.
* Upper floors of a multi-floor game package are separate packages (one location per floor), not one continuous level.
* On UPBGE, "Hinge Physics" for door panels is experimental and unverified in a live session.
* Early testing release — expect rough edges. Generation is fully seeded, so bug reports with settings are easy to reproduce
  (*Debug: Last Generation Params > Copy Parameters*).

## License

GPL-3.0-or-later — see [LICENSE](LICENSE).
