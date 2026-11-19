"""Generates an island world as maps and data: blender --factory-startup -b -P tools/generate_world.py -- <out folder> [size m=2000] [res m=4] [seed=1]
Writes world.json (monuments, roads, biomes), height16.png, biome.png and overview.png.
With --build the world is also built in Blender (chunks, water, roads, every monument as its plan) and exported as one glb per chunk beside the manifest; --ink dresses it in the ink look."""
import importlib.util, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("gla", os.path.join(ROOT, "levelArchitect_v2.py"))
gla = importlib.util.module_from_spec(spec); spec.loader.exec_module(gla)
args = sys.argv[sys.argv.index("--") + 1:]
build, ink = "--build" in args, "--ink" in args
args = [a for a in args if not a.startswith("--")]
out = args[0]
size = float(args[1]) if len(args) > 1 else 2000.0
res = float(args[2]) if len(args) > 2 else 4.0
seed = int(args[3]) if len(args) > 3 else 1
t0 = time.time()
w = gla.generate_world(size, res, seed)
if build:
    import bpy
    gla.register()
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    built = gla.world_build(bpy.context, w, 64, monuments=True, skin="ink" if ink else "")
    man = gla.world_export_chunks(bpy.context, w, built, out)
    files = ["world.json"] + [c["glb"] for c in man["chunks"]]
else:
    files = gla.world_write(w, out)
print("WORLD %.0f m, %d x %d cells, %d monuments, %d roads, %.1f s -> %s" % (size, w["height"].shape[0], w["height"].shape[1], len(w["monuments"]), len(w["roads"]), time.time() - t0, ", ".join(files)))
