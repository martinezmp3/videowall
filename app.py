#!/usr/bin/env python3
import os, subprocess, socket, yaml, psutil, hashlib, secrets, json, smtplib, threading
from pathlib import Path
from email.mime.text import MIMEText
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from functools import wraps

CONFIG_PATH = "/opt/videowall/config.yml"
SECRET_FILE = "/opt/videowall/.secret"
STATE_FILE  = "/opt/videowall/state.json"
SNAP_DIR    = "/opt/videowall/static/snapshots"

app = Flask(__name__, template_folder="/opt/videowall/templates", static_folder="/opt/videowall/static")
app.jinja_env.globals["enumerate"] = enumerate

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
    with open(CONFIG_PATH, 'w') as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

def hash_pw(pw): return hashlib.sha256(pw.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def d(*a, **kw):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*a, **kw)
    return d

def sysinfo():
    ips = []
    for iface, addrs in psutil.net_if_addrs().items():
        for a in addrs:
            if a.family == socket.AF_INET and not a.address.startswith('127.'):
                ips.append(f"{iface}: {a.address}")
    try:
        r = subprocess.run(["xrandr","--query"], capture_output=True, text=True,
                           env={**os.environ,"DISPLAY":":0"})
        displays = [l for l in r.stdout.splitlines() if ' connected' in l]
    except Exception:
        displays = []
    try:
        state = json.loads(Path(STATE_FILE).read_text()) if Path(STATE_FILE).exists() else {}
    except Exception:
        state = {}
    vm = psutil.virtual_memory()
    return {
        'hostname': socket.gethostname(),
        'ips': ips,
        'cpu': psutil.cpu_percent(interval=0.5),
        'ram_pct': vm.percent,
        'ram_used': f"{vm.used//(1024**2)}MB",
        'ram_total': f"{vm.total//(1024**2)}MB",
        'disk_pct': psutil.disk_usage('/').percent,
        'displays': displays,
        'rotation_state': state,
    }

def take_snapshot_bg(cam_id, url):
    out = f"{SNAP_DIR}/{cam_id}.jpg"
    try:
        subprocess.run([
            "ffmpeg", "-rtsp_transport", "tcp", "-i", url,
            "-frames:v", "1", "-update", "1", "-q:v", "3", out, "-y"
        ], capture_output=True, timeout=20)
    except Exception:
        pass

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        cfg = load_config()
        if hash_pw(request.form.get('password','')) == cfg.get('system',{}).get('admin_password_hash',''):
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        flash('Invalid password')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html', cfg=load_config(), sys=sysinfo())

@app.route('/config', methods=['GET','POST'])
@login_required
def config_page():
    cfg = load_config()
    if request.method == 'POST':
        action = request.form.get('action','')

        if action == 'system':
            cfg['system']['alert_email_from']   = request.form.get('email_from','')
            cfg['system']['alert_email_to']     = request.form.get('email_to','')
            cfg['system']['gmail_app_password'] = request.form.get('gmail_pass','')
            cfg['system']['watchdog_interval']  = int(request.form.get('watchdog_interval', 30))
            pw = request.form.get('new_password','')
            if pw: cfg['system']['admin_password_hash'] = hash_pw(pw)
            save_config(cfg); flash('System settings saved')

        elif action == 'add_camera':
            cam_id = request.form.get('cam_id','').strip().replace(' ','_').lower()
            cam = {
                'id':         cam_id,
                'name':       request.form.get('cam_name','').strip(),
                'url':        request.form.get('cam_url','').strip(),
                'substream':  request.form.get('cam_sub','').strip(),
                'use_substream': False,
            }
            if not cam_id or not cam['url']:
                flash('Camera ID and URL are required')
            elif any(c['id'] == cam_id for c in cfg.get('cameras',[])):
                flash(f"Camera ID '{cam_id}' already exists")
            else:
                cfg.setdefault('cameras',[]).append(cam)
                save_config(cfg)
                threading.Thread(target=take_snapshot_bg, args=(cam_id, cam['url']), daemon=True).start()
                flash(f"Camera '{cam['name']}' added — snapshot capturing in background")

        elif action == 'del_camera':
            cam_id = request.form.get('cam_id','')
            cfg['cameras'] = [c for c in cfg.get('cameras',[]) if c['id'] != cam_id]
            for mon in cfg.get('monitors',[]):
                for step in mon.get('rotation',[]):
                    step['cameras'] = [c for c in step.get('cameras',[]) if c != cam_id]
            save_config(cfg)
            snap = Path(f"{SNAP_DIR}/{cam_id}.jpg")
            if snap.exists(): snap.unlink()
            flash(f"Camera '{cam_id}' removed")

        elif action == 'toggle_substream':
            cam_id = request.form.get('cam_id','')
            for c in cfg.get('cameras',[]):
                if c['id'] == cam_id:
                    c['use_substream'] = not c.get('use_substream', False)
                    break
            save_config(cfg)
            flash('Substream setting updated')

        elif action == 'add_step':
            mon_idx = int(request.form.get('monitor_id',1)) - 1
            step = {
                'name':     request.form.get('step_name','New Step'),
                'layout':   int(request.form.get('layout', 1)),
                'duration': int(request.form.get('duration', 10)),
                'cameras':  [],
            }
            try:
                cfg['monitors'][mon_idx].setdefault('rotation',[]).append(step)
                save_config(cfg); flash(f"Step '{step['name']}' added")
            except IndexError:
                flash('Invalid monitor')

        elif action == 'del_step':
            mon_idx = int(request.form.get('monitor_id',1)) - 1
            step_idx = int(request.form.get('step_idx',0))
            try:
                del cfg['monitors'][mon_idx]['rotation'][step_idx]
                save_config(cfg); flash('Step removed')
            except IndexError:
                flash('Invalid step')

        elif action == 'move_step':
            mon_idx  = int(request.form.get('monitor_id',1)) - 1
            step_idx = int(request.form.get('step_idx',0))
            direction = request.form.get('direction','up')
            rot = cfg['monitors'][mon_idx].get('rotation',[])
            if direction == 'up' and step_idx > 0:
                rot[step_idx-1], rot[step_idx] = rot[step_idx], rot[step_idx-1]
            elif direction == 'down' and step_idx < len(rot)-1:
                rot[step_idx+1], rot[step_idx] = rot[step_idx], rot[step_idx+1]
            save_config(cfg)

        elif action == 'update_step':
            mon_idx  = int(request.form.get('monitor_id',1)) - 1
            step_idx = int(request.form.get('step_idx',0))
            cam_ids  = request.form.getlist('cameras')
            try:
                step = cfg['monitors'][mon_idx]['rotation'][step_idx]
                step['name']     = request.form.get('step_name', step['name'])
                step['layout']   = int(request.form.get('layout', step['layout']))
                step['duration'] = int(request.form.get('duration', step['duration']))
                step['cameras']  = cam_ids
                save_config(cfg); flash(f"Step '{step['name']}' updated")
            except IndexError:
                flash('Invalid step')

        elif action == 'add_monitor':
            cfg.setdefault('monitors',[]).append({
                'id': len(cfg.get('monitors',[])) + 1,
                'name': request.form.get('monitor_name', f"Monitor {len(cfg.get('monitors',[]))+1}"),
                'rotation': [{'name':'Quad View','layout':4,'duration':0,'cameras':[]}]
            })
            save_config(cfg); flash('Monitor added')

        subprocess.run(['systemctl','restart','videowall-display'], check=False)
        return redirect(url_for('config_page'))

    return render_template('config.html', cfg=cfg)

@app.route('/api/snapshot/<cam_id>', methods=['POST'])
@login_required
def snapshot(cam_id):
    cfg = load_config()
    cams = {c['id']: c for c in cfg.get('cameras',[])}
    if cam_id not in cams:
        return jsonify({'ok': False, 'msg': 'Camera not found'})
    cam = cams[cam_id]
    url = cam.get('substream', cam['url']) if cam.get('use_substream') and cam.get('substream') else cam['url']
    out = f"{SNAP_DIR}/{cam_id}.jpg"
    try:
        r = subprocess.run(
            ["ffmpeg","-rtsp_transport","tcp","-i",url,"-frames:v","1","-update","1","-q:v","3",out,"-y"],
            capture_output=True, timeout=20
        )
        if r.returncode == 0:
            return jsonify({'ok': True, 'url': f"/static/snapshots/{cam_id}.jpg?t={int(os.path.getmtime(out))}"})
        return jsonify({'ok': False, 'msg': 'ffmpeg failed'})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})

@app.route('/api/restart', methods=['POST'])
@login_required
def restart():
    subprocess.run(['systemctl','restart','videowall-display'], check=False)
    return jsonify({'ok': True})

@app.route('/api/reboot', methods=['POST'])
@login_required
def reboot():
    subprocess.Popen(['shutdown','-r','now']); return jsonify({'ok': True})

@app.route('/api/status')
@login_required
def status():
    return jsonify(sysinfo())

@app.route('/api/test-email', methods=['POST'])
@login_required
def test_email():
    cfg = load_config(); s = cfg.get('system',{})
    try:
        msg = MIMEText('VideoWall email alert test — working correctly.')
        msg['Subject'] = '[VideoWall] Test Alert'
        msg['From'] = s['alert_email_from']
        msg['To']   = s['alert_email_to']
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as srv:
            srv.login(s['alert_email_from'], s['gmail_app_password'])
            srv.send_message(msg)
        return jsonify({'ok': True, 'msg': 'Test email sent'})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
