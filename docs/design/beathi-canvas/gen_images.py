"""Deterministic artwork generator for the Beathi Canvas design references.

Pure math: fixed integer-hash value noise, no `random`, no wall-clock input.
Outputs four PNG assets used by frame-a/b/c.html:

  fog-ridge.png   960x540  layered fog ridges, cool duotone (photo A)
  fog-bright.png  960x540  low-sun variant, warmer            (photo B)
  paper-fiber.png 512x512  warm paper with fiber grain        (texture)
  halftone.png    512x512  ink dot field on transparency      (print overlay)

Everything lands in build/beathi-references/ (outside Git).
"""
from __future__ import annotations

import numpy as np
from PIL import Image
from pathlib import Path

OUT = Path(__file__).resolve().parent


def _hash01(v: np.ndarray, seed: float) -> np.ndarray:
    return np.modf(np.sin(v * 127.1 + seed * 311.7) * 43758.5453)[0] * 0.5 + 0.5


def vnoise2(x: np.ndarray, y: np.ndarray, seed: float) -> np.ndarray:
    xi, yi = np.floor(x), np.floor(y)
    xf, yf = x - xi, y - yi
    u = xf * xf * (3 - 2 * xf)
    v = yf * yf * (3 - 2 * yf)
    base = xi * 157.31 + yi * 113.97 + seed * 271.3
    n00 = _hash01(base, 1.0)
    n10 = _hash01(base + 157.31, 1.0)
    n01 = _hash01(base + 113.97, 1.0)
    n11 = _hash01(base + 271.28, 1.0)
    top = n00 + (n10 - n00) * u
    bottom = n01 + (n11 - n01) * u
    return top + (bottom - top) * v


def fbm2(x: np.ndarray, y: np.ndarray, seed: float, octaves: int = 4) -> np.ndarray:
    total = np.zeros_like(x)
    amp, freq, norm = 1.0, 1.0, 0.0
    for o in range(octaves):
        total += amp * vnoise2(x * freq, y * freq, seed + o * 13.7)
        norm += amp
        amp *= 0.5
        freq *= 2.03
    return total / norm


def _grain(img: np.ndarray, strength: float, seed: float) -> np.ndarray:
    h, w = img.shape[:2]
    g = _hash01(np.arange(h * w, dtype=np.float64), seed).reshape(h, w) - 0.5
    return img + g[..., None] * strength


def _vignette(img: np.ndarray, amount: float) -> np.ndarray:
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    nx = (xx / w - 0.5) * 2
    ny = (yy / h - 0.5) * 2
    d = np.sqrt(nx * nx + ny * ny) / 1.414
    m = 1.0 - amount * np.clip(d, 0, 1) ** 2
    return img * m[..., None]


def _save(name: str, arr: np.ndarray) -> None:
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    Image.fromarray(arr).save(OUT / name, optimize=True)
    print("wrote", name, arr.shape)


def fog_ridge(name: str, seed: float, sun: bool) -> None:
    w, h = 960, 540
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    t = yy / h

    # sky: pale cool gray, slightly warmer toward the horizon
    top = np.array([210.0, 209.0, 205.0])
    horizon = np.array([176.0, 182.0, 186.0])
    sky = top[None, None, :] * (1 - t[..., None]) + horizon[None, None, :] * t[..., None]
    if sun:
        cx, cy, r = w * 0.64, h * 0.34, 240.0
        glow = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (r * r)))
        sky = sky + glow[..., None] * np.array([52.0, 44.0, 30.0])
    bands = (fbm2(xx * 0.006, yy * 0.02, seed + 5.0) - 0.5) * 14.0
    img = sky + bands[..., None] * np.array([1.0, 1.0, 0.98])

    # four ridge layers, far -> near, haze blended toward fog color
    fog = np.array([199.0, 202.0, 204.0])
    ridges = [
        (268.0, 34.0, 0.0060, (156.0, 162.0, 170.0), 0.58),
        (326.0, 58.0, 0.0042, (118.0, 124.0, 134.0), 0.40),
        (392.0, 86.0, 0.0030, (76.0, 81.0, 91.0), 0.22),
        (468.0, 118.0, 0.0021, (39.0, 43.0, 51.0), 0.08),
    ]
    for i, (base, amp, freq, col, haze) in enumerate(ridges):
        n = fbm2(xx * freq, np.full_like(xx, 7.7), seed + 31.0 * (i + 1), octaves=4)
        ridge_y = base - (n - 0.5) * 2.0 * amp
        mask = (yy >= ridge_y).astype(np.float64)
        soft = np.clip((yy - ridge_y) / 40.0, 0, 1)  # fog softening at the crest
        mask = mask * (0.55 + 0.45 * soft)
        layer = np.array(col)[None, None, :] * np.ones((h, w, 3))
        layer = layer * (1 - haze) + fog[None, None, :] * haze
        img = img * (1 - mask[..., None]) + layer * mask[..., None]

    img = _grain(img, 7.0, seed + 91.0)
    img = _vignette(img, 0.20)
    _save(name, img)


def paper_fiber() -> None:
    n = 512
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float64)
    base = np.array([244.5, 241.5, 233.5])
    lum = (fbm2(xx * 0.014, yy * 0.014, 11.0) - 0.5) * 7.0
    lum += (fbm2(xx * 0.42, yy * 0.055, 23.0) - 0.5) * 5.5  # horizontal fiber streaks
    blotch = (fbm2(xx * 0.008, yy * 0.008, 37.0) > 0.63) * -3.5
    lum = lum + blotch
    g = (_hash01(np.arange(n * n, dtype=np.float64), 3.0).reshape(n, n) - 0.5) * 3.0
    img = base[None, None, :] + (lum + g)[..., None]
    _save("paper-fiber.png", img)


def halftone() -> None:
    n = 512
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float64)
    field = fbm2(xx * 0.012, yy * 0.012, 61.0, octaves=3)
    cell = 8.0
    cx = (np.floor(xx / cell) + 0.5) * cell
    cy = (np.floor(yy / cell) + 0.5) * cell
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    r = np.clip(0.7 + 3.4 * field, 0.25, 4.3)
    alpha = np.clip(r - dist + 0.5, 0.0, 1.0) * 235.0
    ink = np.array([23.0, 23.0, 26.0])
    img = np.zeros((n, n, 4))
    img[..., 0], img[..., 1], img[..., 2] = ink
    img[..., 3] = alpha
    _save("halftone.png", img)


if __name__ == "__main__":
    fog_ridge("fog-ridge.png", 7.0, sun=False)
    fog_ridge("fog-bright.png", 19.0, sun=True)
    paper_fiber()
    halftone()
