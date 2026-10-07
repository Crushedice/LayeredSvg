#!/usr/bin/env python3
"""Build the layered 2.5D eye from the painted source frames.

Reads assets-src/nix-eye/*.png and writes, into prototype/nix-eye/layers/:

  base.webp        full canvas, iris painted out (sclera only)
  iris.webp        iris with the pupil slit inpainted away
  pupil.webp       pupil slit + rim, same box as iris.webp (scaled for affect)
  glow.webp        orange circuit lines on transparency
  marks.webp       every warm face marking (lines, slashes) copied from the
                   base, hue-shifted per affect in CSS
  blink-NN.webp    eye-region patch per blink frame, eye opening cut out so
                   the live iris keeps showing (and moving) through a blink
  blink-NN-marks.webp  that frame's own markings (the slashes ride on the lid)
  sclera.svg       clip path of the eye opening, in canvas coordinates
  layers.css       per-layer box positions as % of the canvas
  layers.json      the same boxes + frame list, for other front-ends

Requires: pip install opencv-python-headless numpy pillow
"""
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets-src" / "nix-eye"
OUT = ROOT / "prototype" / "nix-eye" / "layers"

W, H = 1516, 1037  # canvas of base.png; other frames are cropped/scaled to it
BLINK_FRAMES = ["02", "03", "04", "05", "06", "07", "08", "09-closed"]
WEBP_Q = 88


def load(name, flags=cv2.IMREAD_COLOR):
    img = cv2.imread(str(SRC / name), flags)
    if img is None:
        raise SystemExit(f"missing {SRC / name}")
    h, w = img.shape[:2]
    if (w, h) == (W, H):
        return img
    if abs(w - W) <= 2 and abs(h - H) <= 2:  # off-by-one exports: crop
        return img[:H, :W]
    return cv2.resize(img, (W, H), interpolation=cv2.INTER_LANCZOS4)


def hsv_split(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(int)
    return hsv[..., 0], hsv[..., 1], hsv[..., 2]


def ellipse(k):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))


def largest_component(mask):
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask)
    if n < 2:
        raise SystemExit("mask is empty")
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    return (lab == i).astype(np.uint8) * 255


def fill_holes(mask):
    cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    out = np.zeros_like(mask)
    cv2.drawContours(out, cs, -1, 255, -1)
    return out


def bbox(mask, pad=0):
    ys, xs = np.where(mask > 0)
    x0, y0 = max(int(xs.min()) - pad, 0), max(int(ys.min()) - pad, 0)
    x1, y1 = min(int(xs.max()) + pad + 1, W), min(int(ys.max()) + pad + 1, H)
    return x0, y0, x1 - x0, y1 - y0


def save_webp(bgra, path):
    rgba = cv2.cvtColor(bgra, cv2.COLOR_BGRA2RGBA)
    Image.fromarray(rgba).save(path, "WEBP", quality=WEBP_Q, method=6)


def eye_window(mask, y0=250, y1=850, x0=300, x1=1150):
    m = mask.copy()
    m[:y0], m[y1:], m[:, :x0], m[:, x1:] = 0, 0, 0, 0
    return m


def sclera_mask(base):
    """Pale blue-grey sclera, including the lid-shadowed upper band."""
    h, s, v = hsv_split(base)
    m = ((v > 85) & (s < 120) & (h > 95) & (h < 140)).astype(np.uint8) * 255
    m = largest_component(eye_window(m))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, ellipse(21))
    return fill_holes(m)


def opening_mask(frame, sclera):
    """Visible eye opening (sclera + iris) of a blink frame, within the open-eye sclera."""
    h, s, v = hsv_split(frame)
    pale = (v > 85) & (s < 120) & (h > 95) & (h < 140)
    warm = (v > 110) & (s > 110) & ((h < 35) | (h > 165))
    m = ((pale | warm) & (sclera > 0)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, ellipse(7))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    keep = np.zeros_like(m)
    for j in range(1, n):
        if st[j, cv2.CC_STAT_AREA] > 800:
            keep[lab == j] = 255
    keep = cv2.morphologyEx(keep, cv2.MORPH_CLOSE, ellipse(15))
    return fill_holes(keep) & sclera


def blink_region(base, frames):
    """Everything the lids touch across the blink, as a soft-edged patch mask."""
    b = base.astype(np.float32)
    d = np.zeros((H, W), np.float32)
    for f in frames:
        d = np.maximum(d, np.abs(f.astype(np.float32) - b).mean(2))
    d = cv2.GaussianBlur(d, (0, 0), 6)
    m = (d > 25).astype(np.uint8) * 255
    m = largest_component(eye_window(m, 200, 880, 250, 1200))
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    hull = np.zeros_like(m)
    cv2.fillPoly(hull, [cv2.convexHull(cs[0])], 255)
    return cv2.dilate(hull, ellipse(41))


def split_pupil(iris_bgra, box):
    """Return (iris without pupil, pupil-only) crops of the iris layer."""
    x, y, w, h = box
    c = iris_bgra[y:y + h, x:x + w].copy()
    _, _, v = hsv_split(c[..., :3])
    dark = ((v < 70) & (c[..., 3] > 200)).astype(np.uint8) * 255
    mid = w // 2  # the slit sits in the middle third
    dark[:, : mid - w // 6], dark[:, mid + w // 6:] = 0, 0
    core = largest_component(dark)
    core = cv2.morphologyEx(core, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 25)))
    cs, _ = cv2.findContours(core, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    core = np.zeros_like(core)
    cv2.fillPoly(core, [cv2.convexHull(cs[0])], 255)
    pm = cv2.dilate(core, ellipse(17))  # include the yellow rim
    body = c.copy()
    body[..., :3] = cv2.inpaint(c[..., :3], cv2.dilate(pm, np.ones((5, 5), np.uint8)), 15, cv2.INPAINT_TELEA)
    pupil = c.copy()
    pupil[..., 3] = np.minimum(c[..., 3], cv2.GaussianBlur(pm, (0, 0), 1.5))
    px, _, pw, _ = cv2.boundingRect(core)
    return body, pupil, (px + pw / 2) / w  # pupil centre as fraction of box width


def marks_alpha(bgr, eye_zone):
    """Soft alpha of the saturated warm face markings plus their glow halo.

    Shapes touching eye_zone (lower lid rim, outer-corner triangle) belong to the
    eye, not the markings, and are dropped whole so none is left half-recoloured.
    """
    h, s, v = hsv_split(bgr)
    s, v = s / 255, v / 255
    warm = ((h < 28) | (h > 165)).astype(np.float32)
    core = np.clip((s - .35) / .35, 0, 1) * np.clip((v - .25) / .35, 0, 1) * warm
    core[:, :120] = 0  # ear piece on the far left is not a marking
    n, lab, _, _ = cv2.connectedComponentsWithStats((core > .1).astype(np.uint8))
    touching = list(set(np.unique(lab[eye_zone > 0])) - {0})
    core[cv2.dilate(np.isin(lab, touching).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0] = 0
    loose = np.clip((s - .15) / .3, 0, 1) * np.clip((v - .1) / .25, 0, 1) * warm
    halo = np.minimum(cv2.GaussianBlur(core, (0, 0), 5) * 3, loose)
    return np.maximum(core, halo)


def mask_to_path(mask):
    cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cs, key=cv2.contourArea)
    c = cv2.approxPolyDP(c, 1.0, True)[:, 0, :]
    return "M" + " L".join(f"{x},{y}" for x, y in c) + " Z"


def pct(box):
    x, y, w, h = box
    return {"left": 100 * x / W, "top": 100 * y / H, "width": 100 * w / W, "height": 100 * h / H}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    base = load("base.png")
    sclera = sclera_mask(base)
    frames = {n: load(f"blink-{n}.png") for n in BLINK_FRAMES}
    layers = {}

    # base
    save_webp(cv2.cvtColor(base, cv2.COLOR_BGR2BGRA), OUT / "base.webp")
    layers["base"] = pct((0, 0, W, H))

    # sclera clip
    (OUT / "sclera.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" preserveAspectRatio="none">'
        f'<path d="{mask_to_path(sclera)}" fill="#fff"/></svg>\n'
    )
    layers["sclera"] = pct(bbox(sclera))

    # iris + pupil
    iris = load("iris.png", cv2.IMREAD_UNCHANGED)
    ibox = bbox((iris[..., 3] > 128).astype(np.uint8), pad=4)
    body, pupil, pupil_cx = split_pupil(iris, ibox)
    save_webp(body, OUT / "iris.webp")
    save_webp(pupil, OUT / "pupil.webp")
    layers["iris"] = pct(ibox)

    # glow lines
    glow = load("glow.png", cv2.IMREAD_UNCHANGED)
    gbox = bbox((glow[..., 3] > 0).astype(np.uint8))
    gx, gy, gw, gh = gbox
    save_webp(glow[gy:gy + gh, gx:gx + gw], OUT / "glow.webp")
    layers["glow"] = pct(gbox)

    # face markings. The lower half of the eye never moves during a blink, so warm shapes
    # touching it (lid rim, corner triangle) are the eye's own colour in every frame.
    ys = np.where(sclera.any(axis=1))[0]
    eye_zone = sclera.copy()
    eye_zone[: (ys.min() + ys.max()) // 2] = 0
    eye_zone = cv2.dilate(eye_zone, np.ones((21, 21), np.uint8))
    ma = marks_alpha(base, eye_zone)
    mbox = bbox((ma > .02).astype(np.uint8))
    mx, my, mw, mh = mbox
    save_webp(np.dstack([base, (ma * 255).astype(np.uint8)])[my:my + mh, mx:mx + mw], OUT / "marks.webp")
    layers["marks"] = pct(mbox)

    # blink patches
    region = blink_region(base, frames.values())
    rbox = bbox(region)
    rx, ry, rw, rh = rbox
    soft_region = cv2.GaussianBlur(region, (0, 0), 12).astype(np.float32) / 255
    names = []
    for n, f in frames.items():
        hole = opening_mask(f, sclera)
        hole = cv2.GaussianBlur(cv2.dilate(hole, ellipse(3)), (0, 0), 1.2).astype(np.float32) / 255
        alpha = (soft_region * (1 - hole) * 255).clip(0, 255).astype(np.uint8)
        patch = np.dstack([f, alpha])[ry:ry + rh, rx:rx + rw]
        name = f"blink-{n.split('-')[0]}"
        save_webp(patch, OUT / f"{name}.webp")
        fa = (marks_alpha(f, eye_zone) * alpha).clip(0, 255).astype(np.uint8)
        save_webp(np.dstack([f, fa])[ry:ry + rh, rx:rx + rw], OUT / f"{name}-marks.webp")
        names.append(name)
    layers["blink"] = pct(rbox)

    css = ["/* generated by tools/build_eye_layers.py — do not edit */"]
    for k, b in layers.items():
        css.append(
            f".nix-eye .l-{k}{{left:{b['left']:.4f}%;top:{b['top']:.4f}%;"
            f"width:{b['width']:.4f}%;height:{b['height']:.4f}%}}"
        )
    css.append(f".nix-eye{{--pupil-origin:{100 * pupil_cx:.2f}%;aspect-ratio:{W}/{H}}}")
    (OUT / "layers.css").write_text("\n".join(css) + "\n")
    (OUT / "layers.json").write_text(json.dumps(
        {"canvas": [W, H], "boxes": layers, "pupilOriginX": pupil_cx, "blinkFrames": names}, indent=2) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
