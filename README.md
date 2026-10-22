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
[![Automated checks](https://img.shields.io/badge/automated%20checks-1000%2B-brightgreen)](tests/blender_headless_test.py)

**Procedural dungeons, towers and castles for Blender** — a Wave-Function-Collapse-style room/corridor/stair solver with
brick-textured masonry, real doors and windows, spiral-stair towers, ruins, and engine-ready glTF packages.

<p align="center"><img src="docs/img/hero_castle.gif" alt="A castle with a different brick tint per tower, turning" width="720"></p>

## What you get

| | |
|---|---|
| **Layouts** | Rooms, corridors, stairs over several floors and sub-levels. Rectangular, Round, Mixed and Cave rooms, bent stairwells, Corridor Stairs, continuous elevation. Fully seeded and reproducible. |
| **Masonry** | Brick- and stone-textured walls (procedural normal maps, a few thousand vertices instead of thousands of modelled bricks), stone door frames and framed windows, a different brick colour per room. |
| **Structures** | A round **Tower** (spiral stairs, railing, lanterns, furniture) and a walled **Castle** (four towers, wall walk, gate, furnished keep). |
| **Ruins** | One slider breaks towers, castles and walls down: stepped jagged tops, breaches, collapsed arches, rubble. Doorways stay passable. |
| **Doors, windows, props** | Arched / pointed / flat doors with swinging panels, windows with glass, torches with real lights, themed furniture. |
| **Plans** *(experimental)* | Describe a site as a nested plan — fortress, farm, hamlet, street, district, walled town, hut cluster — in one of **seven style packs** (or a mix), with regular, round or organic shapes, standing on a **Geometry Nodes terrain** in one of six biomes; stored in the .blend and as JSON. See [Plans](#plans-from-one-building-to-a-site-experimental) and [the roadmap](docs/WORLD_GENERATOR_PLAN.md). |
| **Engine export** | glTF/GLB, collision mesh, and **game packages**: glb + JSON of walkable areas, rooms, stairs, lights and props — per floor if you like. |
| **Tested** | 1000+ automated checks (ray-cast passability, normals, vertex budgets, round-trips) on Blender 4.2 LTS and 5.2. |

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

## Plans: from one building to a site (experimental)

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

### Heightmaps and mixed biomes

<p align="center"><img src="docs/img/heightmap_terrain.png" alt="A terrain shaped by a greyscale heightmap, with desert, mountain and forest regions and a hamlet standing on the ground" width="900"></p>

A greyscale picture can shape the ground (`heightmap`, see [docs/examples/heightmap.png](docs/examples/heightmap.png)), `pad_mode: "terrain"` lifts the plans onto it,
and up to three more biomes can take over inside polygons or noise-made patches (`regions`).

### From a floor plan

<p align="center"><img src="docs/img/svgplan.png" alt="A village built from an SVG floor plan: houses, a chapel, a walled farm, roads and a tower, with a desert region marked in the drawing" width="900"></p>

Draw the site in Inkscape (or export a DXF from CAD — or paint a PNG with the colour legend), label the shapes (`house`, `chapel`, `farm_yard_wood`, `road_main`, `desert_dunes` ...) and import it —
closed outlines become buildings or fenced yards, lines become roads, circles trees and towers, and a shape labelled with a biome becomes a terrain region.
Try [docs/examples/village_plan.svg](docs/examples/village_plan.svg) with *Metres per unit* = 0.12.
The same village painted as a picture with the colour legend ([docs/examples/village_plan.png](docs/examples/village_plan.png), 0.15 m per pixel):

<p align="center"><img src="docs/img/picplan.png" alt="A village imported from a coloured PNG: houses, a barn, a wooden yard, a tower, roads with rounded ends and a desert region" width="900"></p>

### Seven style packs and a mix

<p align="center"><img src="docs/img/styles_sheet.png" alt="The same village in Medieval, Egyptian, Mexican, Chinese, Inca, Futuristic and Alpine styles, and a mixed street" width="900"></p>

Medieval, Egyptian, Mexican adobe, Chinese (curved roofs), Inca, Futuristic and Alpine chalet — each is data (materials plus building
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
* In Blender: sidebar **Level Architect > Plans (experimental)** — choose **Style**, **Shape** and **Biome**, pick a button, press **Build**.
  Full guide: [docs/USER_GUIDE.md](docs/USER_GUIDE.md#plans-sites-villages-towns); format: [docs/PLAN_FORMAT.md](docs/PLAN_FORMAT.md);
  roadmap towards bigger settlements, rivers and regions: [docs/WORLD_GENERATOR_PLAN.md](docs/WORLD_GENERATOR_PLAN.md).

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

The full walkthrough is the **[User Guide](docs/USER_GUIDE.md)**.

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

Short screen recordings (they predate the masonry, tower and castle features, but the core workflow is unchanged):

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
