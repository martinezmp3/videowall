#!/bin/bash
# VideoWall Offline USB Installer Builder
# Run on the VideoWall machine (Debian 12 bookworm, all packages installed).
# Output: a bootable ISO you can flash to any USB stick.
#
# Usage:  bash /opt/videowall/build/build-usb.sh

set -e
BOLD='\033[1m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[BUILD]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

[[ $EUID -ne 0 ]] && error "Run as root:  sudo bash build-usb.sh"

# ── Config ────────────────────────────────────────────────────────────────────
VIDEOWALL_DIR="/opt/videowall"
BUILD_DIR="/tmp/vw-usb-build"
ISO_CACHE="/tmp/debian-12-netinst.amd64.iso"
OUTPUT_ISO="/tmp/videowall-installer.iso"
# Pinned to Debian 12 (Bookworm) — stable base for VideoWall
DEBIAN_12_ARCHIVE="https://cdimage.debian.org/cdimage/archive"

PACKAGES=(
    git curl wget sudo
    python3 python3-pip python3-pil
    mpv ffmpeg
    xorg xserver-xorg x11-xserver-utils xdotool xinit
    feh scrot
    network-manager
    nginx openssl
    vainfo intel-media-va-driver libva-drm2 libva-x11-2
    net-tools nmap fail2ban ufw
    dpkg-dev gzip
    libnginx-mod-http-auth-pam
    libva-x11-2 libva-drm2
)

echo ""
echo -e "${BOLD}=================================================${NC}"
echo -e "${BOLD}  VideoWall USB Installer Builder${NC}"
echo -e "${BOLD}  JJ Smart Solutions${NC}"
echo -e "${BOLD}=================================================${NC}"
echo ""

# ── Root password for the installed system ────────────────────────────────────
if [ -n "${VW_ROOT_PASS:-}" ]; then
    ROOT_PASS="$VW_ROOT_PASS"
    info "Using root password from VW_ROOT_PASS environment variable."
else
    echo -e "Set the ${BOLD}secret root password${NC} for VideoWall systems:"
    while true; do
        read -s -p "  Root password: " ROOT_PASS; echo ""
        read -s -p "  Confirm:       " ROOT_PASS2; echo ""
        [[ "$ROOT_PASS" == "$ROOT_PASS2" ]] && break
        warn "Passwords don't match — try again."
    done
    [[ ${#ROOT_PASS} -lt 8 ]] && error "Password must be at least 8 characters"
fi
ROOT_HASH=$(openssl passwd -6 "$ROOT_PASS")
info "Root password configured."
echo ""

# ── Build dependencies ────────────────────────────────────────────────────────
info "Checking build tools..."
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    xorriso isolinux syslinux-utils dpkg-dev wget > /dev/null 2>&1
info "Build tools ready."

# ── Debian ISO ────────────────────────────────────────────────────────────────
if [ -f "$ISO_CACHE" ]; then
    info "Using cached Debian ISO: $ISO_CACHE"
else
    info "Finding latest Debian 12 (Bookworm) netinstall ISO..."
    ARCHIVE_INDEX=$(wget -qO- "$DEBIAN_12_ARCHIVE/")
    VER_12=$(echo "$ARCHIVE_INDEX" | grep -o '12\.[0-9]*\.[0-9]*' | sort -V | tail -1)
    [ -z "$VER_12" ] && VER_12="12.13.0"
    ISO_URL="${DEBIAN_12_ARCHIVE}/${VER_12}/amd64/iso-cd/debian-${VER_12}-amd64-netinst.iso"
    info "Downloading debian-${VER_12}-amd64-netinst.iso (~650 MB)..."
    wget -q --show-progress -O "$ISO_CACHE" "$ISO_URL"
fi

# ── Build directory ───────────────────────────────────────────────────────────
info "Preparing build workspace..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"/{vw-packages,vw-pip,videowall}

# ── VideoWall files ───────────────────────────────────────────────────────────
info "Copying VideoWall source files..."
cp -r "$VIDEOWALL_DIR"/. "$BUILD_DIR/videowall/"
# Strip runtime/personal files — installer writes a clean config
rm -f  "$BUILD_DIR/videowall/config.yml"
rm -f  "$BUILD_DIR/videowall/state.json"
rm -f  "$BUILD_DIR/videowall/supervisor.py.bak"
rm -rf "$BUILD_DIR/videowall/static/snapshots/"
mkdir -p "$BUILD_DIR/videowall/static/snapshots"
info "VideoWall files copied."

# ── Download apt packages (recursive deps) ────────────────────────────────────
info "Resolving package dependency tree..."
DEP_LIST=$(apt-cache depends --recurse --no-recommends --no-suggests \
    --no-conflicts --no-breaks --no-replaces --no-enhances \
    "${PACKAGES[@]}" 2>/dev/null \
    | grep "^\w" | grep -v "<" | sort -u | tr '\n' ' ')

info "Downloading packages (this takes a few minutes)..."
cd "$BUILD_DIR/vw-packages"
# shellcheck disable=SC2086
apt-get download $DEP_LIST 2>/dev/null || true
PKG_COUNT=$(ls ./*.deb 2>/dev/null | wc -l)
info "Downloaded $PKG_COUNT packages."

# Build the package index here (build machine has dpkg-dev; target won't)
info "Building offline package index..."
dpkg-scanpackages -m . 2>/dev/null | gzip -9 > Packages.gz
info "Package index ready."

# ── Download pip wheels ───────────────────────────────────────────────────────
info "Downloading Python package wheels..."
pip3 download flask pyyaml psutil -d "$BUILD_DIR/vw-pip" -q
info "Python wheels ready."

# ── Extract Debian ISO ────────────────────────────────────────────────────────
info "Extracting Debian installer ISO..."
mkdir -p /tmp/iso-mnt "$BUILD_DIR/iso-work"
mount -o loop,ro "$ISO_CACHE" /tmp/iso-mnt
cp -rp /tmp/iso-mnt/. "$BUILD_DIR/iso-work/"
umount /tmp/iso-mnt
chmod -R u+w "$BUILD_DIR/iso-work"
info "ISO extracted."

# ── Inject files into ISO ─────────────────────────────────────────────────────
info "Injecting VideoWall bundle into ISO..."
cp -r "$BUILD_DIR/vw-packages" "$BUILD_DIR/iso-work/"
cp -r "$BUILD_DIR/vw-pip"      "$BUILD_DIR/iso-work/"
cp -r "$BUILD_DIR/videowall"   "$BUILD_DIR/iso-work/"
cp    "$VIDEOWALL_DIR/build/vw-postinstall.sh" "$BUILD_DIR/iso-work/"

# ── Generate preseed.cfg ──────────────────────────────────────────────────────
info "Writing preseed.cfg..."
cat > "$BUILD_DIR/iso-work/preseed.cfg" << PRESEED
# ============================================================
#  VideoWall Automated Installer — JJ Smart Solutions
#  Built: $(date)
# ============================================================

# Locale / keyboard
d-i debian-installer/locale string en_US.UTF-8
d-i keyboard-configuration/xkb-keymap select us

# Network — DHCP, hostname
d-i netcfg/choose_interface select auto
d-i netcfg/get_hostname string videowall
d-i netcfg/get_domain string local

# No internet mirror — fully offline
d-i apt-setup/use_mirror boolean false
d-i apt-setup/services-select multiselect
d-i apt-setup/security_host string

# Clock — UTC internally, US Eastern display. No NTP during install.
d-i clock-setup/utc boolean true
d-i time/zone string America/New_York
d-i clock-setup/ntp boolean false

# Disk — auto-select first non-removable disk, wipe it, single partition
d-i partman/early_command string \\
    DISK=\$(list-devices disk | head -1); \\
    debconf-set partman-auto/disk "\$DISK"
d-i partman-auto/method string regular
d-i partman-auto/choose_recipe select atomic
d-i partman-partitioning/confirm_write_new_label boolean true
d-i partman/choose_partition select finish
d-i partman/confirm boolean true
d-i partman/confirm_nooverwrite boolean true
d-i partman-lvm/confirm boolean true
d-i partman-lvm/confirm_nooverwrite boolean true
d-i partman-md/confirm boolean true

# Root account — secret password set at build time
d-i passwd/root-login boolean true
d-i passwd/root-password-crypted password ${ROOT_HASH}
d-i passwd/make-user boolean false

# Minimal base — no recommended packages, no extra tasks
d-i base-installer/install-recommends boolean false
tasksel tasksel/first multiselect
d-i pkgsel/include string sudo
d-i pkgsel/upgrade select none
d-i pkgsel/update-policy select none
popularity-contest popularity-contest/participate boolean false

# Bootloader
d-i grub-installer/only_debian boolean true
d-i grub-installer/with_other_os boolean true
d-i grub-installer/bootdev string default

# Post-install: copy bundle from USB and run VideoWall installer
d-i preseed/late_command string \\
    mkdir -p /target/tmp/vw-packages /target/tmp/vw-pip /target/opt/videowall; \\
    cp -rp /cdrom/vw-packages/. /target/tmp/vw-packages/; \\
    cp -rp /cdrom/vw-pip/.      /target/tmp/vw-pip/; \\
    cp -rp /cdrom/videowall/.   /target/opt/videowall/; \\
    cp /cdrom/vw-postinstall.sh /target/tmp/vw-postinstall.sh; \\
    chmod +x /target/tmp/vw-postinstall.sh; \\
    in-target bash /tmp/vw-postinstall.sh 2>&1 | tee /var/log/vw-install.log

d-i finish-install/reboot_in_progress note
PRESEED

# ── Bootloader — auto-boot into installer with preseed ────────────────────────
info "Patching bootloader for automated install..."

# GRUB (UEFI)
GRUB_CFG="$BUILD_DIR/iso-work/boot/grub/grub.cfg"
if [ -f "$GRUB_CFG" ]; then
    # Insert VideoWall entry at top, timeout 5 s
    cat > /tmp/grub-header.cfg << 'GRUBHDR'
set default=0
set timeout=5
menuentry "Install VideoWall (JJ Smart Solutions)" {
    set background_color=black
    linux   /install.amd/vmlinuz auto=true priority=critical \
            preseed/file=/cdrom/preseed.cfg --- quiet
    initrd  /install.amd/initrd.gz
}
GRUBHDR
    cat /tmp/grub-header.cfg "$GRUB_CFG" > /tmp/grub-new.cfg
    cp /tmp/grub-new.cfg "$GRUB_CFG"
    info "GRUB (UEFI) configured."
fi

# Isolinux (BIOS)
ISOLINUX_CFG="$BUILD_DIR/iso-work/isolinux/txt.cfg"
if [ -f "$ISOLINUX_CFG" ]; then
    cat > "$ISOLINUX_CFG" << 'ISOLINUX'
default videowall
label videowall
    menu label Install VideoWall ^(JJ Smart Solutions)
    kernel /install.amd/vmlinuz
    append initrd=/install.amd/initrd.gz auto=true priority=critical \
           preseed/file=/cdrom/preseed.cfg --- quiet
ISOLINUX
    # 5-second timeout
    sed -i 's/^TIMEOUT .*/TIMEOUT 50/' "$BUILD_DIR/iso-work/isolinux/isolinux.cfg" 2>/dev/null || true
    info "Isolinux (BIOS) configured."
fi

# ── Recalculate checksums ─────────────────────────────────────────────────────
info "Recalculating ISO checksums..."
cd "$BUILD_DIR/iso-work"
find . -follow -type f ! -name "md5sum.txt" | sort | xargs md5sum > md5sum.txt

# ── Repack bootable ISO (BIOS + UEFI hybrid) ─────────────────────────────────
info "Repacking ISO — BIOS + UEFI hybrid..."
xorriso -as mkisofs \
    -r -J -joliet-long -l -cache-inodes \
    -isohybrid-mbr /usr/lib/ISOLINUX/isohdpfx.bin \
    -c isolinux/boot.cat \
    -b isolinux/isolinux.bin \
    -no-emul-boot -boot-load-size 4 -boot-info-table \
    -eltorito-alt-boot \
    -e boot/grub/efi.img \
    -no-emul-boot -isohybrid-gpt-basdat \
    -o "$OUTPUT_ISO" \
    "$BUILD_DIR/iso-work" 2>&1 | grep -E "^(xorriso|Written|ISO)" || true

ISO_SIZE=$(du -sh "$OUTPUT_ISO" | cut -f1)

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}=================================================${NC}"
echo -e "  ${GREEN}VideoWall USB Installer Ready!${NC}"
echo -e "${BOLD}=================================================${NC}"
echo ""
echo -e "  File:  ${BOLD}$OUTPUT_ISO${NC}"
echo -e "  Size:  ${BOLD}$ISO_SIZE${NC}"
echo ""
echo -e "  ${BOLD}Flash to USB (Linux/Mac):${NC}"
echo -e "  dd if=$OUTPUT_ISO of=/dev/sdX bs=4M status=progress"
echo ""
echo -e "  ${BOLD}Flash to USB (Windows / Mac GUI):${NC}"
echo -e "  Use balenaEtcher — free at etcher.balena.io"
echo ""
echo -e "  ${BOLD}Install instructions for the customer:${NC}"
echo -e "  1. Plug USB into the mini PC"
echo -e "  2. Power on — if it doesn't boot from USB, press F11/F12"
echo -e "     for boot menu and select the USB drive"
echo -e "  3. The screen will show 'Install VideoWall'"
echo -e "     — wait, do not touch anything (~15-20 min)"
echo -e "  4. Machine reboots automatically into VideoWall"
echo -e "  5. Connect phone/laptop to same network,"
echo -e "     open https://<device-ip> to configure cameras"
echo ""
echo -e "  ${BOLD}Disable Secure Boot${NC} in BIOS if the USB won't boot."
echo -e "${BOLD}=================================================${NC}"
echo ""
