#!/bin/bash
# VideoWall Installer — JJ Smart Solutions
# Usage on a fresh Debian install:
#   curl -fsSL https://raw.githubusercontent.com/martinezmp3/videowall/main/install.sh | bash
# Or after cloning:
#   sudo bash install.sh

set -e

REPO="https://github.com/martinezmp3/videowall.git"
INSTALL_DIR="/opt/videowall"
LOG_DIR="/var/log/videowall"
SSL_CERT="/etc/ssl/certs/videowall.crt"
SSL_KEY="/etc/ssl/private/videowall.key"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

echo "============================================"
echo "  VideoWall Installer — JJ Smart Solutions"
echo "============================================"
echo ""

[[ $EUID -ne 0 ]] && error "Run as root:  sudo bash install.sh"

# ── 1. System packages ────────────────────────────────────────────────────────
info "Installing system packages..."
apt-get update -qq
apt-get install -y \
    git curl wget \
    python3 python3-pip python3-pil \
    mpv ffmpeg \
    xorg x11-xserver-utils xdotool \
    feh scrot \
    network-manager \
    nginx openssl \
    vainfo intel-media-va-driver libva-drm2 libva-x11-2 \
    net-tools 2>&1 | grep -E "^(Get|Setting|Unpacking|Selecting|Processing)" || true

# ── 2. Python packages ────────────────────────────────────────────────────────
info "Installing Python packages..."
pip3 install flask pyyaml psutil --break-system-packages -q

# ── 3. Clone / update repo ───────────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing VideoWall installation..."
    cd "$INSTALL_DIR"
    git pull --ff-only
elif [ -f "$(dirname "$0")/supervisor.py" ]; then
    info "Installing from local repo copy..."
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

# ── 5. SSL certificate ───────────────────────────────────────────────────────
if [ ! -f "$SSL_CERT" ]; then
    info "Generating self-signed SSL certificate (10 years)..."
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "$SSL_KEY" \
        -out "$SSL_CERT" \
        -subj "/CN=videowall.local/O=JJ Smart Solutions/C=US" \
        2>/dev/null
    chmod 600 "$SSL_KEY"
fi

# ── 6. Nginx ─────────────────────────────────────────────────────────────────
info "Configuring nginx..."
cp "$INSTALL_DIR/nginx-videowall.conf" /etc/nginx/sites-available/videowall
ln -sf /etc/nginx/sites-available/videowall /etc/nginx/sites-enabled/videowall
rm -f /etc/nginx/sites-enabled/default
nginx -t -q 2>/dev/null && systemctl enable --now nginx

# ── 7. Auto-login root on tty1 ───────────────────────────────────────────────
info "Configuring auto-login..."
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << 'AUTOLOGIN'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I $TERM
AUTOLOGIN

# ── 8. Systemd services ───────────────────────────────────────────────────────
info "Installing systemd services..."
cp "$INSTALL_DIR/videowall-display.service" /etc/systemd/system/
cp "$INSTALL_DIR/videowall-web.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable videowall-display videowall-web

# ── 9. Initial config (setup mode) ───────────────────────────────────────────
if [ ! -f "$INSTALL_DIR/config.yml" ]; then
    info "Creating initial config (setup mode)..."
    python3 - << 'PYEOF'
import yaml, hashlib, os
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
print("  Config written.")
PYEOF
fi

# ── 10. Generate setup screen ─────────────────────────────────────────────────
info "Generating setup screen image..."
DISPLAY="" python3 "$INSTALL_DIR/setup_screen_gen.py" 2>/dev/null || warn "Setup screen generation skipped (no display yet — will generate at first boot)"

# ── 11. NetworkManager: ensure it manages ethernet ───────────────────────────
info "Configuring NetworkManager..."
cat > /etc/NetworkManager/NetworkManager.conf << 'NMCONF'
[main]
plugins=ifupdown,keyfile

[ifupdown]
managed=true
NMCONF
systemctl enable --now NetworkManager 2>/dev/null || true

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "============================================"
echo -e "  ${GREEN}VideoWall install complete!${NC}"
echo "============================================"
echo ""
echo "  Default admin password : videowall"
echo "  WiFi hotspot on boot   : VideoWall-Setup  (pass: jjsmart123)"
echo "  Web admin              : https://<device-ip>"
echo ""
echo "  To start now (no reboot):"
echo "    systemctl start videowall-display videowall-web"
echo ""
echo "  On next reboot the system will start automatically."
echo "============================================"
