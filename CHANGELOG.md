# Changelog

Game Level Architect — early testing release. Generation is fully seeded, so any level can be
reproduced exactly from its settings (see **Debug: Last Generation Params** in the panel).

## 0.23.0

- **Round rooms now have a real shape.** Every Round room's floor is a real merged n-gon disc
  (`Room Shape Sides`, 3=triangle, 4=square/diamond, higher=smoother circle) instead of a blocky
  per-tile grid approximation, and the guard-rail wall now hugs that same shape exactly -- with a
  real opening left wherever a corridor connects, not a fully sealed ring. Rect rooms are
  unchanged.
- **New: Presets** (Isometric / FPS-Immersive-Sim / Compact Roguelike / Megadungeon). One click
  sets Width/Rooms/Room Shape/Sub-Levels/Elevation/Stairs/Walls/Doors/Torches to values tuned for
  a target camera/genre -- Step 1 still has to be pressed afterward, same as any other setting.
- Known limitation: a Round room's door frame is still a straight box, even against its now-curved
  wall -- doors still open in the correct place, the frame shape itself just doesn't match yet.

## 0.22.0

- **New: Export Collision Mesh** (Export tab, second button). Exports Floor + Walls + Stairs
  only -- no Doors, Torches, Decoration, or Lights -- suitable to assign directly as a level's
  collision geometry in a game engine. Doors are left out because they're a walk-through frame by
  design; their posts would otherwise be a minor snag at every doorway.

## 0.21.0

- **New: One-click glTF/GLB Export** (new **Export** tab). Selects every generated object and
  exports straight to `.glb`/`.gltf`, aware of the addon's own naming/grouping so you don't have
  to know which objects to select yourself. Two settings: **Binary (.glb)** (default -- one
  self-contained file) and **Include Lights** (default on -- exports the real torch-placed Point
  lights too). glTF only for now, not FBX.

## 0.20.0

- **New: Arched Doors + Entrance/Exit Gates.** Ordinary doorways can now use a Round or Pointed
  arch instead of a flat lintel (**Style**, Doors tab, plus an **Arch Height** slider). Entrance
  and Exit always get their own larger, always-arched Gate in the usual green/red, regardless of
  Style, so they read as landmarks distinct from an ordinary room doorway.
- **New: Bent Stairwells.** Room-based stairwells can now bend through one flat landing instead
  of climbing in a single straight line -- a 90-degree L turn or a 180-degree U dog-leg
  (**Bend Chance** / **Bend Style**, Stairs tab). Off by default; not available with Corridor
  Stairs, which is too narrow for a landing.

## 0.19.0

- **New: Trim-sheet-ready UVs.** Every baked mesh (Walls/Doors/Stairs/Ramps/Torches/Decoration)
  now gets real world-space UVs instead of a flat placeholder, so a tiling texture or trim sheet
  repeats correctly across a wall run instead of sampling one pixel everywhere. New **UV Tile
  Size** setting (Scale & Style section) controls how large a texture reads in-world (meters per
  tile). Simple Viewport Colors' flat swatches look identical either way -- this only matters once
  you assign your own detailed texture.
- **New: Round Corners** (Walls tab) -- an opt-in live Bevel modifier that rounds sharp wall
  corners, with an adjustable radius. Doesn't touch the underlying wall mesh, so it's adjustable
  after generation with no regeneration needed.
- **New: Freeze for Texture Work** (Setup tab) -- renames the current Blueprint/Walls/Stairs/
  Doors/Props out of the way into a dedicated collection, so the next Generate click can't touch
  them. Lets you hand-apply materials/textures to a specific generated level and keep experimenting
  with settings afterward without losing that work.

## 0.18.0

- **New: Per-Floor Overrides.** In the Rooms section, add breakpoints like "floor 0: small
  rectangular rooms, Dungeon style" / "floor 5: big round rooms, Cave style" -- room size blends
  smoothly between breakpoints, Shape and Style switch at each one. Leave the list empty (the
  default) and nothing changes from before. Doesn't apply while Room Shape is Cave (the whole
  level stays Cave, as before); Walls/Doors/Stairs/Props still use one material for the whole
  level regardless of these breakpoints.
- **Lower polycount for Stairs, Ramps, and Decoration** -- same idea as 0.17.4's Walls/Doors fix:
  every stair tread, ramp segment, and prop (crate/barrel/cone) no longer carries a bottom face,
  since it was always hidden behind the floor underneath it. Torches were checked too and left
  as-is -- they're wall-mounted, not floor-touching, so there's nothing hidden to remove.

## 0.17.4

- **Fixed: the last Corridor Stairs "missing wall" cases** (~7-10% of stair cells, previously a
  known, accepted residual). A corridor pathfound after a stairwell was placed could still end up
  running alongside its open (no-walkway-by-design) side with nothing between them. Now fixed at
  wall-generation time -- every Corridor Stairs cell's perpendicular sides always get a wall,
  regardless of what ends up next to them. Room-based stairs (which have a real walkway there by
  design) are unaffected.
- **Lower polycount for Walls and Doors** -- every wall box, and every door post, no longer
  carries a bottom face (it was always hidden behind the floor tile underneath it). A door's
  lintel keeps its bottom face, since that one actually is visible from underneath. Purely a
  polycount reduction on large maps; nothing should look different.

## 0.17.3

- **Major fix: "Separate by Floor/Room" could crash on its second run** with
  `RuntimeError: Collection '...' already in collection '...'`. Caused by Blender leaving the
  outliner's active collection sitting inside the PREVIOUS run's own nested split tree; running
  the operator again then tried to re-file that same top-level collection inside its own
  descendant. Fixed -- re-running it (or Generate Props, which had the same latent exposure) no
  longer depends on what's currently active in the outliner.

## 0.17.2

- **"Separate by Floor/Room" now clearly refuses to run if you applied the Geometry Nodes
  modifier by hand first**, instead of silently giving rooms an empty material slot. This
  operator has never needed a manual "Apply Modifier" step (since 0.13.1) -- it does that
  correctly itself -- and doing it anyway discards the per-room material data Blender doesn't
  preserve across a real Apply Modifier. If you see this error: regenerate the Blueprint (Step 1)
  and run Separate by Floor/Room directly on it, without applying the modifier first.

## 0.17.1

- **Fixed: after "Separate by Floor/Room," a room object's Material field in the Properties
  panel showed the wrong material** (a floor-level color, not that room's own color) even though
  the room rendered with the correct color in the viewport. Split objects used to carry the
  entire level's material list (every floor level, every room, entrance, exit -- 30-50+ entries
  for a real level); now each split object only carries the material(s) it actually uses, so its
  Material field shows the right one immediately, no manual reassignment needed.

## 0.17.0

- **New: every room/corridor/ceiling and baked mesh (Walls, Stairs, Doors, Torches, Decoration)
  now carries a "viewport_color" Color Attribute.** In the viewport shading dropdown, switch
  Solid Shading's Color from "Material" to "Attribute" and rooms show their real distinct colors
  immediately -- no UV map, no material setup, and none of the fragility 0.16.1-0.16.3 fixed
  (this reads a plain per-face color, not a material or a UV-sampled texture, so it can't be
  affected by either class of bug). A second, more robust way to see per-room color at a glance,
  alongside "Material" mode (0.16.3) and "Texture" mode (0.16.1/0.16.2).
- **Fixed: Style mode (procedural dungeon/cave/open-area shaders) materials never set a real
  viewport display color at all**, so Solid Shading's "Material" color mode always showed them as
  flat default gray, room tint or not. Now they carry their real tinted color there too.

## 0.16.3

- **Major fix: Separate by Floor/Room objects all showed the same color, regardless of viewport
  shading mode.** The real root cause (not the UV gaps fixed in 0.16.1/0.16.2, though those were
  real too): rebuilding the material list during the split silently reset every face's material
  assignment to the same one, so every room object pointed at the same color -- only "Random"
  viewport shading (which colors by object, not material) ever looked different between rooms.
  Every room now correctly keeps its own distinct color after separating.

## 0.16.2

- **Fixed: Walls, Doors, Stairs, Ramps, Torches, and Decoration now also have a UV map.** 0.16.1
  only fixed this for the floor/room mesh -- every other generated mesh is built through separate
  code and had the exact same "Texture" viewport-shading-mode gap. Fixed the same way, same place.

## 0.16.1

- **Fixed: Solid Shading's "Texture" color mode now actually works.** The addon never generated
  a UV map before, so switching the viewport's Solid Shading color mode to "Texture" (a separate
  display path from "Material" -- useful if "Material" mode isn't showing what you expect) showed
  nothing useful, on both live-generated and Separate-by-Floor/Room-split objects.

## 0.16.0

- **New: the sidebar panel is now organized into tabs** (Setup / Walls / Stairs / Doors / Props)
  instead of one long scroll of collapsible sections -- pick a tab via the icon row at the top,
  and only that step's settings (plus its own Generate button) show. Debug params stay pinned at
  the bottom regardless of which tab is open. No settings were removed, renamed, or moved between
  steps -- purely a layout change.

## 0.15.0

- **New: Style mode (the procedural dungeon/cave/open-area shaders) now gets real per-floor and
  per-room coloring**, matching what Simple Viewport Colors already had. Previously every corridor
  on every floor was the same material, and so was every room -- now each room and each floor
  level gets its own tinted variant of the same procedural shader, so it still has the brick/rock/
  noise pattern, just colored distinctly like Simple mode's rooms are.

## 0.14.1

- **Door Height now joins the Wall Height / Level Height / Sub-Levels per Floor sync** from
  0.14.0 -- same clipping issue applied to door frames (default 2.2m), same fix. Shrinking Level
  Height below what either Wall Height or Door Height needs now shrinks both to fit.

## 0.14.0

- **New: Wall Height, Level Height, and Sub-Levels per Floor now keep each other consistent.**
  Previously, raising Sub-Levels per Floor (or Wall Height) with no cross-check let walls
  visibly clip through the floor above, since a wall's real headroom is Level Height divided by
  Sub-Levels per Floor, not Level Height alone. Now, changing any one of the three automatically
  adjusts the others to keep walls fitting within their slice -- Level Height grows first if it
  can, Wall Height only shrinks as a last resort. No more manual coordination between these three
  settings needed.

## 0.13.3

- **Major fix: with Floor Thickness set to 0.0, every floor face pointed the wrong way** --
  invisible from directly above with Backface Culling on in the viewport (fine with it off,
  Blender's default, which is why this went unnoticed). Same latent issue existed for Ceiling
  Thickness = 0.0, fixed too. If you've been generating with a 0.0 thickness and manually
  flipping normals afterward, you no longer need to -- it's correct straight out of Step 1 now.

## 0.13.2

- **Major fix: room boundaries could get corrupted data, causing a room to split into scattered
  pieces (or the wrong room's color) at the edges.** Root cause was in how Blender's own mesh
  Geometry Nodes system welds seams between adjacent floor tiles -- at a room/corridor boundary,
  the weld could keep the wrong neighboring tile's data for that shared corner. Fixed at the
  source, so this no longer happens. If you noticed odd room colors near walls, or "Separate by
  Floor/Room" giving you way more room objects than expected, this was it.
- **"Separate by Floor/Room" now gives ceilings their own object per floor** (when Add Ceiling is
  on), instead of a room's ceiling patch making that whole room look like two disconnected pieces.
- Rooms that are always genuinely split into two pieces (a stairwell's entry/exit landing tiles,
  with the stair itself in between) now fold into that floor's Corridors object instead of
  becoming a visibly fragmented "Room."

## 0.13.1

- **Fixed: "Separate by Floor/Room" lost per-room colors if you applied the Geometry Nodes
  modifier first, exactly as the previous instructions told you to.** Blender's own "Apply
  Modifier" / "Convert to Mesh" drops the material list this addon relies on for per-room
  coloring (a Blender behavior, not something this addon can prevent by asking nicely). Fixed by
  having the button do that step itself, correctly, instead of asking you to do it by hand first
  — **you no longer need to apply the modifier before using Separate by Floor/Room at all**, just
  run it directly on the Step 1 object.

## 0.13.0

- **"Separate by Floor" is now "Separate by Floor/Room".** Instead of one flat mesh object per
  floor, it now splits each floor into one object per room plus a single combined corridor
  object, organized into a real collection tree (`Procedural Level Blueprint (Split) > Floor N >
  Rooms` / `Corridors`) so you can hide, isolate, or export a single room or a single floor's
  corridors independently. Still needs the blueprint's Geometry Nodes modifier applied first,
  same as before.

## 0.12.3

- **Major fix: "Color Rooms/Corridors" (default ON) never actually applied on a fresh
  generation.** Every level generated so far, by anyone, rendered with flat floor-level coloring
  only — real per-room colors never reached the geometry, regardless of the checkbox in the
  panel. Root cause was in how the addon wired its own Geometry Nodes modifier at generation
  time; nothing you did was wrong. "Add Ceiling" had the same underlying issue if turned on
  before ever generating. Both are fixed now — a fresh Blueprint generation with default settings
  actually shows per-room colors immediately, no workaround needed.
- Found this while putting together a screenshot for the README, not from a report — if you've
  been generating levels and wondering why rooms all looked one flat color per floor instead of
  individually colored, this was it.

## 0.12.2

- **Fixed:** `Room18.png` was an accidental duplicate of `Room17.png`'s color — two "different"
  rooms could render identically. Now its own dark sage swatch as intended.
- **Lowered minimum Blender version from 5.2 to 4.2 LTS.** Actually tested the full pipeline
  against real Blender 4.2.21 LTS and 4.5.2 LTS — both pass clean, no addon changes were needed.
  The 5.2 floor was more conservative than the addon actually required.

## 0.12.1

- **Fixed:** Corridor Stairs could be missing a wall on one side, making them look wrong and
  hard to actually walk (most noticeable on Cave floors, where stairwells sit close to tunnels).
  Should be rare now, not gone completely — see Known Issues.

## 0.12.0

- **New: Room Shape = Cave.** Instead of separate rooms joined by corridors, a floor becomes one
  winding organic network of tunnels and round chambers. Chamber count/size reuse the existing
  Min/Max Rooms and Min/Max Room Size settings. Pairs well with Corridor Stairs.

## 0.11.0

- **New: Debug: Last Generation Params panel.** Collapsed section at the bottom of the sidebar
  showing every current setting plus a **Copy Parameters** button, so you can grab the exact
  config behind a level to report a bug or share a repro — paste the result back to me and I can
  reproduce your exact level.

## 0.10.2

- **Fixed:** Room Shape = Round rooms didn't actually look round at the sizes this generator
  produces — carved shape is now a visible plus/diamond at minimum size, scaling to a proper
  octagon at larger sizes.

## 0.10.1

- GUI cleanup: merged duplicate stair settings sections, collapsed the Rooms section by default,
  paired several settings onto shared rows — same settings, less scrolling.

## 0.10.0 and earlier

Everything up to and including: room/corridor/stair layout solver, Geometry Nodes floor
rendering, baked-mesh walls and stairs (stepped or ramp), doors, wall torches with real lights,
floor decoration props, continuous room elevation (sloped floors instead of hard steps),
Corridor Stairs, ceilings, per-floor/per-stair object splitting, and the flat-color texture/
palette system. See `DEVELOPMENT.md` if you want the full build history.

---

## Known issues

- **Cave mode ignores Sub-Levels per Floor / Split-Level Chance** — every Cave floor sits flat at
  its logical floor's base height.
- **Cave mode is an all-or-nothing setting per generation** — every floor becomes Cave, there's
  no per-floor mix yet (e.g. "floor 1 normal, floor 2 cave"). On the list for later.
- **Round rooms, extreme aspect ratios**: very rarely (~1-2% of rooms) a single stray tile can end
  up unreachable at odd width/length combinations. Pre-existing, low impact.

## Reporting a bug

Generation is fully seeded and reproducible. When something looks wrong:

1. Click **Copy Parameters** in the Debug panel (bottom of the sidebar).
2. Paste that alongside a screenshot or description of what looked wrong.

That's enough to reproduce your exact level from scratch.
