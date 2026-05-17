#!/usr/bin/env python3
"""Generate the factory-reset setup instruction screen PNG."""
import subprocess, re, os
from PIL import Image, ImageDraw, ImageFont

try:
    import qrcode as _qrcode
    HAVE_QR = True
except ImportError:
    HAVE_QR = False

W, H = 1920, 1080
BG     = (13,  17,  23)
ACCENT = (88,  166, 255)
GREEN  = (63,  185, 80)
MUTED  = (139, 148, 158)
WHITE  = (230, 237, 243)
YELLOW = (210, 153, 34)
RED    = (218, 54,  51)
TEAL   = (56,  189, 166)

img  = Image.new('RGB', (W, H), BG)
draw = ImageDraw.Draw(img)

def load_font(size, bold=False):
    candidates = [
        f'/usr/share/fonts/truetype/dejavu/DejaVuSans{"-Bold" if bold else ""}.ttf',
        f'/usr/share/fonts/truetype/liberation/LiberationSans{"-Bold" if bold else "-Regular"}.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf' if bold else '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
    ]
    for p in candidates:
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()

font_big   = load_font(72, bold=True)
font_title = load_font(48, bold=True)
font_step  = load_font(36, bold=True)
font_body  = load_font(32)
font_value = load_font(40, bold=True)
font_small = load_font(26)
font_tiny  = load_font(22)

cx = W // 2

def text_c(y, txt, font, color=WHITE):
    bbox = draw.textbbox((0, 0), txt, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) // 2, y), txt, font=font, fill=color)

def text_l(x, y, txt, font, color=WHITE):
    draw.text((x, y), txt, font=font, fill=color)

# ── Network detection ─────────────────────────────────────────────────────────
def get_eth_ip():
    try:
        out = subprocess.check_output(['ip', '-4', 'addr', 'show', 'scope', 'global'],
                                      text=True, stderr=subprocess.DEVNULL)
        # Skip the AP interface (10.42.x.x is the NM hotspot range)
        for m in re.finditer(r'inet ([\d.]+)', out):
            ip = m.group(1)
            if not ip.startswith('10.42.'):
                return ip
        return None
    except Exception:
        return None

def is_ap_active():
    """NetworkManager hotspot creates 10.42.0.1 on the AP interface."""
    try:
        out = subprocess.check_output(['ip', '-4', 'addr', 'show'],
                                      text=True, stderr=subprocess.DEVNULL)
        return '10.42.0.1' in out
    except Exception:
        return False

def make_qr(url, size=380):
    if not HAVE_QR:
        return None
    try:
        qr = _qrcode.QRCode(box_size=10, border=3,
                             error_correction=_qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color='white', back_color=BG)
        return qr_img.convert('RGB').resize((size, size), Image.LANCZOS)
    except Exception:
        return None

eth_ip    = get_eth_ip()
ap_active = is_ap_active()

# ── Layout constants ──────────────────────────────────────────────────────────
# When we have an IP and can show a QR code the right 420px are reserved for it.
QR_SIZE    = 380
QR_MARGIN  = 30
QR_X       = W - QR_SIZE - QR_MARGIN - 40   # left edge of QR panel
CONTENT_W  = QR_X - 20 if (eth_ip and HAVE_QR) else W  # available left width

COL_L = 120
Y0    = 175
GAP   = 175

circle_r = 26
def circle(x, y, num, color):
    draw.ellipse([(x - circle_r, y - circle_r), (x + circle_r, y + circle_r)], fill=color)
    bbox = draw.textbbox((0, 0), str(num), font=font_step)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    draw.text((x - tw//2, y - th//2 - 2), str(num), font=font_step, fill=BG)

# ── Chrome ────────────────────────────────────────────────────────────────────
draw.rectangle([(0, 0), (W, 8)],   fill=ACCENT)
draw.rectangle([(0, H - 8), (W, H)], fill=ACCENT)

title_area_w = CONTENT_W if (eth_ip and HAVE_QR) else W
# Header text centred over the content column only
header_cx = COL_L + (CONTENT_W - COL_L) // 2
def text_cc(y, txt, font, color=WHITE):
    bbox = draw.textbbox((0, 0), txt, font=font)
    tw = bbox[2] - bbox[0]
    draw.text((header_cx - tw // 2, y), txt, font=font, fill=color)

text_cc(30,  "JJ Smart Solutions",          font_title, ACCENT)
text_cc(90,  "VideoWall  —  Initial Setup", font_step,  MUTED)
draw.rectangle([(COL_L, 148), (CONTENT_W - 20, 151)], fill=(48, 54, 61))

# ── Network status banner ─────────────────────────────────────────────────────
if eth_ip:
    bx1, bx2 = COL_L, CONTENT_W - 20
    draw.rounded_rectangle([(bx1, Y0), (bx2, Y0 + 74)],
                            radius=10, fill=(18, 40, 20), outline=GREEN, width=2)
    text_l(bx1 + 20, Y0 + 8,  "Device is on your network — open your browser:", font_body, MUTED)
    text_l(bx1 + 20, Y0 + 42, f"https://{eth_ip}", font_value, GREEN)
    Y_START = Y0 + 96
elif ap_active:
    bx1, bx2 = COL_L, CONTENT_W - 20
    draw.rounded_rectangle([(bx1, Y0), (bx2, Y0 + 74)],
                            radius=10, fill=(20, 28, 45), outline=ACCENT, width=2)
    text_l(bx1 + 20, Y0 + 8,  "No Ethernet detected — connect via the WiFi hotspot below.", font_body, MUTED)
    text_l(bx1 + 20, Y0 + 42, "Once on Ethernet this screen will update automatically.", font_body, MUTED)
    Y_START = Y0 + 96
else:
    bx1, bx2 = COL_L, CONTENT_W - 20
    draw.rounded_rectangle([(bx1, Y0), (bx2, Y0 + 74)],
                            radius=10, fill=(45, 18, 18), outline=RED, width=2)
    text_l(bx1 + 20, Y0 + 8,  "No network connection detected.", font_body, RED)
    text_l(bx1 + 20, Y0 + 42, "Connect an Ethernet cable — this screen updates when an IP is assigned.", font_body, MUTED)
    Y_START = Y0 + 96

# ── Steps ─────────────────────────────────────────────────────────────────────
Y1 = Y_START

if ap_active or (not eth_ip):
    # Step 1: Network connection
    circle(COL_L, Y1 + 22, 1, ACCENT)
    if ap_active:
        text_l(COL_L + 46, Y1,      "Connect phone or laptop to WiFi:", font_step, MUTED)
        text_l(COL_L + 46, Y1 + 44, "Network:", font_body, MUTED)
        text_l(COL_L + 220, Y1 + 40, "VideoWall-Setup", font_value, WHITE)
        text_l(COL_L + 46, Y1 + 88, "Password:", font_body, MUTED)
        text_l(COL_L + 220, Y1 + 84, "jjsmart123", font_value, GREEN)
        step1_h = 135
    else:
        text_l(COL_L + 46, Y1,      "Plug in an Ethernet cable:", font_step, MUTED)
        text_l(COL_L + 46, Y1 + 44, "Connect this device to your router/switch.", font_body, MUTED)
        text_l(COL_L + 46, Y1 + 84, "This screen will show the address once connected.", font_body, MUTED)
        step1_h = 120
    Y2 = Y1 + step1_h + 20
    step_start = 2
else:
    # Ethernet is already connected, skip WiFi step
    Y2 = Y1
    step_start = 1

# Step 2 (or 1 if eth connected): Browser URL
circle(COL_L, Y2 + 22, step_start, ACCENT)
text_l(COL_L + 46, Y2, "Open your browser and go to:", font_step, MUTED)
if eth_ip:
    text_l(COL_L + 46, Y2 + 44, f"https://{eth_ip}", font_value, ACCENT)
    if ap_active:
        text_l(COL_L + 46, Y2 + 88, "or  http://10.42.0.1  via the WiFi hotspot", font_body, MUTED)
elif ap_active:
    text_l(COL_L + 46, Y2 + 44, "http://10.42.0.1", font_value, ACCENT)

Y3 = Y2 + GAP

# Step 3: Login
circle(COL_L, Y3 + 22, step_start + 1, ACCENT)
text_l(COL_L + 46, Y3,      "Log in with the default credentials:", font_step, MUTED)
text_l(COL_L + 46, Y3 + 44, "Username:", font_body, MUTED)
text_l(COL_L + 220, Y3 + 40, "admin", font_value, WHITE)
text_l(COL_L + 46, Y3 + 88, "Password:", font_body, MUTED)
text_l(COL_L + 220, Y3 + 84, "videowall", font_value, GREEN)

Y4 = Y3 + GAP

# Step 4: Configure
circle(COL_L, Y4 + 22, step_start + 2, ACCENT)
text_l(COL_L + 46, Y4,      "Add cameras, build playlists, set schedule.", font_step, MUTED)
text_l(COL_L + 46, Y4 + 44, "Then change your admin password in Config → System.", font_body, MUTED)

# ── Warning box ───────────────────────────────────────────────────────────────
by1 = H - 168
draw.rounded_rectangle([(COL_L, by1), (CONTENT_W - 20, H - 80)],
                        radius=12, fill=(43, 31, 12), outline=YELLOW, width=2)
text_l(COL_L + 20, by1 + 14, "  Change your password after setup", font_small, YELLOW)
text_l(COL_L + 20, by1 + 50, "  Config -> System -> New Admin Password", font_tiny, MUTED)

# ── QR Code (right panel, only when IP is known) ──────────────────────────────
if eth_ip and HAVE_QR:
    url = f"https://{eth_ip}"
    qr_img = make_qr(url, QR_SIZE)
    if qr_img:
        qr_y = (H - QR_SIZE) // 2 - 40
        img.paste(qr_img, (QR_X, qr_y))
        # Caption
        bbox = draw.textbbox((0, 0), "Scan to open setup page", font=font_small)
        tw = bbox[2] - bbox[0]
        cap_x = QR_X + (QR_SIZE - tw) // 2
        draw.text((cap_x, qr_y + QR_SIZE + 14), "Scan to open setup page",
                  font=font_small, fill=MUTED)
        draw.text((cap_x, qr_y + QR_SIZE + 46), url, font=font_tiny, fill=ACCENT)
        # Thin divider
        div_x = QR_X - 20
        draw.rectangle([(div_x, 100), (div_x + 1, H - 100)], fill=(48, 54, 61))

# ── Footer ────────────────────────────────────────────────────────────────────
text_c(H - 52, "jjsmartsolutions.com", font_small, MUTED)

OUT = '/opt/videowall/static/setup_screen.png'
img.save(OUT)
print(f"Saved: {OUT} ({W}x{H})")
if eth_ip: print(f"  IP shown: {eth_ip}  QR: {'yes' if HAVE_QR else 'no (qrcode not installed)'}")
if ap_active: print("  WiFi AP active: VideoWall-Setup")
if not eth_ip and not ap_active: print("  No network — showing cable-connect instructions")
