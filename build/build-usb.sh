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
ISO_CACHE="${ISO_CACHE:-/tmp/debian-12-netinst.amd64.iso}"
# When running inside Docker (mount: -v /tmp:/build), /build maps to host /tmp
[ -d "/build" ] && _ISO_DEFAULT="/build/videowall-installer.iso" || _ISO_DEFAULT="/tmp/videowall-installer.iso"
OUTPUT_ISO="${OUTPUT_ISO:-$_ISO_DEFAULT}"
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
    openssh-server rfkill
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

# ── Build dependencies ────────────────────────────────────────────────────────
info "Checking build tools..."
apt-get update -qq > /dev/null 2>&1
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    xorriso isolinux syslinux-utils dpkg-dev wget \
    cpio gzip python3 python3-pip python3-pil \
    fonts-dejavu-core openssl > /dev/null 2>&1
info "Build tools ready."
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
# Stamp version from git commit (or build date if git unavailable)
VW_VERSION=$(git -C "$VIDEOWALL_DIR" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d)
echo "$VW_VERSION" > "$BUILD_DIR/videowall/VERSION"
info "VideoWall files copied (version: $VW_VERSION)."

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
pip3 download flask pyyaml psutil qrcode -d "$BUILD_DIR/vw-pip" -q
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

# ── Generate GRUB background image ───────────────────────────────────────────
info "Generating GRUB splash screen..."
python3 - << 'GRUB_BG_PY'
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    import sys; print("  python3-pil not available — skipping GRUB background"); sys.exit(0)
import os

W, H = 1024, 768
BG      = (13,  17,  23)
ACCENT  = (88,  166, 255)
MUTED   = (60,  70,  85)
WHITE   = (230, 237, 243)
DARK    = (22,  27,  34)
GREEN   = (63,  185, 80)

img  = Image.new('RGB', (W, H), BG)
draw = ImageDraw.Draw(img)

def font(size, bold=False):
    candidates = [
        f'/usr/share/fonts/truetype/dejavu/DejaVuSans{"-Bold" if bold else ""}.ttf',
        f'/usr/share/fonts/truetype/liberation/LiberationSans{"-Bold" if bold else "-Regular"}.ttf',
    ]
    for p in candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

def ctext(y, txt, f, color):
    bb = draw.textbbox((0,0), txt, font=f)
    x = (W - (bb[2]-bb[0])) // 2
    draw.text((x, y), txt, font=f, fill=color)

# Gradient-style horizontal bar at top and bottom
for y in range(6):
    alpha = int(255 * (1 - y/6))
    draw.rectangle([(0, y), (W, y)],   fill=ACCENT)
    draw.rectangle([(0, H-1-y), (W, H-1-y)], fill=ACCENT)

# Subtle grid pattern
for x in range(0, W, 80):
    draw.line([(x, 0), (x, H)], fill=(20, 25, 32), width=1)
for y in range(0, H, 80):
    draw.line([(0, y), (W, y)], fill=(20, 25, 32), width=1)

# Center card
cx, cy = W//2, H//2
cw, ch = 640, 300
draw.rounded_rectangle(
    [(cx-cw//2, cy-ch//2), (cx+cw//2, cy+ch//2)],
    radius=18, fill=DARK, outline=ACCENT, width=2
)

# Logo text
f_big   = font(64, bold=True)
f_sub   = font(28, bold=True)
f_small = font(20)
f_hint  = font(18)

ctext(cy - 110, "VideoWall", f_big, WHITE)
ctext(cy - 30,  "by JJ Smart Solutions", f_sub, ACCENT)

# Divider line inside card
draw.rectangle([(cx-250, cy+12), (cx+250, cy+13)], fill=MUTED)

ctext(cy + 28,  "Professional Camera Display System", f_small, MUTED)

# Bottom hint
ctext(H - 60, "Booting installer — please wait...", f_hint, MUTED)

out = '/tmp/vw-usb-build/grub-bg.png'
img.save(out)
print(f"  GRUB background saved: {out}")
GRUB_BG_PY

mkdir -p "$BUILD_DIR/iso-work/boot/grub"
cp "$BUILD_DIR/grub-bg.png" "$BUILD_DIR/iso-work/boot/grub/videowall-bg.png" 2>/dev/null || true
info "GRUB background ready."

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

# Network — skip entirely (offline install, no network needed)
d-i netcfg/enable boolean false
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

# Post-install: copy bundle from USB and register the first-boot installer.
# The heavy VideoWall install (apt packages, pip, services) runs on first boot
# via vw-firstboot.service so the user sees animated progress on screen.
# This late_command only copies files — it finishes in ~1-2 minutes.
d-i preseed/late_command string \\
    mkdir -p /target/var/lib/videowall-installer/vw-packages \\
             /target/var/lib/videowall-installer/vw-pip \\
             /target/opt/videowall \\
             /target/var/log /target/var/lib \\
             /target/etc/systemd/system/multi-user.target.wants \\
             /target/etc/systemd/system/getty@tty1.service.d; \\
    cp -rp /cdrom/vw-packages/. /target/var/lib/videowall-installer/vw-packages/; \\
    cp -rp /cdrom/vw-pip/.      /target/var/lib/videowall-installer/vw-pip/; \\
    cp -rp /cdrom/videowall/.   /target/opt/videowall/; \\
    chmod +x /target/opt/videowall/build/vw-firstboot.sh; \\
    cp /target/opt/videowall/build/vw-firstboot.service \\
       /target/etc/systemd/system/vw-firstboot.service; \\
    ln -sf /etc/systemd/system/vw-firstboot.service \\
       /target/etc/systemd/system/multi-user.target.wants/vw-firstboot.service; \\
    cp /target/opt/videowall/build/getty-autologin.conf \\
       /target/etc/systemd/system/getty@tty1.service.d/autologin.conf; \\
    cp /target/opt/videowall/build/root-bash-profile /target/root/.bash_profile; \\
    chmod +x /target/root/.bash_profile; \\
    touch /target/var/lib/videowall-firstboot; \\
    echo "Files copied — first-boot installer ready."

d-i finish-install/reboot_in_progress note
PRESEED

# ── Embed preseed into initrd ─────────────────────────────────────────────────
# Extract the initrd, add preseed.cfg to the root, and repack.
# The Debian installer's find-preseeds script looks for /preseed.cfg in the
# initrd filesystem when auto=true is set.  Appending a second cpio stream
# is unreliable; full extract+repack is the only safe method.
info "Embedding preseed.cfg into initrd (extract → inject → repack)..."
INITRD="$BUILD_DIR/iso-work/install.amd/initrd.gz"
INITRD_WORK="/tmp/initrd-repack"
rm -rf "$INITRD_WORK"
mkdir -p "$INITRD_WORK/work"

# Some Debian initrds have an uncompressed early-cpio section (microcode) before
# the main gzip stream.  Detect the gzip magic offset to handle both cases.
GZIP_OFFSET=$(python3 -c "
data = open('$INITRD', 'rb').read()
i = data.find(b'\x1f\x8b')
print(i if i >= 0 else 0)
")

if [ "$GZIP_OFFSET" -gt 0 ]; then
    dd if="$INITRD" bs=1 count="$GZIP_OFFSET" of="$INITRD_WORK/early.cpio" 2>/dev/null
    dd if="$INITRD" bs=1 skip="$GZIP_OFFSET" 2>/dev/null \
        | zcat | (cd "$INITRD_WORK/work" && cpio -id --quiet 2>/dev/null)
else
    zcat "$INITRD" | (cd "$INITRD_WORK/work" && cpio -id --quiet 2>/dev/null)
fi

cp "$BUILD_DIR/iso-work/preseed.cfg" "$INITRD_WORK/work/preseed.cfg"

(cd "$INITRD_WORK/work" && find . | cpio --quiet -o -H newc | gzip -9 > /tmp/initrd-main.gz)

if [ -f "$INITRD_WORK/early.cpio" ]; then
    cat "$INITRD_WORK/early.cpio" /tmp/initrd-main.gz > "$INITRD"
else
    cp /tmp/initrd-main.gz "$INITRD"
fi
rm -rf "$INITRD_WORK" /tmp/initrd-main.gz
info "Preseed embedded into initrd."

# ── Bootloader — auto-boot into installer ─────────────────────────────────────
# auto=true activates unattended mode; file=/preseed.cfg tells the installer
# to load the preseed from the initrd root (where we just placed it).
info "Patching bootloader for automated install..."

# GRUB (UEFI) — branded graphical menu
GRUB_CFG="$BUILD_DIR/iso-work/boot/grub/grub.cfg"
if [ -f "$GRUB_CFG" ]; then
    cat > "$GRUB_CFG" << 'GRUBCFG'
set default=0
set timeout=8
set timeout_style=menu

# ── Graphical terminal + background ──────────────────────────────────────────
if loadfont /boot/grub/fonts/unicode.pf2 ; then
    set gfxmode=1024x768,800x600,auto
    insmod gfxterm
    insmod png
    terminal_output gfxterm
    if background_image /boot/grub/videowall-bg.png ; then
        set color_normal=light-gray/black
        set color_highlight=white/blue
    fi
fi

# ── Menu style ────────────────────────────────────────────────────────────────
set menu_color_normal=cyan/black
set menu_color_highlight=black/cyan

menuentry "  Install VideoWall  —  JJ Smart Solutions" --class debian {
    linux  /install.amd/vmlinuz auto=true file=/preseed.cfg priority=critical --- quiet
    initrd /install.amd/initrd.gz
}

menuentry "  Debian standard install (manual)" {
    linux  /install.amd/vmlinuz --- quiet
    initrd /install.amd/initrd.gz
}
GRUBCFG
    info "GRUB (UEFI) configured with branded background."
fi

# Isolinux (BIOS) — replace both isolinux.cfg and txt.cfg for full control
cat > "$BUILD_DIR/iso-work/isolinux/isolinux.cfg" << 'ISOLINUXMAIN'
path
include txt.cfg
default videowall
prompt 0
timeout 50
ISOLINUXMAIN

cat > "$BUILD_DIR/iso-work/isolinux/txt.cfg" << 'ISOLINUX'
label videowall
    menu label Install VideoWall (JJ Smart Solutions)
    menu default
    kernel /install.amd/vmlinuz
    append initrd=/install.amd/initrd.gz auto=true file=/preseed.cfg priority=critical --- quiet

label manual
    menu label Debian standard install (manual)
    kernel /install.amd/vmlinuz
    append initrd=/install.amd/initrd.gz --- quiet
ISOLINUX
info "Isolinux (BIOS) configured."

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
