"""Re-skins a tile map: every tile of the old map is looked up in its old tileset (exact match), takes that tile's role (floor / canopy / stone / water,
from the old roles json) and is replaced by a tile of the same role from a new tileset. The result is a new map picture with the same layout and a new look.

    python3 tools/reskin_map.py OLD_MAP.png OLD_SHEET.png OLD_ROLES.json NEW_SHEET.png NEW_ROLES.json OUT.png [floor=dirt,paving] [stone=brick] [canopy=canopy] [water=water]

NEW_ROLES.json also needs a "names" list (as tileset_demo.json has); the optional role=name,name arguments choose which new tiles stand for a role.
Tiles of the old map that match no old tile (sprites of items and enemies) become floor. numpy + Pillow.
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
    res = np.zeros((ty * T, tx * T, 3), np.uint8)
    for y in range(ty):
        for x in range(tx):
            role = lut.get(a[y * T:(y + 1) * T, x * T:(x + 1) * T].tobytes(), "floor")
            if role == "prop":
                role = "stone"
            ids = pool.get(role) or pool["floor"]
            res[y * T:(y + 1) * T, x * T:(x + 1) * T] = ntiles[ids[int(rng.integers(0, len(ids)))]]
    Image.fromarray(res).save(out)
    print("wrote", out, (tx, ty), "tiles")


if __name__ == "__main__":
    main()
