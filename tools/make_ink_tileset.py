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
    TILES.append(("wall", wall_tile(i), "stone"))
TILES.append(("pillar", pillar_tile(1), "prop"))
for i in range(2):
    TILES.append(("chasm", chasm_tile(i), "water"))
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
    rock = k == "rock"                                            # the rock tiles next to floor (4-neighbour) become wall
    near = np.zeros_like(rock)
    solid = ~rock
    near[1:, :] |= solid[:-1, :]
    near[:-1, :] |= solid[1:, :]
    near[:, 1:] |= solid[:, :-1]
    near[:, :-1] |= solid[:, 1:]
    k[rock & near] = "wall"
    return k


def to_ids(kinds, seed=2):
    r = np.random.default_rng(seed)
    out = np.zeros(kinds.shape, int)
    for y in range(kinds.shape[0]):
        for x in range(kinds.shape[1]):
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
        json.dump({"tile": T, "cols": COLS, "roles": [t[2] for t in TILES], "names": [t[0] for t in TILES]}, f, indent=1)
    write_png(os.path.join(d, "ink_map.png"), render_map(to_ids(make_dungeon(seed=seed))))
    print("wrote ink_tileset.png, ink_tileset.json and ink_map.png in", d)
