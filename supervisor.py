#!/usr/bin/env python3
import subprocess, threading, time, yaml, os, sys, signal, logging, smtplib, socket
from email.mime.text import MIMEText

CONFIG_PATH = "/opt/videowall/config.yml"

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

def cam_url(cam):
    if cam.get('use_substream') and cam.get('substream'):
        return cam['substream']
    return cam['url']

def get_monitor_geometries():
    result = subprocess.run(
        ["xrandr", "--listmonitors"], capture_output=True, text=True,
        env={**os.environ, "DISPLAY": ":0"}
    )
    monitors = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) >= 3:
            geom = parts[2].lstrip('+*')
            try:
                seg = geom.split('+')
                wh = seg[0]
                x, y = int(seg[1]), int(seg[2])
                w = int(wh.split('x')[0].split('/')[0])
                h = int(wh.split('x')[1].split('/')[0])
                monitors.append({'w': w, 'h': h, 'x': x, 'y': y})
            except Exception as e:
                log.warning(f"Cannot parse monitor line: {line} — {e}")
    return monitors

def grid_positions(monitor, layout, num_cameras):
    w, h, ox, oy = monitor['w'], monitor['h'], monitor['x'], monitor['y']
    grid = {1:(1,1), 2:(2,1), 4:(2,2), 6:(3,2), 9:(3,3), 16:(4,4)}
    cols, rows = grid.get(layout, (2,2))
    cw, ch = w // cols, h // rows
    return [
        {'w': cw, 'h': ch, 'x': ox + (i % cols) * cw, 'y': oy + (i // cols) * ch}
        for i in range(min(num_cameras, cols * rows))
    ]

def launch_mpv(cam, pos):
    url = cam_url(cam)
    geo = f"{pos['w']}x{pos['h']}+{pos['x']}+{pos['y']}"
    cmd = [
        "mpv", url,
        f"--geometry={geo}",
        "--no-border", "--no-osc", "--no-input-default-bindings",
        "--loop=inf", "--hwdec=vaapi", "--vo=gpu", "--gpu-context=x11egl",
        "--profile=low-latency", "--rtsp-transport=tcp",
        "--demuxer-readahead-secs=0", "--cache=no",
        f"--title={cam['name']}", "--ontop", "--really-quiet",
    ]
    env = {**os.environ, "DISPLAY": ":0", "LIBVA_DRIVER_NAME": "iHD"}
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    log.info(f"MPV: {cam['name']} @ {geo} PID={proc.pid}")
    return proc

def send_alert(config, subject, body):
    try:
        s = config.get('system', {})
        user, pwd, to = s.get('alert_email_from',''), s.get('gmail_app_password',''), s.get('alert_email_to','')
        if not all([user, pwd, to]):
            return
        msg = MIMEText(body)
        msg['Subject'] = f"[VideoWall] {subject}"
        msg['From'] = user
        msg['To'] = to
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as srv:
            srv.login(user, pwd)
            srv.send_message(msg)
        log.info(f"Alert sent: {subject}")
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

# Shared state for dashboard to read
rotation_state = {}  # monitor_id -> {step_name, step_idx, total_steps}
rotation_lock = threading.Lock()

class MonitorManager:
    def __init__(self, mon_config, geometry, cam_index):
        self.config = mon_config
        self.geo = geometry
        self.cam_index = cam_index
        self.step_idx = 0
        self.procs = []
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)

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
        cam_ids = step.get('cameras', [])
        cams = [self.cam_index[cid] for cid in cam_ids if cid in self.cam_index]
        layout = step.get('layout', len(cams))
        positions = grid_positions(self.geo, layout, len(cams))
        self.procs = [launch_mpv(cam, positions[i]) for i, cam in enumerate(cams[:len(positions)])]

    def _restart_dead(self, step):
        cam_ids = step.get('cameras', [])
        cams = [self.cam_index[cid] for cid in cam_ids if cid in self.cam_index]
        positions = grid_positions(self.geo, step.get('layout', len(cams)), len(cams))
        for i, proc in enumerate(self.procs):
            if proc.poll() is not None and i < len(cams) and i < len(positions):
                log.warning(f"Restarting dead stream: {cams[i]['name']}")
                self.procs[i] = launch_mpv(cams[i], positions[i])

    def _run(self):
        rotation = self.config.get('rotation', [])
        if not rotation:
            log.warning(f"Monitor {self.config.get('id')} has no rotation steps"); return

        mon_id = self.config.get('id', 1)
        while self.running:
            step = rotation[self.step_idx]
            log.info(f"Monitor {mon_id}: [{self.step_idx+1}/{len(rotation)}] '{step.get('name')}' for {step.get('duration',0)}s")

            with rotation_lock:
                rotation_state[mon_id] = {
                    'step_name': step.get('name'),
                    'step_idx': self.step_idx,
                    'total_steps': len(rotation),
                    'duration': step.get('duration', 0),
                    'layout': step.get('layout', 1),
                }

            self._launch_step(step)
            duration = step.get('duration', 0)

            if duration > 0:
                end = time.time() + duration
                while self.running and time.time() < end:
                    time.sleep(2)
                    self._restart_dead(step)
                self.step_idx = (self.step_idx + 1) % len(rotation)
            else:
                while self.running:
                    time.sleep(5)
                    self._restart_dead(step)

def watchdog(config):
    interval = config.get('system', {}).get('watchdog_interval', 30)
    dead = set()
    while True:
        time.sleep(interval)
        try:
            cfg = load_config()
            for cam in cfg.get('cameras', []):
                url = cam_url(cam)
                alive = check_stream(url)
                if not alive and cam['id'] not in dead:
                    dead.add(cam['id'])
                    log.warning(f"Stream DOWN: {cam['name']}")
                    send_alert(cfg, f"Stream Down: {cam['name']}",
                               f"Camera '{cam['name']}' at {url} is not responding.\nHost: {socket.gethostname()}")
                elif alive and cam['id'] in dead:
                    dead.discard(cam['id'])
                    log.info(f"Stream RECOVERED: {cam['name']}")
                    send_alert(cfg, f"Stream Recovered: {cam['name']}",
                               f"Camera '{cam['name']}' is back online.\nHost: {socket.gethostname()}")
        except Exception as e:
            log.error(f"Watchdog error: {e}")

def write_state(managers):
    """Write rotation state to file so Flask can read it without importing supervisor"""
    import json
    state_path = "/opt/videowall/state.json"
    while True:
        time.sleep(2)
        try:
            with rotation_lock:
                state = dict(rotation_state)
            with open(state_path, 'w') as f:
                json.dump(state, f)
        except Exception:
            pass

def main():
    log.info("VideoWall Supervisor starting...")
    for _ in range(30):
        r = subprocess.run(["xdpyinfo"], capture_output=True, env={**os.environ,"DISPLAY":":0"})
        if r.returncode == 0: break
        log.info("Waiting for X server...")
        time.sleep(2)
    else:
        log.error("X server not ready, exiting"); sys.exit(1)

    config = load_config()
    cam_index = build_cam_index(config)
    geometries = get_monitor_geometries()
    log.info(f"Detected {len(geometries)} monitor(s): {geometries}")
    log.info(f"Camera library: {list(cam_index.keys())}")

    threading.Thread(target=watchdog, args=(config,), daemon=True).start()

    managers = []
    for i, mon in enumerate(config.get('monitors', [])):
        if i >= len(geometries):
            log.warning(f"Monitor {i+1} not connected, skipping"); continue
        m = MonitorManager(mon, geometries[i], cam_index)
        m.start(); managers.append(m)

    threading.Thread(target=write_state, args=(managers,), daemon=True).start()

    def shutdown(sig, frame):
        log.info("Shutting down...")
        for m in managers: m.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    while True: time.sleep(10)

if __name__ == "__main__":
    main()
