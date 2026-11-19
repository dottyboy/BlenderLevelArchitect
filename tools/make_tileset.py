"""Draws an original 16-px tileset and a demo tile map for 'Level from Tile Map' (numpy + a tiny PNG writer, no other libraries):

    python3 tools/make_tileset.py            # writes docs/examples/tileset_demo.png, tileset_demo.json and tilemap_demo.png

The tileset is a sheet of 8 tiles per row; tileset_demo.json gives each tile's role (floor / canopy / stone / water), which the
tile map tool uses when the map is matched against the tileset (an exact pixel match per tile).
"""
import json, os, struct, zlib
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = 16
rng = np.random.default_rng(7)


def write_png(path, a):
    a = np.ascontiguousarray(a.astype(np.uint8))
    raw = b"".join(b"\x00" + row.tobytes() for row in a)

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", a.shape[1], a.shape[0], 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def pal(*hexes):
    return np.array([[int(h[i:i + 2], 16) for i in (1, 3, 5)] for h in hexes], dtype=np.uint8)


def noise_tile(palette, seed, speck=0.06, scale=4):
    r = np.random.default_rng(seed)
    base = r.random((T // scale + 2, T // scale + 2))
    up = np.kron(base, np.ones((scale, scale)))[:T, :T]
    up = np.clip(up + r.normal(0, 0.12, (T, T)), 0, 0.999)
    img = palette[(up * len(palette)).astype(int)]
    m = r.random((T, T)) < speck
    img[m] = palette[-1]
    return img


def grass(seed, flowers=False):
    img = noise_tile(pal("#3f7a2e", "#468533", "#4f9138", "#5aa042"), seed, 0.05)
    r = np.random.default_rng(seed + 50)
    for _ in range(5):                                         # little blades
        x, y = r.integers(1, T - 1), r.integers(2, T - 1)
        img[y, x] = (0x2f, 0x62, 0x24); img[y - 1, x] = (0x6d, 0xb8, 0x4f)
    if flowers:
        for col in ((0xf2, 0xd2, 0x3a), (0xf4, 0xf4, 0xe8), (0xc8, 0x6b, 0xe0)):
            x, y = r.integers(1, T - 1), r.integers(1, T - 1)
            img[y, x] = col
    return img


def dirt(seed):
    img = noise_tile(pal("#6b4f33", "#755839", "#80623f", "#8c6d47"), seed, 0.08, 3)
    return img


def sand(seed):
    return noise_tile(pal("#d6c28a", "#dccb94", "#e3d49f", "#cdb97e"), seed, 0.05, 5)


def paving(seed):
    img = np.zeros((T, T, 3), np.uint8)
    img[:] = (0x4c, 0x4a, 0x48)
    r = np.random.default_rng(seed)
    for by in range(0, T, 8):
        off = 0 if (by // 8) % 2 == 0 else 4
        for bx in range(-off, T, 8):
            tone = int(r.integers(0, 4)) * 6
            col = np.array((0x86, 0x82, 0x7c)) + tone - 8
            x0, x1, y0, y1 = max(bx + 1, 0), min(bx + 8, T), by + 1, min(by + 8, T)
            img[y0:y1, x0:x1] = col
            img[y0, x0:x1] = np.clip(col + 14, 0, 255)
            img[y1 - 1, x0:x1] = np.clip(col - 18, 0, 255)
    return img


def water(seed):
    img = np.zeros((T, T, 3), np.uint8)
    img[:] = (0x2a, 0x5f, 0x9e)
    r = np.random.default_rng(seed)
    for _ in range(4):
        y, x = r.integers(1, T - 1), r.integers(0, T - 5)
        img[y, x:x + 4] = (0x4a, 0x86, 0xc8)
        img[y + 1 if y + 1 < T else y, x + 1:x + 3] = (0x20, 0x4c, 0x84)
    return img


def canopy(seed):
    base = pal("#1f5a26", "#27682d", "#2f7a35", "#3b8c3f")
    img = noise_tile(base, seed, 0.0, 2)
    r = np.random.default_rng(seed + 9)
    for _ in range(6):                                          # leaf clusters with a highlight and a shadow
        cx, cy = r.integers(2, T - 2), r.integers(2, T - 2)
        img[cy - 1:cy + 1, cx - 1:cx + 1] = (0x4f, 0xa5, 0x4a)
        img[cy + 1, cx - 1:cx + 2] = (0x17, 0x45, 0x1c)
    return img


def brick(seed, window=False):
    img = np.zeros((T, T, 3), np.uint8)
    img[:] = (0x3a, 0x34, 0x30)
    r = np.random.default_rng(seed)
    for by in range(0, T, 4):
        off = 0 if (by // 4) % 2 == 0 else 4
        for bx in range(-off, T, 8):
            tone = int(r.integers(0, 4)) * 7
            col = np.array((0x9a, 0x6a, 0x52)) + tone - 10
            x0, x1, y0, y1 = max(bx + 1, 0), min(bx + 8, T), by + 1, by + 4
            img[y0:y1, x0:x1] = col
            img[y0, x0:x1] = np.clip(col + 22, 0, 255)
    if window:
        img[4:13, 4:12] = (0x70, 0x66, 0x60)                  # a pale stone frame round a glazed window
        img[5:12, 5:11] = (0x2c, 0x3a, 0x58)
        img[5:12, 8] = (0x70, 0x66, 0x60)
        img[8, 5:11] = (0x70, 0x66, 0x60)
        img[5:7, 5:7] = (0x6f, 0x8f, 0xc0)
    return img


def rubble(seed):
    img = noise_tile(pal("#5a5650", "#6a665f", "#7b766d", "#8b867b"), seed, 0.12, 3)
    r = np.random.default_rng(seed)
    for _ in range(4):
        x, y = r.integers(1, T - 4), r.integers(1, T - 4)
        img[y:y + 3, x:x + 3] = (0x94, 0x8f, 0x84)
        img[y + 2, x:x + 3] = (0x4a, 0x46, 0x40)
    return img


TILES = [("grass", grass(1), "floor"), ("grass", grass(2), "floor"), ("grass", grass(3, True), "floor"), ("dirt", dirt(4), "floor"),
         ("dirt", dirt(5), "floor"), ("paving", paving(6), "floor"), ("sand", sand(7), "floor"), ("water", water(8), "water"),
         ("canopy", canopy(9), "canopy"), ("canopy", canopy(10), "canopy"), ("canopy", canopy(11), "canopy"), ("brick", brick(12), "stone"),
         ("brick", brick(13), "stone"), ("brick window", brick(14, True), "stone"), ("rubble", rubble(15), "stone"), ("paving", paving(16), "floor")]
COLS = 8
IDX = {}
for i, (kind, _img, _role) in enumerate(TILES):
    IDX.setdefault(kind, []).append(i)


def sheet():
    rows = (len(TILES) + COLS - 1) // COLS
    out = np.zeros((rows * T, COLS * T, 3), np.uint8)
    for i, (_k, img, _r) in enumerate(TILES):
        out[(i // COLS) * T:(i // COLS + 1) * T, (i % COLS) * T:(i % COLS + 1) * T] = img
    return out


def fbm(h, w, seed, octaves=4, base=6):
    r = np.random.default_rng(seed)
    total, amp, norm = np.zeros((h, w)), 1.0, 0.0
    for o in range(octaves):
        n = base * 2 ** o
        g = r.random((n + 2, n + 2))
        ys, xs = np.linspace(0, n, h, endpoint=False), np.linspace(0, n, w, endpoint=False)
        y0, x0 = ys.astype(int), xs.astype(int)
        fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]
        fy, fx = fy * fy * (3 - 2 * fy), fx * fx * (3 - 2 * fx)
        v = (g[y0][:, x0] * (1 - fx) + g[y0][:, x0 + 1] * fx) * (1 - fy) + (g[y0 + 1][:, x0] * (1 - fx) + g[y0 + 1][:, x0 + 1] * fx) * fy
        total += v * amp
        norm += amp
        amp *= 0.5
    return total / norm


def make_map(w=64, h=48, seed=3):
    r = np.random.default_rng(seed)
    elev = fbm(h, w, seed)
    wood = fbm(h, w, seed + 1, 3, 4)
    pick = lambda kind: IDX[kind][int(r.integers(0, len(IDX[kind])))]
    m = np.zeros((h, w), int)
    for y in range(h):
        for x in range(w):
            e = elev[y, x]
            if e < 0.40:
                m[y, x] = pick("water")
            elif e < 0.44:
                m[y, x] = pick("sand")
            elif wood[y, x] > 0.56 and e > 0.5:
                m[y, x] = pick("canopy")
            else:
                m[y, x] = pick("grass")
    # a walled yard and a small house on dry ground, joined by a dirt path
    def room(x0, y0, x1, y1, door):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                edge = x in (x0, x1) or y in (y0, y1)
                m[y, x] = (pick("brick") if r.random() > 0.08 else pick("brick window")) if edge else pick("paving")
        dx, dy = door
        m[dy, dx] = pick("paving")
    room(8, 10, 22, 22, (15, 22))
    room(40, 26, 52, 36, (46, 26))
    for (x, y) in ((10, 12), (14, 18), (19, 14)):                         # fallen stones in the yard
        m[y, x] = pick("rubble")
    px, py = 15, 23
    while (px, py) != (46, 25):                                          # dirt path from one door to the other
        if r.random() < 0.55 and px != 46:
            px += 1 if px < 46 else -1
        elif py != 25:
            py += 1 if py < 25 else -1
        m[py, px] = pick("dirt")
        if py < 25 and px == 46:
            m[py + 1, px] = pick("dirt")
    m[25, 46] = pick("dirt")
    return m


def render_map(m):
    out = np.zeros((m.shape[0] * T, m.shape[1] * T, 3), np.uint8)
    for y in range(m.shape[0]):
        for x in range(m.shape[1]):
            out[y * T:(y + 1) * T, x * T:(x + 1) * T] = TILES[m[y, x]][1]
    return out


if __name__ == "__main__":
    d = os.path.join(ROOT, "docs", "examples")
    write_png(os.path.join(d, "tileset_demo.png"), sheet())
    with open(os.path.join(d, "tileset_demo.json"), "w") as f:
        json.dump({"tile": T, "cols": COLS, "roles": [t[2] for t in TILES], "names": [t[0] for t in TILES]}, f, indent=1)
    write_png(os.path.join(d, "tilemap_demo.png"), render_map(make_map()))
    print("wrote tileset_demo.png, tileset_demo.json and tilemap_demo.png in", d)
