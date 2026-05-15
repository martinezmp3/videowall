#!/bin/bash
set -e
echo '=== VideoWall Installer ==='

apt update -q
apt install -y git python3 python3-pip mpv ffmpeg xorg xinit openbox   x11-xserver-utils xdotool net-tools vainfo intel-media-va-driver   libva-drm2 libva-x11-2 nginx

pip3 install flask flask-login pyyaml psutil --break-system-packages

mkdir -p /opt/videowall/templates /opt/videowall/static /var/log/videowall

cp -r ./* /opt/videowall/ 2>/dev/null || true

# Auto-login
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << 'AUTOLOGIN'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I $TERM
AUTOLOGIN

cp videowall-display.service /etc/systemd/system/
cp videowall-web.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable videowall-display videowall-web

echo '=== Install complete ==='
echo 'Edit /opt/videowall/config.yml then: systemctl start videowall-display videowall-web'
