#!/usr/bin/env python3
import os, re, io, signal as _signal, subprocess, socket, yaml, psutil, hashlib, secrets, json, smtplib, threading
from pathlib import Path
from datetime import datetime
from email.mime.text import MIMEText
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from functools import wraps

CONFIG_PATH = "/opt/videowall/config.yml"
SECRET_FILE = "/opt/videowall/.secret"
STATE_FILE  = "/opt/videowall/state.json"
SNAP_DIR    = "/opt/videowall/static/snapshots"
VERSION     = "1.0"
BUILT_BY    = "Jorge Martinez"
COMPANY     = "JJ Smart Solutions"
COMPANY_URL = "https://jjsmartsolutions.com"

app = Flask(__name__, template_folder="/opt/videowall/templates", static_folder="/opt/videowall/static")
app.jinja_env.globals.update(enumerate=enumerate, len=len, VERSION=VERSION,
                              BUILT_BY=BUILT_BY, COMPANY=COMPANY, COMPANY_URL=COMPANY_URL)

Path(SNAP_DIR).mkdir(parents=True, exist_ok=True)

if Path(SECRET_FILE).exists():
    app.secret_key = Path(SECRET_FILE).read_text().strip()
else:
    key = secrets.token_hex(32)
    Path(SECRET_FILE).write_text(key); os.chmod(SECRET_FILE, 0o600)
    app.secret_key = key

def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

def save_config(cfg):
    with open(CONFIG_PATH,'w') as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def d(*a,**kw):
        if not session.get('logged_in'): return redirect(url_for('login'))
        return f(*a,**kw)
    return d

def sysinfo():
    ips = []
    for iface,addrs in psutil.net_if_addrs().items():
        for a in addrs:
            if a.family==socket.AF_INET and not a.address.startswith('127.'):
                ips.append(f"{iface}: {a.address}")
    try:
        r = subprocess.run(["xrandr","--query"],capture_output=True,text=True,env={**os.environ,"DISPLAY":":0"})
        displays = [l for l in r.stdout.splitlines() if ' connected' in l]
    except Exception: displays=[]
    try:
        state = json.loads(Path(STATE_FILE).read_text()) if Path(STATE_FILE).exists() else {}
    except Exception: state={}
    vm = psutil.virtual_memory()
    return {
        'hostname': socket.gethostname(), 'ips': ips,
        'cpu': psutil.cpu_percent(interval=0.5),
        'ram_pct': vm.percent, 'ram_used': f"{vm.used//(1024**2)}MB", 'ram_total': f"{vm.total//(1024**2)}MB",
        'disk_pct': psutil.disk_usage('/').percent,
        'displays': displays, 'rotation_state': state,
        'now': datetime.now().strftime('%a %H:%M'),
    }

def take_snap_bg(cam_id, url):
    out = f"{SNAP_DIR}/{cam_id}.jpg"
    try:
        subprocess.run(["ffmpeg","-rtsp_transport","tcp","-i",url,
                        "-frames:v","1","-update","1","-q:v","3",out,"-y"],
                       capture_output=True, timeout=20)
    except Exception: pass

# ── Auth ──────────────────────────────────────────────────
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        cfg = load_config()
        if hash_pw(request.form.get('password','')) == cfg.get('system',{}).get('admin_password_hash',''):
            session['logged_in'] = True; return redirect(url_for('dashboard'))
        flash('Invalid password')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

# ── Pages ─────────────────────────────────────────────────
def reload_display():
    """Send SIGUSR1 to the supervisor for a live reload (no Xorg restart).
    Falls back to full service restart if the PID cannot be found."""
    try:
        r = subprocess.run(
            ['systemctl', 'show', '-p', 'MainPID', '--value', 'videowall-display'],
            capture_output=True, text=True)
        pid = int(r.stdout.strip())
        if pid > 0:
            _signal.kill(pid, _signal.SIGUSR1)
            return
    except Exception:
        pass
    reload_display()


@app.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html', cfg=load_config(), sys=sysinfo())

@app.route('/config')
@login_required
def config_page():
    return render_template('config.html', cfg=load_config())

# ── Cameras ───────────────────────────────────────────────
@app.route('/api/camera/add', methods=['POST'])
@login_required
def camera_add():
    cfg = load_config()
    cam_id = request.form.get('cam_id','').strip().replace(' ','_').lower()
    cam = {'id':cam_id,'name':request.form.get('cam_name','').strip(),
           'url':request.form.get('cam_url','').strip(),
           'substream':request.form.get('cam_sub','').strip(),'use_substream':False,
           'fill_mode': request.form.get('cam_fill','stretch')}
    if not cam_id or not cam['url']:
        flash('Camera ID and URL are required')
    elif any(c['id']==cam_id for c in cfg.get('cameras',[])):
        flash(f"ID '{cam_id}' already exists")
    else:
        cfg.setdefault('cameras',[]).append(cam)
        save_config(cfg)
        threading.Thread(target=take_snap_bg,args=(cam_id,cam['url']),daemon=True).start()
        flash(f"Camera '{cam['name']}' added")
    return redirect(url_for('config_page')+'#cameras')

@app.route('/api/camera/delete', methods=['POST'])
@login_required
def camera_delete():
    cfg = load_config(); cam_id = request.form.get('cam_id','')
    cfg['cameras'] = [c for c in cfg.get('cameras',[]) if c['id']!=cam_id]
    for pl in cfg.get('playlists',[]):
        for step in pl.get('rotation',[]):
            step['cameras'] = [c for c in step.get('cameras',[]) if c!=cam_id]
    save_config(cfg)
    snap = Path(f"{SNAP_DIR}/{cam_id}.jpg")
    if snap.exists(): snap.unlink()
    flash('Camera removed'); return redirect(url_for('config_page')+'#cameras')

@app.route('/api/camera/toggle-sub', methods=['POST'])
@login_required
def camera_toggle_sub():
    cfg = load_config(); cam_id = request.form.get('cam_id','')
    for c in cfg.get('cameras',[]):
        if c['id']==cam_id: c['use_substream']=not c.get('use_substream',False); break
    save_config(cfg); return redirect(url_for('config_page')+'#cameras')

# ── Playlists ─────────────────────────────────────────────
@app.route('/api/playlist/add', methods=['POST'])
@login_required
def playlist_add():
    cfg = load_config()
    pl_id = request.form.get('pl_id','').strip().replace(' ','_').lower()
    if not pl_id: flash('Playlist ID required'); return redirect(url_for('config_page')+'#playlists')
    if any(p['id']==pl_id for p in cfg.get('playlists',[])):
        flash(f"Playlist '{pl_id}' already exists"); return redirect(url_for('config_page')+'#playlists')
    cfg.setdefault('playlists',[]).append({
        'id': pl_id, 'name': request.form.get('pl_name','New Playlist'), 'rotation':[]
    })
    save_config(cfg); flash('Playlist created.', 'success'); return redirect(url_for('config_page')+'#playlists')

@app.route('/api/playlist/delete', methods=['POST'])
@login_required
def playlist_delete():
    cfg = load_config(); pl_id = request.form.get('pl_id','')
    cfg['playlists'] = [p for p in cfg.get('playlists',[]) if p['id']!=pl_id]
    save_config(cfg); flash('Playlist deleted.', 'success'); return redirect(url_for('config_page')+'#playlists')

@app.route('/api/playlist/step/add', methods=['POST'])
@login_required
def step_add():
    cfg = load_config(); pl_id = request.form.get('pl_id','')
    step = {'name':request.form.get('step_name','New Step'),
            'layout':int(request.form.get('layout',1)),
            'duration':int(request.form.get('duration',10)),'cameras':[]}
    for pl in cfg.get('playlists',[]):
        if pl['id']==pl_id: pl.setdefault('rotation',[]).append(step); break
    save_config(cfg); flash('Step added'); return redirect(url_for('config_page')+'#playlists')

@app.route('/api/playlist/step/update', methods=['POST'])
@login_required
def step_update():
    cfg = load_config()
    pl_id = request.form.get('pl_id',''); step_idx = int(request.form.get('step_idx',0))
    for pl in cfg.get('playlists',[]):
        if pl['id']==pl_id and step_idx < len(pl.get('rotation',[])):
            step = pl['rotation'][step_idx]
            step['name']     = request.form.get('step_name', step['name'])
            lraw = request.form.get('layout', str(step['layout']))
            try: step['layout'] = int(lraw)
            except ValueError: step['layout'] = lraw
            step['duration'] = int(request.form.get('duration', step['duration']))
            step['cameras']  = request.form.getlist('cameras')
            break
    save_config(cfg); flash('Step saved.', 'success')
    reload_display()
    return redirect(url_for('config_page')+'#playlists')

@app.route('/api/playlist/step/delete', methods=['POST'])
@login_required
def step_delete():
    cfg = load_config()
    pl_id = request.form.get('pl_id',''); step_idx = int(request.form.get('step_idx',0))
    for pl in cfg.get('playlists',[]):
        if pl['id']==pl_id:
            try: del pl['rotation'][step_idx]
            except IndexError: pass
            break
    save_config(cfg); flash('Step removed')
    reload_display()
    return redirect(url_for('config_page')+'#playlists')

@app.route('/api/playlist/step/move', methods=['POST'])
@login_required
def step_move():
    cfg = load_config()
    pl_id = request.form.get('pl_id',''); step_idx = int(request.form.get('step_idx',0))
    direction = request.form.get('direction','up')
    for pl in cfg.get('playlists',[]):
        if pl['id']==pl_id:
            rot = pl.get('rotation',[])
            if direction=='up' and step_idx>0:
                rot[step_idx-1],rot[step_idx]=rot[step_idx],rot[step_idx-1]
            elif direction=='down' and step_idx<len(rot)-1:
                rot[step_idx+1],rot[step_idx]=rot[step_idx],rot[step_idx+1]
            break
    save_config(cfg)
    reload_display()
    return redirect(url_for('config_page')+'#playlists')

# ── Schedule ──────────────────────────────────────────────
@app.route('/api/schedule/add', methods=['POST'])
@login_required
def schedule_add():
    cfg = load_config(); mon_idx = int(request.form.get('monitor_id',1))-1
    rule = {
        'name':     request.form.get('rule_name','New Rule'),
        'playlist': request.form.get('playlist',''),
        'days':     request.form.getlist('days'),
        'start':    request.form.get('start','08:00'),
        'end':      request.form.get('end','20:00'),
    }
    try:
        cfg['monitors'][mon_idx].setdefault('schedule',[]).append(rule)
        save_config(cfg); flash('Schedule rule added')
        reload_display()
    except IndexError: flash('Invalid monitor')
    return redirect(url_for('config_page')+'#schedule')

@app.route('/api/schedule/delete', methods=['POST'])
@login_required
def schedule_delete():
    cfg = load_config()
    mon_idx = int(request.form.get('monitor_id',1))-1
    rule_idx = int(request.form.get('rule_idx',0))
    try:
        del cfg['monitors'][mon_idx]['schedule'][rule_idx]
        save_config(cfg); flash('Rule removed')
        reload_display()
    except IndexError: flash('Invalid index')
    return redirect(url_for('config_page')+'#schedule')

@app.route('/api/schedule/set-default', methods=['POST'])
@login_required
def schedule_set_default():
    cfg = load_config(); mon_idx = int(request.form.get('monitor_id',1))-1
    try:
        cfg['monitors'][mon_idx]['default_playlist'] = request.form.get('playlist','')
        save_config(cfg); flash('Default playlist updated')
        reload_display()
    except IndexError: flash('Invalid monitor')
    return redirect(url_for('config_page')+'#schedule')

# ── System ────────────────────────────────────────────────
@app.route('/api/system/save', methods=['POST'])
@login_required
def system_save():
    cfg = load_config()
    cfg['system']['alert_email_from']   = request.form.get('email_from','')
    cfg['system']['alert_email_to']     = request.form.get('email_to','')
    cfg['system']['gmail_app_password'] = request.form.get('gmail_pass','')
    cfg['system']['watchdog_interval']  = int(request.form.get('watchdog_interval',30))
    cfg['system']['debug_log']          = request.form.get('debug_log') == '1'
    pw = request.form.get('new_password','')
    if pw: cfg['system']['admin_password_hash'] = hash_pw(pw)
    save_config(cfg)
    reload_display()
    flash('Settings saved.', 'success')
    return redirect(url_for('config_page')+'#system')

@app.route('/api/restart', methods=['POST'])
@login_required
def restart():
    reload_display()
    return jsonify({'ok':True})

@app.route('/api/reboot', methods=['POST'])
@login_required
def reboot():
    subprocess.Popen(['shutdown','-r','now']); return jsonify({'ok':True})

@app.route('/api/status')
@login_required
def status():
    return jsonify(sysinfo())

@app.route('/api/snapshot/<cam_id>', methods=['POST'])
@login_required
def snapshot(cam_id):
    cfg = load_config()
    cams = {c['id']:c for c in cfg.get('cameras',[])}
    if cam_id not in cams: return jsonify({'ok':False,'msg':'Not found'})
    cam = cams[cam_id]
    url = cam.get('substream',cam['url']) if cam.get('use_substream') and cam.get('substream') else cam['url']
    out = f"{SNAP_DIR}/{cam_id}.jpg"
    try:
        r = subprocess.run(["ffmpeg","-rtsp_transport","tcp","-i",url,
                            "-frames:v","1","-update","1","-q:v","3",out,"-y"],
                           capture_output=True, timeout=20)
        if r.returncode==0:
            return jsonify({'ok':True,'url':f"/static/snapshots/{cam_id}.jpg?t={int(os.path.getmtime(out))}"})
        return jsonify({'ok':False,'msg':'ffmpeg failed'})
    except Exception as e:
        return jsonify({'ok':False,'msg':str(e)})

@app.route('/api/test-email', methods=['POST'])
@login_required
def test_email():
    cfg=load_config(); s=cfg.get('system',{})
    try:
        msg=MIMEText('VideoWall email alert test — working correctly.')
        msg['Subject']='[VideoWall] Test Alert'; msg['From']=s['alert_email_from']; msg['To']=s['alert_email_to']
        with smtplib.SMTP_SSL('smtp.gmail.com',465) as srv:
            srv.login(s['alert_email_from'],s['gmail_app_password']); srv.send_message(msg)
        return jsonify({'ok':True,'msg':'Test email sent'})
    except Exception as e:
        return jsonify({'ok':False,'msg':str(e)})

@app.route('/api/camera/update', methods=['POST'])
@login_required
def camera_update():
    cfg = load_config()
    cam_id = request.form.get('cam_id','')
    for cam in cfg.get('cameras',[]):
        if cam['id'] == cam_id:
            cam['name']      = request.form.get('cam_name', cam['name']).strip()
            new_url          = request.form.get('cam_url', cam['url']).strip()
            url_changed      = new_url != cam['url']
            cam['url']       = new_url
            cam['substream'] = request.form.get('cam_sub', cam.get('substream','')).strip()
            cam['fill_mode'] = request.form.get('cam_fill', cam.get('fill_mode','stretch'))
            save_config(cfg)
            if url_changed:
                threading.Thread(target=take_snap_bg, args=(cam_id, new_url), daemon=True).start()
            flash(f"Camera '{cam['name']}' updated")
            reload_display()
            break
    return redirect(url_for('config_page')+'#cameras')

@app.route('/api/schedule/update', methods=['POST'])
@login_required
def schedule_update():
    cfg = load_config()
    mon_idx  = int(request.form.get('monitor_id',1)) - 1
    rule_idx = int(request.form.get('rule_idx',0))
    try:
        rule = cfg['monitors'][mon_idx]['schedule'][rule_idx]
        rule['name']     = request.form.get('rule_name', rule['name'])
        rule['playlist'] = request.form.get('playlist', rule['playlist'])
        rule['days']     = request.form.getlist('days')
        rule['start']    = request.form.get('start', rule['start'])
        rule['end']      = request.form.get('end', rule['end'])
        save_config(cfg)
        flash('Schedule rule updated.', 'success')
        reload_display()
    except IndexError:
        flash('Invalid rule.', 'danger')
    return redirect(url_for('config_page')+'#schedule')

@app.route('/api/screenshot')
@login_required
def screenshot():
    """Capture all connected monitors and return as JPEG."""
    import time as _time
    out = '/tmp/vw_screenshot.jpg'
    env = {**os.environ, 'DISPLAY': ':0'}
    # Remove old file first — scrot silently skips overwriting existing files
    try: os.remove(out)
    except FileNotFoundError: pass
    # scrot -z captures all screens, -q 85 = JPEG quality
    r = subprocess.run(
        ['scrot', '-z', '-q', '85', out],
        env=env, capture_output=True, text=True, timeout=10
    )
    if r.returncode != 0 or not os.path.exists(out):
        return jsonify({'ok': False, 'msg': r.stderr or 'scrot failed'}), 500
    ts = _time.strftime('%Y%m%d_%H%M%S')
    return send_file(out, mimetype='image/jpeg',
                     as_attachment=request.args.get('dl') == '1',
                     download_name=f'videowall_screenshot_{ts}.jpg')


# ─── Backup / Restore / Factory Reset ────────────────────────────────────────
DEFAULT_CONFIG = {
    'system': {
        'admin_password_hash': '',  # filled at runtime
        'alert_email_from': '',
        'alert_email_to': '',
        'gmail_app_password': '',
        'watchdog_interval': 30,
    },
    'cameras': [],
    'playlists': [],
    'monitors': [
        {'id': 1, 'name': 'Monitor 1', 'x': 0, 'y': 0, 'w': 1920, 'h': 1080, 'schedule': []}
    ],
    'setup_mode': True,
}

@app.route('/api/backup')
@login_required
def backup_download():
    import datetime as _dt
    ts   = _dt.datetime.now().strftime('%Y%m%d_%H%M%S')
    data = open(CONFIG_PATH, 'rb').read()
    buf  = io.BytesIO(data)
    buf.seek(0)
    return send_file(buf, as_attachment=True,
                     download_name=f'videowall_backup_{ts}.yml',
                     mimetype='application/x-yaml')

@app.route('/api/restore', methods=['POST'])
@login_required
def backup_restore():
    f = request.files.get('backup_file')
    if not f:
        flash('No file selected.', 'danger')
        return redirect(url_for('config_page') + '#system')
    try:
        data = yaml.safe_load(f.read())
        if not isinstance(data, dict) or 'system' not in data:
            flash('Invalid backup file — missing system section.', 'danger')
            return redirect(url_for('config_page') + '#system')
        # Remove setup_mode if present in backup
        data.pop('setup_mode', None)
        save_config(data)
        threading.Timer(1.0, reload_display).start()
        flash('Configuration restored successfully. Display restarting...', 'success')
    except Exception as e:
        flash(f'Restore failed: {e}', 'danger')
    return redirect(url_for('config_page') + '#system')

@app.route('/api/factory-reset', methods=['POST'])
@login_required
def factory_reset():
    confirm = request.form.get('confirm', '')
    if confirm != 'RESET':
        flash('Factory reset cancelled — type RESET to confirm.', 'danger')
        return redirect(url_for('config_page') + '#system')

    # Build fresh config
    cfg = dict(DEFAULT_CONFIG)
    cfg['system'] = dict(DEFAULT_CONFIG['system'])
    cfg['system']['admin_password_hash'] = hash_pw('videowall')

    # Regenerate setup screen (in case AP SSID changed, etc.)
    subprocess.run(['python3', '/opt/videowall/setup_screen_gen.py'], check=False)

    save_config(cfg)

    # Start WiFi AP in background
    ap_cmd = (
        'nmcli con delete VideoWall-Hotspot 2>/dev/null; '
        'nmcli dev wifi hotspot '
        f'ifname {WIFI_IFACE} con-name VideoWall-Hotspot '
        'ssid VideoWall-Setup password jjsmart123 band bg'
    )
    subprocess.Popen(['bash', '-c', ap_cmd])

    # Restart display service so supervisor picks up setup_mode
    threading.Timer(1.0, reload_display).start()

    session.clear()
    return redirect(url_for('login') + '?reset=1')


@app.route('/api/logs')
@login_required
def get_logs():
    lines  = min(int(request.args.get('lines', 150)), 1000)
    level  = request.args.get('level', 'all')
    log_file = '/var/log/videowall/supervisor.log'
    try:
        with open(log_file, errors='replace') as f:
            all_lines = f.readlines()
        if level == 'warning':
            all_lines = [l for l in all_lines if any(x in l for x in ('[WARNING]','[ERROR]','[CRITICAL]'))]
        elif level == 'error':
            all_lines = [l for l in all_lines if any(x in l for x in ('[ERROR]','[CRITICAL]'))]
        tail = all_lines[-lines:]
        return jsonify({'ok': True, 'lines': tail, 'total': len(all_lines),
                        'debug': load_config().get('system',{}).get('debug_log', False)})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})

@app.route('/api/logs/download')
@login_required
def download_logs():
    import time as _t
    ts = _t.strftime('%Y%m%d_%H%M%S')
    return send_file('/var/log/videowall/supervisor.log',
                     as_attachment=True,
                     download_name=f'videowall_log_{ts}.txt',
                     mimetype='text/plain')


@app.route('/api/monitor/rename', methods=['POST'])
@login_required
def monitor_rename():
    cfg     = load_config()
    mon_idx = int(request.form.get('monitor_id', 1)) - 1
    name    = request.form.get('name', '').strip()
    if not name:
        flash('Monitor name cannot be empty.', 'danger')
        return redirect(url_for('config_page') + '#schedule')
    try:
        cfg['monitors'][mon_idx]['name'] = name
        save_config(cfg)
        flash(f'Monitor renamed to "{name}".', 'success')
    except IndexError:
        flash('Invalid monitor.', 'danger')
    return redirect(url_for('config_page') + '#schedule')


# ─── Network management ──────────────────────────────────────────────────────
ETH_IFACE  = 'enp0s31f6'
WIFI_IFACE = 'wlp1s0'
AP_CON     = 'VideoWall-Hotspot'

def _iface_ip(iface):
    try:
        out = subprocess.check_output(['ip','addr','show', iface], text=True, stderr=subprocess.DEVNULL)
        m = re.search(r'inet ([\d./]+)', out)
        return m.group(1) if m else None
    except Exception:
        return None

def _eth_config():
    try:
        txt = open('/etc/network/interfaces').read()
        if f'iface {ETH_IFACE} inet static' in txt:
            mode = 'static'
            cfg = {}
            for key, pat in [('address', r'address\s+([\d./]+)'), ('gateway', r'gateway\s+([\d.]+)'), ('dns', r'dns-nameservers\s+(\S+)')]:
                m = re.search(pat, txt)
                if m: cfg[key] = m.group(1)
            return {'mode': mode, **cfg}
    except Exception:
        pass
    return {'mode': 'dhcp'}

@app.route('/api/network/status')
@login_required
def net_status():
    eth = _eth_config()
    eth['ip'] = _iface_ip(ETH_IFACE)
    wifi_ip    = _iface_ip(WIFI_IFACE)
    wifi_ssid  = None
    wifi_state = 'unavailable'
    ap_active  = False
    ap_ssid    = None
    try:
        out = subprocess.check_output(
            ['nmcli','-t','-f','DEVICE,STATE,CONNECTION','dev'], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            parts = line.split(':')
            if parts[0] == WIFI_IFACE:
                wifi_state = parts[1]
                wifi_ssid  = parts[2] if len(parts) > 2 and parts[2] != '--' else None
    except Exception:
        pass
    try:
        out = subprocess.check_output(
            ['nmcli','-t','-f','NAME,TYPE,DEVICE','con','show','--active'], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            parts = line.split(':')
            if len(parts) >= 2 and '802-11-wireless' in parts[1]:
                name = parts[0]
                mode_out = subprocess.check_output(
                    ['nmcli','-t','-f','802-11-wireless.mode','con','show', name],
                    text=True, stderr=subprocess.DEVNULL)
                if 'ap' in mode_out.lower():
                    ap_active = True
                    ap_ssid   = name
    except Exception:
        pass
    return jsonify({
        'eth':  {'iface': ETH_IFACE,  'ip': eth.pop('ip'), **eth},
        'wifi': {'iface': WIFI_IFACE, 'ip': wifi_ip, 'state': wifi_state, 'ssid': wifi_ssid},
        'ap':   {'active': ap_active, 'ssid': ap_ssid}
    })

@app.route('/api/network/eth', methods=['POST'])
@login_required
def net_eth():
    mode = request.form.get('mode','dhcp')
    try:
        txt = open('/etc/network/interfaces').read()
    except Exception:
        txt = 'source /etc/network/interfaces.d/*\nauto lo\niface lo inet loopback\n'
    block = f'\nallow-hotplug {ETH_IFACE}\n'
    if mode == 'static':
        ip  = request.form.get('ip','')
        mask= request.form.get('mask','24')
        gw  = request.form.get('gateway','')
        dns = request.form.get('dns','8.8.8.8')
        block += f'iface {ETH_IFACE} inet static\n    address {ip}/{mask}\n'
        if gw:  block += f'    gateway {gw}\n'
        block += f'    dns-nameservers {dns}\n'
    else:
        block += f'iface {ETH_IFACE} inet dhcp\niface {ETH_IFACE} inet6 auto\n'
    # Replace existing ETH block
    new_txt = re.sub(
        rf'\nallow-hotplug {ETH_IFACE}.*?(?=\n(?:allow-hotplug|auto (?!lo)|iface (?!lo)|$))',
        block, txt, flags=re.DOTALL)
    if new_txt == txt:
        new_txt = txt.rstrip() + '\n' + block
    with open('/etc/network/interfaces','w') as f:
        f.write(new_txt)
    # Apply in background so the HTTP response returns first
    subprocess.Popen(['bash','-c', f'sleep 2 && ifdown {ETH_IFACE} 2>/dev/null; ifup {ETH_IFACE}'])
    flash('Ethernet settings saved — applying in background. No reboot needed.', 'success')
    return redirect(url_for('config_page')+'#network')

@app.route('/api/network/wifi/scan', methods=['POST'])
@login_required
def wifi_scan():
    try:
        subprocess.run(['nmcli','dev','wifi','rescan','ifname',WIFI_IFACE],
                       timeout=8, check=False, stderr=subprocess.DEVNULL)
        out = subprocess.check_output(
            ['nmcli','--terse','-f','IN-USE,SSID,SIGNAL,SECURITY','dev','wifi','list','ifname',WIFI_IFACE],
            text=True, timeout=10, stderr=subprocess.DEVNULL)
        nets = []
        seen = set()
        for line in out.splitlines():
            parts = line.split(':')
            if len(parts) < 3: continue
            ssid = parts[1].strip()
            if not ssid or ssid in seen: continue
            seen.add(ssid)
            nets.append({
                'in_use':   parts[0].strip() == '*',
                'ssid':     ssid,
                'signal':   int(parts[2]) if parts[2].isdigit() else 0,
                'security': parts[3].strip() if len(parts) > 3 else ''
            })
        nets.sort(key=lambda x: -x['signal'])
        return jsonify({'ok': True, 'networks': nets})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})

@app.route('/api/network/wifi/connect', methods=['POST'])
@login_required
def wifi_connect():
    ssid = request.form.get('ssid','')
    pw   = request.form.get('password','')
    if not ssid:
        return jsonify({'ok': False, 'msg': 'SSID required'})
    # Remove any stale saved profile first (prevents "Secrets required" error)
    subprocess.run(['nmcli','con','delete', ssid], capture_output=True, timeout=5)
    cmd = ['nmcli','dev','wifi','connect', ssid, 'ifname', WIFI_IFACE]
    if pw: cmd += ['password', pw]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        ok = r.returncode == 0
        return jsonify({'ok': ok, 'msg': (r.stdout or r.stderr).strip()})
    except subprocess.TimeoutExpired:
        return jsonify({'ok': False, 'msg': 'Connection timed out (30 s)'})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})

@app.route('/api/network/wifi/disconnect', methods=['POST'])
@login_required
def wifi_disconnect():
    try:
        subprocess.run(['nmcli','dev','disconnect', WIFI_IFACE], timeout=10, check=True, capture_output=True)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})

@app.route('/api/network/ap/start', methods=['POST'])
@login_required
def ap_start():
    ssid = request.form.get('ssid', 'VideoWall-Setup')
    pw   = request.form.get('password', 'jjsmart123')
    if len(pw) < 8:
        return jsonify({'ok': False, 'msg': 'Password must be at least 8 characters'})
    subprocess.run(['nmcli','con','delete', AP_CON], capture_output=True)
    try:
        r = subprocess.run([
            'nmcli','dev','wifi','hotspot',
            'ifname', WIFI_IFACE, 'con-name', AP_CON,
            'ssid', ssid, 'password', pw, 'band', 'bg'
        ], capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            return jsonify({'ok': True, 'msg': f'AP "{ssid}" active — connect at 10.42.0.1'})
        return jsonify({'ok': False, 'msg': (r.stderr or r.stdout).strip()})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})

@app.route('/api/network/ap/stop', methods=['POST'])
@login_required
def ap_stop():
    try:
        subprocess.run(['nmcli','con','down',   AP_CON], capture_output=True, timeout=10)
        subprocess.run(['nmcli','con','delete', AP_CON], capture_output=True, timeout=10)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})


if __name__=='__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
