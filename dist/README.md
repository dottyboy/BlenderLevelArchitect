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

[![License: GPL v3](https://img.shields.io/github/license/dottyboy/BlenderLevelArchitect)](../LICENSE)
[![Blender 4.2+](https://img.shields.io/badge/blender-4.2%2B-orange)](https://www.blender.org/)
[![Latest release](https://img.shields.io/github/v/release/dottyboy/BlenderLevelArchitect)](https://github.com/dottyboy/BlenderLevelArchitect/releases/latest)

Procedural game-level generator for Blender: a Wave-Function-Collapse-style room/corridor/stair
layout solver paired with automatic mesh generation (Geometry Nodes for floors, baked Python mesh
for walls and stairs).

![Example generated level -- rooms, corridors, doors, stairs, torches and decoration, each room individually colored](screenshot.png)

**Watch it generate:** [docs/showcase.mp4](../docs/showcase.mp4) — Generate Blueprint, Separate by
Floor/Room (real per-room color), Cave Mode's organic tunnels, a full populated level, and
Per-Floor Overrides, ~19 seconds.

<video src="../docs/showcase.mp4" controls width="100%"></video>

**Status: early testing release.** Feedback welcome, expect rough edges.

License: GPL-3.0-or-later (see `game_level_architect/LICENSE`).

## Requirements

- Blender 4.2 LTS or newer (tested through 5.2).

## Installing

1. Download `game_level_architect.zip` from the
   [Releases page](https://github.com/dottyboy/BlenderLevelArchitect/releases/latest) (don't
   unzip it).
2. In Blender: **Edit > Preferences > Add-ons > Install from Disk...**, then pick the zip.
   (On some Blender builds you can also just drag the zip into the 3D viewport.)
3. Enable **Game Level Architect** in the add-ons list if it isn't already checked.
4. Open the 3D Viewport sidebar (press **N**) and find the **Level Architect** tab.

The `Textures/` folder bundled inside the zip must stay next to the add-on's Python file — it's
used for the built-in flat-color material set. If you ever move the installed add-on folder by
hand, move `Textures/` along with it.

## Tutorials

- **Getting Started** ([docs/tutorial_getting_started.mp4](../docs/tutorial_getting_started.mp4),
  ~2:23) — walks through all 5 steps in order (Blueprint → Walls → Stairs → Doors → Props) plus
  Separate by Floor/Room, on one level built up step by step, with captions pointing at which
  panel setting to use.
- **Room Shapes & Corridor Stairs**
  ([docs/tutorial_room_shapes.mp4](../docs/tutorial_room_shapes.mp4), ~2:07) — Rectangular, Round,
  and Mixed room layouts, Cave Mode's organic tunnel networks, and Corridor Stairs (a 1-wide
  stairwell flush with the corridor, no separate room needed).
- **Materials & Per-Floor Overrides**
  ([docs/tutorial_materials.mp4](../docs/tutorial_materials.mp4), ~2:02) — Simple Viewport Colors
  vs. Style mode's procedural shaders, and Per-Floor Overrides (room size blending smoothly
  between breakpoints while shape and style switch), with a same-scale side-by-side of a small
  floor-0 room next to a large floor-3 room.
- **Props & Lighting** ([docs/tutorial_props_lighting.mp4](../docs/tutorial_props_lighting.mp4),
  ~2:03) — wall torches (a mesh plus a real Point light per lit torch), scattered crate/barrel/
  cone decoration, and a fully populated level with everything together.

## Basic workflow

The panel is organized into tabs (Setup / Walls / Stairs / Doors / Props / Export, icon row at
the top) — each tab holds that step's settings and its own Generate button, so only one step's
settings show at a time. A persistent Debug section stays at the bottom regardless of which tab
is open. **Presets** (Isometric / FPS-Immersive-Sim / Compact Roguelike / Megadungeon), above the
tab row, one-click set a bundle of settings tuned for a target camera/genre — Step 1 still has to
be pressed afterward, same as any other setting. The steps build on each other's output in order:

1. **Step 1: Generate Blueprint** — builds the room/corridor/stair layout and the floor mesh
   (via a Geometry Nodes modifier). Optional continuous room elevation and Corridor Stairs are
   both configured here too, before generating.
2. **Step 2: Generate Walls** — builds wall geometry from the blueprint's layout. Optional
   "Per Floor" grouping splits walls into one object per floor.
3. **Step 3: Generate Stairs** — builds stair geometry (stepped stairs or a smooth ramp).
   "Per Floor" or "Per Stair" grouping controls how many separate objects you get.
4. **Step 4: Generate Doors** — door frames at every point a corridor enters a room or two rooms
   meet directly, each with a real swinging panel object hinged on one edge ("Generate Door
   Panels", on by default). On UPBGE specifically, an experimental "UPBGE Hinge Physics" toggle
   (off by default) can also set each panel up with a rigid body + hinge constraint so it can
   swing during play — not yet confirmed to actually animate in a running game, only that the
   constraint is created correctly, so treat it as experimental until you've verified it yourself
   in a live UPBGE session.
5. **Step 5: Generate Props** — wall-mounted torches (each with a real light, not just a mesh)
   and scattered decoration (crate/barrel/cone, or themed furniture — tables, chairs,
   bookshelves, beds, coffins, candle stands — via the Theme setting), organized into their own
   "Procedural Level Props" collection so they can be hidden or deleted independently of the
   structural geometry.
6. **Round Tower** (Tower tab) — a standalone round tower at the 3D cursor: brick-textured shell with
   a real arched door, slit windows, stone frames, plinth, cornice and battlements, at a vertex
   budget picked by Brick Detail (Low/Medium/High), with floor slabs and spiral stairs inside and a Ruin slider that breaks the walls down.
7. **Castle** (Castle tab) — a walled castle at the 3D cursor: four corner towers with interiors, curtain
   walls with battlements and arrow slits, an arched gate, a keep and a courtyard; the Ruin slider breaks
   everything down.
8. **Export** — one-click glTF/GLB export (+ Game Package, per-floor packages and castle packages for an engine loader) (plus **Export Game Package**: glb + a JSON with walkable rectangles, entrance/exit, rooms, stairs and lights for an engine loader) of everything generated (Binary .glb or plain .gltf,
   optionally including the real torch lights), plus a separate **Export Collision Mesh** button
   that exports just Floor + Walls + Stairs — no Doors, Torches, Decoration, or Lights — suitable
   to assign directly as a level's collision geometry in a game engine.

**Round rooms have a real shape**, not a blocky per-tile approximation — every Round room's floor
is a merged n-gon disc (**Room Shape Sides**, Setup tab, 3 = triangle up to a smooth circle), its
wall hugs that same curve with a real opening wherever a corridor connects, and its doorway frames
(including the arch, with Round/Pointed Door Style) follow the wall's own curve at that exact spot
instead of standing at a straight, mismatched angle against it. By default (Walls tab, **Round
Rooms: Masonry**) that wall is a brick-textured stone ring with stone door frames and scattered
stones; **Classic** keeps the older plain-box ring with Room Shape Sides.

**Add Ceiling** (under Scale & Style) closes every room's ceiling instead of leaving it open —
turn this on for an FPS-style playtest so rooms don't open onto empty space overhead. It's a live
Geometry Nodes toggle, so it can be flipped after generating without re-running Step 1, and
Isometric Mode automatically hides it again for a dollhouse-style top-down view.

**Separate by Floor/Room** (next to Step 1) splits the blueprint mesh into one object per room
plus a combined corridor object per floor, organized into a collection tree (Floor N > Rooms /
Corridors) so a room or a floor's corridors can be hidden, isolated, or exported on their own.
Run it directly on the Step 1 object — it reads the still-live Geometry Nodes modifier itself,
no need to apply it first (doing that manually beforehand, via Object > Apply > Visual Geometry
to Mesh, actually breaks per-room coloring on the result — Blender's own Convert/Apply drops the
material list for this kind of setup, so let this button do that step instead).

Regenerating Step 1 rebuilds the whole layout from scratch (new seed unless "Random Seed" is
turned off); Steps 2-6 can each be re-run independently after tweaking their own settings without
regenerating the blueprint.

## Reporting issues

This is a testing release — if something looks wrong (stairs, walls, connectivity, materials),
note your generation settings (map size, room/stair counts, seed) along with what you saw, since
generation is fully seeded and reproducible. The panel's **Debug: Last Generation Params**
section has a **Copy Parameters** button that grabs the exact settings for you.

See `CHANGELOG.md` (next to this file) for version history and currently known issues before
reporting — your case might already be a documented tradeoff rather than a new bug.
