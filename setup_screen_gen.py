#!/usr/bin/env python3
"""Generate the factory-reset setup instruction screen PNG."""
from PIL import Image, ImageDraw, ImageFont
import os

W, H = 1920, 1080
BG      = (13,  17,  23)   # #0d1117
ACCENT  = (88,  166, 255)  # #58a6ff blue
GREEN   = (63,  185, 80)   # #3fb950
MUTED   = (139, 148, 158)  # #8b949e
WHITE   = (230, 237, 243)  # #e6edf3
YELLOW  = (210, 153, 34)   # #d29922

img  = Image.new('RGB', (W, H), BG)
draw = ImageDraw.Draw(img)

# Try to load system fonts; fall back gracefully
def load_font(size, bold=False):
    candidates = [
        f'/usr/share/fonts/truetype/dejavu/DejaVuSans{"-Bold" if bold else ""}.ttf',
        f'/usr/share/fonts/truetype/liberation/LiberationSans{"-Bold" if bold else "-Regular"}.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf' if bold else '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
    ]
    for p in candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

font_big    = load_font(72, bold=True)
font_title  = load_font(48, bold=True)
font_step   = load_font(38, bold=True)
font_body   = load_font(34)
font_value  = load_font(42, bold=True)
font_small  = load_font(26)
font_tiny   = load_font(22)

cx = W // 2

def text_c(y, txt, font, color=WHITE):
    """Draw centered text."""
    bbox = draw.textbbox((0, 0), txt, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) // 2, y), txt, font=font, fill=color)

def text_l(x, y, txt, font, color=WHITE):
    draw.text((x, y), txt, font=font, fill=color)

# ── Top bar ──────────────────────────────────────────────────────────────────
draw.rectangle([(0, 0), (W, 8)], fill=ACCENT)
draw.rectangle([(0, H - 8), (W, H)], fill=ACCENT)

# ── Company name ─────────────────────────────────────────────────────────────
text_c(38,  "JJ Smart Solutions", font_title, ACCENT)
text_c(102, "VideoWall  —  Initial Setup Guide", font_step, MUTED)

# ── Divider ───────────────────────────────────────────────────────────────────
draw.rectangle([(cx - 420, 160), (cx + 420, 163)], fill=(48, 54, 61))

# ── Steps (two-column layout) ────────────────────────────────────────────────
COL_L = 200
COL_R = 1020
Y0    = 200
GAP   = 200

# Step 1
circle_r = 28
def circle(x, y, num, color):
    draw.ellipse([(x - circle_r, y - circle_r), (x + circle_r, y + circle_r)], fill=color)
    bbox = draw.textbbox((0, 0), str(num), font=font_step)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    draw.text((x - tw//2, y - th//2 - 2), str(num), font=font_step, fill=BG)

# ─ Step 1 ────────────────────────────────────────────────────────────────────
circle(COL_L, Y0 + 24, 1, ACCENT)
text_l(COL_L + 50, Y0,      "Connect your phone to WiFi:", font_step,  MUTED)
text_l(COL_L + 50, Y0 + 48, "Network:", font_body, MUTED)
text_l(COL_L + 200, Y0 + 44, "VideoWall-Setup", font_value, WHITE)
text_l(COL_L + 50, Y0 + 98, "Password:", font_body, MUTED)
text_l(COL_L + 230, Y0 + 94, "jjsmart123", font_value, GREEN)

# ─ Step 2 ────────────────────────────────────────────────────────────────────
Y1 = Y0 + GAP + 20
circle(COL_L, Y1 + 24, 2, ACCENT)
text_l(COL_L + 50, Y1,      "Open your browser and go to:", font_step, MUTED)
text_l(COL_L + 50, Y1 + 50, "http://10.42.0.1", font_value, ACCENT)

# ─ Step 3 ────────────────────────────────────────────────────────────────────
Y2 = Y1 + GAP - 10
circle(COL_L, Y2 + 24, 3, ACCENT)
text_l(COL_L + 50, Y2,      "Log in with default credentials:", font_step, MUTED)
text_l(COL_L + 50, Y2 + 50, "Username:", font_body, MUTED)
text_l(COL_L + 220, Y2 + 46, "admin", font_value, WHITE)
text_l(COL_L + 50, Y2 + 100, "Password:", font_body, MUTED)
text_l(COL_L + 220, Y2 + 96, "videowall", font_value, GREEN)

# ─ Step 4 ────────────────────────────────────────────────────────────────────
Y3 = Y2 + GAP - 10
circle(COL_L, Y3 + 24, 4, ACCENT)
text_l(COL_L + 50, Y3,      "Add cameras, build playlists, set schedule,", font_step, MUTED)
text_l(COL_L + 50, Y3 + 50, "then change your admin password.", font_step, MUTED)

# ── Warning box ───────────────────────────────────────────────────────────────
bx1, bx2 = cx - 380, cx + 380
by1 = H - 180
draw.rounded_rectangle([(bx1, by1), (bx2, H - 80)], radius=12,
                        fill=(43, 31, 12), outline=YELLOW, width=2)
text_c(by1 + 14, "⚠  Change your password after setup  ⚠", font_small, YELLOW)
text_c(by1 + 52, "Go to Config → System → New Admin Password", font_tiny, MUTED)

# ── Bottom branding ───────────────────────────────────────────────────────────
text_c(H - 58, "jjsmartsolutions.com", font_small, MUTED)

# ── Save ─────────────────────────────────────────────────────────────────────
OUT = '/opt/videowall/static/setup_screen.png'
img.save(OUT)
print(f"Saved: {OUT} ({W}x{H})")
