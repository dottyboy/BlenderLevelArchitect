# Contributing

Thanks for considering it — this is a solo-maintained, early-testing-release project, so please
keep expectations calibrated: response times may be slow, and not every PR will fit the project's
direction, but bug reports and small, focused fixes are genuinely welcome.

## Reporting bugs

See **Reporting issues** in [README.md](README.md) first — generation is fully seeded, so a bug
report is far more useful with the exact settings that produced it (the panel's **Debug: Last
Generation Params > Copy Parameters** button grabs these for you). Check `CHANGELOG.md`'s "Known
issues" too; your case might already be a documented tradeoff rather than a new bug.

## Contributing code

Read [DEVELOPMENT.md](DEVELOPMENT.md) first — it covers the actual architecture, why several
things are built the way they are (e.g. walls/stairs are baked Python mesh rather than Geometry
Nodes, on purpose, after two GN attempts proved unreliable — see §1), and a running list of known
issues and ideas that might already cover what you're about to build.

### Testing before you open a PR

This project has two layers of testing, and both matter for different reasons:

1. **Offline mock (`tests/stub_bpy.py`)** — fakes just enough of `bpy` to run the solver and
   plain-Python mesh builders (walls/stairs/doors/props) without launching Blender at all. Fast
   (hundreds of seeded trials in seconds) — use this for iterating on solver/connectivity/mesh-math
   logic.
2. **Real Blender (`./run_blender_tests.sh [path-to-blender]`)** — runs
   `tests/blender_headless_test.py` inside an actual headless Blender process. This is the only
   check that evaluates the Geometry Nodes graph and real mesh/UV/material data — **required**
   before any change touching the GN graph, a live GN modifier interaction, or wall/stair/door/
   prop mesh-building code (vertex winding, face construction, etc.). It's caught real,
   project-wide bugs the mock structurally can't see.

Run `./generate_test_blends.sh [path-to-blender]` too if your change affects generated geometry
visibly — it builds one `.blend` per scenario in `tests/generate_test_blends.py`'s `SCENARIOS`
list (all on the same fixed seed) plus a top-down PNG render of each into `test_blends/Renders/`,
so a feature can be glanced at without opening Blender. Add a new scenario tuple there for any
new toggle worth showing off.

### Conventions

- Every non-obvious design decision gets a docstring or comment explaining **why**, not what —
  see almost any function in `levelArchitect_v2.py` for the expected depth. If you had to think
  hard about an edge case, a future reader (including future-you) will too.
- Match the existing code's caution around live Blender API behavior that can't be verified
  offline (see DEVELOPMENT.md §1's Geometry Nodes note, and `_set_prop`'s best-effort setattr
  pattern for enum/property names that can drift across Blender versions).
- Update `DEVELOPMENT.md` (and `CHANGELOG.md` for anything user-facing) alongside the code —
  this project treats those as living documents, not write-once release notes.

## License

By contributing, you agree your contribution is licensed under this project's license,
GPL-3.0-or-later (see [LICENSE](LICENSE)).
