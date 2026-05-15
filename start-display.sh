#!/bin/bash
export DISPLAY=:0
export LIBVA_DRIVER_NAME=iHD
export LIBVA_DRI3_DISABLE=1

# ── Start Xorg and wait for it to be ready ────────────────────────────────────
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

# Give GPU/driver a moment to detect all connected outputs after X starts
sleep 3

# ── Configure displays ────────────────────────────────────────────────────────
# Wait up to 15s for at least one external display to appear
for i in $(seq 1 15); do
    EXT_COUNT=$(xrandr | grep " connected" | grep -cv "^eDP" || true)
    [ "$EXT_COUNT" -gt 0 ] && break
    echo "Waiting for external display detection... ($i)"
    sleep 1
done

# Build layout: external monitors first (left→right), laptop screen last
X_OFFSET=0
FIRST=1

while IFS= read -r line; do
    OUTPUT=$(echo "$line" | awk '{print $1}')
    PREF=$(xrandr | grep -A1 "^${OUTPUT} connected" | tail -1 | awk '{print $1}')
    [ -z "$PREF" ] && continue
    W=$(echo "$PREF" | cut -dx -f1)
    echo "External: $OUTPUT  ${PREF}  pos=${X_OFFSET}x0"
    if [ "$FIRST" -eq 1 ]; then
        xrandr --output "$OUTPUT" --mode "$PREF" --pos "${X_OFFSET}x0" --primary
        FIRST=0
    else
        xrandr --output "$OUTPUT" --mode "$PREF" --pos "${X_OFFSET}x0"
    fi
    X_OFFSET=$((X_OFFSET + W))
done < <(xrandr | grep " connected" | grep -v "^eDP")

# Laptop built-in: add after externals (or use as primary if none found)
EDP=$(xrandr | grep "^eDP" | awk '{print $1}' | head -1)
if [ -n "$EDP" ]; then
    EDP_PREF=$(xrandr | grep -A1 "^${EDP} connected" | tail -1 | awk '{print $1}')
    if [ "$FIRST" -eq 1 ]; then
        echo "No external found — using built-in $EDP as primary"
        xrandr --output "$EDP" --mode "$EDP_PREF" --pos "0x0" --primary
    else
        echo "Built-in: $EDP  ${EDP_PREF}  pos=${X_OFFSET}x0"
        xrandr --output "$EDP" --mode "$EDP_PREF" --pos "${X_OFFSET}x0"
    fi
fi

# Let xrandr changes settle before supervisor reads monitor layout
sleep 2

echo "Final monitor layout:"
xrandr --listmonitors

# ── Desktop cleanup ───────────────────────────────────────────────────────────
xset s off
xset -dpms
xset s noblank
xsetroot -solid black

# ── Start supervisor ──────────────────────────────────────────────────────────
exec python3 /opt/videowall/supervisor.py
