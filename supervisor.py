#!/usr/bin/env python3
import subprocess, threading, time, yaml, os, sys, signal, logging, smtplib, socket, json, re
from datetime import datetime
from email.mime.text import MIMEText

CONFIG_PATH = "/opt/videowall/config.yml"
STATE_FILE        = "/opt/videowall/state.json"
SECOND_SCREEN_IMG = "/opt/videowall/static/second_screen_setup.png"

from logging.handlers import RotatingFileHandler as _RFH

LOG_FILE = "/var/log/videowall/supervisor.log"
_fmt     = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
_fh      = _RFH(LOG_FILE, maxBytes=5*1024*1024, backupCount=4)
_fh.setFormatter(_fmt)
_sh      = logging.StreamHandler()
_sh.setFormatter(_fmt)
logging.root.setLevel(logging.INFO)
logging.root.addHandler(_fh)
logging.root.addHandler(_sh)
log = logging.getLogger(__name__)

def apply_log_level(cfg):
    lvl = logging.DEBUG if cfg.get('system',{}).get('debug_log') else logging.INFO
    if logging.root.level == lvl: return
    logging.root.setLevel(lvl)
    log.info(f"Log level set to {'DEBUG' if lvl == logging.DEBUG else 'INFO'}")

def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def save_config(cfg):
    """Atomically write config to avoid partial-read races."""
    tmp = CONFIG_PATH + '.tmp'
    with open(tmp, 'w') as f:
        yaml.dump(cfg, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp, CONFIG_PATH)

def build_cam_index(config):
    return {c['id']: c for c in config.get('cameras', [])}

def build_playlist_index(config):
    return {p['id']: p for p in config.get('playlists', [])}

def cam_url(cam):
    if cam.get('use_substream') and cam.get('substream'):
        return cam['substream']
    return cam['url']

def is_schedule_active(rule, now=None):
    if now is None:
        now = datetime.now()
    day_map = ['mon','tue','wed','thu','fri','sat','sun']
    today     = day_map[now.weekday()]
    yesterday = day_map[(now.weekday() - 1) % 7]
    days = rule.get('days', [])
    try:
        sh, sm = map(int, rule['start'].split(':'))
        eh, em = map(int, rule['end'].split(':'))
    except Exception:
        return False
    s_min = sh * 60 + sm
    e_min = eh * 60 + em
    c_min = now.hour * 60 + now.minute
    if s_min < e_min:
        return today in days and s_min <= c_min < e_min
    else:  # overnight
        if today in days and c_min >= s_min:
            return True
        if yesterday in days and c_min < e_min:
            return True
        return False

def get_active_playlist_id(mon_config, playlist_index):
    now = datetime.now()
    for rule in mon_config.get('schedule', []):
        if is_schedule_active(rule, now):
            pl_id = rule.get('playlist')
            if pl_id in playlist_index:
                return pl_id
    return mon_config.get('default_playlist')

def get_monitor_geometries():
    result = subprocess.run(
        ["xrandr","--listmonitors"], capture_output=True, text=True,
        env={**os.environ,"DISPLAY":":0"}
    )
    monitors = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) >= 3:
            geom = parts[2].lstrip('+*')
            try:
                seg = geom.split('+')
                wh  = seg[0]
                x, y = int(seg[1]), int(seg[2])
                w = int(wh.split('x')[0].split('/')[0])
                h = int(wh.split('x')[1].split('/')[0])
                monitors.append({'w':w,'h':h,'x':x,'y':y})
            except Exception as e:
                log.warning(f"Cannot parse monitor: {line} — {e}")
    # Sort left-to-right so Monitor 1 in config = leftmost physical screen
    monitors.sort(key=lambda m: (m['x'], m['y']))
    return monitors

def grid_positions(monitor, layout, num_cameras):
    w,h,ox,oy = monitor['w'],monitor['h'],monitor['x'],monitor['y']

    # ── Custom layouts ────────────────────────────────────────
    if layout == '3L4S':
        # 3 large (quarter each) + bottom-right quarter split into 4 small
        positions = [
            {'w':w//2,  'h':h//2,  'x':ox,        'y':oy},          # Large TL
            {'w':w//2,  'h':h//2,  'x':ox+w//2,   'y':oy},          # Large TR
            {'w':w//2,  'h':h//2,  'x':ox,        'y':oy+h//2},     # Large BL
            {'w':w//4,  'h':h//4,  'x':ox+w//2,   'y':oy+h//2},     # Small 1
            {'w':w//4,  'h':h//4,  'x':ox+3*w//4, 'y':oy+h//2},     # Small 2
            {'w':w//4,  'h':h//4,  'x':ox+w//2,   'y':oy+3*h//4},   # Small 3
            {'w':w//4,  'h':h//4,  'x':ox+3*w//4, 'y':oy+3*h//4},   # Small 4
        ]
        return positions[:num_cameras]

    elif layout == 'feat8':
        # 1 large main (top-right 3/4) + 3 left sidebar + 4 bottom strip
        positions = [
            {'w':3*w//4,'h':3*h//4,'x':ox+w//4,   'y':oy},          # Main (large)
            {'w':w//4,  'h':h//4,  'x':ox,        'y':oy},          # Left top
            {'w':w//4,  'h':h//4,  'x':ox,        'y':oy+h//4},     # Left mid
            {'w':w//4,  'h':h//4,  'x':ox,        'y':oy+h//2},     # Left bot
            {'w':w//4,  'h':h//4,  'x':ox,        'y':oy+3*h//4},   # Bottom 1
            {'w':w//4,  'h':h//4,  'x':ox+w//4,   'y':oy+3*h//4},   # Bottom 2
            {'w':w//4,  'h':h//4,  'x':ox+w//2,   'y':oy+3*h//4},   # Bottom 3
            {'w':w//4,  'h':h//4,  'x':ox+3*w//4, 'y':oy+3*h//4},   # Bottom 4
        ]
        return positions[:num_cameras]

    # ── Standard equal grids ──────────────────────────────────
    grid = {1:(1,1),2:(2,1),4:(2,2),6:(3,2),9:(3,3),16:(4,4)}
    cols,rows = grid.get(int(layout) if str(layout).lstrip('-').isdigit() else 4,(2,2))
    cw,ch = w//cols, h//rows
    return [
        {'w':cw,'h':ch,'x':ox+(i%cols)*cw,'y':oy+(i//cols)*ch}
        for i in range(min(num_cameras, cols*rows))
    ]

def launch_mpv(cam, pos):
    url = cam_url(cam)
    geo = f"{pos['w']}x{pos['h']}+{pos['x']}+{pos['y']}"
    fill_mode = cam.get('fill_mode', 'stretch')
    fill_flags = []
    if fill_mode == 'stretch':
        fill_flags = ['--keepaspect=no']
    elif fill_mode == 'zoom':
        fill_flags = ['--keepaspect=yes', '--panscan=1.0']
    # fit = default, no extra flags needed
    cmd = [
        "mpv", url, f"--geometry={geo}",
        "--no-border","--no-osc","--no-input-default-bindings",
        "--hwdec=vaapi","--vo=gpu","--gpu-context=x11egl",
        "--scale=bilinear","--dscale=bilinear","--cscale=bilinear",
        "--no-audio","--vd-lavc-threads=2",
        "--profile=low-latency","--rtsp-transport=tcp",
        "--demuxer-readahead-secs=0.5","--cache=no",
        f"--title={cam['name']}","--ontop","--really-quiet",
    ] + fill_flags
    env = {**os.environ,"DISPLAY":":0","LIBVA_DRIVER_NAME":"iHD"}
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    log.info(f"MPV: {cam['name']} @ {geo} PID={proc.pid}")
    return proc

def send_alert(config, subject, body):
    try:
        s = config.get('system',{})
        user,pwd,to = s.get('alert_email_from',''),s.get('gmail_app_password',''),s.get('alert_email_to','')
        if not all([user,pwd,to]): return
        msg = MIMEText(body)
        msg['Subject'] = f"[VideoWall] {subject}"
        msg['From'] = user; msg['To'] = to
        with smtplib.SMTP_SSL('smtp.gmail.com',465) as srv:
            srv.login(user,pwd); srv.send_message(msg)
        log.info(f"Alert: {subject}")
    except Exception as e:
        log.error(f"Email failed: {e}")

def check_stream(url, timeout=8):
    try:
        r = subprocess.run(
            ["ffprobe","-v","quiet","-rtsp_transport","tcp","-i",url,
             "-show_entries","format=duration","-of","csv=p=0"],
            capture_output=True, timeout=timeout
        )
        return r.returncode == 0
    except Exception:
        return False

def _auto_add_monitors(config, geometries):
    """Add stub entries to config for newly connected displays."""
    existing = len(config.get('monitors', []))
    added = False
    for idx in range(existing, len(geometries)):
        mon_id = idx + 1
        config.setdefault('monitors', []).append({
            'id': mon_id, 'name': f'Monitor {mon_id}',
            'default_playlist': None, 'schedule': []
        })
        log.info(f"Auto-detected Monitor {mon_id} — added to config")
        added = True
    if added:
        save_config(config)

def screen_monitor():
    """Poll xrandr every 15 s; trigger SIGUSR1 when monitor count changes."""
    last_count = -1
    while True:
        time.sleep(15)
        try:
            count = len(get_monitor_geometries())
            if last_count < 0:
                last_count = count
                continue
            if count != last_count:
                log.info(f"Display change: {last_count} → {count} monitor(s) — reloading")
                last_count = count
                os.kill(os.getpid(), signal.SIGUSR1)
        except Exception as e:
            log.error(f"Screen monitor: {e}")

rotation_state = {}
rotation_lock  = threading.Lock()

class MonitorManager:
    def __init__(self, mon_config, geometry, cam_index, playlist_index):
        self.config         = mon_config
        self.geo            = geometry
        self.cam_index      = cam_index
        self.playlist_index = playlist_index
        self.active_pl_id   = None
        self.step_idx       = 0
        self.procs          = []
        self.running        = True
        self._setup_proc    = None
        self.thread         = threading.Thread(target=self._run, daemon=True)

    def start(self): self.thread.start()

    def stop(self):
        self.running = False
        self._kill_all()

    def _kill_all(self):
        if self._setup_proc and self._setup_proc.poll() is None:
            try:
                self._setup_proc.terminate()
                self._setup_proc.wait(timeout=2)
            except Exception:
                pass
        self._setup_proc = None
        for p in self.procs:
            try: p.terminate(); p.wait(timeout=3)
            except Exception:
                try: p.kill()
                except Exception: pass
        self.procs = []

    def _show_setup_image(self):
        """Display the second-screen instruction image on this monitor's area."""
        if not os.path.exists(SECOND_SCREEN_IMG):
            return
        if self._setup_proc and self._setup_proc.poll() is None:
            return  # already showing
        geo = self.geo
        env = {**os.environ, "DISPLAY": ":0"}
        self._setup_proc = subprocess.Popen([
            "mpv", SECOND_SCREEN_IMG,
            f"--geometry={geo['w']}x{geo['h']}+{geo['x']}+{geo['y']}",
            "--no-border", "--loop-file=inf", "--keepaspect=no",
            "--vo=gpu", "--gpu-context=x11egl", "--ontop", "--really-quiet",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        log.info(f"Monitor {self.config.get('id')}: setup image PID={self._setup_proc.pid}")

    def _launch_step(self, step):
        self._kill_all()
        cams = [self.cam_index[cid] for cid in step.get('cameras',[]) if cid in self.cam_index]
        layout = step.get('layout', max(1, len(cams)))
        positions = grid_positions(self.geo, layout, len(cams))
        self.procs = [launch_mpv(cam, positions[i]) for i,cam in enumerate(cams[:len(positions)])]

    def _restart_dead(self, step):
        cams = [self.cam_index[cid] for cid in step.get('cameras',[]) if cid in self.cam_index]
        positions = grid_positions(self.geo, step.get('layout', max(1,len(cams))), len(cams))
        for i,proc in enumerate(self.procs):
            if proc.poll() is not None and i < len(cams) and i < len(positions):
                log.warning(f"Restarting: {cams[i]['name']}")
                self.procs[i] = launch_mpv(cams[i], positions[i])

    def _update_state(self, pl_name, step, total):
        mon_id = str(self.config.get('id',1))
        with rotation_lock:
            rotation_state[mon_id] = {
                'playlist_name': pl_name,
                'step_name': step.get('name',''),
                'step_idx': self.step_idx,
                'total_steps': total,
                'duration': step.get('duration',0),
                'layout': step.get('layout',1),
                'schedule_active': self._active_schedule_name(),
            }

    def _active_schedule_name(self):
        now = datetime.now()
        for rule in self.config.get('schedule',[]):
            if is_schedule_active(rule, now):
                return rule.get('name','')
        return 'Default'

    def _run(self):
        while self.running:
            # Check if playlist should change (schedule)
            new_pl_id = get_active_playlist_id(self.config, self.playlist_index)
            if new_pl_id != self.active_pl_id:
                log.info(f"Monitor {self.config.get('id')}: playlist → '{new_pl_id}'")
                self.active_pl_id = new_pl_id
                self.step_idx = 0
                self._kill_all()

            if not self.active_pl_id or self.active_pl_id not in self.playlist_index:
                self._show_setup_image()
                log.warning(f"Monitor {self.config.get('id')}: no active playlist, waiting...")
                time.sleep(30); continue

            pl = self.playlist_index[self.active_pl_id]
            rotation = pl.get('rotation',[])
            if not rotation:
                time.sleep(30); continue

            if self.step_idx >= len(rotation):
                self.step_idx = 0

            step = rotation[self.step_idx]
            log.info(f"Monitor {self.config.get('id')} [{pl['name']}]: step {self.step_idx+1}/{len(rotation)} '{step.get('name')}'")
            self._update_state(pl['name'], step, len(rotation))
            self._launch_step(step)

            duration = step.get('duration', 0)
            if duration > 0:
                end_time = time.time() + duration
                while self.running and time.time() < end_time:
                    # Check for playlist change every 10s during wait
                    time.sleep(min(10, end_time - time.time()))
                    self._restart_dead(step)
                    new_pl = get_active_playlist_id(self.config, self.playlist_index)
                    if new_pl != self.active_pl_id:
                        break  # schedule changed, outer loop handles it
                self.step_idx = (self.step_idx + 1) % len(rotation)
            else:
                # Static — stay on this step, just monitor stream health + schedule
                while self.running:
                    time.sleep(10)
                    self._restart_dead(step)
                    new_pl = get_active_playlist_id(self.config, self.playlist_index)
                    if new_pl != self.active_pl_id:
                        break

def watchdog(config):
    interval = config.get('system',{}).get('watchdog_interval', 30)
    dead = set()
    while True:
        time.sleep(interval)
        try:
            cfg = load_config()
            apply_log_level(cfg)
            log.debug(f"Watchdog tick — checking {len(cfg.get('cameras',[]))} cameras")
            for cam in cfg.get('cameras',[]):
                url = cam_url(cam)
                log.debug(f"Health check: {cam['name']} → {url}")
                alive = check_stream(url)
                if not alive and cam['id'] not in dead:
                    dead.add(cam['id'])
                    log.warning(f"DOWN: {cam['name']}")
                    send_alert(cfg, f"Stream Down: {cam['name']}",
                               f"Camera '{cam['name']}' at {url} is not responding.\nHost: {socket.gethostname()}")
                elif alive and cam['id'] in dead:
                    dead.discard(cam['id'])
                    log.info(f"RECOVERED: {cam['name']}")
                    send_alert(cfg, f"Stream Recovered: {cam['name']}",
                               f"Camera '{cam['name']}' is back online.")
        except Exception as e:
            log.error(f"Watchdog error: {e}")

def write_state_loop():
    while True:
        time.sleep(3)
        try:
            with rotation_lock:
                state = dict(rotation_state)
            state['_ts'] = datetime.now().strftime('%H:%M:%S')
            with open(STATE_FILE,'w') as f:
                json.dump(state, f)
        except Exception: pass

def _setup_get_eth_ip():
    """Return the first non-AP global IPv4 address, or None."""
    try:
        out = subprocess.check_output(['ip', '-4', 'addr', 'show', 'scope', 'global'],
                                      text=True, stderr=subprocess.DEVNULL)
        for m in re.finditer(r'inet ([\d.]+)', out):
            ip = m.group(1)
            if not ip.startswith('10.42.'):
                return ip
        return None
    except Exception:
        return None

def _setup_ap_active():
    """Return True if NetworkManager hotspot is up (creates 10.42.0.1)."""
    try:
        out = subprocess.check_output(['ip', '-4', 'addr', 'show'],
                                      text=True, stderr=subprocess.DEVNULL)
        return '10.42.0.1' in out
    except Exception:
        return False

def _setup_try_start_ap():
    """Attempt to bring up the VideoWall-Setup WiFi hotspot."""
    if _setup_ap_active():
        return True
    log.info("Setup mode: starting WiFi hotspot 'VideoWall-Setup'...")
    try:
        r = subprocess.run([
            'nmcli', 'dev', 'wifi', 'hotspot',
            'con-name', 'VideoWall-Hotspot',
            'ssid',     'VideoWall-Setup',
            'password', 'jjsmart123',
            'band',     'bg',
        ], capture_output=True, text=True, timeout=20)
        time.sleep(3)
        active = _setup_ap_active()
        if active:
            log.info("WiFi AP started: VideoWall-Setup @ 10.42.0.1")
        else:
            log.warning(f"WiFi AP did not start (no adapter?): {r.stderr.strip()}")
        return active
    except Exception as e:
        log.warning(f"AP start failed: {e}")
        return False

def _setup_regen_screen():
    try:
        subprocess.run(["python3", "/opt/videowall/setup_screen_gen.py"],
                       env={**os.environ, "DISPLAY": ""},
                       capture_output=True, timeout=20)
    except Exception as e:
        log.warning(f"Could not regenerate setup screen: {e}")

def show_setup_screen():
    """Display the factory-reset setup screen, updating when network state changes."""
    screen_path = "/opt/videowall/static/setup_screen.png"
    env = {**os.environ, "DISPLAY": ":0"}

    log.info("Setup mode: starting WiFi AP and generating setup screen...")
    _setup_try_start_ap()
    _setup_regen_screen()

    subprocess.run(["xsetroot", "-solid", "black"], env=env)
    subprocess.run(["pkill", "-x", "mpv"], capture_output=True)

    feh_proc = None
    last_ip = _setup_get_eth_ip()
    last_ap = _setup_ap_active()

    def _start_feh():
        nonlocal feh_proc
        if feh_proc and feh_proc.poll() is None:
            feh_proc.terminate()
            try: feh_proc.wait(timeout=3)
            except Exception: pass
        feh_proc = subprocess.Popen(
            ["feh", "--fullscreen", "--auto-zoom", "--borderless", screen_path],
            env=env)

    _start_feh()

    while True:
        time.sleep(10)
        try:
            cfg = load_config()
            if not cfg.get("setup_mode"):
                log.info("Setup mode cleared — restarting display...")
                if feh_proc and feh_proc.poll() is None:
                    feh_proc.terminate()
                return
        except Exception:
            pass

        # Restart feh if it died
        if feh_proc and feh_proc.poll() is not None:
            _start_feh()

        # Detect network changes and refresh the screen
        cur_ip = _setup_get_eth_ip()
        cur_ap = _setup_ap_active()
        if cur_ip != last_ip or cur_ap != last_ap:
            log.info(f"Network change: IP={cur_ip}, AP={cur_ap} — refreshing setup screen")
            last_ip, last_ap = cur_ip, cur_ap
            _setup_regen_screen()
            _start_feh()

def main():
    log.info("VideoWall Supervisor starting...")
    for _ in range(30):
        r = subprocess.run(["xdpyinfo"], capture_output=True, env={**os.environ,"DISPLAY":":0"})
        if r.returncode == 0: break
        log.info("Waiting for X server..."); time.sleep(2)
    else:
        log.error("X server not ready"); sys.exit(1)

    config         = load_config()
    apply_log_level(config)
    # ── Setup / factory-reset mode ──────────────────────────────────────────
    if config.get("setup_mode"):
        show_setup_screen()
        # After setup_mode cleared, restart the whole supervisor cleanly
        os.execv(sys.executable, [sys.executable] + sys.argv)
        return
    cam_index      = build_cam_index(config)
    playlist_index = build_playlist_index(config)
    geometries     = get_monitor_geometries()

    log.info(f"Monitors: {len(geometries)} — Cameras: {list(cam_index.keys())} — Playlists: {list(playlist_index.keys())}")

    threading.Thread(target=watchdog,        args=(config,), daemon=True).start()
    threading.Thread(target=screen_monitor,                      daemon=True).start()
    threading.Thread(target=write_state_loop, daemon=True).start()

    managers = []
    for i, mon in enumerate(config.get('monitors',[])):
        if i >= len(geometries):
            log.warning(f"Monitor {i+1} not connected, skipping"); continue
        m = MonitorManager(mon, geometries[i], cam_index, playlist_index)
        m.start(); managers.append(m)

    _reload = threading.Event()

    def shutdown(sig, frame):
        log.info("Shutting down...")
        for m in managers: m.stop()
        sys.exit(0)

    def on_reload(sig, frame):
        _reload.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGUSR1, on_reload)

    while True:
        time.sleep(1)
        if not _reload.is_set():
            continue
        _reload.clear()
        log.info("Reload signal received — reloading config")

        # Show loading screen
        env = {**os.environ, "DISPLAY": ":0"}
        feh = subprocess.Popen(
            ["feh", "--fullscreen", "--auto-zoom", "--borderless",
             "/opt/videowall/static/loading_screen.png"],
            env=env
        )
        time.sleep(0.6)

        # Stop all camera managers
        for m in managers:
            m.stop()
        managers.clear()
        time.sleep(0.8)

        # Reload config and restart
        try:
            config         = load_config()
            cam_index      = build_cam_index(config)
            playlist_index = build_playlist_index(config)
            geometries     = get_monitor_geometries()
            _auto_add_monitors(config, geometries)
            cam_index      = build_cam_index(config)
            playlist_index = build_playlist_index(config)
            feh.terminate()
            if config.get("setup_mode"):
                log.info("Setup mode active after reload — showing setup screen")
                show_setup_screen()
                os.execv(sys.executable, [sys.executable] + sys.argv)
                return
            for i, mon in enumerate(config.get("monitors", [])):
                if i >= len(geometries):
                    log.warning(f"Monitor {i+1} not connected, skipping"); continue
                m = MonitorManager(mon, geometries[i], cam_index, playlist_index)
                m.start(); managers.append(m)
            log.info("Reload complete")
        except Exception as e:
            log.error(f"Reload failed: {e}")
            feh.terminate()

if __name__ == "__main__":
    main()
