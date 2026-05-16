#!/usr/bin/env python3
"""Generate the second-screen / new-monitor instruction PNG."""
from PIL import Image, ImageDraw, ImageFont
import os

W, H = 1920, 1080
BG     = (13,  17,  23)
ACCENT = (88,  166, 255)
GREEN  = (63,  185, 80)
MUTED  = (139, 148, 158)
WHITE  = (230, 237, 243)
YELLOW = (210, 153, 34)

img  = Image.new('RGB', (W, H), BG)
draw = ImageDraw.Draw(img)

def load_font(size, bold=False):
    candidates = [
        f'/usr/share/fonts/truetype/dejavu/DejaVuSans{"-Bold" if bold else ""}.ttf',
        f'/usr/share/fonts/truetype/liberation/LiberationSans{"-Bold" if bold else "-Regular"}.ttf',
    ]
    for p in candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

font_big   = load_font(80, bold=True)
font_title = load_font(52, bold=True)
font_sub   = load_font(38, bold=True)
font_body  = load_font(34)
font_value = load_font(42, bold=True)
font_small = load_font(28)
font_tiny  = load_font(22)

def text_c(y, txt, font, color=WHITE):
    bbox = draw.textbbox((0, 0), txt, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) // 2, y), txt, font=font, fill=color)

def text_l(x, y, txt, font, color=WHITE):
    draw.text((x, y), txt, font=font, fill=color)

# Top / bottom accent bars
draw.rectangle([(0, 0),   (W, 8)], fill=ACCENT)
draw.rectangle([(0, H-8), (W, H)], fill=ACCENT)

# Header
text_c(36,  "JJ Smart Solutions — VideoWall", font_title, ACCENT)
text_c(106, "New Monitor Detected", font_sub, WHITE)

# Divider
draw.rectangle([(W//2 - 500, 168), (W//2 + 500, 171)], fill=(48,54,61))

# Icon area — big monitor icon placeholder
draw.rounded_rectangle([(W//2-90, 190), (W//2+90, 310)], radius=12,
                        fill=(30,37,47), outline=ACCENT, width=3)
text_c(215, "2", font_big, ACCENT)

text_c(330, "This screen has been auto-detected.", font_body, MUTED)
text_c(376, "Assign a playlist to it from the web admin:", font_body, MUTED)

# URL box
draw.rounded_rectangle([(W//2-360, 430), (W//2+360, 510)],
                        radius=10, fill=(22,27,34), outline=ACCENT, width=2)
text_c(448, "https://<device-ip>  →  Monitors", font_value, ACCENT)

# Steps
COL = W//2 - 340
Y   = 545
GAP = 82

steps = [
    ("1", "Log in to the web admin panel."),
    ("2", 'Go to the  Monitors  tab.'),
    ("3", f'Find "Monitor 2" and assign a playlist.'),
    ("4", "Cameras will appear on this screen immediately."),
]

cr = 22
for num, txt in steps:
    draw.ellipse([(COL-cr, Y-cr), (COL+cr, Y+cr)], fill=ACCENT)
    bb = draw.textbbox((0,0), num, font=font_sub)
    draw.text((COL-(bb[2]-bb[0])//2, Y-(bb[3]-bb[1])//2-2), num, font=font_sub, fill=BG)
    text_l(COL+44, Y-20, txt, font_body, WHITE)
    Y += GAP

# Warning box
bx1, bx2 = W//2-420, W//2+420
by1 = H - 160
draw.rounded_rectangle([(bx1, by1), (bx2, H-70)],
                        radius=12, fill=(43,31,12), outline=YELLOW, width=2)
text_c(by1+16, "This screen will show cameras once a playlist is assigned.", font_small, YELLOW)
text_c(by1+54, "If no playlist is configured it will remain on this screen.", font_tiny, MUTED)

# Footer
text_c(H-52, "jjsmartsolutions.com", font_small, MUTED)

OUT = '/opt/videowall/static/second_screen_setup.png'
img.save(OUT)
print(f"Saved: {OUT}  ({W}x{H})")
