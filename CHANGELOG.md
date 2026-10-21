# Changelog

Game Level Architect — early testing release. Generation is fully seeded, so any level can be
reproduced exactly from its settings (see **Debug: Last Generation Params** in the panel).

## 0.35.0

- **Game package lists the decoration placements.** The JSON now has `props` (kind, engine position, yaw) and
  `wall_height`, taken from a `gla_props` custom property the Props step stores on the decoration object. The glb
  still contains the baked prop mesh; an engine that has its own models can ignore the mesh and place those
  instead (Vampire Adventure does: crates, columns, coffins, tombs, tables, chairs, beds, shelves, chests,
  barrels, candelabra).

## 0.34.0

- **New: Export Castle Package (glb + json)** (Castle tab). The same "gla-export/1" format as a level
  package, for the castle: walkable courtyard (minus the keep and the tower bases), the gate passage and an
  open apron in front of the gate on a 0.5 m grid, an entrance at the far end of the apron, six torch lights
  (both sides of the gate, courtyard corners). `kind: "castle"`, `interior: false` tell a loader to use a sky.
  Every cell keeps 0.45 m clear of masonry.
- Tests: format/kind, cell/rectangle consistency, and a ray from every walkable cell to each walkable
  neighbour proving no wall stands between them (>500 pairs), no cell inside masonry, gate on/off entrance,
  operator writing both files.
- Used by Vampire Adventure as a playable location (`dungeon_castle`) -- see that project's README.

## 0.33.0

- **New: Export Game Package (glb + json)** (Export tab). Besides the glTF it writes a JSON file
  ("gla-export/1") next to it describing what a game engine has to know: per floor the walkable tiles merged
  into a few rectangles (an exact cover), the entrance and exit, stairs, every room (shape and rectangle),
  and the torch lights (position, colour, watts, radius). Everything is in engine coordinates (x right, y up,
  z = -Blender y). The glb always comes out as one self-contained binary with textures embedded.
- First consumer: the Vampire Adventure project loads such a package as a playable location (see its
  README, "Generated dungeons"): rectangle-based walking, route finding over the tiles, wall cut-away
  between camera and player, torches as real lights, Architect's flat room colours restyled to that game's
  stone/wood/cobble, brick rings keep their own textures.
- Tests: the rectangle merge on 40 random tile sets, coverage = exactly the walkable tiles, entrance/exit
  inside a rectangle, light list and axis conversion, the export operator writing both files.
- Known: a package describes all floors but a consumer is expected to use one; export single-floor
  levels (Height = 1) for such loaders. Tower and Castle are not packaged yet.

## 0.32.0

- **Fixed: torches floated in open air.** The wall-adjacency test for torch placement compared a 2D
  position against a set of 3D cells, so every direction always counted as "has a wall" and a torch could
  hang on an open doorway or in the middle of a room. It checks the real neighbouring cell now. This changes
  where torches land for existing seeds (they now sit on real walls), which is the point.
- **Round rooms: torches and props follow the curved wall.** With Masonry walls, torches hang on the inner
  skin of the ring (oriented along the wall's normal, kept out of doorways, none on ruined rings), the
  real lights move with them, and decoration props stay inside the ring and no longer try to stand against
  invisible square-cell walls.
- **Castle is walkable.** The curtain walls have a walkway behind a parapet (merlons only on the outer
  half, wall thickness default 1.5 m), and each corner tower has a floor exactly at the wall-walk height
  with doors out onto both walls, so ground door -> spiral stairs -> wall-level floor -> door -> walkway
  is one continuous path. Tower floors can now be placed at explicit heights (`floor_levels`).
- **Better stone.** Stone blocks, caps, merlons, plinth and floor slabs use a textured limestone
  (large dressed blocks, normal map) instead of flat grey; bricks are less orange, and both have soft
  weathering blotches.
- Tests: ring torches/props geometry, wall-walk height, parapet, walking out of the tower door onto the walk.
- Known: a tower's windows can still end up behind a spiral step; tower interiors have no props or lights.

## 0.31.0

- **New: Castle** (new Castle tab, built at the 3D cursor). A walled castle assembled from masonry parts:
  four corner towers (each with a door facing the courtyard, slit windows and the Round Tower's interior
  of floors and spiral stairs), four curtain walls with battlements and arrow slits whose ends are buried
  in the tower masonry, a large arched gate in the south wall, an optional keep in the courtyard (its
  door faces the gate) and a stone courtyard slab. Width, depth, wall height/thickness, tower radius and
  height, Gate, Keep and Brick Detail are adjustable.
- **Ruin works on the whole castle** (one slider): towers, walls and keep break down into stepped
  jagged edges with breaches, collapsed arches and rubble; the gate stays passable.
- **New building block: straight masonry wall runs** (`_WallRunBuilder`), the flat sibling of the tower
  shell: brick-textured skins, arched/pointed/flat openings with reveals and stone frames, plinth,
  battlements, ruin, stones, rubble. Used by the castle's curtain walls and keep; not yet wired into
  ordinary level walls.
- Tests: wall solidity and outward normals, gate and ruined-gate passability, tower/wall joints without
  holes, towers above walls, keep/gate toggles, more ruin = lower walls, deterministic seed, refusal when
  the towers do not fit.
- Known: the tower doors open onto the courtyard but nothing connects a tower's upper floors to the wall
  tops, and the keep has no interior.

## 0.30.0

- **New: ruins.** A "Ruin" slider (0..1, default 0) on the Tower tab and, for Masonry Round rooms, on the
  Walls tab. The wall top breaks down into a jagged edge that steps along whole brick courses (low-
  frequency noise plus a few deep notches), flat stone caps and vertical end faces close the broken
  edges, and fallen blocks lie around the base (outside for towers, inside against the wall for rooms,
  always clear of doorways and low enough to step over). A window or arch whose top fell away becomes a
  plain breach; windows above the broken top simply vanish. Battlements disappear, tower floors above the
  lowest broken wall top are gone, and doorways stay passable. Seeded, so a ruin is reproducible.
- **Fixed: stacked tower windows.** On towers of three or more storeys the windows of different storeys
  share an angle, and only the lowest was actually cut through the wall. Every storey's window is cut now.
- Tests: ruin profile (varied, lower with more ruin, deterministic), upward-facing caps, door ray,
  no geometry below ground, stacked windows; Round-room passages with Ruin = 1 across 5 seeds x 3 door
  styles (27 108 cell pairs).

## 0.29.1

- **Fixed: masonry Round-room rings clipped stair runs at full wall height.** The "stair clips the
  ring" problem showed up once walls were as tall as in a real level (the old tests only used 0.61 m
  walls). Two causes in the masonry ring: a floor-level doorway got a window-sill stone that sank
  0.14 m below the floor into the stairs of the level underneath (now only real windows get a sill
  stone), and the ring, frames and proud stones stood exactly on the room's rim, so anything 6 cm
  proud poked into the neighbouring cell (the ring now stays 0.1 m inside the rim). The stairs test
  now runs at both wall heights and asserts zero overlaps.
- Not fixed: the Classic ring still clips stairs in 1 of 5 test seeds at 3 m wall height (4 face
  overlaps); Masonry is the default.

## 0.29.0

- **Round rooms get masonry walls** (Walls tab, "Round Rooms": Masonry (default) / Classic). Masonry
  uses the Round Tower method on every Round room: a smooth brick-textured ring sitting on the room's
  rim ellipse (the wall grows inward, so it stays inside the room's reserved rectangle), dressed-stone
  frames, scattered proud stones, an optional flat stone cap (Cap Top), and real openings cut exactly
  where a corridor or neighbouring room meets the ring -- as wide as the passage (at least 1.4 m)
  instead of a whole 30-degree polygon edge. Openings follow Door Style (Flat / Round arch / Pointed
  arch) and Door Height; walls too low for a door get a plain full-height gap. Elliptical rooms
  (width != length) are handled by building a circle and stretching it. Round rooms no longer get a
  separate RoundDoors object in Masonry mode (the frames are part of the ring). Classic keeps the old
  n-gon ring and oriented door frames unchanged.
- Tower: pointed arches and a "gap" opening kind were added to the shared builder.
- Verified by ray casts: across 5 seeds x 3 door styles x 2 wall heights (>1000 adjacent walkable cell
  pairs), no passage between walkable cells is blocked by a masonry ring; stairs never intersect a ring
  with low walls.
- Known: with full-height (3 m) walls, a stair run can still clip a Round room's ring. The Classic ring
  does it too (the older tests only ran with 0.61 m walls); not fixed here.

## 0.28.0

- **Round Tower interiors.** New "Floors + Spiral Stairs" option (on by default) and "Stair Width".
  The tower is split into storeys of at least 3 m that divide the shell height exactly, so the top
  slab is the roof platform right behind the battlements. Floor slabs (with thickness) separate the
  storeys, joined by one full turn of stone spiral stairs per storey hugging the inner wall
  (~0.18 m risers). Each slab is open over the stair lane exactly where a climber would otherwise
  hit their head (the last 2.2 m of the climb) and solid everywhere else. Windows now align to the
  storeys. Towers with an inner radius under 1.6 m skip the interior instead of failing.
- Verified with ray casts: every step's top is at its expected height, 2 m of headroom above every
  step, correct slab heights. Not handled yet: a step can sit in front of a slit window's inner
  side, and there is no railing on the open side of the stairs.

## 0.27.0

- **New: Round Tower** (new Tower tab, built at the 3D cursor). Instead of modelling every brick
  (a 9 m tower needed ~1400 bricks and ~8 400 vertices, and still looked ragged), the wall is a
  smooth cylindrical shell (outer + inner skin) carrying a procedural brick albedo + normal map,
  generated once per session and embedded in glTF exports. Everything that gives the silhouette is
  real geometry: an arched door and slit windows cut through the wall (with reveals), dressed-stone
  jamb/voussoir frames, plinth, cornice, battlements and a ground slab.
- **Brick Detail** picks the geometry budget: Low (~900 vertices: textured shell, openings, plinth,
  cornice, battlements), Medium (~1 900: adds stone frames and scattered proud stones, default),
  High (~3 700: many more proud stones). Radius, height, wall thickness, door angle, battlements and
  windows per storey are adjustable. The Export tab includes the tower.
- Not yet: interior floors/stairs, towers as rooms inside a generated level, tapered towers.

## 0.26.0

- **New: windows.** Walls tab, "Window Chance" (0 = off, default). Exposed edges of ordinary
  (Rect-style) room walls get a real rectangular opening cut through the wall — two piers, a sill
  and a lintel, so you can see and shoot through it — plus a separate "Procedural_Level_Windows"
  object with frame, mullion cross and a translucent glass pane. Width, sill height and opening
  height are adjustable. Corridors, Round rooms and Corridor-Stairs sides never get windows;
  windows on one wall stay at least 2 tiles apart. Seeded like everything else. The glass is
  excluded from the Collision Mesh export (it exports Walls only), the openings are not.
- **New: themed decoration props.** Props tab, "Theme": Generic (the old crates/barrels/cones,
  default and unchanged), Mixed Rooms (each room randomly themed), Crypt (coffins, tombs,
  columns, candle stands), Library (bookshelves, tables, chairs, chests), Hall, Bedroom, Storage.
  Props are stacked primitives (tables with legs, chairs with backs, bookshelves with books,
  beds, coffins, candle stands...), all still in the single decoration mesh. Wall-type props
  stand against a wall facing into the room; every placement is checked to stay inside its own
  tile and clear of walls (new regression test checks every vertex in every theme).
- Idea source: the prop shapes and room themes come from the sibling Dracula adventure project's
  prop library, reduced to plain primitives.

## 0.25.1

- **Fixed: Round rooms could clip stairs, or wall off a corridor that should be walkable.** User
  repro (a Round-room level with multiple Sub-Levels per Floor): stairs sometimes visibly clipped
  through a nearby Round room's wall, and some corridors dead-ended at a low wall a player would
  have to jump rather than walk through. Three real, independent bugs, all in the Round room wall
  ring/floor disc/door frame machinery added in 0.23.0/0.24.0:
  - A Round room only carves cells inside its inscribed ellipse, leaving its own bounding-box
    corners empty -- room/stairwell placement treated that as free space (it genuinely has no
    floor there), but the wall ring is a real ellipse spanning the room's FULL rectangle, cutting
    straight through those corners. Room/stairwell placement now also reserves a Round room's full
    rectangle, not just its carved cells.
  - A corridor can still legitimately route through that same "empty" corner (corridors can't be
    allowed to fail mid-carve) -- the wall ring and door-frame builders now also open wherever that
    happens, instead of silently sealing a real, walkable corridor.
  - The deeper root cause behind the actual clipping: the ring/disc/door builders computed a Round
    room's world-space center half a tile off from where its cells are actually carved (an
    off-by-one ported in from the sibling project, which uses a different grid convention) -- fixed
    to match the grid-space ellipse test exactly.
  - Added a dedicated multi-seed regression test (Round rooms + multi-floor Stairs together) --
    the existing Round rooms test pins Height=1 (no stairs ever run), so this exact combination had
    no guaranteed coverage before.

## 0.25.0

- **New: Door panels + experimental UPBGE hinge physics.** Every ordinary doorway now gets a real
  swinging panel object, not just a frame -- "Generate Door Panels" in the Doors tab, on by
  default, hinged on one edge. On UPBGE specifically, an experimental "UPBGE Hinge Physics" toggle
  (off by default) also wires up a rigid body + hinge constraint per panel. Whether UPBGE's live
  game runtime actually simulates that constraint hasn't been verified -- confirm by pressing
  Start Game and pushing a door before relying on it. Entrance/Exit gates and Round room doorways
  are unaffected -- gates stay fixed set pieces, Round doors are still frame-only for now.
- Fixed: Isometric Mode's top-slice cull could silently delete an elevated room's entire floor.
  Continuous elevation (Elevation Chance/Split Level Chance) could push a room's Z close enough to
  a sub-level boundary that the cull's modulo math wrapped around into the cull zone meant for
  ceilings -- rescoped the cull to ceiling only, since floor should never be culled by this
  feature in the first place.
- Fixed: Freeze for Texture Work renamed a frozen object but never its underlying mesh/light data,
  so the next regeneration's same-named data silently drifted to a numeric `.001` suffix instead
  -- the data-block gets the same rename treatment as the object now.

## 0.24.0

- **Round room doors now follow the curved wall too.** A doorway on a Round room's rim still
  placed a straight, axis-aligned frame -- now it's oriented along the wall's own curve at that
  exact spot, matching the real n-gon wall ring instead of standing at a mismatched angle against
  it. Works with Flat, Round, and Pointed Door Style. Rect rooms are unaffected.

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
