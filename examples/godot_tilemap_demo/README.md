# Tile map level in Godot

A small Godot 4 project that loads a Game Level Architect **tile-map package** (`level/demo.glb` + `level/demo.json`, format `gla-export/1`)
and lets you walk through it with WASD or the arrow keys. The JSON's walk rectangles are the only ground you can stand on, so trees,
walls, water and props block you without any physics.

* Open the folder in Godot 4.7 (or newer) and press Play. The start screen lists every package found in `level/` (`demo`: colour map with trees, a lake and walls; `ink`: the ink-on-paper dungeon with a raised platform); Esc comes back to it. Drop another `name.glb` + `name.json` pair exported with *Export Tile Map Package* into `level/` and it appears in the list. `godot --path . -- --level ink` goes straight into one level.
* Headless check: `godot --headless --path . -- --selftest [--level ink]` prints `SELFTEST OK` when the entrance and exit are standable, no prop sits on walkable ground and every tree stands on blocked ground; for a level with stairs it also walks the stairs up to the platform (floor and height change) and checks that the platform edge beside them cannot be climbed.
* Screenshot (needs a display, e.g. `xvfb-run`): `godot --path . -- --shot out.png --at 3.6 -18`.
* The packages are made by `tools/export_demo_package.py` (`blender --factory-startup -b -P tools/export_demo_package.py` for `demo`, add `-- ink` for the ink dungeon) from the original demo tilesets and maps in `docs/examples/`.
