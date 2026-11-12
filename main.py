#!/usr/bin/env python3
"""Eclipse Moth -- procedural artwork rendered with the Python standard library.

A moth seen from above, wings spread: each wing plate is a total solar eclipse,
near-black against a blazing golden corona that hugs the wing edge and burns
brightest at the tips. Deep violet-to-black radial sky, slim dark body, two
feathery antennae, a little gold dust.

Rendering notes
---------------
* Everything is analytic: signed distance fields for the wing plates, ellipse
  distance approximations for the body, an exact spine function for antennae.
  Anti-aliasing comes from a 1-pixel smoothstep on the signed distance, so the
  edges are clean without any dithering or noise.
* The piece is mirror-symmetric about the vertical axis, so only the right half
  (512 columns) is evaluated; the left half is a byte-slice reversal of it.
* PNG is emitted by hand: IHDR / IDAT / IEND, RGB8, zlib deflate.

Modules used: math, os, struct, zlib (standard library only).
"""

import math
import os
import struct
import zlib

W = 1024
H = 1024
HALF = W // 2
INV = 2.0 / W          # one distance unit spans W/2 = 512 px
AA = 0.5 * INV         # half a pixel: total smoothstep width = 1 px


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def smoothstep(e0, e1, x):
    t = (x - e0) / (e1 - e0)
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return t * t * (3.0 - 2.0 * t)


def clamp01(x):
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def ell_params(cx, cy, a, b, ang):
    """Pre-computed rotated-ellipse distance parameters."""
    ca = math.cos(ang)
    sa = math.sin(ang)
    return (cx, cy, ca, sa, 1.0 / a, 1.0 / b,
            1.0 / (a * a), 1.0 / (b * b))


def ell(e, x, y, sqrt=math.sqrt):
    """Approximate signed distance to a rotated ellipse (negative inside)."""
    dx = x - e[0]
    dy = y - e[1]
    ca = e[2]
    sa = e[3]
    u = dx * ca + dy * sa
    v = dy * ca - dx * sa
    k0 = sqrt((u * e[4]) ** 2 + (v * e[5]) ** 2)
    k1 = sqrt((u * e[6]) ** 2 + (v * e[7]) ** 2)
    if k1 == 0.0:
        return -1e3
    return k0 * (k0 - 1.0) / k1


def smin(a, b, k):
    """Polynomial smooth minimum -- welds forewing and hindwing together."""
    h = k - abs(a - b)
    if h <= 0.0:
        return a if a < b else b
    h = h / k
    m = a if a < b else b
    return m - 0.25 * h * h * k


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------

FORE = ell_params(0.430, -0.285, 0.440, 0.225, -0.40)
HIND = ell_params(0.318, 0.300, 0.360, 0.292, 0.36)
HEAD = ell_params(0.0, -0.428, 0.033, 0.040, 0.0)

# feathery antenna: spine x(t), y(t) with t in [0, 1]
AX0, AY0 = 0.025, -0.435
AXS, AYS = 0.372, -0.470
APOW = 2.10
TEETH = 9.5

MOTES = (
    (0.640, -0.760, 0.0055, 0.85),
    (0.828, -0.318, 0.0042, 0.62),
    (0.560, 0.640, 0.0050, 0.58),
    (0.905, 0.104, 0.0034, 0.50),
    (0.300, -0.885, 0.0032, 0.46),
    (0.742, 0.452, 0.0040, 0.42),
    (0.432, -0.700, 0.0028, 0.34),
    (0.196, 0.812, 0.0036, 0.40),
    (0.985, -0.620, 0.0028, 0.30),
)


# --------------------------------------------------------------------------
# renderer
# --------------------------------------------------------------------------

def render():
    exp = math.exp
    sqrt = math.sqrt
    fabs = math.fabs
    pi = math.pi

    rows = []
    for j in range(H):
        y = (j + 0.5) * INV - 1.0
        rh = bytearray(HALF * 3)
        p = 0

        # ---- per-row body profile -------------------------------------
        s = (y + 0.44) / 1.06
        body_on = -0.02 < s < 1.06
        bw = 0.0
        if body_on:
            bw = 0.021
            bw += 0.038 * exp(-((s - 0.090) / 0.130) ** 2)
            bw += 0.022 * exp(-((s - 0.420) / 0.300) ** 2)
            bw *= 1.0 - smoothstep(0.76, 1.00, s)
            bw *= smoothstep(-0.02, 0.015, s)
            if bw < 0.0:
                bw = 0.0

        for i in range(HALF):
            x = (i + 0.5) * INV

            # ---------------- sky: deep violet -> near black -----------
            r2 = x * x + y * y
            t = r2 * 0.60
            if t > 1.0:
                t = 1.0
            tt = t * t * (3.0 - 2.0 * t)
            r = sqrt(r2)

            cr = 0.108 * (1.0 - tt) + 0.011 * tt
            cg = 0.046 * (1.0 - tt) + 0.007 * tt
            cb = 0.196 * (1.0 - tt) + 0.022 * tt

            # faint violet halo where the corona bleeds into the dark
            hz = 0.042 * exp(-((r - 0.70) / 0.34) ** 2)
            cr += hz * 0.95
            cg += hz * 0.42
            cb += hz * 1.25

            # ---------------- wing plate -------------------------------
            d = smin(ell(FORE, x, y, sqrt), ell(HIND, x, y, sqrt), 0.100)
            cov = 1.0 - smoothstep(-AA, AA, d)

            # ---------------- corona outside the edge ------------------
            if cov < 0.999:
                dn = d if d > 0.0 else 0.0
                if dn < 0.42:
                    k = (r - 0.15) * 1.34
                    if k < 0.0:
                        k = 0.0
                    elif k > 1.0:
                        k = 1.0
                    tipw = 0.30 + 0.98 * (k ** 1.45)

                    core = exp(-((dn - 0.0085) * 62.0) ** 2)
                    mid = exp(-dn * 17.0)
                    far = exp(-dn * 5.5)
                    g = tipw * (1.02 * core + 0.50 * mid + 0.15 * far)
                    g *= (1.0 - cov)
                    if g > 0.001:
                        gi = g if g < 1.0 else 1.0
                        cr += (1.00 - 0.02 * gi) * g
                        cg += (0.80 + 0.20 * gi) * g
                        cb += (0.50 + 0.46 * gi) * g

            # ---------------- wing plate fill + inner rim -------------
            if cov > 0.001:
                din = -d
                bleed = exp(-(din if din > 0.0 else 0.0) * 15.0)
                pr = 0.030 + bleed * 0.46
                pg = 0.024 + bleed * 0.33
                pb = 0.052 + bleed * 0.13
                cr = cr * (1.0 - cov) + pr * cov
                cg = cg * (1.0 - cov) + pg * cov
                cb = cb * (1.0 - cov) + pb * cov

                inn = exp(-((din - 0.0060) * 85.0) ** 2)
                if inn > 0.002:
                    kk = (r - 0.15) * 1.34
                    if kk < 0.0:
                        kk = 0.0
                    elif kk > 1.0:
                        kk = 1.0
                    rw = (0.42 + 0.72 * kk) * inn * cov
                    cr += 1.00 * rw
                    cg += 0.88 * rw
                    cb += 0.62 * rw

            # ---------------- slim body + rounded head -----------------
            hb = 1e3
            if -0.505 < y < -0.345:
                hb = ell(HEAD, x, y, sqrt)
            if (body_on and bw > 0.0005) or hb < 0.4:
                db = fabs(x) - bw if bw > 0.0005 else 1e3
                if hb < 0.4:
                    db = smin(db, hb, 0.020)
                covb = 1.0 - smoothstep(-AA, AA, db)
                if covb > 0.002:
                    br = 0.040
                    bg_ = 0.030
                    bb = 0.058
                    cr = cr * (1.0 - covb) + br * covb
                    cg = cg * (1.0 - covb) + bg_ * covb
                    cb = cb * (1.0 - covb) + bb * covb
                    rim = exp(-((db + 0.0016) * 300.0) ** 2)
                    rim *= 0.55 * covb
                    cr += 1.00 * rim
                    cg += 0.84 * rim
                    cb += 0.58 * rim

            # ---------------- feathery antenna --------------------------
            if y < -0.425 and x < 0.470:
                ta = -(y - AY0) / (-AYS)
                if 0.0 <= ta < 1.04:
                    xsp = AX0 + AXS * (ta ** APOW)
                    perp = fabs(x - xsp)
                    if perp < 0.075:
                        slope = (AXS * APOW * (ta ** 0.6 if ta > 1e-6 else 0.0)) / (-AYS)
                        perp = perp / sqrt(1.0 + slope * slope)
                        ts = clamp01(ta)
                        wave = math.sin(pi * ts)
                        spine = exp(-(perp / (0.0040 + 0.0018 * wave)) ** 2)
                        fe = 0.009 + 0.015 * wave * wave
                        rib = 0.40 * exp(-(perp / fe) ** 2)
                        rib *= 0.58 + 0.42 * math.cos(2.0 * pi * TEETH * ts)
                        a = spine + rib * wave * 0.85 + 0.12 * exp(-(perp / 0.014) ** 2)
                        if a > 0.003:
                            if a > 1.0:
                                a = 1.0
                            cr += 1.00 * a
                            cg += 0.93 * a
                            cb += 0.76 * a

            # ---------------- gold dust ---------------------------------
            for mx, my, mr, ma in MOTES:
                ddx = x - mx
                if ddx > 0.03 or ddx < -0.03:
                    continue
                ddy = y - my
                dd = (ddx * ddx + ddy * ddy) / (mr * mr)
                if dd < 9.0:
                    a = ma * exp(-dd * 1.8)
                    cr += 1.00 * a
                    cg += 0.87 * a
                    cb += 0.55 * a

            # ---------------- write -------------------------------------
            rv = int(cr * 255.0 + 0.5)
            gv = int(cg * 255.0 + 0.5)
            bv = int(cb * 255.0 + 0.5)
            if rv > 255:
                rv = 255
            elif rv < 0:
                rv = 0
            if gv > 255:
                gv = 255
            elif gv < 0:
                gv = 0
            if bv > 255:
                bv = 255
            elif bv < 0:
                bv = 0
            rh[p] = rv
            rh[p + 1] = gv
            rh[p + 2] = bv
            p += 3

        # mirror the right half into the left half (byte-slice reversal)
        lh = bytearray(HALF * 3)
        lh[0::3] = rh[0::3][::-1]
        lh[1::3] = rh[1::3][::-1]
        lh[2::3] = rh[2::3][::-1]
        rows.append(b"\x00" + bytes(lh) + bytes(rh))

    return rows


# --------------------------------------------------------------------------
# PNG container
# --------------------------------------------------------------------------

def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data +
            struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png(path, rows):
    raw = b"".join(rows)
    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" +
           _chunk(b"IHDR", ihdr) +
           _chunk(b"IDAT", zlib.compress(raw, 9)) +
           _chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)
    return len(png)


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "./output")
    os.makedirs(out_dir, exist_ok=True)
    rows = render()
    path = os.path.join(out_dir, "entry.png")
    size = write_png(path, rows)
    print("wrote %s  %d bytes  %dx%d" % (path, size, W, H))


if __name__ == "__main__":
    main()