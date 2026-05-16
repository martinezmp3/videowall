#!/usr/bin/env python3
"""Generate the factory-reset setup instruction screen PNG."""
import subprocess, re
from PIL import Image, ImageDraw, ImageFont
import os

W, H = 1920, 1080
BG      = (13,  17,  23)
ACCENT  = (88,  166, 255)
GREEN   = (63,  185, 80)
MUTED   = (139, 148, 158)
WHITE   = (230, 237, 243)
YELLOW  = (210, 153, 34)

img  = Image.new('RGB', (W, H), BG)
draw = ImageDraw.Draw(img)

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
font_step   = load_font(36, bold=True)
font_body   = load_font(32)
font_value  = load_font(40, bold=True)
font_small  = load_font(26)
font_tiny   = load_font(22)

cx = W // 2

def text_c(y, txt, font, color=WHITE):
    bbox = draw.textbbox((0, 0), txt, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) // 2, y), txt, font=font, fill=color)

def text_l(x, y, txt, font, color=WHITE):
    draw.text((x, y), txt, font=font, fill=color)

# ── Detect current IP ─────────────────────────────────────────────────────────
def get_eth_ip():
    try:
        out = subprocess.check_output(['ip', '-4', 'addr', 'show', 'scope', 'global'],
                                      text=True, stderr=subprocess.DEVNULL)
        m = re.search(r'inet ([\d.]+)', out)
        return m.group(1) if m else None
    except Exception:
        return None

eth_ip = get_eth_ip()

# ── Header ────────────────────────────────────────────────────────────────────
draw.rectangle([(0, 0), (W, 8)], fill=ACCENT)
draw.rectangle([(0, H - 8), (W, H)], fill=ACCENT)
text_c(35,  "JJ Smart Solutions", font_title, ACCENT)
text_c(96, "VideoWall  —  Initial Setup Guide", font_step, MUTED)
draw.rectangle([(cx - 440, 152), (cx + 440, 155)], fill=(48, 54, 61))

circle_r = 26
def circle(x, y, num, color):
    draw.ellipse([(x - circle_r, y - circle_r), (x + circle_r, y + circle_r)], fill=color)
    bbox = draw.textbbox((0, 0), str(num), font=font_step)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    draw.text((x - tw//2, y - th//2 - 2), str(num), font=font_step, fill=BG)

COL_L = 180
Y0    = 175
GAP   = 185

# ── Ethernet IP banner (shown when IP is known) ───────────────────────────────
if eth_ip:
    draw.rounded_rectangle([(cx - 500, Y0), (cx + 500, Y0 + 74)],
                            radius=10, fill=(20, 40, 20), outline=GREEN, width=2)
    text_c(Y0 + 8,  "This device is on your network — open your browser and go to:", font_body, MUTED)
    text_c(Y0 + 40, f"https://{eth_ip}", font_value, GREEN)
    Y_START = Y0 + 100
else:
    draw.rounded_rectangle([(cx - 500, Y0), (cx + 500, Y0 + 74)],
                            radius=10, fill=(40, 20, 20), outline=YELLOW, width=2)
    text_c(Y0 + 8,  "No Ethernet connection detected.", font_body, YELLOW)
    text_c(Y0 + 40, "Connect via Ethernet or use the WiFi hotspot below.", font_body, MUTED)
    Y_START = Y0 + 100

# ── Step 1: WiFi hotspot ──────────────────────────────────────────────────────
Y1 = Y_START
circle(COL_L, Y1 + 22, 1, ACCENT)
text_l(COL_L + 46, Y1,      "Connect phone/laptop to WiFi:", font_step, MUTED)
text_l(COL_L + 46, Y1 + 44, "Network:", font_body, MUTED)
text_l(COL_L + 210, Y1 + 40, "VideoWall-Setup", font_value, WHITE)
text_l(COL_L + 46, Y1 + 90, "Password:", font_body, MUTED)
text_l(COL_L + 210, Y1 + 86, "jjsmart123", font_value, GREEN)

# ── Step 2: Browser URL ───────────────────────────────────────────────────────
Y2 = Y1 + GAP + 10
circle(COL_L, Y2 + 22, 2, ACCENT)
text_l(COL_L + 46, Y2,      "Open browser and go to:", font_step, MUTED)
if eth_ip:
    text_l(COL_L + 46, Y2 + 44, f"https://{eth_ip}", font_value, ACCENT)
    text_l(COL_L + 46, Y2 + 88, "or  http://10.42.0.1  (via WiFi hotspot)", font_body, MUTED)
else:
    text_l(COL_L + 46, Y2 + 44, "http://10.42.0.1", font_value, ACCENT)

# ── Step 3: Login ─────────────────────────────────────────────────────────────
Y3 = Y2 + GAP + 10
circle(COL_L, Y3 + 22, 3, ACCENT)
text_l(COL_L + 46, Y3,      "Log in:", font_step, MUTED)
text_l(COL_L + 46, Y3 + 44, "Username:", font_body, MUTED)
text_l(COL_L + 210, Y3 + 40, "admin", font_value, WHITE)
text_l(COL_L + 46, Y3 + 88, "Password:", font_body, MUTED)
text_l(COL_L + 210, Y3 + 84, "videowall", font_value, GREEN)

# ── Step 4: Configure ─────────────────────────────────────────────────────────
Y4 = Y3 + GAP + 10
circle(COL_L, Y4 + 22, 4, ACCENT)
text_l(COL_L + 46, Y4,      "Add cameras, build playlists, set schedule.", font_step, MUTED)
text_l(COL_L + 46, Y4 + 44, "Then change your admin password in Config → System.", font_body, MUTED)

# ── Warning box ───────────────────────────────────────────────────────────────
bx1, bx2 = cx - 380, cx + 380
by1 = H - 175
draw.rounded_rectangle([(bx1, by1), (bx2, H - 82)], radius=12,
                        fill=(43, 31, 12), outline=YELLOW, width=2)
text_c(by1 + 14, "⚠  Change your password after setup  ⚠", font_small, YELLOW)
text_c(by1 + 50, "Go to Config → System → New Admin Password", font_tiny, MUTED)

# ── Bottom ────────────────────────────────────────────────────────────────────
text_c(H - 58, "jjsmartsolutions.com", font_small, MUTED)

OUT = '/opt/videowall/static/setup_screen.png'
img.save(OUT)
print(f"Saved: {OUT} ({W}x{H})")
if eth_ip:
    print(f"  IP shown: {eth_ip}")
else:
    print("  No Ethernet IP — showing WiFi hotspot only")
