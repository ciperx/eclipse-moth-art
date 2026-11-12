#!/usr/bin/env python3
"""Papercut Lighthouse -- layered paper cut-out art, Python standard library only.

Eight flat paper plates, painted far to near, each a solid fill laid over a
soft 20% drop shadow nudged (4, 6) down-right, so the picture reads as card
stacked in real depth:

    1  night sky (deep navy) with punched cream stars
    2  low moon, pale cream disc
    3  the beam: one wide translucent pale-gold paper wedge, apex at the lantern
    4  far sea band, dark teal, scalloped paper crest
    5  mid sea band
    6  near sea band
    7  pale cliff on the right
    8  lighthouse: white tower, two dark paper rings, warm-yellow lantern room

Rendering notes
---------------
* No textures, no noise, no dithering: every layer is one flat colour, and the
  only gradient in the piece lives inside the beam.
* Shapes are drawn as row spans (steep edges: tower, moon, stars) or column
  spans (shallow edges: sea crests, cliff, beam). Coverage on the spanning axis
  is analytic -- the exact overlap of the 1px pixel box with the span -- so cut
  edges land on clean, even anti-aliased boundaries at 1024.
* Drop shadows are a 7px soft halo around each plate's silhouette, displaced
  (4, 6): a straight offset alone would vanish under plates whose body runs off
  the bottom of the frame, the halo keeps a visible rim all the way round and
  reads heaviest on the lower-right side, as paper lit from the upper left.
* Full-coverage interiors are written with byte-slice assignment and shadows
  with bytes.translate against a 20%-darken table, so only the edges and the
  halo cost real per-pixel work.
* PNG is assembled by hand: IHDR / IDAT / IEND, RGB8, zlib deflate.

Modules used: math, os, struct, zlib.
"""

import math
import os
import struct
import zlib

W = H = 1024
ROW = W * 3
NPX = W * H

# ---------------------------------------------------------------------------
# palette -- one flat colour per paper plate
# ---------------------------------------------------------------------------
SKY      = (13, 27, 52)
STAR     = (247, 239, 214)
MOON     = (243, 231, 196)
BEAM     = (255, 226, 132)
SEA_FAR  = (30, 82, 94)
SEA_MID  = (21, 62, 74)
SEA_NEAR = (14, 44, 55)
CLIFF    = (203, 197, 180)
LH_WHITE = (246, 243, 233)
LH_DARK  = (34, 37, 48)
LANTERN  = (255, 202, 82)

# 20% darken, for drop shadows
DARK_TBL = bytes(min(255, int(v * 0.8)) for v in range(256))

DX, DY, RB = 4.0, 6.0, 10.0    # shadow offset and halo radius

buf = bytearray(bytes(SKY) * NPX)


# ---------------------------------------------------------------------------
# span maths
# ---------------------------------------------------------------------------
def cuts(a, b, n):
    """Split span [a, b) inside [0, n) into (edge pixels, interior run).

    Returns (parts, mid): parts = [(pixel, coverage), ...] for the at most two
    partially covered end pixels, mid = (i0, i1) for the fully covered interior.
    None when the span misses the canvas entirely.
    """
    if a < 0.0:
        a = 0.0
    if b > n:
        b = float(n)
    if b <= a:
        return None
    ia = int(a)
    ib = int(b)
    parts = []
    mid = None
    if ib > ia:
        if a > ia:
            parts.append((ia, ia + 1.0 - a))
            ia += 1
        if b > ib:
            parts.append((ib, b - ib))
        if ia < ib:
            mid = (ia, ib)
    else:
        parts.append((ia, b - a))
    return parts, mid


def _ramp(c, lo, hi, r):
    """Soft shoulder: 0 at lo, 1 from lo + r, and mirrored at the hi end."""
    a = (c - lo) / r
    if a > 1.0:
        a = 1.0
    b = (hi - c) / r
    if b > 1.0:
        b = 1.0
    return a if a < b else b


# ---------------------------------------------------------------------------
# span writers
# ---------------------------------------------------------------------------
def fill_rows(y0, y1, fxa, fxb, col, alpha=1.0):
    """Paint the horizontal span [fxa(y), fxb(y)) on every row of [y0, y1)."""
    r, g, b = col
    for y in range(max(0, y0), min(H, y1)):
        res = cuts(fxa(y), fxb(y), W)
        if res is None:
            continue
        parts, mid = res
        o0 = y * ROW
        for i, c in parts:
            o = o0 + i * 3
            a = alpha * c
            ia = 1.0 - a
            buf[o] = int(buf[o] * ia + r * a + 0.5)
            buf[o + 1] = int(buf[o + 1] * ia + g * a + 0.5)
            buf[o + 2] = int(buf[o + 2] * ia + b * a + 0.5)
        if mid:
            oa = o0 + mid[0] * 3
            ob = o0 + mid[1] * 3
            if alpha >= 1.0:
                buf[oa:ob] = bytes(col) * ((ob - oa) // 3)
            else:
                ia = 1.0 - alpha
                for o in range(oa, ob, 3):
                    buf[o] = int(buf[o] * ia + r * alpha + 0.5)
                    buf[o + 1] = int(buf[o + 1] * ia + g * alpha + 0.5)
                    buf[o + 2] = int(buf[o + 2] * ia + b * alpha + 0.5)


def fill_cols(x0, x1, fya, fyb, col, alpha=1.0):
    """Paint the vertical span [fya(x), fyb(x)) on every column of [x0, x1)."""
    r, g, b = col
    for x in range(max(0, x0), min(W, x1)):
        res = cuts(fya(x), fyb(x), H)
        if res is None:
            continue
        parts, mid = res
        base = x * 3
        for i, c in parts:
            o = i * ROW + base
            a = alpha * c
            ia = 1.0 - a
            buf[o] = int(buf[o] * ia + r * a + 0.5)
            buf[o + 1] = int(buf[o + 1] * ia + g * a + 0.5)
            buf[o + 2] = int(buf[o + 2] * ia + b * a + 0.5)
        if mid:
            if alpha >= 1.0:
                for i in range(mid[0], mid[1]):
                    o = i * ROW + base
                    buf[o] = r
                    buf[o + 1] = g
                    buf[o + 2] = b
            else:
                ia = 1.0 - alpha
                for i in range(mid[0], mid[1]):
                    o = i * ROW + base
                    buf[o] = int(buf[o] * ia + r * alpha + 0.5)
                    buf[o + 1] = int(buf[o + 1] * ia + g * alpha + 0.5)
                    buf[o + 2] = int(buf[o + 2] * ia + b * alpha + 0.5)


def shadow_rows(y0, y1, fxa, fxb):
    """Soft 20% drop shadow for a row-span plate, halo radius RB, offset (4, 6)."""
    top = y0 + DY - RB
    bot = y1 + DY + RB
    for y in range(int(math.floor(top)), int(math.ceil(bot))):
        if y < 0 or y >= H:
            continue
        c = y + 0.5
        if c < y0 + DY:
            t = (c - top) / RB
        elif c <= y1 + DY:
            t = 1.0
        else:
            t = (bot - c) / RB
        if t <= 0.0:
            continue
        if t > 1.0:
            t = 1.0
        yy = y - DY
        if yy < y0:
            yy = y0
        elif yy > y1 - 1e-6:
            yy = y1 - 1e-6
        xa = fxa(yy) + DX - RB
        xb = fxb(yy) + DX + RB
        ia = int(xa) if xa > 0.0 else 0
        ib = int(math.ceil(xb))
        if ib > W:
            ib = W
        if ib <= ia:
            continue
        o0 = y * ROW
        full = t >= 1.0
        if full:
            r0 = ia + int(RB) + 1
            r1 = ib - int(RB) - 1
            if r1 > r0:
                oa = o0 + r0 * 3
                ob = o0 + r1 * 3
                buf[oa:ob] = buf[oa:ob].translate(DARK_TBL)
                segs = ((ia, r0), (r1, ib))
            else:
                segs = ((ia, ib),)
        else:
            segs = ((ia, ib),)
        for s0, s1 in segs:
            for i in range(s0, s1):
                k = t * _ramp(i + 0.5, xa, xb, RB)
                if k <= 0.0:
                    continue
                f = 1.0 - 0.2 * k
                o = o0 + i * 3
                buf[o] = int(buf[o] * f)
                buf[o + 1] = int(buf[o + 1] * f)
                buf[o + 2] = int(buf[o + 2] * f)


def shadow_cols(x0, x1, fya, fyb):
    """Soft 20% drop shadow for a column-span plate, halo radius RB, offset (4, 6)."""
    left = x0 + DX - RB
    right = x1 + DX + RB
    for x in range(int(math.floor(left)), int(math.ceil(right))):
        if x < 0 or x >= W:
            continue
        t = _ramp(x + 0.5, left, right, RB)
        if t <= 0.0:
            continue
        xx = x - DX
        if xx < x0:
            xx = x0
        elif xx > x1 - 1e-6:
            xx = x1 - 1e-6
        ya = fya(xx) + DY - RB
        yb = fyb(xx) + DY + RB
        ia = int(ya) if ya > 0.0 else 0
        ib = int(math.ceil(yb))
        if ib > H:
            ib = H
        if ib <= ia:
            continue
        base = x * 3
        if t >= 1.0:
            fi = 205
            r0 = ia + int(RB) + 1
            r1 = ib - int(RB) - 1
            if r1 > r0:
                for i in range(ia, r0):
                    k = _ramp(i + 0.5, ya, yb, RB)
                    if k > 0.0:
                        f = 1.0 - 0.2 * k
                        o = i * ROW + base
                        buf[o] = int(buf[o] * f)
                        buf[o + 1] = int(buf[o + 1] * f)
                        buf[o + 2] = int(buf[o + 2] * f)
                for i in range(r0, r1):
                    o = i * ROW + base
                    buf[o] = (buf[o] * fi) >> 8
                    buf[o + 1] = (buf[o + 1] * fi) >> 8
                    buf[o + 2] = (buf[o + 2] * fi) >> 8
                for i in range(r1, ib):
                    k = _ramp(i + 0.5, ya, yb, RB)
                    if k > 0.0:
                        f = 1.0 - 0.2 * k
                        o = i * ROW + base
                        buf[o] = int(buf[o] * f)
                        buf[o + 1] = int(buf[o + 1] * f)
                        buf[o + 2] = int(buf[o + 2] * f)
                continue
        for i in range(ia, ib):
            k = t * _ramp(i + 0.5, ya, yb, RB)
            if k <= 0.0:
                continue
            f = 1.0 - 0.2 * k
            o = i * ROW + base
            buf[o] = int(buf[o] * f)
            buf[o + 1] = int(buf[o + 1] * f)
            buf[o + 2] = int(buf[o + 2] * f)


def plate(y0, y1, fxa, fxb, col, shadow=True):
    """A row-span paper plate: drop shadow first, then the flat fill."""
    if shadow:
        shadow_rows(y0, y1, fxa, fxb)
    fill_rows(y0, y1, fxa, fxb, col)


def plate_cols(x0, x1, fya, fyb, col, shadow=True):
    """A column-span paper plate: drop shadow first, then the flat fill."""
    if shadow:
        shadow_cols(x0, x1, fya, fyb)
    fill_cols(x0, x1, fya, fyb, col)


def rim(x0, x1, top, thick, alpha):
    """A thin lit line under a cut edge -- the visible thickness of the paper."""
    fill_cols(x0, x1, top, lambda x: top(x) + thick, (255, 255, 255),
              alpha=alpha)


# ---------------------------------------------------------------------------
# layer 1 -- sky and punched stars
# ---------------------------------------------------------------------------
_seed = 20261112


def rnd():
    global _seed
    _seed = (_seed * 1103515245 + 12345) & 0x7FFFFFFF
    return _seed


MOON_CX, MOON_CY, MOON_R = 236.0, 452.0, 58.0
APEX_X, APEX_Y = 790.0, 274.0


def draw_stars():
    for _ in range(92):
        cx = float(rnd() % W)
        cy = 22.0 + (rnd() % 560)
        rad = 1.05 + (rnd() % 100) / 100.0 * 1.45
        if cy > 588.0 or math.hypot(cx - MOON_CX, cy - MOON_CY) < MOON_R + 16.0:
            continue
        plate(int(cy - rad - 1), int(cy + rad + 2),
              lambda y, cx=cx, cy=cy, rad=rad: cx - math.sqrt(
                  max(0.0, rad * rad - (y + 0.5 - cy) ** 2)),
              lambda y, cx=cx, cy=cy, rad=rad: cx + math.sqrt(
                  max(0.0, rad * rad - (y + 0.5 - cy) ** 2)),
              STAR, shadow=False)


# ---------------------------------------------------------------------------
# layer 2 -- low moon
# ---------------------------------------------------------------------------
def draw_moon():
    plate(int(MOON_CY - MOON_R - 1), int(MOON_CY + MOON_R + 2),
          lambda y: MOON_CX - math.sqrt(
              max(0.0, MOON_R ** 2 - (y + 0.5 - MOON_CY) ** 2)),
          lambda y: MOON_CX + math.sqrt(
              max(0.0, MOON_R ** 2 - (y + 0.5 - MOON_CY) ** 2)),
          MOON)


# ---------------------------------------------------------------------------
# layer 3 -- the beam: translucent pale-gold wedge (the one gradient allowed)
# ---------------------------------------------------------------------------
FALL = [0.30 + 0.70 * (1.0 - abs(2.0 * (k + 0.5) / 128.0 - 1.0)) ** 0.55
        for k in range(128)]
BEAM_X0 = -40.0


def draw_beam():
    r, g, b = BEAM
    span = APEX_X - BEAM_X0
    for x in range(0, int(APEX_X)):
        t = (APEX_X - x) / span          # 0 at the lantern, 1 at the far end
        ya = APEX_Y + t * (88.0 - APEX_Y)
        yb = APEX_Y + t * (436.0 - APEX_Y)
        a_len = 0.72 - 0.30 * t
        res = cuts(ya, yb, H)
        if res is None:
            continue
        parts, mid = res
        inv = 1.0 / (yb - ya)
        base = x * 3
        for i, c in parts:
            w = FALL[min(127, int((i + 0.5 - ya) * inv * 128.0))]
            a = a_len * w * c
            ia = 1.0 - a
            o = i * ROW + base
            buf[o] = int(buf[o] * ia + r * a + 0.5)
            buf[o + 1] = int(buf[o + 1] * ia + g * a + 0.5)
            buf[o + 2] = int(buf[o + 2] * ia + b * a + 0.5)
        if mid:
            for i in range(mid[0], mid[1]):
                w = FALL[min(127, int((i + 0.5 - ya) * inv * 128.0))]
                a = a_len * w
                ia = 1.0 - a
                o = i * ROW + base
                buf[o] = int(buf[o] * ia + r * a + 0.5)
                buf[o + 1] = int(buf[o + 1] * ia + g * a + 0.5)
                buf[o + 2] = int(buf[o + 2] * ia + b * a + 0.5)

    # hotter core running down the middle of the same paper wedge
    cr, cg, cb = 255, 238, 156
    for x in range(0, int(APEX_X)):
        t = (APEX_X - x) / span
        ya = APEX_Y + t * (88.0 - APEX_Y)
        yb = APEX_Y + t * (436.0 - APEX_Y)
        a_core = 0.30 * (1.0 - t) ** 0.70
        ycen = 0.5 * (ya + yb)
        hw = 0.44 * (yb - ya)
        res = cuts(ycen - hw, ycen + hw, H)
        if res is None:
            continue
        parts, mid = res
        inv = 1.0 / (2.0 * hw)
        base = x * 3
        for i, c in parts:
            w = FALL[min(127, int((i + 0.5 - (ycen - hw)) * inv * 128.0))]
            a = a_core * w * c
            ia = 1.0 - a
            o = i * ROW + base
            buf[o] = int(buf[o] * ia + cr * a + 0.5)
            buf[o + 1] = int(buf[o + 1] * ia + cg * a + 0.5)
            buf[o + 2] = int(buf[o + 2] * ia + cb * a + 0.5)
        if mid:
            for i in range(mid[0], mid[1]):
                w = FALL[min(127, int((i + 0.5 - (ycen - hw)) * inv * 128.0))]
                a = a_core * w
                ia = 1.0 - a
                o = i * ROW + base
                buf[o] = int(buf[o] * ia + cr * a + 0.5)
                buf[o + 1] = int(buf[o + 1] * ia + cg * a + 0.5)
                buf[o + 2] = int(buf[o + 2] * ia + cb * a + 0.5)


# ---------------------------------------------------------------------------
# layers 4-6 -- sea plates with scalloped paper crests
# ---------------------------------------------------------------------------
def sea_top(base_y, amp, freq, phase, scallop, period):
    def f(x):
        u = (x / period) % 1.0
        return (base_y + amp * math.sin(freq * x + phase)
                - scallop * math.sin(math.pi * u))
    return f


def draw_sea():
    bands = (
        (596.0, 5.0, 0.009, 1.2, 16.0, 128.0, SEA_FAR),
        (700.0, 6.0, 0.011, 0.4, 18.0, 120.0, SEA_MID),
        (812.0, 6.0, 0.007, 2.1, 22.0, 156.0, SEA_NEAR),
    )
    for base_y, amp, freq, phase, scallop, period, col in bands:
        top = sea_top(base_y, amp, freq, phase, scallop, period)
        plate_cols(0, W, top, lambda x: float(H), col)
        rim(0, W, lambda x, t=top: t(x) + 1.0, 1.1, 0.085)


# ---------------------------------------------------------------------------
# layer 7 -- pale cliff on the right
# ---------------------------------------------------------------------------
CLIFF_PTS = (
    (496.0, 1024.0), (548.0, 952.0), (596.0, 886.0), (632.0, 822.0),
    (660.0, 758.0), (684.0, 700.0), (700.0, 648.0), (712.0, 596.0),
    (726.0, 552.0), (748.0, 532.0), (776.0, 521.0), (812.0, 516.0),
    (880.0, 513.0), (1024.0, 510.0),
)

# the sloping face, inverted: (y, leftmost x) rows, used for its drop shadow
CLIFF_LEFT = tuple((y, x) for x, y in reversed(CLIFF_PTS[:9]))


def cliff_top(x):
    if x < CLIFF_PTS[0][0]:
        return float(H)
    for k in range(len(CLIFF_PTS) - 1):
        x0, y0 = CLIFF_PTS[k]
        x1, y1 = CLIFF_PTS[k + 1]
        if x <= x1:
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return CLIFF_PTS[-1][1]


def cliff_left(y):
    """Inverse of the cliff's sloping face: the leftmost cliff column per row."""
    if y < CLIFF_LEFT[0][0]:
        return float(W)
    for k in range(len(CLIFF_LEFT) - 1):
        y0, x0 = CLIFF_LEFT[k]
        y1, x1 = CLIFF_LEFT[k + 1]
        if y <= y1:
            t = (y - y0) / (y1 - y0)
            return x0 + t * (x1 - x0)
    return CLIFF_LEFT[-1][1]


def draw_cliff():
    # the sloping face is near-vertical, so its shadow runs as row spans;
    # the flat top is near-horizontal, so that shadow runs as column spans
    shadow_rows(int(CLIFF_LEFT[0][0]), H,
                lambda y: cliff_left(y), lambda y: float(W))
    shadow_cols(int(CLIFF_LEFT[0][1]), W, cliff_top, lambda x: float(H))
    fill_cols(0, W, cliff_top, lambda x: float(H), CLIFF)
    rim(0, W, lambda x: cliff_top(x) + 1.0, 1.1, 0.09)


# ---------------------------------------------------------------------------
# layer 8 -- the lighthouse
# ---------------------------------------------------------------------------
LH_CX = 790.0
BODY_TOP, BODY_BOT = 306.0, 572.0
TOP_HALF, BOT_HALF = 34.0, 66.0
LAN_TOP, LAN_HALF = 250.0, 40.0
ROOF_TOP, ROOF_HALF = 231.0, 11.0


def body_half(y):
    t = (y - BODY_TOP) / (BODY_BOT - BODY_TOP)
    return TOP_HALF + t * (BOT_HALF - TOP_HALF)


def draw_lighthouse():
    # white tower
    plate(int(BODY_TOP), int(BODY_BOT) + 1,
          lambda y: LH_CX - body_half(y + 0.5),
          lambda y: LH_CX + body_half(y + 0.5), LH_WHITE)
    # lantern room, warm yellow, sitting straight on the tower
    plate(int(LAN_TOP), int(BODY_TOP) + 1,
          lambda y: LH_CX - LAN_HALF, lambda y: LH_CX + LAN_HALF, LANTERN)
    # flared roof
    plate(int(ROOF_TOP), int(LAN_TOP) + 1,
          lambda y: LH_CX - (ROOF_HALF + (LAN_HALF + 7.0 - ROOF_HALF)
                             * (y + 0.5 - ROOF_TOP) / (LAN_TOP - ROOF_TOP)),
          lambda y: LH_CX + (ROOF_HALF + (LAN_HALF + 7.0 - ROOF_HALF)
                             * (y + 0.5 - ROOF_TOP) / (LAN_TOP - ROOF_TOP)),
          LH_DARK)
    # two thin dark paper rings, each shadowed against the white tower
    for y0 in (392, 462):
        plate(y0, y0 + 18,
              lambda y: LH_CX - body_half(y + 0.5) - 3.0,
              lambda y: LH_CX + body_half(y + 0.5) + 3.0, LH_DARK)


# ---------------------------------------------------------------------------
# paint + encode
# ---------------------------------------------------------------------------
def paint():
    draw_stars()
    draw_moon()
    draw_beam()
    draw_sea()
    draw_cliff()
    draw_lighthouse()


def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def encode():
    raw = bytearray()
    for y in range(H):
        o = y * ROW
        raw.append(0)
        raw += buf[o:o + ROW]
    comp = zlib.compress(bytes(raw), 9)
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", comp)
            + _chunk(b"IEND", b""))


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "./output")
    os.makedirs(out_dir, exist_ok=True)
    paint()
    data = encode()
    path = os.path.join(out_dir, "entry.png")
    with open(path, "wb") as f:
        f.write(data)
    print("wrote %s  %d bytes  %dx%d" % (path, len(data), W, H))


if __name__ == "__main__":
    main()