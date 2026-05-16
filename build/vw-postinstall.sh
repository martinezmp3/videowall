#!/bin/bash
# Runs inside the installed system (chroot) after Debian base install.
# Sets up the local apt repo and installs all VideoWall components.
set -e
LOG="/var/log/videowall-postinstall.log"
mkdir -p "$(dirname "$LOG")"
exec >> "$LOG" 2>&1
echo "======================================"
echo " VideoWall Post-Install  $(date)"
echo "======================================"

# ── 1. Local apt repo from bundled packages ──────────────────────────────────
echo "[1/4] Setting up offline package repository..."
# Packages.gz was pre-built by build-usb.sh — already present in /tmp/vw-packages
cat > /etc/apt/sources.list << 'SOURCES'
# VideoWall offline install — local USB packages only
deb [trusted=yes] file:///tmp/vw-packages ./
SOURCES
rm -f /etc/apt/sources.list.d/*.list 2>/dev/null || true
apt-get update -qq

# ── 2. Install all packages ──────────────────────────────────────────────────
echo "[2/4] Installing system packages..."
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    git curl wget \
    python3 python3-pip python3-pil \
    mpv ffmpeg \
    xorg x11-xserver-utils xdotool \
    feh scrot \
    network-manager \
    nginx openssl \
    vainfo intel-media-va-driver libva-drm2 libva-x11-2 \
    net-tools nmap fail2ban ufw

# ── 3. Python packages from bundled wheels ───────────────────────────────────
echo "[3/4] Installing Python packages..."
pip3 install --no-index --find-links=/tmp/vw-pip \
    flask pyyaml psutil --break-system-packages -q

# ── 4. Run VideoWall installer ───────────────────────────────────────────────
echo "[4/4] Running VideoWall installer..."
export VIDEOWALL_OFFLINE=1
bash /opt/videowall/install.sh

# ── Cleanup ──────────────────────────────────────────────────────────────────
rm -rf /tmp/vw-packages /tmp/vw-pip
echo "======================================"
echo " Post-Install complete  $(date)"
echo "======================================"
