#!/bin/bash
export DISPLAY=:0
export LIBVA_DRIVER_NAME=iHD
export LIBVA_DRI3_DISABLE=1

# Retry starting Xorg until the display is usable (GPU may not be ready at early boot)
for i in $(seq 1 20); do
    if ! pgrep -x Xorg > /dev/null; then
        Xorg :0 -nolisten tcp vt1 &
    fi
    sleep 4
    if DISPLAY=:0 xdpyinfo > /dev/null 2>&1; then
        echo "Xorg ready on attempt $i"
        break
    fi
    echo "Xorg not ready (attempt $i), retrying..."
    pkill -x Xorg 2>/dev/null
    sleep 3
done

# Disable screen saver and power management
xset s off
xset -dpms
xset s noblank

# Black background
xsetroot -solid black

# Start supervisor
exec python3 /opt/videowall/supervisor.py
