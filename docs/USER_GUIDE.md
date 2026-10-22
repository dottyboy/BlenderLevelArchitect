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
[Towers and castles](#towers-and-castles) · [Ruins](#ruins) · [Exporting](#exporting) · [Tips](#tips)

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
