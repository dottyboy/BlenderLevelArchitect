"""Draw docs/examples/house_floorplan.png: a small three-room-plus house plan (1 cm per pixel),
the kind of picture 'House from Floor-Plan Picture' reads.  numpy + a tiny PNG writer, no other libraries.

    python3 tools/make_house_example.py
"""
import os, struct, zlib
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H, M = 1300, 840, 60                       # house size in px (cm) and the white margin
cv = np.full((H + 2 * M, W + 2 * M), 255, np.uint8)


def box(x0, y0, x1, y1, v=0):
    cv[M + y0:M + y1, M + x0:M + x1] = v


def line_pt(x, y, v=130):
    cv[M + y - 1:M + y + 1, M + x - 1:M + x + 1] = v


T = 22
box(0, 0, W, T); box(0, H - T, W, H); box(0, 0, T, H); box(W - T, 0, W, H)        # outer walls
box(0, 420 - 5, W, 420 + 6)                                                       # long inner wall
box(420 - 5, 0, 420 + 6, 420); box(700 - 5, 0, 700 + 6, 420)                      # bedroom / bath walls
box(760 - 5, 420, 760 + 6, H)                                                     # living / kitchen wall


def window_h(x0, x1, y):                                                          # gap in a horizontal outer wall, two thin lines
    box(x0, y, x1, y + T, 255)
    for dy in (7, 14):
        cv[M + y + dy:M + y + dy + 1, M + x0:M + x1] = 130


def window_v(y0, y1, x):
    box(x, y0, x + T, y1, 255)
    for dx in (7, 14):
        cv[M + y0:M + y1, M + x + dx:M + x + dx + 1] = 130


def door_h(x0, x1, y, up):                                                        # doorway in the inner wall y, hinge at x0, opens up (-y) or down
    box(x0, y - 6, x1, y + 6, 255)
    r = x1 - x0
    s = -1 if up else 1
    for k in range(r + 1):
        line_pt(x0, y + s * k)                                                    # the open leaf
    for th in np.linspace(0, np.pi / 2, 300):
        line_pt(int(round(x0 + r * np.cos(th))), int(round(y + s * r * np.sin(th))))


def door_v(y0, y1, x, left):
    box(x - 6, y0, x + 6, y1, 255)
    r = y1 - y0
    s = -1 if left else 1
    for k in range(r + 1):
        line_pt(x + s * k, y0)
    for th in np.linspace(0, np.pi / 2, 300):
        line_pt(int(round(x + s * r * np.sin(th))), int(round(y0 + r * np.cos(th))))


window_h(120, 300, 0); window_h(880, 1120, 0)                                     # bedroom windows, north
window_v(540, 740, 0); window_v(540, 740, W - T)                                  # living room west, kitchen east
box(300, H - T, 420, H, 255)                                                      # the front entrance, south
window_h(900, 1100, H - T)                                                        # kitchen window, south
door_h(150, 240, 420, True); door_h(520, 610, 420, True); door_h(950, 1040, 420, True)
door_v(600, 690, 760, True)
for (x0, y0, x1, y1) in ((60, 60, 150, 130), (480, 90, 640, 150), (780, 80, 880, 140)):   # a few furniture outlines the reader must ignore
    cv[M + y0:M + y1, M + x0:M + x0 + 1] = 0; cv[M + y0:M + y1, M + x1:M + x1 + 1] = 0
    cv[M + y0:M + y0 + 1, M + x0:M + x1] = 0; cv[M + y1:M + y1 + 1, M + x0:M + x1] = 0


def write_png(path, a):
    raw = b"".join(b"\x00" + row.tobytes() for row in a)
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", a.shape[1], a.shape[0], 8, 0, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


out = os.path.join(ROOT, "docs", "examples", "house_floorplan.png")
write_png(out, cv)
print("wrote", out, "- the walls span 13.0 m, so use width=13.0")
