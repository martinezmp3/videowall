#!/bin/bash
export DISPLAY=:0
export LIBVA_DRIVER_NAME=iHD
export LIBVA_DRI3_DISABLE=1

# Start X server if not running
if ! pgrep -x Xorg > /dev/null; then
    Xorg :0 -nolisten tcp vt1 &
    sleep 3
fi

# Disable screen saver and power management
xset s off
xset -dpms
xset s noblank

# Black background
xsetroot -solid black

# Start supervisor
exec python3 /opt/videowall/supervisor.py
