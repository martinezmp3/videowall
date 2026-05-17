#!/bin/bash
# VideoWall First Boot Installer
# Runs once on the first boot of a freshly installed system.
# Shows an animated terminal UI while packages are installed.
# Triggered by vw-firstboot.service; self-disables when done.

set -e

LOG="/var/log/videowall-install.log"
FLAG="/var/lib/videowall-firstboot"
PKG_DIR="/var/lib/videowall-installer"

BOLD=$'\033[1m'; DIM=$'\033[2m'; NC=$'\033[0m'
GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[1;33m'
CYAN=$'\033[0;36m'; WHITE=$'\033[1;37m'; BLUE=$'\033[0;34m'
BGREEN=$'\033[1;32m'; BCYAN=$'\033[1;36m'; BBLUE=$'\033[1;34m'

SPIN='/-\|'
SPIN_LEN=4
SPIN_I=0

STEP_NAMES=(
    "Setting up package repository"
    "Installing system packages"
    "Installing Python libraries"
    "Configuring VideoWall"
    "Finalizing — services start on exit"
)
STEP_STATUS=()
for i in "${!STEP_NAMES[@]}"; do STEP_STATUS[$i]="pending"; done

next_spin() {
    local ch="${SPIN:$(( SPIN_I % SPIN_LEN )):1}"
    SPIN_I=$(( SPIN_I + 1 ))
    printf '%s' "$ch"
}

# ── Set a larger, more readable console font ──────────────────────────────────
_set_font() {
    for font in \
        "Uni2-TerminusBold24x12" \
        "Lat15-TerminusBold24x12" \
        "Uni2-Terminus20x10" \
        "Lat15-Terminus20x10" \
        "Lat15-Fixed18" \
        "default8x16"; do
        if setfont "${font}" 2>/dev/null; then
            break
        fi
        # Try .psf.gz variant
        local path
        for dir in /usr/share/consolefonts /usr/share/kbd/consolefonts; do
            path="${dir}/${font}.psf.gz"
            [ -f "$path" ] && setfont "$path" 2>/dev/null && return
        done
    done
}
_set_font

# ── Terminal dimensions ───────────────────────────────────────────────────────
COLS=$(tput cols 2>/dev/null || echo 80)
ROWS=$(tput lines 2>/dev/null || echo 24)
# Content box width — never wider than terminal minus 4 margin chars
BOX_W=$(( COLS - 4 ))
[ "$BOX_W" -gt 90 ] && BOX_W=90

# ── Draw helpers ──────────────────────────────────────────────────────────────
_hline() {
    # args: char width
    local ch="$1" w="$2"
    printf '%*s' "$w" '' | tr ' ' "$ch"
}

_box_top()    { printf "  +%s+\n" "$(_hline - $(( BOX_W - 2 )))"; }
_box_bottom() { printf "  +%s+\n" "$(_hline - $(( BOX_W - 2 )))"; }
_box_mid()    { printf "  +%s+\n" "$(_hline - $(( BOX_W - 2 )))"; }

_box_row() {
    # Print a padded content row inside the box
    # Usage: _box_row "text" [color]
    local text="$1" color="${2:-}"
    # Strip ANSI for length calculation
    local plain
    plain=$(printf '%s' "$text" | sed 's/\x1b\[[0-9;]*m//g')
    local pad=$(( BOX_W - 2 - ${#plain} ))
    [ "$pad" -lt 0 ] && pad=0
    printf "  |${color}%s${NC}%*s|\n" "$text" "$pad" ""
}

_box_empty() {
    printf "  |%*s|\n" "$(( BOX_W - 2 ))" ""
}

# ── Draw the fullscreen TUI ───────────────────────────────────────────────────
draw_screen() {
    local spin="${1:- }"

    printf '\033[H'   # cursor home (no full clear — avoids flash)

    # ── Header ────────────────────────────────────────────────────────────────
    _box_top

    local title="  VideoWall Installer  —  JJ Smart Solutions  "
    local tpad=$(( (BOX_W - 2 - ${#title}) / 2 ))
    [ "$tpad" -lt 0 ] && tpad=0
    printf "  |${BCYAN}%*s%s%*s${NC}|\n" \
        "$tpad" "" "$title" "$(( BOX_W - 2 - tpad - ${#title} ))" ""

    _box_mid

    _box_empty
    _box_row "  Please wait while VideoWall is being installed..." "${DIM}"
    _box_empty

    # ── Step list ─────────────────────────────────────────────────────────────
    local done_count=0
    for i in "${!STEP_NAMES[@]}"; do
        local name="${STEP_NAMES[$i]}"
        case "${STEP_STATUS[$i]}" in
            done)
                _box_row "  ${BGREEN}[DONE]${NC}  $name"
                done_count=$(( done_count + 1 ))
                ;;
            running)
                _box_row "  ${BCYAN}[ ${spin}  ]${NC}  $name"
                ;;
            error)
                _box_row "  ${RED}[FAIL]${NC}  $name"
                ;;
            *)
                _box_row "  ${DIM}[    ]${NC}  $name"
                ;;
        esac
    done

    _box_empty

    # ── Progress bar ──────────────────────────────────────────────────────────
    local total=${#STEP_NAMES[@]}
    local pct=$(( done_count * 100 / total ))
    local bar_w=$(( BOX_W - 14 ))   # space for "  [" + "] 100%" padding
    [ "$bar_w" -lt 10 ] && bar_w=10
    local filled=$(( pct * bar_w / 100 ))
    local empty=$(( bar_w - filled ))

    local bar_filled="" bar_empty=""
    [ "$filled" -gt 0 ] && bar_filled=$(printf '%0.s#' $(seq 1 "$filled"))
    [ "$empty"  -gt 0 ] && bar_empty=$( printf '%0.s-' $(seq 1 "$empty"))

    local bar_line="  [${BCYAN}${bar_filled}${DIM}${bar_empty}${NC}] ${pct}%"
    _box_row "$bar_line"

    _box_empty

    # ── Log tail ──────────────────────────────────────────────────────────────
    _box_row "  ${DIM}Recent output:${NC}" ""
    local log_lines=5
    if [[ -f "$LOG" ]]; then
        while IFS= read -r line; do
            # Truncate to fit inside box
            local trunc="${line:0:$(( BOX_W - 6 ))}"
            _box_row "  ${DIM}${trunc}${NC}"
            log_lines=$(( log_lines - 1 ))
        done < <(tail -5 "$LOG" 2>/dev/null)
    fi
    # Fill remaining log lines with empty rows
    while [ "$log_lines" -gt 0 ]; do
        _box_empty
        log_lines=$(( log_lines - 1 ))
    done

    _box_bottom

    printf "\033[J"   # clear from cursor to end of screen
}

# ── Run one install step with live animation ──────────────────────────────────
run_step() {
    local idx=$1
    shift

    STEP_STATUS[$idx]="running"

    "$@" >> "$LOG" 2>&1 &
    local pid=$!

    while kill -0 "$pid" 2>/dev/null; do
        draw_screen "$(next_spin)"
        sleep 0.15
    done

    wait "$pid"
    local rc=$?

    if [[ $rc -eq 0 ]]; then
        STEP_STATUS[$idx]="done"
    else
        STEP_STATUS[$idx]="error"
        draw_screen "!"
        printf "\n  ${RED}${BOLD}ERROR${NC} in step: %s\n" "${STEP_NAMES[$idx]}"
        printf "  Check %s for details.\n\n" "$LOG"
        tput cnorm 2>/dev/null
        exit 1
    fi

    draw_screen " "
}

# ── Setup ─────────────────────────────────────────────────────────────────────
mkdir -p "$(dirname "$LOG")"
{
    echo "======================================"
    echo " VideoWall First Boot  $(date)"
    echo "======================================"
} >> "$LOG"

tput civis 2>/dev/null || true  # hide cursor
clear 2>/dev/null || printf '\033[2J\033[H'

trap 'tput cnorm 2>/dev/null || true; tput sgr0 2>/dev/null || true' EXIT

# Initial draw so the screen isn't blank while step 0 starts
draw_screen " "

# ── Step 0: Offline apt repo ──────────────────────────────────────────────────
run_step 0 bash -c "
    cat > /etc/apt/sources.list << 'SOURCES'
# VideoWall offline install
deb [trusted=yes] file://${PKG_DIR}/vw-packages ./
SOURCES
    rm -f /etc/apt/sources.list.d/*.list 2>/dev/null || true
    printf '#!/bin/sh\nexit 0\n' > /usr/sbin/dpkg-preconfigure
    chmod +x /usr/sbin/dpkg-preconfigure
    DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true apt-get update -qq
"

# ── Step 1: System packages ───────────────────────────────────────────────────
run_step 1 bash -c '
    DEBIAN_FRONTEND=noninteractive DEBCONF_NONINTERACTIVE_SEEN=true \
    apt-get install -y --no-install-recommends \
        git curl wget \
        python3 python3-pip python3-pil \
        mpv ffmpeg \
        xorg x11-xserver-utils xdotool \
        feh scrot \
        network-manager \
        nginx openssl \
        vainfo intel-media-va-driver libva-drm2 libva-x11-2 \
        net-tools nmap fail2ban ufw \
        openssh-server rfkill
'

# ── Step 2: Python packages ───────────────────────────────────────────────────
run_step 2 pip3 install \
    --no-index --find-links="${PKG_DIR}/vw-pip" \
    flask pyyaml psutil qrcode \
    --break-system-packages -q

# ── Step 3: VideoWall application ─────────────────────────────────────────────
run_step 3 bash -c 'VIDEOWALL_OFFLINE=1 SKIP_START=1 bash /opt/videowall/install.sh'

# ── Step 4: Finalize — WiFi enable, SSH off, daemon reload ────────────────────
run_step 4 bash -c '
    rfkill unblock all 2>/dev/null || true
    nmcli radio wifi on 2>/dev/null || true
    systemctl disable --now ssh 2>/dev/null || true
    systemctl daemon-reload
'

# ── Cleanup ───────────────────────────────────────────────────────────────────
rm -rf "$PKG_DIR"
rm -f "$FLAG"

STEP_STATUS[4]="done"
draw_screen " "

printf "\n"
_box_top
_box_row "  ${BGREEN}Installation complete!${NC}  VideoWall is starting..." ""
_box_bottom
printf "\n"
tput cnorm 2>/dev/null

# Start services without blocking
systemctl start --no-block videowall-display videowall-web nginx 2>/dev/null || true
sleep 3
