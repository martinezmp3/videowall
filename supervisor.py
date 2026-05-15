#!/usr/bin/env python3
import subprocess, threading, time, yaml, os, sys, signal, logging, smtplib, socket, json
from datetime import datetime
from email.mime.text import MIMEText

CONFIG_PATH = "/opt/videowall/config.yml"
STATE_FILE  = "/opt/videowall/state.json"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(), logging.FileHandler("/var/log/videowall/supervisor.log")]
)
log = logging.getLogger(__name__)

def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

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
        "--loop=inf","--hwdec=vaapi","--vo=gpu","--gpu-context=x11egl",
        "--profile=low-latency","--rtsp-transport=tcp",
        "--demuxer-readahead-secs=0","--cache=no",
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
        self.thread         = threading.Thread(target=self._run, daemon=True)

    def start(self): self.thread.start()

    def stop(self):
        self.running = False
        self._kill_all()

    def _kill_all(self):
        for p in self.procs:
            try: p.terminate(); p.wait(timeout=3)
            except Exception:
                try: p.kill()
                except Exception: pass
        self.procs = []

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
            for cam in cfg.get('cameras',[]):
                url = cam_url(cam)
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

def main():
    log.info("VideoWall Supervisor starting...")
    for _ in range(30):
        r = subprocess.run(["xdpyinfo"], capture_output=True, env={**os.environ,"DISPLAY":":0"})
        if r.returncode == 0: break
        log.info("Waiting for X server..."); time.sleep(2)
    else:
        log.error("X server not ready"); sys.exit(1)

    config         = load_config()
    cam_index      = build_cam_index(config)
    playlist_index = build_playlist_index(config)
    geometries     = get_monitor_geometries()

    log.info(f"Monitors: {len(geometries)} — Cameras: {list(cam_index.keys())} — Playlists: {list(playlist_index.keys())}")

    threading.Thread(target=watchdog,        args=(config,), daemon=True).start()
    threading.Thread(target=write_state_loop, daemon=True).start()

    managers = []
    for i, mon in enumerate(config.get('monitors',[])):
        if i >= len(geometries):
            log.warning(f"Monitor {i+1} not connected, skipping"); continue
        m = MonitorManager(mon, geometries[i], cam_index, playlist_index)
        m.start(); managers.append(m)

    def shutdown(sig, frame):
        log.info("Shutting down...")
        for m in managers: m.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    while True: time.sleep(10)

if __name__ == "__main__":
    main()
