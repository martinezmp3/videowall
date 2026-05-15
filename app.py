#!/usr/bin/env python3
import os, subprocess, socket, yaml, psutil, hashlib, secrets, json, smtplib, threading
from pathlib import Path
from datetime import datetime
from email.mime.text import MIMEText
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
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
    save_config(cfg); flash('Playlist created'); return redirect(url_for('config_page')+'#playlists')

@app.route('/api/playlist/delete', methods=['POST'])
@login_required
def playlist_delete():
    cfg = load_config(); pl_id = request.form.get('pl_id','')
    cfg['playlists'] = [p for p in cfg.get('playlists',[]) if p['id']!=pl_id]
    save_config(cfg); flash('Playlist deleted'); return redirect(url_for('config_page')+'#playlists')

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
            step['layout']   = int(request.form.get('layout', step['layout']))
            step['duration'] = int(request.form.get('duration', step['duration']))
            step['cameras']  = request.form.getlist('cameras')
            break
    save_config(cfg); flash('Step saved')
    subprocess.run(['systemctl','restart','videowall-display'],check=False)
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
    subprocess.run(['systemctl','restart','videowall-display'],check=False)
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
    subprocess.run(['systemctl','restart','videowall-display'],check=False)
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
        subprocess.run(['systemctl','restart','videowall-display'],check=False)
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
        subprocess.run(['systemctl','restart','videowall-display'],check=False)
    except IndexError: flash('Invalid index')
    return redirect(url_for('config_page')+'#schedule')

@app.route('/api/schedule/set-default', methods=['POST'])
@login_required
def schedule_set_default():
    cfg = load_config(); mon_idx = int(request.form.get('monitor_id',1))-1
    try:
        cfg['monitors'][mon_idx]['default_playlist'] = request.form.get('playlist','')
        save_config(cfg); flash('Default playlist updated')
        subprocess.run(['systemctl','restart','videowall-display'],check=False)
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
    pw = request.form.get('new_password','')
    if pw: cfg['system']['admin_password_hash'] = hash_pw(pw)
    save_config(cfg); flash('Settings saved')
    return redirect(url_for('config_page')+'#system')

@app.route('/api/restart', methods=['POST'])
@login_required
def restart():
    subprocess.run(['systemctl','restart','videowall-display'],check=False)
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
            subprocess.run(['systemctl','restart','videowall-display'], check=False)
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
        flash('Schedule rule updated')
        subprocess.run(['systemctl','restart','videowall-display'], check=False)
    except IndexError:
        flash('Invalid rule')
    return redirect(url_for('config_page')+'#schedule')

if __name__=='__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
