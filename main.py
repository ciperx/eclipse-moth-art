#!/usr/bin/env python3
"""Teacup Nap -- procedural artwork rendered with the Python standard library.

A tiny round kitten asleep inside a mint-green teacup, seen from the side: a
big soft cream head with two triangular ears, eyes drawn as two gentle closed
arcs, a tiny pink nose, blush cheeks and one little paw draped over the rim.
The cup carries a thin gold rim and a small heart; one thin curl of steam
rises above it. Warm cream background with a very soft glow behind the cup.

Rendering notes
---------------
* Everything is analytic: signed distance fields for each shape (ellipses,
  rounded triangles, a heart implicit, a swept teacup silhouette), turned into
  coverage by a one-pixel smoothstep. No dithering, no noise, no hard lines --
  every edge is soft by construction, and shading is a gentle multiply.
* The mug is not symmetric (one handle, one paw, one heart, one curl of
  steam), so all 1024 columns are evaluated; only the per-row profile of the
  cup wall and of the steam curl is hoisted out of the pixel loop.
* Every shape is culled by a bounding box before its distance function runs,
  which is what keeps a pure-Python renderer inside a few seconds.
* PNG is emitted by hand: IHDR / IDAT / IEND, RGB8, zlib deflate.

Modules used: math, os, struct, zlib (standard library only).
"""

import math
import os
import struct
import zlib

W = 1024
H = 1024
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
    """Polynomial smooth minimum -- welds the ears onto the head."""
    h = k - abs(a - b)
    if h <= 0.0:
        return a if a < b else b
    h = h / k
    m = a if a < b else b
    return m - 0.25 * h * h * k


def tri_sd(x, y, ax, ay, bx, by, cx, cy):
    """Signed distance to a triangle (negative inside)."""
    e0x = bx - ax
    e0y = by - ay
    e1x = cx - bx
    e1y = cy - by
    e2x = ax - cx
    e2y = ay - cy
    v0x = x - ax
    v0y = y - ay
    v1x = x - bx
    v1y = y - by
    v2x = x - cx
    v2y = y - cy

    t = (v0x * e0x + v0y * e0y) / (e0x * e0x + e0y * e0y)
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    q0x = v0x - e0x * t
    q0y = v0y - e0y * t

    t = (v1x * e1x + v1y * e1y) / (e1x * e1x + e1y * e1y)
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    q1x = v1x - e1x * t
    q1y = v1y - e1y * t

    t = (v2x * e2x + v2y * e2y) / (e2x * e2x + e2y * e2y)
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    q2x = v2x - e2x * t
    q2y = v2y - e2y * t

    s = e0x * e2y - e0y * e2x
    s = 1.0 if s >= 0.0 else -1.0

    d0 = q0x * q0x + q0y * q0y
    d1 = q1x * q1x + q1y * q1y
    d2 = q2x * q2x + q2y * q2y
    w0 = s * (v0x * e0y - v0y * e0x)
    w1 = s * (v1x * e1y - v1y * e1x)
    w2 = s * (v2x * e2y - v2y * e2x)

    d = d0 if d0 < d1 else d1
    w = w0 if w0 < w1 else w1
    if d2 < d:
        d = d2
    if w2 < w:
        w = w2
    return -math.sqrt(d) if w > 0.0 else math.sqrt(d)


def heart_sd(x, y, cx, cy, s):
    """Approximate distance to a heart curve (negative inside)."""
    u = (x - cx) / s
    v = (cy - y) / s
    q = u * u + v * v - 1.0
    f = q * q * q - u * u * v * v * v
    gx = 6.0 * u * q * q - 2.0 * u * v * v * v
    gy = 6.0 * v * q * q - 3.0 * u * u * v * v
    g = math.sqrt(gx * gx + gy * gy)
    if g < 1e-6:
        return 1e3
    return f / g * s


# --------------------------------------------------------------------------
# geometry -- teacup seen from the side
# --------------------------------------------------------------------------

RIM_Y = 0.075          # rim centre line
RIM_RX = 0.615
RIM_RY = 0.100
BASE_Y = 0.800
TOP_HW = 0.560
BOT_HW = 0.360
RB = 0.120             # bottom rounding (elliptical foot)
T_B = 1.0 - RB / (BASE_Y - RIM_Y)


def _body_w(t):
    return TOP_HW + (BOT_HW - TOP_HW) * t + 0.020 * math.sin(math.pi * t)


W_B = _body_w(T_B)


def cup_hw(y):
    """Half width of the cup wall at height y (-1 where there is no wall)."""
    if y < RIM_Y or y >= BASE_Y:
        return -1.0
    t = (y - RIM_Y) / (BASE_Y - RIM_Y)
    if t <= T_B:
        return _body_w(t)
    u = (t - T_B) / (1.0 - T_B)
    return W_B * math.sqrt(1.0 - u * u)


RIM = ell_params(0.0, RIM_Y, RIM_RX, RIM_RY, 0.0)
INNER = ell_params(0.0, RIM_Y, RIM_RX * 0.995, RIM_RY * 0.985, 0.0)
HANDLE_O = ell_params(0.585, 0.400, 0.170, 0.150, -0.27)
HANDLE_I = ell_params(0.585, 0.400, 0.088, 0.072, -0.27)
SAUCER = ell_params(0.0, 0.830, 0.800, 0.105, 0.0)
SAUCER_EDGE = ell_params(0.0, 0.846, 0.795, 0.100, 0.0)
WELL = ell_params(0.0, 0.820, 0.700, 0.078, 0.0)
SHADOW = ell_params(0.0, 0.872, 0.860, 0.095, 0.0)
HEAD = ell_params(0.0, -0.055, 0.340, 0.300, 0.0)
PAW = ell_params(0.320, 0.115, 0.100, 0.125, 0.20)
FOOT_SH = ell_params(0.0, 0.818, 0.470, 0.058, 0.0)

# right ear, a rounded triangle; the left one is the mirror image
EAR_A = (0.060, -0.260)
EAR_B = (0.330, -0.215)
EAR_C = (0.300, -0.470)
EAR_R = 0.030
# inner ear: the same triangle shrunk about its centroid
IN_A = (0.126, -0.283)
IN_B = (0.303, -0.249)
IN_C = (0.275, -0.410)
IN_R = 0.020

EYE_X = 0.125
EYE_Y = -0.120
EYE_HW = 0.062
EYE_BOW = 0.030

NOSEY = -0.035
CHEEK = ell_params(0.215, -0.055, 0.089, 0.056, 0.0)
HEART_X = -0.245
HEART_Y = 0.430
HEART_S = 0.088
ST_TAU = math.pi * 1.2       # one slow curl, not a zig-zag
STEAM_Y0 = 0.125             # the wisp starts inside the cup opening
STEAM_Y1 = -0.870


# --------------------------------------------------------------------------
# renderer
# --------------------------------------------------------------------------

def render():
    exp = math.exp
    sqrt = math.sqrt
    sin = math.sin
    cos = math.cos
    fabs = math.fabs
    pi = math.pi

    rows = []
    for j in range(H):
        y = (j + 0.5) * INV - 1.0

        # ---- per-row cup wall -------------------------------------------
        hw = cup_hw(y)
        body_on = hw > 0.0
        rim_sh = 0.0
        if body_on:
            dy = y - RIM_Y
            rim_sh = 0.26 * exp(-(dy / 0.115) ** 2)
        bot_sh = 0.0
        if y > BASE_Y - 0.16:
            bot_sh = 0.14 * smoothstep(BASE_Y - 0.16, BASE_Y - 0.01, y)

        # ---- per-row steam curl -----------------------------------------
        st_on = -0.95 < y < 0.14
        st_xc = 0.0
        st_nrm = 1.0
        st_w = 0.01
        st_env = 0.0
        if st_on:
            t = (STEAM_Y0 - y) / (STEAM_Y0 - STEAM_Y1)
            if 0.0 <= t <= 1.0:
                u = (t - 0.40) / 0.60
                if u < 0.0:
                    u = 0.0
                elif u > 1.0:
                    u = 1.0
                sw = 8.1681 * t                      # 2*pi*1.3
                st_xc = -0.465 + 0.300 * u * u + 0.018 * sin(sw)
                dxdt = u + 0.1470 * cos(sw)
                slope = dxdt / (STEAM_Y0 - STEAM_Y1)
                st_nrm = 1.0 / sqrt(1.0 + slope * slope)
                st_w = 0.0150 * (1.0 - 0.55 * t)
                st_env = 0.74 * smoothstep(0.0, 0.20, t) * \
                    (1.0 - smoothstep(0.76, 1.0, t))
                if st_env < 0.004:
                    st_on = False
            else:
                st_on = False

        row = bytearray(W * 3)
        p = 0

        for i in range(W):
            x = (i + 0.5) * INV - 1.0

            # ---------------- warm cream background + soft glow --------
            r2 = x * x + y * y
            gl = exp(-r2 * 1.55)
            cr = 0.9640 + 0.0300 * gl
            cg = 0.9200 + 0.0320 * gl
            cb = 0.8560 + 0.0400 * gl
            vg = 0.032 * smoothstep(0.55, 1.30, sqrt(r2))
            cr -= vg
            cg -= vg * 0.94
            cb -= vg * 0.86

            # ---------------- saucer -----------------------------------
            if y > 0.66 and -0.90 < x < 0.90:
                d = ell(SHADOW, x, y, sqrt)
                if d < 0.30:
                    a = 0.17 * (1.0 - smoothstep(-0.14, 0.26, d))
                    cr += (0.796 - cr) * a
                    cg += (0.742 - cg) * a
                    cb += (0.672 - cb) * a

                d = ell(SAUCER_EDGE, x, y, sqrt)
                if d < 0.02:
                    cov = 1.0 - smoothstep(-AA, AA, d)
                    cr += (0.792 - cr) * cov
                    cg += (0.878 - cg) * cov
                    cb += (0.850 - cb) * cov

                d = ell(SAUCER, x, y, sqrt)
                if d < 0.02:
                    cov = 1.0 - smoothstep(-AA, AA, d)
                    # shallow well in the middle
                    d2 = ell(WELL, x, y, sqrt)
                    wl = 1.0 - smoothstep(-0.030, 0.030, d2)
                    sr = 0.844 - 0.058 * wl
                    sg = 0.918 - 0.050 * wl
                    sb = 0.882 - 0.054 * wl
                    # darker outer edge -> saucer thickness
                    ed = smoothstep(-0.060, 0.000, d)
                    sr -= 0.072 * ed
                    sg -= 0.064 * ed
                    sb -= 0.058 * ed
                    cr += (sr - cr) * cov
                    cg += (sg - cg) * cov
                    cb += (sb - cb) * cov

            # ---------------- cup handle (right, behind the wall) ------
            if 0.14 < y < 0.66 and x > 0.44:
                d = ell(HANDLE_O, x, y, sqrt)
                if d < 0.03:
                    di = ell(HANDLE_I, x, y, sqrt)
                    dd = d if d > -di else -di
                    cov = 1.0 - smoothstep(-AA, AA, dd)
                    if cov > 0.002:
                        f = 1.0
                        f -= 0.16 * smoothstep(0.30, 0.72, y)
                        f -= 0.13 * smoothstep(0.58, 0.84, x)
                        f -= 0.10 * (1.0 - smoothstep(0.475, 0.560, x))
                        f += 0.05 * exp(-((y - 0.290) / 0.150) ** 2) * \
                            exp(-((x - 0.560) / 0.120) ** 2)
                        hr = 0.618 * f
                        hg = 0.858 * f
                        hb = 0.762 * f
                        cr += (hr - cr) * cov
                        cg += (hg - cg) * cov
                        cb += (hb - cb) * cov

            # ---------------- inside of the cup ------------------------
            if y < RIM_Y + RIM_RY + 0.01 and -0.63 < x < 0.63:
                d = ell(INNER, x, y, sqrt)
                if d < 0.01:
                    cov = 1.0 - smoothstep(-AA, AA, d)
                    k = smoothstep(RIM_Y - RIM_RY, RIM_Y + RIM_RY, y)
                    ir = 0.404 + 0.030 * k
                    ig = 0.612 + 0.034 * k
                    ib = 0.548 + 0.030 * k
                    cr += (ir - cr) * cov
                    cg += (ig - cg) * cov
                    cb += (ib - cb) * cov

            # ---------------- contact shadow on the saucer -------------
            if 0.70 < y < 0.92 and -0.52 < x < 0.52:
                d = ell(FOOT_SH, x, y, sqrt)
                if d < 0.06:
                    a = 0.34 * (1.0 - smoothstep(-0.020, 0.055, d))
                    if a > 0.002:
                        cr += (0.452 - cr) * a
                        cg += (0.628 - cg) * a
                        cb += (0.542 - cb) * a

            # ---------------- cup wall ---------------------------------
            if body_on and -hw - 0.02 < x < hw + 0.02:
                e = x - hw
                cov = 1.0 - smoothstep(-AA, AA, e)
                cov *= smoothstep(RIM_Y - AA, RIM_Y + AA, y)
                if cov > 0.002:
                    f = 1.0
                    f -= rim_sh                                  # cast by rim
                    f -= 0.13 * smoothstep(0.02, 0.52, x)        # right shade
                    f -= 0.11 * (1.0 - smoothstep(-0.075, 0.0, e))
                    f -= 0.11 * (1.0 - smoothstep(-0.075, 0.0, -hw - x))
                    f += 0.075 * exp(-((x + 0.210) / 0.230) ** 2) * \
                        (1.0 - smoothstep(0.18, 0.62, y))
                    f -= bot_sh
                    mr = 0.618 * f
                    mg = 0.858 * f
                    mb = 0.762 * f
                    cr += (mr - cr) * cov
                    cg += (mg - cg) * cov
                    cb += (mb - cb) * cov

            # ---------------- little heart on the cup ------------------
            if -0.36 < x < -0.13 and 0.30 < y < 0.58:
                d = heart_sd(x, y, HEART_X, HEART_Y, HEART_S)
                if d < 0.02:
                    cov = 1.0 - smoothstep(-AA, AA * 2.0, d)
                    f = 1.0 - 0.055 * smoothstep(-0.05, 0.06, y - HEART_Y)
                    cr += (0.964 * f - cr) * cov
                    cg += (0.688 * f - cg) * cov
                    cb += (0.724 * f - cb) * cov

            # ---------------- gold rim (whole ellipse) -----------------
            if y < RIM_Y + RIM_RY + 0.02 and -0.63 < x < 0.63:
                d = ell(RIM, x, y, sqrt)
                if -0.02 < d < 0.02:
                    band = d if d > 0.0 else -d
                    cov = 1.0 - smoothstep(0.0040, 0.0072, band)
                    if cov > 0.002:
                        cr += (0.876 - cr) * cov
                        cg += (0.734 - cg) * cov
                        cb += (0.436 - cb) * cov

            # ---------------- kitten: head + ears ----------------------
            if -0.52 < y < 0.20 and -0.40 < x < 0.40:
                ax = x if x > 0.0 else -x
                d = ell(HEAD, x, y, sqrt)
                de_e = 1e3
                if -0.51 < y < -0.18 and 0.02 < ax < 0.40:
                    de_e = tri_sd(ax, y, EAR_A[0], EAR_A[1], EAR_B[0], EAR_B[1],
                                  EAR_C[0], EAR_C[1]) - EAR_R
                    if de_e < d:
                        d = smin(d, de_e, 0.045)
                cov = 1.0 - smoothstep(-AA, AA, d)
                if cov > 0.002:
                    # soft contact shadow where the fur meets the cup interior
                    if 0.0 < d < 0.040 and y < RIM_Y + 0.01:
                        a = 0.30 * (1.0 - smoothstep(0.0, 0.040, d))
                        a *= 1.0 - smoothstep(RIM_Y - 0.09, RIM_Y + 0.01, y)
                        if a > 0.002:
                            cr += (0.330 - cr) * a
                            cg += (0.500 - cg) * a
                            cb += (0.450 - cb) * a
                    cov *= 1.0 - smoothstep(RIM_Y + 0.020, RIM_Y + 0.095, y)
                    sh = 0.060 * smoothstep(-0.030, 0.150, y)      # under chin
                    sh += 0.040 * smoothstep(0.130, 0.330, x)      # right side
                    sh -= 0.020 * exp(-((y + 0.190) / 0.190) ** 2) * \
                        exp(-((x - 0.010) / 0.230) ** 2)           # forehead
                    f = 1.0 - sh
                    cr += (0.992 * f - cr) * cov
                    cg += (0.955 * f - cg) * cov
                    cb += (0.884 * f - cb) * cov

                    # inner ear, soft blush
                    if -0.44 < y < -0.20 and 0.08 < ax < 0.33:
                        de = tri_sd(ax, y, IN_A[0], IN_A[1], IN_B[0], IN_B[1],
                                    IN_C[0], IN_C[1]) - IN_R
                        if de < 0.03:
                            cv = 1.0 - smoothstep(-0.010, 0.012, de)
                            cv *= cov * 0.62
                            cv *= 1.0 - smoothstep(-0.004, 0.004, de_e)
                            cr += (0.962 - cr) * cv
                            cg += (0.706 - cg) * cv
                            cb += (0.742 - cb) * cv

            # ---------------- face -------------------------------------
            if -0.20 < y < 0.06 and -0.32 < x < 0.32:
                dh = ell(HEAD, x, y, sqrt)
                if dh < 0.0:
                    ax = x if x > 0.0 else -x
                    # closed eye: a gentle arc bowing upwards
                    u = (ax - EYE_X) / EYE_HW
                    if -1.10 < u < 1.10:
                        uu = u if u < 1.0 else 1.0
                        uu = uu if uu > -1.0 else -1.0
                        ya = EYE_Y - EYE_BOW * (1.0 - uu * uu)
                        sl = 2.0 * EYE_BOW * uu / EYE_HW
                        dd = fabs(y - ya) / sqrt(1.0 + sl * sl)
                        if dd < 0.020:
                            a = 1.0 - smoothstep(0.0052, 0.0128, dd)
                            a *= 1.0 - smoothstep(0.72, 1.02, fabs(u))
                            a *= 0.94
                            cr += (0.452 - cr) * a
                            cg += (0.372 - cg) * a
                            cb += (0.336 - cb) * a

                    # tiny nose (rounded triangle pointing down)
                    if -0.075 < x < 0.075 and -0.07 < y < 0.0:
                        dn = tri_sd(x, y, 0.0, NOSEY - 0.018,
                                    0.021, NOSEY + 0.010,
                                    -0.021, NOSEY + 0.010) - 0.007
                        if dn < 0.02:
                            a = 1.0 - smoothstep(-0.006, 0.009, dn)
                            if a > 0.004:
                                cr += (0.938 - cr) * a
                                cg += (0.605 - cg) * a
                                cb += (0.652 - cb) * a

                    # small "w" mouth, very soft, symmetric
                    if ax < 0.030 and 0.000 < y < 0.045:
                        u = ax / 0.026
                        if u < 1.02:
                            ym = 0.021 - 0.007 * cos(pi * u * 2.0)
                            sl = 0.007 * 2.0 * pi / 0.026 * sin(pi * u * 2.0)
                            dd = fabs(y - ym) / sqrt(1.0 + sl * sl)
                            a = (1.0 - smoothstep(0.0038, 0.0092, dd)) * 0.50
                            a *= 1.0 - smoothstep(0.80, 1.02, u)
                            if a > 0.003:
                                cr += (0.585 - cr) * a
                                cg += (0.470 - cg) * a
                                cb += (0.428 - cb) * a

                    # blush cheek
                    dc = ell(CHEEK, ax, y, sqrt)
                    if dc < 0.06:
                        a = 0.44 * (1.0 - smoothstep(-0.030, 0.030, dc))
                        if a > 0.002:
                            cr += (0.968 - cr) * a
                            cg += (0.686 - cg) * a
                            cb += (0.726 - cb) * a

            # ---------------- gold rim, front half (over the kitten) ---
            if RIM_Y - 0.01 < y < RIM_Y + RIM_RY + 0.02 and -0.63 < x < 0.63:
                d = ell(RIM, x, y, sqrt)
                if -0.02 < d < 0.02:
                    band = d if d > 0.0 else -d
                    cov = 1.0 - smoothstep(0.0040, 0.0072, band)
                    cov *= smoothstep(RIM_Y - 0.004, RIM_Y + 0.004, y)
                    if cov > 0.002:
                        cr += (0.876 - cr) * cov
                        cg += (0.734 - cg) * cov
                        cb += (0.436 - cb) * cov

            # ---------------- paw over the rim -------------------------
            if 0.16 < x < 0.48 and -0.06 < y < 0.30:
                d = ell(PAW, x, y, sqrt)
                if d < 0.042:
                    a = 0.13 * (1.0 - smoothstep(-0.030, 0.040, d))
                    if a > 0.002:
                        cr += (0.762 - cr) * a
                        cg += (0.688 - cg) * a
                        cb += (0.628 - cb) * a
                if d < 0.02:
                    cov = 1.0 - smoothstep(-AA, AA, d)
                    f = 1.0 - 0.085 * smoothstep(0.02, 0.22, y)
                    f -= 0.055 * smoothstep(0.34, 0.46, x)
                    f += 0.025 * exp(-((x - 0.278) / 0.075) ** 2) * \
                        (1.0 - smoothstep(-0.01, 0.07, y))
                    pr = 0.992 * f
                    pg = 0.955 * f
                    pb = 0.884 * f
                    cr += (pr - cr) * cov
                    cg += (pg - cg) * cov
                    cb += (pb - cb) * cov

                    # three soft toe creases + a light shadow under the paw
                    if 0.140 < y < 0.250 and cov > 0.4:
                        for xt in (0.258, 0.322, 0.386):
                            dx = x - xt
                            if -0.013 < dx < 0.013:
                                a = 1.0 - smoothstep(0.0030, 0.0098,
                                                     dx if dx > 0 else -dx)
                                a *= smoothstep(0.140, 0.170, y) * \
                                    (1.0 - smoothstep(0.210, 0.245, y))
                                a *= 0.85
                                if a > 0.002:
                                    cr -= 0.110 * a
                                    cg -= 0.126 * a
                                    cb -= 0.134 * a

            # ---------------- one thin curl of steam -------------------
            if st_on:
                d = (x - st_xc) * st_nrm
                if d < 0.0:
                    d = -d
                if d < st_w * 3.2:
                    a = (1.0 - smoothstep(0.0, st_w, d)) * 0.94
                    a += 0.20 * (1.0 - smoothstep(st_w, st_w * 3.0, d))
                    a *= st_env
                    if a > 0.004:
                        cr += (0.991 - cr) * a
                        cg += (0.986 - cg) * a
                        cb += (0.973 - cb) * a

            # ---------------- write ------------------------------------
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
            row[p] = rv
            row[p + 1] = gv
            row[p + 2] = bv
            p += 3

        rows.append(b"\x00" + bytes(row))

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