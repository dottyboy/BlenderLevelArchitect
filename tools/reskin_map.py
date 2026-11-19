"""Re-skins a tile map: every tile of the old map is looked up in its old tileset (exact match), takes that tile's role (floor / canopy / stone / water,
from the old roles json) and is replaced by a tile of the same role from a new tileset. The result is a new map picture with the same layout and a new look.

    python3 tools/reskin_map.py OLD_MAP.png OLD_SHEET.png OLD_ROLES.json NEW_SHEET.png NEW_ROLES.json OUT.png
(OLD_SHEET and OLD_ROLES may each be several files, comma separated, when a map uses several sheets.) [floor=dirt,paving] [stone=brick] [canopy=canopy] [water=water]

NEW_ROLES.json also needs a "names" list (as tileset_demo.json has); the optional role=name,name arguments choose which new tiles stand for a role.
Tiles of the old map that match no old tile (sprites of items and enemies) become floor. numpy + Pillow.

With an ink-style tileset (tiles named rock and wall, see tools/make_ink_tileset.py) forest and stone become solid rock, rock beside open ground becomes brick wall and water a chasm.

If NEW_ROLES.json has "autotiles" ({kind: {"first": id, "base": kind}}, 16 variants each, bit N=1 E=2 S=4 W=8 = that neighbour is the same kind; tools/make_tileset.py
writes such a tileset) the new map uses them: floor becomes grass with dirt patches, canopy, water and dirt get rounded, blended edges.
"""
import json, sys
import numpy as np
from PIL import Image


def sheet_tiles(path, meta):
    a = np.array(Image.open(path).convert("RGB"))
    t, cols, margin, gutter = int(meta["tile"]), int(meta["cols"]), int(meta.get("margin", 0)), int(meta.get("gutter", 0))
    out = []
    for i in range(len(meta["roles"])):
        y, x = margin + (i // cols) * (t + gutter), margin + (i % cols) * (t + gutter)
        out.append(a[y:y + t, x:x + t])
    return out, t


def main():
    old_map, old_sheet, old_json, new_sheet, new_json, out = sys.argv[1:7]
    prefer = {}
    for arg in sys.argv[7:]:
        role, names = arg.split("=", 1)
        prefer[role] = names.split(",")
    nm = json.load(open(new_json))
    ntiles, T2 = sheet_tiles(new_sheet, nm)
    lut = {}
    for sheet_path, json_path in zip(old_sheet.split(","), old_json.split(",")):          # several old sheets may be given, comma separated
        om = json.load(open(json_path))
        otiles, T = sheet_tiles(sheet_path, om)
        if T != T2:
            raise SystemExit("tile sizes differ: %d vs %d" % (T, T2))
        for i, t in enumerate(otiles):
            lut.setdefault(t.tobytes(), om["roles"][i])
    pool = {}
    for role in ("floor", "canopy", "stone", "water"):
        names = prefer.get(role)
        idx = [i for i, r in enumerate(nm["roles"]) if r == role and (not names or nm["names"][i] in names)]
        pool[role] = idx or [i for i, r in enumerate(nm["roles"]) if r == role]
    a = np.array(Image.open(old_map).convert("RGB"))
    ty, tx = a.shape[0] // T, a.shape[1] // T
    rng = np.random.default_rng(5)
    roles = np.empty((ty, tx), dtype=object)
    for y in range(ty):
        for x in range(tx):
            role = lut.get(a[y * T:(y + 1) * T, x * T:(x + 1) * T].tobytes(), "floor")
            roles[y, x] = "stone" if role == "prop" else role
    auto = nm.get("autotiles")
    ids = np.zeros((ty, tx), int)
    if "wall" in nm.get("names", []) and "rock" in nm["names"]:      # an ink / dungeon tileset: forest and stone both become solid rock, rock next to open ground becomes wall, water a chasm
        names = nm["names"]
        kinds = np.full((ty, tx), "floor", dtype=object)
        solid = (roles == "stone") | (roles == "canopy")
        kinds[solid] = "rock"
        kinds[roles == "water"] = "chasm"
        near = np.zeros((ty, tx), bool)
        open_ = ~solid
        near[1:, :] |= open_[:-1, :]
        near[:-1, :] |= open_[1:, :]
        near[:, 1:] |= open_[:, :-1]
        near[:, :-1] |= open_[:, 1:]
        kinds[solid & near] = "wall"
        # tidy up: small loose bits of the old map (statues, bushes, decorations) become pillars; tiny pockets of floor inside rock are filled
        def components(mask):
            seen = np.zeros_like(mask)
            for y0 in range(ty):
                for x0 in range(tx):
                    if mask[y0, x0] and not seen[y0, x0]:
                        comp, stack = [], [(y0, x0)]
                        seen[y0, x0] = True
                        while stack:
                            cy, cx = stack.pop()
                            comp.append((cy, cx))
                            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                                yy, xx = cy + dy, cx + dx
                                if 0 <= yy < ty and 0 <= xx < tx and mask[yy, xx] and not seen[yy, xx]:
                                    seen[yy, xx] = True
                                    stack.append((yy, xx))
                        yield comp
        for comp in components(solid):
            if len(comp) <= 4 and all(0 < y < ty - 1 and 0 < x < tx - 1 for y, x in comp):
                for y, x in comp:
                    kinds[y, x] = "pillar"
        for comp in components(~solid & (roles != "water")):
            if len(comp) <= 2 and all(0 < y < ty - 1 and 0 < x < tx - 1 for y, x in comp):
                for y, x in comp:
                    kinds[y, x] = "wall"
        for y in range(ty):
            for x in range(tx):
                c = [i for i, n in enumerate(names) if n == kinds[y, x]]
                ids[y, x] = c[int(rng.integers(0, len(c)))]
    elif auto:
        names = nm["names"]
        plain = lambda kind: [i for i, n in enumerate(names) if n == kind]
        patch = rng.random((ty // 4 + 3, tx // 4 + 3))                    # dirt patches on the open ground: a slow noise, upsampled
        patch = np.kron(patch, np.ones((4, 4)))[:ty, :tx] + rng.normal(0, 0.05, (ty, tx))
        kinds = np.full((ty, tx), "grass", dtype=object)
        kinds[roles == "stone"] = "brick"
        kinds[roles == "canopy"] = "canopy"
        kinds[roles == "water"] = "water"
        kinds[(roles == "floor") & (patch > 0.68)] = "dirt"
        for y in range(ty):
            for x in range(tx):
                k = kinds[y, x]
                if k in auto:
                    same = lambda yy, xx: (not (0 <= yy < ty and 0 <= xx < tx)) or kinds[yy, xx] == k
                    mask = (1 if same(y - 1, x) else 0) | (2 if same(y, x + 1) else 0) | (4 if same(y + 1, x) else 0) | (8 if same(y, x - 1) else 0)
                    ids[y, x] = auto[k]["first"] + mask
                else:
                    c = plain(k)
                    ids[y, x] = c[int(rng.integers(0, len(c)))]
    else:
        for y in range(ty):
            for x in range(tx):
                c = pool.get(roles[y, x]) or pool["floor"]
                ids[y, x] = c[int(rng.integers(0, len(c)))]
    res = np.zeros((ty * T, tx * T, 3), np.uint8)
    for y in range(ty):
        for x in range(tx):
            res[y * T:(y + 1) * T, x * T:(x + 1) * T] = ntiles[ids[y, x]]
    Image.fromarray(res).save(out)
    print("wrote", out, (tx, ty), "tiles")


if __name__ == "__main__":
    main()
