# Tile map level in Godot

A small Godot 4 project that loads a Game Level Architect **tile-map package** (`level/demo.glb` + `level/demo.json`, format `gla-export/1`)
and lets you walk through it with WASD or the arrow keys. The JSON's walk rectangles are the only ground you can stand on, so trees,
walls, water and props block you without any physics.

* Open the folder in Godot 4.7 (or newer) and press Play.
* Headless check: `godot --headless --path . -- --selftest` prints `SELFTEST OK` when the entrance and exit are standable, no prop sits on walkable ground and every tree stands on blocked ground.
* Screenshot (needs a display, e.g. `xvfb-run`): `godot --path . -- --shot out.png --at 3.6 -18`.
* The package is made by `tools/export_demo_package.py` (run it with `blender --factory-startup -b -P tools/export_demo_package.py`) from the original demo tileset and map in `docs/examples/`.
