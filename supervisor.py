#!/usr/bin/env python3
import subprocess, threading, time, yaml, os, sys, signal, logging, smtplib, socket
from email.mime.text import MIMEText
from pathlib import Path

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
                wh, x, y = geom.split('+')[0], geom.split('+')[1], geom.split('+')[2]
                w = int(wh.split('x')[0].split('/')[0])
                h = int(wh.split('x')[1].split('/')[0])
                monitors.append({'w': w, 'h': h, 'x': int(x), 'y': int(y)})
            except Exception as e:
                log.warning(f"Could not parse monitor: {line} - {e}")
    return monitors

def grid_positions(monitor, layout, num_cameras):
    w, h, ox, oy = monitor['w'], monitor['h'], monitor['x'], monitor['y']
    grid = {1:(1,1), 2:(2,1), 4:(2,2), 6:(3,2), 9:(3,3), 16:(4,4)}
    cols, rows = grid.get(layout, (2,2))
    cell_w, cell_h = w // cols, h // rows
    positions = []
    for i in range(min(num_cameras, cols * rows)):
        col, row = i % cols, i // cols
        positions.append({'w': cell_w, 'h': cell_h, 'x': ox + col*cell_w, 'y': oy + row*cell_h})
    return positions

def launch_mpv(camera, pos, display=":0"):
    url = camera.get('substream', camera['url']) if camera.get('use_substream') and camera.get('substream') else camera['url']
    geometry = f"{pos['w']}x{pos['h']}+{pos['x']}+{pos['y']}"
    cmd = [
        "mpv", url,
        f"--geometry={geometry}",
        "--no-border", "--no-osc", "--no-input-default-bindings",
        "--loop=inf", "--hwdec=vaapi", "--vo=gpu", "--gpu-context=x11egl",
        "--profile=low-latency", "--rtsp-transport=tcp",
        "--demuxer-readahead-secs=0", "--cache=no",
        f"--title={camera['name']}", "--ontop", "--really-quiet",
    ]
    env = {**os.environ, "DISPLAY": display, "LIBVA_DRIVER_NAME": "iHD"}
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    log.info(f"MPV launched: {camera['name']} at {geometry} PID={proc.pid}")
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
        log.error(f"Email alert failed: {e}")

def check_stream(url, timeout=8):
    try:
        r = subprocess.run(
            ["ffprobe","-v","quiet","-rtsp_transport","tcp","-i",url,"-show_entries","format=duration","-of","csv=p=0"],
            capture_output=True, timeout=timeout
        )
        return r.returncode == 0
    except Exception:
        return False

class MonitorManager:
    def __init__(self, mon_config, geometry):
        self.config = mon_config
        self.geo = geometry
        self.screen_idx = 0
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

    def _launch_screen(self, screen):
        self._kill_all()
        cams = screen.get('cameras', [])
        layout = screen.get('layout', len(cams))
        positions = grid_positions(self.geo, layout, len(cams))
        self.procs = [launch_mpv(cam, positions[i]) for i, cam in enumerate(cams[:len(positions)])]

    def _restart_dead(self, screen):
        cams = screen.get('cameras', [])
        positions = grid_positions(self.geo, screen.get('layout', len(cams)), len(cams))
        for i, proc in enumerate(self.procs):
            if proc.poll() is not None and i < len(cams) and i < len(positions):
                log.warning(f"Restarting dead stream: {cams[i]['name']}")
                self.procs[i] = launch_mpv(cams[i], positions[i])

    def _run(self):
        screens = self.config.get('screens', [])
        if not screens:
            log.warning(f"Monitor {self.config.get('id')} has no screens"); return
        while self.running:
            screen = screens[self.screen_idx]
            log.info(f"Monitor {self.config.get('id')}: screen '{screen.get('name')}'")
            self._launch_screen(screen)
            duration = screen.get('duration', 0)
            if duration > 0:
                end = time.time() + duration
                while self.running and time.time() < end:
                    time.sleep(2)
                    self._restart_dead(screen)
                self.screen_idx = (self.screen_idx + 1) % len(screens)
            else:
                while self.running:
                    time.sleep(5)
                    self._restart_dead(screen)

def watchdog(config):
    interval = config.get('system', {}).get('watchdog_interval', 30)
    dead = set()
    while True:
        time.sleep(interval)
        try:
            cfg = load_config()
            cameras = [cam for mon in cfg.get('monitors',[]) for scr in mon.get('screens',[]) for cam in scr.get('cameras',[])]
            for cam in cameras:
                url = cam.get('substream', cam['url']) if cam.get('use_substream') and cam.get('substream') else cam['url']
                alive = check_stream(url)
                if not alive and cam['name'] not in dead:
                    dead.add(cam['name'])
                    log.warning(f"Stream DOWN: {cam['name']}")
                    send_alert(cfg, f"Stream Down: {cam['name']}", f"Stream '{cam['name']}' at {url} is not responding.\nHost: {socket.gethostname()}")
                elif alive and cam['name'] in dead:
                    dead.discard(cam['name'])
                    log.info(f"Stream RECOVERED: {cam['name']}")
                    send_alert(cfg, f"Stream Recovered: {cam['name']}", f"Stream '{cam['name']}' is back online.\nHost: {socket.gethostname()}")
        except Exception as e:
            log.error(f"Watchdog error: {e}")

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
    geometries = get_monitor_geometries()
    log.info(f"Detected {len(geometries)} monitor(s): {geometries}")

    threading.Thread(target=watchdog, args=(config,), daemon=True).start()

    managers = []
    for i, mon in enumerate(config.get('monitors', [])):
        if i >= len(geometries):
            log.warning(f"Monitor {i+1} not connected, skipping"); continue
        m = MonitorManager(mon, geometries[i])
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
