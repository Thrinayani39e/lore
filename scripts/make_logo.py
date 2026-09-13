"""Generates Lore's icon locally with Pillow — a small knowledge-graph motif
(connected nodes, one glowing brighter as the "active memory") on the same
dark navy / indigo palette as the dashboard. Produces:
  - assets/logo-512.png  (Slack app icon)
  - assets/favicon-64.png (dashboard favicon / header)
"""
from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw, ImageFilter

BG = (11, 13, 18, 255)  # matches dashboard --bg
ACCENT = (124, 158, 255, 255)  # matches dashboard --accent
ACCENT_DIM = (60, 80, 140, 255)
LINE = (90, 110, 160, 200)

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")
os.makedirs(OUT_DIR, exist_ok=True)


def draw_icon(size: int) -> Image.Image:
    scale = 4  # supersample for smooth edges, then downscale
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded-square background
    radius = int(s * 0.22)
    draw.rounded_rectangle([0, 0, s, s], radius=radius, fill=BG)

    cx, cy = s / 2, s / 2
    r = s * 0.30  # ring radius for outer nodes

    # 6 nodes arranged in a hexagon + 1 center node — a small hub-and-spoke
    # knowledge graph (deliberately NOT 5 points, which reads as a pentagram)
    angles = [i * (360 / 6) - 90 for i in range(6)]
    outer_points = [
        (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
        for a in angles
    ]
    center = (cx, cy)

    # spokes only (center to each outer node) plus the hexagon ring connecting
    # adjacent outer nodes — reads as a network/hub, not a star
    for p in outer_points:
        draw.line([center, p], fill=LINE, width=max(2, s // 100))
    for i in range(len(outer_points)):
        p1 = outer_points[i]
        p2 = outer_points[(i + 1) % len(outer_points)]
        draw.line([p1, p2], fill=(*LINE[:3], 110), width=max(1, s // 160))

    # glow layer behind nodes
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    node_r = s * 0.045
    glow_draw.ellipse(
        [center[0] - node_r * 2.2, center[1] - node_r * 2.2, center[0] + node_r * 2.2, center[1] + node_r * 2.2],
        fill=(*ACCENT[:3], 160),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=s * 0.03))
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img)

    # outer nodes (dim)
    outer_r = s * 0.032
    for p in outer_points:
        draw.ellipse(
            [p[0] - outer_r, p[1] - outer_r, p[0] + outer_r, p[1] + outer_r],
            fill=ACCENT_DIM,
        )

    # center node (bright — the "active memory")
    draw.ellipse(
        [center[0] - node_r, center[1] - node_r, center[0] + node_r, center[1] + node_r],
        fill=ACCENT,
    )

    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    icon_512 = draw_icon(512)
    icon_512.save(os.path.join(OUT_DIR, "logo-512.png"))

    icon_64 = draw_icon(64)
    icon_64.save(os.path.join(OUT_DIR, "favicon-64.png"))

    print("Wrote", os.path.join(OUT_DIR, "logo-512.png"))
    print("Wrote", os.path.join(OUT_DIR, "favicon-64.png"))
