#!/bin/bash
# VideoWall Installer — JJ Smart Solutions
# Usage on a fresh Debian install:
#   wget -qO- https://raw.githubusercontent.com/martinezmp3/videowall/main/install.sh | bash

set -e

REPO="https://github.com/martinezmp3/videowall.git"
INSTALL_DIR="/opt/videowall"
LOG_DIR="/var/log/videowall"
SSL_CERT="/etc/ssl/certs/videowall.crt"
SSL_KEY="/etc/ssl/private/videowall.key"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

echo ""
echo -e "${BOLD}============================================${NC}"
echo -e "${BOLD}  VideoWall Installer — JJ Smart Solutions${NC}"
echo -e "${BOLD}============================================${NC}"
echo ""

[[ $EUID -ne 0 ]] && error "Run as root:  sudo bash install.sh"

# ── 1. System packages ────────────────────────────────────────────────────────
info "Installing system packages..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git curl wget \
    python3 python3-pip python3-pil \
    mpv ffmpeg \
    xorg x11-xserver-utils xdotool \
    feh scrot \
    network-manager \
    nginx openssl \
    vainfo intel-media-va-driver libva-drm2 libva-x11-2 \
    net-tools 2>&1 | grep -E "^(Get|Setting|Unpacking|Processing)" | head -20 || true

# ── 2. Python packages ────────────────────────────────────────────────────────
info "Installing Python packages..."
pip3 install flask pyyaml psutil --break-system-packages -q

# ── 3. Clone / update repo ───────────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing VideoWall installation..."
    cd "$INSTALL_DIR" && git pull --ff-only
elif [ -f "$(dirname "$0")/supervisor.py" ]; then
    info "Installing from local copy..."
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    mkdir -p "$INSTALL_DIR/static/snapshots" "$INSTALL_DIR/templates"
    cp -r "$SCRIPT_DIR"/. "$INSTALL_DIR/"
else
    info "Cloning VideoWall from GitHub..."
    git clone "$REPO" "$INSTALL_DIR"
fi

# ── 4. Directories & permissions ─────────────────────────────────────────────
info "Setting up directories..."
mkdir -p "$INSTALL_DIR/static/snapshots" "$LOG_DIR"
chmod +x "$INSTALL_DIR/start-display.sh"

# ── 5. Always write a clean config in setup mode ──────────────────────────────
info "Writing fresh config (setup mode — no cameras)..."
python3 - << 'PYEOF'
import yaml, hashlib
cfg = {
    'setup_mode': True,
    'system': {
        'admin_password_hash': hashlib.sha256(b'videowall').hexdigest(),
        'debug_log': False,
        'watchdog_interval': 30,
        'alert_email_from': '',
        'alert_email_to': '',
        'gmail_app_password': '',
    },
    'cameras': [],
    'playlists': [],
    'monitors': [{'id': 1, 'name': 'Monitor 1', 'schedule': []}],
}
with open('/opt/videowall/config.yml', 'w') as f:
    yaml.dump(cfg, f, default_flow_style=False)
print("  Clean config written.")
PYEOF

# ── 6. SSL certificate ───────────────────────────────────────────────────────
info "Generating self-signed SSL certificate..."
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout "$SSL_KEY" \
    -out "$SSL_CERT" \
    -subj "/CN=videowall.local/O=JJ Smart Solutions/C=US" \
    2>/dev/null
chmod 600 "$SSL_KEY"

# ── 7. Nginx ──────────────────────────────────────────────────────────────────
info "Configuring nginx..."
cp "$INSTALL_DIR/nginx-videowall.conf" /etc/nginx/sites-available/videowall
ln -sf /etc/nginx/sites-available/videowall /etc/nginx/sites-enabled/videowall
rm -f /etc/nginx/sites-enabled/default
if ! nginx -t 2>&1; then
    echo -e "\033[0;31m[ERROR]\033[0m nginx config test failed — see errors above"
    exit 1
fi
systemctl enable nginx
systemctl restart nginx

# ── 8. Auto-login root on tty1 ───────────────────────────────────────────────
info "Configuring auto-login..."
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << 'AUTOLOGIN'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I $TERM
AUTOLOGIN

# ── 9. Systemd services ───────────────────────────────────────────────────────
info "Installing and starting services..."
cp "$INSTALL_DIR/videowall-display.service" /etc/systemd/system/
cp "$INSTALL_DIR/videowall-web.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable videowall-display videowall-web

# ── 10. NetworkManager ────────────────────────────────────────────────────────
info "Configuring NetworkManager..."
cat > /etc/NetworkManager/NetworkManager.conf << 'NMCONF'
[main]
plugins=ifupdown,keyfile

[ifupdown]
managed=true
NMCONF
systemctl enable NetworkManager
systemctl restart NetworkManager 2>/dev/null || true

# ── 11. Generate setup screen ─────────────────────────────────────────────────
info "Generating setup screen image..."
DISPLAY="" python3 "$INSTALL_DIR/setup_screen_gen.py" 2>/dev/null \
    && info "Setup screen generated." \
    || warn "Will generate at first boot when display is available."

# ── 12. Start services now ────────────────────────────────────────────────────
info "Starting VideoWall services..."
systemctl restart videowall-web
systemctl restart videowall-display

# ── 13. Show IP address ───────────────────────────────────────────────────────
sleep 3
DEVICE_IP=$(ip -4 addr show scope global | grep -oP '(?<=inet )\d+\.\d+\.\d+\.\d+' | head -1)

echo ""
echo -e "${BOLD}============================================${NC}"
echo -e "  ${GREEN}VideoWall install complete!${NC}"
echo -e "${BOLD}============================================${NC}"
echo ""
echo -e "  Admin password  : ${BOLD}videowall${NC}"
echo -e "  WiFi hotspot    : ${BOLD}VideoWall-Setup${NC}  (pass: jjsmart123)"
echo ""
if [ -n "$DEVICE_IP" ]; then
echo -e "  Web admin       : ${BOLD}https://${DEVICE_IP}${NC}"
else
echo -e "  Web admin       : ${BOLD}https://<device-ip>${NC}"
echo -e "                    (run 'ip addr' to find your IP)"
fi
echo ""
echo -e "  The setup screen should be visible on the display."
echo -e "  Connect to the web admin to add cameras."
echo -e "${BOLD}============================================${NC}"
echo ""
