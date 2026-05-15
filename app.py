#!/usr/bin/env python3
import os, subprocess, socket, yaml, psutil, hashlib, secrets, json, smtplib
from pathlib import Path
from email.mime.text import MIMEText
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from functools import wraps

CONFIG_PATH = "/opt/videowall/config.yml"
SECRET_FILE = "/opt/videowall/.secret"

app = Flask(__name__, template_folder="/opt/videowall/templates", static_folder="/opt/videowall/static")
app.jinja_env.globals["enumerate"] = enumerate

if Path(SECRET_FILE).exists():
    app.secret_key = Path(SECRET_FILE).read_text().strip()
else:
    key = secrets.token_hex(32)
    Path(SECRET_FILE).write_text(key)
    os.chmod(SECRET_FILE, 0o600)
    app.secret_key = key

def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def sysinfo():
    ips = []
    for iface, addrs in psutil.net_if_addrs().items():
        for a in addrs:
            if a.family == socket.AF_INET and not a.address.startswith('127.'):
                ips.append(f"{iface}: {a.address}")
    try:
        r = subprocess.run(["xrandr","--query"], capture_output=True, text=True, env={**os.environ,"DISPLAY":":0"})
        displays = [l for l in r.stdout.splitlines() if ' connected' in l]
    except Exception:
        displays = ["Unable to query"]
    try:
        r2 = subprocess.run(["journalctl","-u","videowall-display","-n","30","--no-pager"], capture_output=True, text=True)
        logs = r2.stdout
    except Exception:
        logs = ""
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
        'logs': logs,
    }

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        cfg = load_config()
        stored = cfg.get('system',{}).get('admin_password_hash','')
        if hash_pw(request.form.get('password','')) == stored:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        flash('Invalid password')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    return render_template('dashboard.html', cfg=load_config(), sys=sysinfo())

@app.route('/config', methods=['GET','POST'])
@login_required
def config_page():
    cfg = load_config()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'system':
            cfg['system']['alert_email_from'] = request.form.get('email_from','')
            cfg['system']['alert_email_to'] = request.form.get('email_to','')
            cfg['system']['gmail_app_password'] = request.form.get('gmail_pass','')
            cfg['system']['watchdog_interval'] = int(request.form.get('watchdog_interval', 30))
            pw = request.form.get('new_password','')
            if pw:
                cfg['system']['admin_password_hash'] = hash_pw(pw)
            save_config(cfg)
            flash('System settings saved')
        elif action == 'add_camera':
            mon_id = int(request.form.get('monitor_id', 1)) - 1
            scr_id = int(request.form.get('screen_id', 1)) - 1
            cam = {
                'name': request.form.get('cam_name'),
                'url': request.form.get('cam_url'),
                'use_substream': False,
                'substream': request.form.get('cam_sub','')
            }
            try:
                cfg['monitors'][mon_id]['screens'][scr_id]['cameras'].append(cam)
                save_config(cfg)
                flash(f"Camera '{cam['name']}' added")
            except IndexError:
                flash('Invalid monitor/screen index')
        elif action == 'del_camera':
            mon_id = int(request.form.get('monitor_id', 1)) - 1
            scr_id = int(request.form.get('screen_id', 1)) - 1
            cam_id = int(request.form.get('cam_id', 0))
            try:
                del cfg['monitors'][mon_id]['screens'][scr_id]['cameras'][cam_id]
                save_config(cfg)
                flash('Camera removed')
            except IndexError:
                flash('Invalid index')
        elif action == 'add_screen':
            mon_id = int(request.form.get('monitor_id', 1)) - 1
            screen = {
                'name': request.form.get('screen_name', 'New Screen'),
                'layout': int(request.form.get('layout', 4)),
                'duration': int(request.form.get('duration', 0)),
                'cameras': []
            }
            try:
                cfg['monitors'][mon_id]['screens'].append(screen)
                save_config(cfg)
                flash(f"Screen '{screen['name']}' added")
            except IndexError:
                flash('Invalid monitor index')
        elif action == 'add_monitor':
            cfg['monitors'].append({
                'id': len(cfg['monitors']) + 1,
                'name': request.form.get('monitor_name', f"Monitor {len(cfg['monitors'])+1}"),
                'screens': [{'name':'Main','layout':4,'duration':0,'cameras':[]}]
            })
            save_config(cfg)
            flash('Monitor added')
        subprocess.run(['systemctl','restart','videowall-display'], check=False)
        return redirect(url_for('config_page'))
    return render_template('config.html', cfg=cfg)

@app.route('/api/restart', methods=['POST'])
@login_required
def restart():
    subprocess.run(['systemctl','restart','videowall-display'], check=False)
    return jsonify({'ok': True})

@app.route('/api/reboot', methods=['POST'])
@login_required
def reboot():
    subprocess.Popen(['shutdown','-r','now'])
    return jsonify({'ok': True})

@app.route('/api/status')
@login_required
def status():
    return jsonify(sysinfo())

@app.route('/api/test-email', methods=['POST'])
@login_required
def test_email():
    cfg = load_config()
    s = cfg.get('system', {})
    try:
        msg = MIMEText('VideoWall email alert test — working correctly.')
        msg['Subject'] = '[VideoWall] Test Alert'
        msg['From'] = s['alert_email_from']
        msg['To'] = s['alert_email_to']
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as srv:
            srv.login(s['alert_email_from'], s['gmail_app_password'])
            srv.send_message(msg)
        return jsonify({'ok': True, 'msg': 'Test email sent successfully'})
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
