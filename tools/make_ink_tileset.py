"""An original 'ink on paper' dungeon tileset and a dungeon map generator for 'Level from Tile Map' (numpy + a tiny PNG writer, no other libraries):

    python3 tools/make_ink_tileset.py [seed]    # writes docs/examples/ink_tileset.png, ink_tileset.json and ink_map.png

The look is a hand-inked dungeon plan: pale paper floors with a dotted grid, black outlines, brick-lined walls, solid rock shown as stipple and small stones,
round pillars. The generator carves rooms and corridors out of rock, fills some halls with rows of pillars, rings a few rooms with pillars and cuts a chasm.
Roles: floor (paper), stone (rock and walls: walls are the rock tiles next to floor), prop (pillar), water (chasm, lowered).
"""
import json, os, struct, zlib
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = 16
PAPER = np.array((0xe8, 0xe8, 0xed), np.uint8)
PAPER2 = np.array((0xdf, 0xdf, 0xe6), np.uint8)
INK = np.array((0x16, 0x16, 0x1d), np.uint8)
DARK = np.array((0x6a, 0x6c, 0x7a), np.uint8)


def write_png(path, a):
    a = np.ascontiguousarray(a.astype(np.uint8))
    raw = b"".join(b"\x00" + row.tobytes() for row in a)

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", a.shape[1], a.shape[0], 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def floor_tile(seed, crack=False):
    img = np.empty((T, T, 3), np.uint8)
    img[:] = PAPER
    r = np.random.default_rng(seed)
    img[r.random((T, T)) < 0.06] = PAPER2
    img[0, 0::4] = INK                                           # the dotted grid of the plan: dots along the top and left edge of every tile
    img[1, 0::4] = INK
    img[0::4, 0] = INK
    img[0::4, 1] = INK
    if crack:
        x, y = int(r.integers(4, 12)), int(r.integers(4, 12))
        for _ in range(int(r.integers(4, 8))):
            img[y, x] = INK
            x = min(max(x + int(r.integers(-1, 2)), 1), T - 2)
            y = min(max(y + 1, 1), T - 2) if r.random() < 0.7 else y
    return img


def rock_tile(seed):
    """Solid rock: paper with stipple and one or two outlined stones."""
    img = np.empty((T, T, 3), np.uint8)
    img[:] = PAPER
    r = np.random.default_rng(seed + 300)
    img[r.random((T, T)) < 0.07] = INK
    for _ in range(int(r.integers(0, 2))):
        cx, cy = int(r.integers(3, T - 3)), int(r.integers(3, T - 3))
        img[cy - 2:cy + 3, cx - 2:cx + 3] = PAPER
        for dx, dy in ((-2, -1), (-2, 0), (-2, 1), (2, -1), (2, 0), (2, 1), (-1, -2), (0, -2), (1, -2), (-1, 2), (0, 2), (1, 2)):
            img[cy + dy, cx + dx] = INK
    return img


def wall_tile(seed, rim=None):
    """A brick wall tile in black ink on pale stone: staggered bricks, a thick outline on the sides that face the floor (`rim` = set of 'n','e','s','w')."""
    img = np.empty((T, T, 3), np.uint8)
    img[:] = PAPER
    r = np.random.default_rng(seed + 700)
    for by in range(0, T, 4):
        img[by, :] = INK                                           # mortar line
        off = 0 if (by // 4) % 2 == 0 else 4
        for bx in range(off, T + 8, 8):
            if 0 <= bx < T:
                img[by:by + 4, bx] = INK
        img[by + 1:by + 4, :][r.random((3, T)) < 0.05] = DARK
    for side in (rim or ()):
        if side == "n":
            img[0:2, :] = INK
        elif side == "s":
            img[T - 2:T, :] = INK
        elif side == "w":
            img[:, 0:2] = INK
        elif side == "e":
            img[:, T - 2:T] = INK
    return img


def wall_rim_tile(mask, diag=None, seed=0):
    """A wall seen from above, like the walls of a hand-inked plan: only a band of bricks along the sides that face the floor (mask bits N=1 E=2 S=4 W=8),
    the rest is solid rock stipple. `diag` (0 NE, 1 SE, 2 SW, 3 NW) draws a small brick corner where only the diagonal neighbour is open."""
    img = rock_tile(seed + 40)
    B = 5                                                         # width of the brick band in px

    def band(y0, y1, x0, x1, outer):
        img[y0:y1, x0:x1] = PAPER
        for by in range(y0, y1, 2):
            img[by, x0:x1] = INK
            off = 0 if ((by - y0) // 2) % 2 == 0 else 3
            for bx in range(x0 + off, x1, 6):
                img[by:by + 2, bx] = INK
        o0, o1 = outer
        img[o0[0]:o1[0], o0[1]:o1[1]] = INK                      # the thick outline on the floor side
    if mask & 1:
        band(0, B, 0, T, ((0, 0), (2, T)))
    if mask & 4:
        band(T - B, T, 0, T, ((T - 2, 0), (T, T)))
    if mask & 8:
        band(0, T, 0, B, ((0, 0), (T, 2)))
    if mask & 2:
        band(0, T, T - B, T, ((0, T - 2), (T, T)))
    if diag is not None:
        ys, xs = {0: (0, T - B), 1: (T - B, T - B), 2: (T - B, 0), 3: (0, 0)}[diag]
        img[ys:ys + B, xs:xs + B] = PAPER
        for by in range(ys, ys + B, 2):
            img[by, xs:xs + B] = INK
        img[ys:ys + B, xs] = INK
        img[ys, xs:xs + B] = INK
    return img


def pillar_tile(seed):
    """A round pillar seen from above: a thick outlined circle with a stippled top, on paper."""
    img = floor_tile(seed)
    ys, xs = np.mgrid[0:T, 0:T]
    d = np.hypot(xs - 7.5, ys - 7.5)
    img[d < 6.2] = PAPER
    img[(d >= 5.2) & (d < 6.4)] = INK
    r = np.random.default_rng(seed + 900)
    img[(d < 4.2) & (r.random((T, T)) < 0.22)] = INK
    return img


def apse_tile(side, seed=0):
    """A half column built into a wall (an apse) seen from above: a semicircle of brick rings bulging out of the wall at `side` (n, e, s, w) on a floor tile."""
    img = floor_tile(seed)
    ys, xs = np.mgrid[0:T, 0:T]
    d = np.hypot(xs - 7.5, ys + 0.5)                              # centred on the top edge: the wall is at the north
    img[d < 7.6] = PAPER
    img[(d >= 6.1) & (d < 7.6)] = INK
    img[(d >= 3.6) & (d < 4.5)] = INK
    ang = np.arctan2(ys + 0.5, xs - 7.5)
    img[(d >= 4.5) & (d < 6.1) & (np.abs(np.sin(ang * 5.0)) < 0.18)] = INK      # radial joints between the bricks of the ring
    return np.rot90(img, k={"n": 0, "e": 3, "s": 2, "w": 1}[side]).copy()


def upper_tile(seed):
    """A raised platform floor: slightly darker paper with a heavier dotted grid and ticks at the corners."""
    img = floor_tile(seed + 50)
    img[img.sum(axis=2) > 650] = (0xd8, 0xd8, 0xe2)
    img[1, 1] = img[1, T - 2] = img[T - 2, 1] = img[T - 2, T - 2] = INK
    return img


def stairs_tile(vertical, seed=0):
    """Steps seen from above: parallel ink lines across the way up (`vertical` False: horizontal lines, the way up is north-south)."""
    img = floor_tile(seed + 70)
    for k in range(2, T, 3):
        if vertical:
            img[:, k] = INK
        else:
            img[k, :] = INK
    return img


def chasm_tile(seed):
    img = np.empty((T, T, 3), np.uint8)
    img[:] = (0x3a, 0x3c, 0x4e)
    r = np.random.default_rng(seed + 1100)
    img[r.random((T, T)) < 0.12] = (0x24, 0x25, 0x33)
    for _ in range(3):                                           # ink strokes across the dark
        x, y = int(r.integers(0, T)), int(r.integers(0, T))
        for _k in range(int(r.integers(4, 8))):
            img[y, x] = INK
            x, y = min(max(x + int(r.integers(-1, 2)), 0), T - 1), min(max(y + 1, 0), T - 1)
    return img


TILES = []                                                      # (kind, image, role)
for i in range(4):
    TILES.append(("floor", floor_tile(i, crack=i == 3), "floor"))
for i in range(4):
    TILES.append(("rock", rock_tile(i), "stone"))
for i in range(2):
    TILES.append(("wall", wall_tile(i), "stone"))                # a full brick tile: also the picture wall faces show (json wall_side)
WALL_SIDE = len(TILES) - 1
WALL_FIRST = len(TILES)                                        # 15 side-mask variants (mask 1..15) then 4 corner variants
for _m in range(1, 16):
    TILES.append(("wallrim", wall_rim_tile(_m, None, _m), "stone"))
for _d in range(4):
    TILES.append(("wallrim", wall_rim_tile(0, _d, 20 + _d), "stone"))
TILES.append(("pillar", pillar_tile(1), "prop"))
for i in range(2):
    TILES.append(("chasm", chasm_tile(i), "water"))
for i in range(2):
    TILES.append(("upper", upper_tile(i), "upper"))
TILES.append(("stairs_ns", stairs_tile(False), "stairs"))
TILES.append(("stairs_ew", stairs_tile(True), "stairs"))
PROP_KINDS = {}
for _side in ("n", "e", "s", "w"):
    PROP_KINDS[len(TILES)] = "apse"
    TILES.append(("apse_" + _side, apse_tile(_side), "prop"))
COLS = 8
IDX = {}
for _i, (_k, _img, _r) in enumerate(TILES):
    IDX.setdefault(_k, []).append(_i)


def sheet():
    rows = (len(TILES) + COLS - 1) // COLS
    out = np.zeros((rows * T, COLS * T, 3), np.uint8)
    out[:] = PAPER
    for i, (_k, img, _r) in enumerate(TILES):
        out[(i // COLS) * T:(i // COLS + 1) * T, (i % COLS) * T:(i % COLS + 1) * T] = img
    return out


def make_dungeon(w=72, h=54, seed=4):
    """Kind names on a w x h grid: rock everywhere, rooms and corridors carved out, pillared halls, pillar rings and a chasm; walls are the rock next to floor."""
    r = np.random.default_rng(seed)
    k = np.full((h, w), "rock", dtype=object)
    rooms = []
    for _ in range(200):
        rw, rh = int(r.integers(6, 15)), int(r.integers(5, 12))
        x0, y0 = int(r.integers(2, w - rw - 2)), int(r.integers(2, h - rh - 2))
        if any(x0 < b[2] + 3 and x0 + rw > b[0] - 3 and y0 < b[3] + 3 and y0 + rh > b[1] - 3 for b in rooms):
            continue
        rooms.append((x0, y0, x0 + rw, y0 + rh))
        if len(rooms) >= 9:
            break
    for (x0, y0, x1, y1) in rooms:
        k[y0:y1, x0:x1] = "floor"
    order = sorted(range(len(rooms)), key=lambda i: rooms[i][0])
    for a, b in zip(order, order[1:]):                            # corridors 2 tiles wide, an L between neighbouring rooms
        ax, ay = (rooms[a][0] + rooms[a][2]) // 2, (rooms[a][1] + rooms[a][3]) // 2
        bx, by = (rooms[b][0] + rooms[b][2]) // 2, (rooms[b][1] + rooms[b][3]) // 2
        k[min(ay, by):max(ay, by) + 2, bx:bx + 2] = "floor"
        k[ay:ay + 2, min(ax, bx):max(ax, bx) + 2] = "floor"
    big = sorted(rooms, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1]))
    if big:                                                       # the biggest hall: two rows of pillars
        x0, y0, x1, y1 = big[0]
        for y in range(y0 + 2, y1 - 1, 3):
            for x in range(x0 + 2, x1 - 1, 3):
                k[y, x] = "pillar"
    if len(big) > 1:                                              # the second: a ring of pillars
        x0, y0, x1, y1 = big[1]
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        rad = max(2, min(x1 - x0, y1 - y0) // 2 - 2)
        for i in range(12):
            a_ = 2 * np.pi * i / 12
            k[int(round(cy + rad * np.sin(a_))), int(round(cx + rad * np.cos(a_)))] = "pillar"
    if len(big) > 2:                                              # the third: a chasm across the middle
        x0, y0, x1, y1 = big[2]
        yy = (y0 + y1) // 2
        for x in range(x0 + 1, x1 - 1):
            k[yy + int(round(np.sin(x * 0.7))), x] = "chasm"
    free = [b for b in rooms if b not in big[:4]]      # apses: half columns along a wall of two other rooms
    for n_, (x0, y0, x1, y1) in enumerate(free[:2]):
        if n_ == 0:
            for x in range(x0 + 1, x1 - 1, 2):
                if k[y0, x] == "floor":
                    k[y0, x] = "apse_n"
        else:
            for y in range(y0 + 1, y1 - 1, 2):
                if k[y, x0] == "floor":
                    k[y, x0] = "apse_w"
    if len(big) > 3:                                              # a raised platform at the far end of another room, reached by a short flight of stairs
        x0, y0, x1, y1 = big[3]
        k[y0:y0 + 3, x0:x1] = "upper"
        mid = (x0 + x1) // 2
        k[y0 + 3, mid - 1:mid + 1] = "stairs_ns"
    rock = k == "rock"                                            # the rock tiles next to floor (4-neighbour) become wall
    near = np.zeros_like(rock)
    solid = ~rock
    near[1:, :] |= solid[:-1, :]
    near[:-1, :] |= solid[1:, :]
    near[:, 1:] |= solid[:, :-1]
    near[:, :-1] |= solid[:, 1:]
    k[rock & near] = "wall"
    return k


def wall_tile_id(solid, y, x):
    """Index of the wall tile for the solid tile (y, x): bricks only on the sides that face open ground, a corner variant when only a diagonal is open,
    None for deep rock."""
    h, w = solid.shape
    op = lambda yy, xx: 0 <= yy < h and 0 <= xx < w and not solid[yy, xx]
    mask = (1 if op(y - 1, x) else 0) | (2 if op(y, x + 1) else 0) | (4 if op(y + 1, x) else 0) | (8 if op(y, x - 1) else 0)
    if mask:
        return WALL_FIRST + mask - 1
    for d, (dy, dx) in enumerate(((-1, 1), (1, 1), (1, -1), (-1, -1))):
        if op(y + dy, x + dx):
            return WALL_FIRST + 15 + d
    return None


def to_ids(kinds, seed=2):
    """Tile ids for a kind grid: rock and wall tiles together are the solid ground; a solid tile with open ground beside it gets the brick-rimmed wall tile
    that matches, other solid tiles stipple rock."""
    r = np.random.default_rng(seed)
    solid = np.isin(kinds, ("rock", "wall"))
    out = np.zeros(kinds.shape, int)
    for y in range(kinds.shape[0]):
        for x in range(kinds.shape[1]):
            if solid[y, x]:
                wid = wall_tile_id(solid, y, x)
                if wid is not None:
                    out[y, x] = wid
                    continue
                ids = IDX["rock"]
            else:
                ids = IDX[kinds[y, x]]
            out[y, x] = ids[int(r.integers(0, len(ids)))]
    return out


def render_map(ids):
    out = np.zeros((ids.shape[0] * T, ids.shape[1] * T, 3), np.uint8)
    for y in range(ids.shape[0]):
        for x in range(ids.shape[1]):
            out[y * T:(y + 1) * T, x * T:(x + 1) * T] = TILES[ids[y, x]][1]
    return out


if __name__ == "__main__":
    import sys
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    d = os.path.join(ROOT, "docs", "examples")
    write_png(os.path.join(d, "ink_tileset.png"), sheet())
    with open(os.path.join(d, "ink_tileset.json"), "w") as f:
        json.dump({"tile": T, "cols": COLS, "roles": [t[2] for t in TILES], "names": [t[0] for t in TILES], "wall_side": WALL_SIDE, "prop_kinds": {str(k): v for k, v in PROP_KINDS.items()},
                   "walltiles": {"first": WALL_FIRST, "note": "15 side-mask variants (N=1 E=2 S=4 W=8, mask 1..15) then 4 corner variants NE SE SW NW"}}, f, indent=1)
    write_png(os.path.join(d, "ink_map.png"), render_map(to_ids(make_dungeon(seed=seed))))
    print("wrote ink_tileset.png, ink_tileset.json and ink_map.png in", d)
