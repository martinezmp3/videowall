# VideoWall Setup & User Guide
**JJ Smart Solutions** — Designed & developed by Jorge Martinez

---

## Table of Contents
1. [First-Time Setup](#1-first-time-setup)
2. [Accessing the Web Admin](#2-accessing-the-web-admin)
3. [Adding Cameras](#3-adding-cameras)
4. [Creating Playlists](#4-creating-playlists)
5. [Scheduling by Time](#5-scheduling-by-time)
6. [Multi-Monitor Setup](#6-multi-monitor-setup)
7. [Network Settings (WiFi / Static IP / Hotspot)](#7-network-settings)
8. [Backup, Restore & Factory Reset](#8-backup-restore--factory-reset)
9. [Dashboard & Remote Troubleshooting](#9-dashboard--remote-troubleshooting)
10. [System Settings](#10-system-settings)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. First-Time Setup

### Hardware
- Plug HDMI cable(s) from the PC into your TV(s) **before booting**.
- Connect Ethernet (recommended) or use WiFi/Hotspot for initial setup.

### On a fresh install
The screen shows a **setup instruction card** with:
- WiFi: `VideoWall-Setup` / Password: `jjsmart123`
- Browser: `http://10.42.0.1`
- Login password: `videowall`

> **Change your admin password immediately** after first login:  
> Config → System → New Admin Password

---

## 2. Accessing the Web Admin

| Method | Address |
|--------|---------|
| Same network (Ethernet or WiFi) | `https://<device-ip>` |
| Via Hotspot (AP mode) | `http://10.42.0.1` |

- The device IP appears in the **Dashboard** under the Host stat box.
- Accept the SSL certificate warning (self-signed — this is normal).
- Default password: `videowall`

---

## 3. Adding Cameras

**Config → Cameras tab**

1. Click **Add Camera** and fill in:
   - **Name** — label shown in the UI (e.g. "Front Door")
   - **Main Stream URL** — high-res RTSP (`rtsp://...`)
   - **Sub-Stream URL** *(optional)* — low-res RTSP for weaker hardware
   - **Use Sub-Stream** — check this on older PCs (5th–7th gen i3/i5) to reduce CPU/GPU load
   - **Fill Mode** — how the video fills its slot:
     - `Stretch` — fills completely, may distort aspect ratio
     - `Zoom` — fills and crops (no black bars, no distortion)
     - `Fit` — letterboxed, preserves full image

2. Click **Add Camera**. A snapshot is captured automatically after ~3 seconds.

3. To **edit** a camera, click the **Edit** button on its card.

> **Tip:** Use sub-streams (low-res) for grid views with many cameras.  
> Use main streams for fullscreen or large-layout slots.

---

## 4. Creating Playlists

**Config → Playlists tab**

A **Playlist** is a sequence of views that rotate automatically. Each step is one view.

### Create a playlist
1. Scroll to **Add Playlist**, enter an ID (e.g. `pl_lobby`) and a Name.
2. Click **Add Playlist**.

### Add steps to a playlist
Each step = one screen layout at a time.

1. Under your playlist, click **Add Step**.
2. Configure the step:
   - **Step Name** — label for this view (e.g. "All Cameras")
   - **Layout** — choose how many cameras / arrangement:
     - `1` — Single camera fullscreen
     - `2` — Side by side
     - `4` — 2×2 grid
     - `6` — 3×2 grid
     - `9` — 3×3 grid
     - `16` — 4×4 grid
     - `3 Large + 4 Small` — 3 big cameras + 4 small in the corner
     - `Featured 8` — 1 main large + sidebar + bottom row
   - **Duration** — seconds before switching to next step (0 = never rotate)
   - **Camera Positions** — assign a camera to each slot using the dropdowns.  
     Changing the layout updates the grid instantly.
3. Click **Save**.

### Reordering steps
Use the **↑ ↓** arrows on each step.

---

## 5. Scheduling by Time

**Config → Schedule tab**

Each monitor has its own schedule. A schedule is a list of **rules** — each rule says:  
*"On these days, between these times, show this playlist."*

### Rename a monitor
Click **Rename** next to the monitor name and type a custom label (e.g. "Front Lobby TV").

### Add a schedule rule
1. Fill in the form at the bottom of a monitor's card:
   - **Rule Name** — e.g. "Business Hours"
   - **Playlist** — which playlist to show
   - **Days** — check the days this rule applies
   - **Start / End** — 24-hour time (e.g. 08:00 → 20:00)
2. Click **Add Rule**.

> **Overnight rules** work automatically.  
> E.g. Start `20:00` / End `08:00` runs from 8 PM to 8 AM.

### Default Playlist
If no rule is currently active, the **Default Playlist** plays. Set it with the dropdown at the top of each monitor's schedule card.

### Edit / Delete rules
Click **Edit** on any rule to change it in a modal. Click **Delete** to remove it.

---

## 6. Multi-Monitor Setup

The system automatically detects all connected HDMI/DisplayPort screens at boot.

| Physical position | Config name |
|-------------------|-------------|
| Leftmost screen | Monitor 1 |
| Next screen right | Monitor 2 |
| … | … |

- Each monitor has its **own schedule** and **own playlist**.
- Plug TVs in **before booting** for reliable detection.
- If you add a screen while running: go to Dashboard → **Restart Display**.

### Rename monitors
**Config → Schedule tab** → click **Rename** next to any monitor name.

---

## 7. Network Settings

**Config → Network tab**

### Ethernet
- **DHCP** — automatic IP from your router (default).
- **Static IP** — enter IP, prefix (e.g. `24`), gateway, and DNS.
- Click **Apply Ethernet Settings**. The device re-connects in ~5 seconds.

> If you're connected via Ethernet, you'll lose connection briefly when applying.

### WiFi
1. Click **Scan for Networks** — nearby networks appear with signal strength.
2. Click any network to bring up the connect form.
3. Enter the password and click **Connect** (up to 30 seconds).
4. **Disconnect** button disconnects from current WiFi.

### Access Point (Hotspot) Mode
Use this when there's no existing network at a customer site.

1. Set a network name (SSID) and password (min 8 characters).
2. Click **Start Hotspot**.
3. Connect your phone/laptop to that WiFi network.
4. Browse to `http://10.42.0.1` to reach the admin panel.

> When the hotspot is active, the device cannot connect to the internet  
> at the same time (WiFi hardware used for one purpose at a time).

---

## 8. Backup, Restore & Factory Reset

**Config → System tab**

### Backup
Click **Download Backup** to save a `.yml` file of all settings — cameras, playlists, schedules, and system config. Keep this file safe.

### Restore
Upload a previously downloaded backup file. **Overwrites all current settings.** The display restarts automatically.

### Factory Reset
> ⚠️ **This cannot be undone without a backup.**

1. Click **Factory Reset…**
2. Type `RESET` to confirm.

**What happens:**
- All cameras, playlists, and schedules are deleted
- Admin password resets to `videowall`
- WiFi hotspot `VideoWall-Setup` starts automatically
- The TV screen switches to the setup instruction card
- You are logged out

The device is ready for a fresh setup without rebooting.

> Always do a **Backup** before a factory reset if you might want to restore later.

---

## 9. Dashboard & Remote Troubleshooting

**Dashboard** (home page after login)

### Stats
- **CPU / RAM / Disk** — live system health
- **Host** — hostname and current IP addresses

### Displays
Shows each connected monitor and its current playlist + active step name.

### Controls
- **Restart Display** — reloads camera streams without rebooting. Use this after changing settings if they don't apply automatically (takes ~2 seconds).
- **Reboot PC** — fully reboots the machine (requires physical presence to verify it comes back up).

### Live Screenshot
Click **Capture** to take a screenshot of everything currently on the display.  
- View it in-browser or click to open full-size.
- **Download** to save to your computer.
- Great for remote support — see exactly what the customer sees.

### System Log
Live tail of the supervisor log, color-coded by severity:
- Gray = info (normal operation)
- Orange = warnings (stream down, no playlist)
- Red = errors

Use **Filter** to show only warnings/errors. Enable **Auto** to refresh every 15 seconds. Click **Download** to get the full log file.

---

## 10. System Settings

**Config → System tab**

| Setting | Description |
|---------|-------------|
| Gmail Address | Sender email for stream-down alerts |
| Alert Recipient | Email that receives alerts |
| Gmail App Password | [Google App Password](https://myaccount.google.com/apppasswords) (not your regular password) |
| Watchdog Interval | How often (seconds) to check if streams are alive |
| New Admin Password | Change the web login password |
| Debug Logging | Enables verbose log output — use only when troubleshooting |

Click **Send Test Email** to verify email alerts are working.

---

## 11. Troubleshooting

### Screen is black / cameras not showing
1. Check Dashboard → **System Log** for errors.
2. Take a **Live Screenshot** to see actual display output.
3. Click **Restart Display** on the Dashboard.
4. Verify RTSP URLs still work (camera may have rebooted with a new IP).

### One camera shows black / not loading
- The stream may be down. The watchdog will automatically restart it.
- Check the log for `DOWN: <camera name>`.
- Try **Edit** on the camera and test the URL in VLC or another player.

### Settings saved but display didn't change
- Click **Restart Display** on the Dashboard.
- If still not working, check the log for `[ERROR]` entries.

### WiFi won't connect — "Secrets required" error
- Delete the network from saved connections and try again.
- Make sure you're entering the correct password.
- The password field must not be left empty for secured networks.

### No cameras on external TV
- Verify the TV is plugged in **before** the PC boots.
- Click **Restart Display** — it re-reads the connected monitors.
- Check Dashboard → Displays to confirm the monitor is detected.

### System log shows "DOWN" for all cameras after reboot
- The cameras may take 1-2 minutes to come back online after a power cycle.
- The watchdog will auto-recover them — watch the log for `RECOVERED:` messages.

### Log fills up / disk space
- Logs rotate automatically at 5 MB each, keeping up to 4 backups (20 MB max).
- Download the log from Dashboard before it rotates if you need history.

---

*VideoWall v1.0 — JJ Smart Solutions — jjsmartsolutions.com*
