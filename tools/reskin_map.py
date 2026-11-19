"""Re-skins a tile map: every tile of the old map is looked up in its old tileset (exact match), takes that tile's role (floor / canopy / stone / water,
from the old roles json) and is replaced by a tile of the same role from a new tileset. The result is a new map picture with the same layout and a new look.

    python3 tools/reskin_map.py OLD_MAP.png OLD_SHEET.png OLD_ROLES.json NEW_SHEET.png NEW_ROLES.json OUT.png [floor=dirt,paving] [stone=brick] [canopy=canopy] [water=water]

NEW_ROLES.json also needs a "names" list (as tileset_demo.json has); the optional role=name,name arguments choose which new tiles stand for a role.
Tiles of the old map that match no old tile (sprites of items and enemies) become floor. numpy + Pillow.

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
    om, nm = json.load(open(old_json)), json.load(open(new_json))
    otiles, T = sheet_tiles(old_sheet, om)
    ntiles, T2 = sheet_tiles(new_sheet, nm)
    if T != T2:
        raise SystemExit("tile sizes differ: %d vs %d" % (T, T2))
    lut = {}
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
    if auto:
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
