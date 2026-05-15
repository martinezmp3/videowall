#!/bin/bash
export DISPLAY=:0
export LIBVA_DRIVER_NAME=iHD
export LIBVA_DRI3_DISABLE=1

# ── Wait for Xorg to be ready ─────────────────────────────────────────────────
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

# ── Configure displays ────────────────────────────────────────────────────────
# Detect all connected external outputs (HDMI and DisplayPort)
EXTERNALS=()
while IFS= read -r line; do
    output=$(echo "$line" | awk '{print $1}')
    # Skip laptop built-in screen (eDP)
    if [[ "$output" != eDP* ]]; then
        EXTERNALS+=("$output")
    fi
done < <(xrandr | grep " connected" | grep -v "^eDP")

if [ ${#EXTERNALS[@]} -gt 0 ]; then
    echo "External displays found: ${EXTERNALS[*]}"
    # Enable each external display in sequence, starting at x=0
    X_OFFSET=0
    FIRST=1
    for OUTPUT in "${EXTERNALS[@]}"; do
        # Get the preferred (first listed) resolution for this output
        PREF=$(xrandr | grep -A1 "^${OUTPUT} connected" | tail -1 | awk '{print $1}')
        W=$(echo "$PREF" | cut -dx -f1)
        echo "Enabling $OUTPUT at ${PREF} (+${X_OFFSET}+0)"
        if [ "$FIRST" -eq 1 ]; then
            xrandr --output "$OUTPUT" --mode "$PREF" --rate 60.00 --pos "${X_OFFSET}x0" --primary
            FIRST=0
        else
            xrandr --output "$OUTPUT" --mode "$PREF" --pos "${X_OFFSET}x0"
        fi
        X_OFFSET=$((X_OFFSET + W))
    done
    # Push laptop screen off to the right (out of camera area) or turn it off
    xrandr --output eDP-1 --off 2>/dev/null || true
else
    echo "No external display found — using built-in screen"
    xrandr --output eDP-1 --auto --primary
fi

# ── Desktop cleanup ───────────────────────────────────────────────────────────
xset s off
xset -dpms
xset s noblank
xsetroot -solid black

# ── Start supervisor ──────────────────────────────────────────────────────────
exec python3 /opt/videowall/supervisor.py
