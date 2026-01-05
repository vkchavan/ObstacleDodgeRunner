# app.py -- Asphalt Rush Dashboard (Diagonal theme background)
# Only visual change: dashboard background is diagonal split (white <> accent)
# Functionality (endpoints, start/stop, color API, logs, submit_score) unchanged.

import os, sys, json, subprocess, threading, time
from flask import Flask, render_template_string, request, jsonify

APP_PORT = 5000
GAME_SCRIPT = "main.py"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GAME_PATH = os.path.join(BASE_DIR, GAME_SCRIPT)
LOG_FILE = os.path.join(BASE_DIR, "session_logs.json")

runtime = {"proc": None, "pid": None, "start_time": None, "args": None}
last_run = {"score": None, "lanes": None, "start_time": None, "end_time": None, "duration_s": None}
logs = []

selected_color = {"hex": "#0f766e", "name": "Teal Dark"}   # darker default
theme_key = "green"

# persist logs best-effort
try:
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w") as f:
            json.dump([], f)
    else:
        with open(LOG_FILE, "r") as f:
            try:
                past = json.load(f)
                if isinstance(past, list):
                    logs.extend(past[-300:])
            except Exception:
                logs.append({"t": time.time(), "level": "warn", "msg": "failed to load logs"})
except Exception:
    pass

def append_log(level, msg, extra=None):
    e = {"t": time.time(), "level": level, "msg": msg}
    if extra is not None:
        e["extra"] = extra
    logs.append(e)
    if len(logs) > 2000:
        logs.pop(0)
    def writer(entry):
        try:
            try:
                with open(LOG_FILE, "r") as f:
                    data = json.load(f)
            except Exception:
                data = []
            data.append(entry)
            if len(data) > 5000:
                data = data[-5000:]
            with open(LOG_FILE, "w") as f:
                json.dump(data, f)
        except Exception:
            pass
    threading.Thread(target=writer, args=(e,), daemon=True).start()

append_log("info", "Dashboard starting (Asphalt Rush — JV)")

app = Flask(__name__)

INDEX_HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Asphalt Rush — Dashboard (JV)</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  /* base tokens */
  :root{
    --white:#ffffff;
    --bg:#f3f6f9;
    --card:#ffffff;
    --muted:#556070;
    --text:#0f172a;
    --green-600:#16a34a; --green-500:#22c55e;
    --blue-700:#0369a1;  --blue-500:#0572c9;
  }

  /* Theme classes provide accent colors used across controls */
  body.theme-green{
    --accent: var(--green-600);
    --accent2: var(--green-500);
    --accent-solid: #16a34a;
  }
  body.theme-blue{
    --accent: var(--blue-700);
    --accent2: var(--blue-500);
    --accent-solid: #0369a1;
  }

  /* DIAGONAL BACKGROUND:
     We create a big fixed pseudo-layer by styling the body with a diagonal linear-gradient.
     The upper-left half is white and lower-right half is accent color (45deg) to achieve a diagonal split.
     Cards keep their white backgrounds for readability. */
  body{
    margin:0;
    font-family:Inter, system-ui, -apple-system, "Segoe UI", Roboto, Arial;
    color:var(--text);
    /* fallback bg if theme class not applied */
    background: linear-gradient(135deg, var(--white) 0%, var(--white) 50%, var(--accent) 50%, var(--accent) 100%);
    min-height:100vh;
  }
  /* ensure each theme uses its accent in the diagonal */
  body.theme-green{
    background: linear-gradient(135deg, var(--white) 0%, var(--white) 48.5%, var(--accent) 48.5%, var(--accent2) 100%);
  }
  body.theme-blue{
    background: linear-gradient(135deg, var(--white) 0%, var(--white) 48.5%, var(--accent) 48.5%, var(--accent2) 100%);
  }

  /* page layout */
  .wrap{max-width:1100px;margin:28px auto;padding:20px}
  .card{background:var(--card);border-radius:12px;padding:20px;box-shadow:0 8px 36px rgba(3,7,18,0.06)}
  .two-column{display:flex;gap:18px}
  .left{width:420px}
  .header{display:flex;align-items:center;gap:16px}
  .logo{width:56px;height:56px;border-radius:10px;background:linear-gradient(135deg,var(--accent),var(--accent2));display:flex;align-items:center;justify-content:center;color:#fff;font-weight:900}
  h1{margin:0;font-size:20px}
  .desc{color:var(--muted);margin-top:6px}
  label{display:block;margin-top:12px;font-size:13px;color:var(--muted)}
  select{width:100%;padding:10px;border-radius:8px;border:1px solid rgba(2,6,23,0.04);background:#fff}
  .controls{display:flex;gap:10px;margin-top:12px}
  .btn{
    position:relative;overflow:visible;
    background:linear-gradient(90deg,var(--accent) 0%, var(--accent2) 100%);
    color:#fff;border:none;padding:10px 14px;border-radius:8px;cursor:pointer;font-weight:700;
    box-shadow:0 8px 20px rgba(3,7,18,0.12);transition:transform .12s ease, box-shadow .12s ease;
  }
  .btn:hover{ transform: translateY(-4px); box-shadow:0 14px 36px rgba(3,7,18,0.18); }
  .btn:active{ transform: translateY(-1px) scale(.995); box-shadow:0 8px 20px rgba(3,7,18,0.12); }
  .btn.ghost{
    background:#fff;border:1px solid rgba(15,23,42,0.06); color:var(--muted); font-weight:700; box-shadow:none;
  }

  .swatches{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
  .swatch{width:44px;height:44px;border-radius:8px;cursor:pointer;border:2px solid rgba(2,6,23,0.04);transition:transform .08s ease, box-shadow .12s}
  .swatch:hover{ transform: translateY(-3px); box-shadow:0 10px 26px rgba(2,6,23,0.12); }
  .swatch.selected{outline:3px solid rgba(0,0,0,0.06)}
  .preview{height:66px;border-radius:10px;margin-top:10px;display:flex;align-items:center;justify-content:center;background:linear-gradient(180deg,#fff,#f6f8fb);border:1px solid rgba(2,6,23,0.03)}
  .fakecar{width:170px;height:48px;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:900;letter-spacing:0.6px}
  .logs{height:320px;overflow:auto;padding:10px;border-radius:8px;border:1px dashed rgba(2,6,23,0.04);background:linear-gradient(180deg,#fff,#fbfdff);margin-top:10px}
  .log-entry{font-family:monospace;font-size:12px;padding:8px;border-bottom:1px solid rgba(2,6,23,0.03)}

  .theme-toggle{display:flex;gap:8px;margin-top:8px;align-items:center}
  .theme-pill{
    width:120px;height:48px;padding:8px;border-radius:8px;border:1px solid rgba(2,6,23,0.04);cursor:pointer;display:flex;align-items:center;justify-content:center;font-weight:800;
    color:var(--text);transition:transform .12s, box-shadow .12s;
  }
  .theme-pill.green{
    background: linear-gradient(180deg, #fff 0%, #fff 50%, var(--green-600) 50%, var(--green-500) 100%);
  }
  .theme-pill.blue{
    background: linear-gradient(180deg, #fff 0%, #fff 50%, var(--blue-700) 50%, var(--blue-500) 100%);
  }
  .theme-pill.active{ box-shadow:0 10px 30px rgba(3,7,18,0.08); transform: translateY(-3px); }

  footer{margin-top:16px;color:var(--muted);font-size:13px}
  @media (max-width:980px){ .two-column{flex-direction:column} .left{width:100%} }
</style>
</head>
<body class="theme-green">
<div class="wrap">
  <div class="card">
    <div class="header">
      <div class="logo">JV</div>
      <div style="flex:1">
        <h1>Asphalt Rush — Dashboard</h1>
        <div class="desc">Pick lanes, mode and a bold car color. Click a theme to switch the whole dashboard style.</div>
      </div>
      <div style="text-align:right">
        <div style="font-weight:700;color:var(--accent2)">Server</div>
        <div class="small">Local</div>
      </div>
    </div>

    <div class="two-column" style="margin-top:18px">
      <div class="left">
        <div class="card" style="padding:12px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div>
              <div class="small">Number of lanes</div>
              <select id="lanes">{% for n in range(2,7) %}<option value="{{n}}">{{n}} lanes</option>{% endfor %}</select>
            </div>
            <div style="width:12px"></div>
            <div>
              <div class="small">Mode</div>
              <select id="mode"><option value="normal">Normal</option><option value="hard">Hard</option></select>
            </div>
          </div>

          <div class="controls" style="margin-top:14px">
            <button id="startBtn" class="btn">Start Game</button>
            <button id="stopBtn" class="btn ghost" disabled>Stop Game</button>
            <button id="refreshBtn" class="btn ghost">Refresh</button>
          </div>

          <label>Car color</label>
          <div id="swatches" class="swatches"></div>
          <div class="preview"><div id="fakeCar" class="fakecar" style="background:#0f766e">JV</div></div>
          <div class="small" style="margin-top:8px">Click a color to preview. Starting passes this color to the game; running game updates color live.</div>
        </div>

        <div style="margin-top:12px" class="card">
          <strong>Last run</strong>
          <div style="margin-top:8px" class="small">Score: <span id="lr_score">—</span></div>
          <div class="small">Lanes: <span id="lr_lanes">—</span></div>
          <div class="small">Duration: <span id="lr_duration">—</span></div>
          <div class="small" id="lr_time">No runs yet</div>
        </div>
      </div>

      <div style="flex:1">
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div>
              <strong>Session Logs</strong>
              <div class="small">Launches, color changes, score posts.</div>
            </div>

            <div class="theme-toggle">
              <div id="themeGreen" class="theme-pill green active">White<br>&bull; Green</div>
              <div id="themeBlue"  class="theme-pill blue">White<br>&bull; Blue</div>
            </div>
          </div>

          <div id="logsBox" class="logs" style="margin-top:12px"></div>

          <footer style="margin-top:12px">Run from the project folder where <code>{{ game_script }}</code> exists. Game shows white lane dividers on black road.</footer>
        </div>
      </div>
    </div>

  </div>
</div>

<script>
document.addEventListener('DOMContentLoaded', function(){
  const PRESET_COLORS = [
    {hex:"#0f766e", name:"Teal Dark"},
    {hex:"#0f7a2a", name:"Green Dark"},
    {hex:"#075985", name:"Blue Dark"},
    {hex:"#0ea5a4", name:"Cyan"},
    {hex:"#9a3412", name:"Deep Orange"},
    {hex:"#b91c1c", name:"Deep Red"},
    {hex:"#6d28d9", name:"Deep Purple"},
    {hex:"#92400e", name:"Amber Dark"},
    {hex:"#0f172a", name:"Charcoal"},
    {hex:"#9f1239", name:"Crimson"},
    {hex:"#0b815a", name:"Emerald"},
    {hex:"#78350f", name:"Bronze"}
  ];

  const swatchesContainer = document.getElementById('swatches');
  const fakeCar = document.getElementById('fakeCar');
  const startBtn = document.getElementById('startBtn');
  const stopBtn = document.getElementById('stopBtn');
  const refreshBtn = document.getElementById('refreshBtn');
  const themeGreen = document.getElementById('themeGreen');
  const themeBlue = document.getElementById('themeBlue');
  const logsBox = document.getElementById('logsBox');

  async function api(path, opts){
    try {
      const r = await fetch(path, opts);
      if (r.ok) return await r.json();
      let text = await r.text().catch(()=>null);
      throw new Error((text && text.length<1000)? text : r.statusText || 'HTTP error');
    } catch (err) {
      return { _error: String(err) };
    }
  }

  function addLog(level, msg, extra){
    const el = document.createElement('div'); el.className = 'log-entry';
    const t = new Date().toLocaleTimeString();
    el.textContent = `[${t}] ${level.toUpperCase()} — ${msg}` + (extra? ' ' + JSON.stringify(extra): '');
    logsBox.prepend(el);
  }

  function renderSwatches(selectedHex){
    swatchesContainer.innerHTML = '';
    PRESET_COLORS.forEach(c=>{
      const d = document.createElement('div');
      d.className = 'swatch'; d.style.background = c.hex; d.title = c.name;
      if((c.hex||'').toLowerCase() === (selectedHex||'').toLowerCase()) d.classList.add('selected');
      d.addEventListener('click', async ()=>{
        document.querySelectorAll('.swatch').forEach(x=>x.classList.remove('selected'));
        d.classList.add('selected');
        fakeCar.style.background = c.hex;
        const r = await api('/api/set_color', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({hex:c.hex, name:c.name})});
        if(r && r._error) addLog('warn','Failed to set color', r._error); else addLog('info','Color selected', {hex:c.hex, name:c.name});
      });
      swatchesContainer.appendChild(d);
    });
  }

  async function loadColor(){
    const resp = await api('/api/color');
    if(resp && !resp._error && resp.hex){
      renderSwatches(resp.hex); fakeCar.style.background = resp.hex;
    } else { renderSwatches('#0f766e'); fakeCar.style.background = '#0f766e'; if(resp && resp._error) addLog('warn','Failed to fetch color', resp._error); }
  }

  async function refreshLogs(){
    const r = await api('/api/logs');
    if(r && r._error){ addLog('warn','Failed to load logs', r._error); return; }
    logsBox.innerHTML = '';
    for(const e of (r.logs||[])){
      const el = document.createElement('div'); el.className='log-entry';
      el.textContent = `[${new Date(e.t*1000).toLocaleTimeString()}] ${e.level.toUpperCase()} — ${e.msg}` + (e.extra? ' '+JSON.stringify(e.extra):'');
      logsBox.prepend(el);
    }
  }

  async function refreshLastRun(){
    const r = await api('/api/last_run');
    if(r && !r._error){
      document.getElementById('lr_score').textContent = r.score===null? '—' : r.score;
      document.getElementById('lr_lanes').textContent = r.lanes===null? '—' : r.lanes;
      document.getElementById('lr_duration').textContent = r.duration_s===null? '—' : (r.duration_s + 's');
      document.getElementById('lr_time').textContent = r.start_time? new Date(r.start_time*1000).toLocaleString() : 'No runs yet';
    }
  }

  async function refreshRuntime(){
    const r = await api('/api/runtime');
    if(r && r._error){ addLog('warn','Failed to get runtime', r._error); return; }
    if(r.running){ startBtn.disabled = true; stopBtn.disabled = false; } else { startBtn.disabled = false; stopBtn.disabled = true; }
  }

  startBtn.addEventListener('click', async ()=>{
    startBtn.disabled = true;
    const lanes = parseInt(document.getElementById('lanes').value||3);
    const mode = document.getElementById('mode').value || 'normal';
    const resp = await api('/api/start', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({lanes, mode})});
    if(resp && resp._error){ addLog('error','Start failed', resp._error); alert('Start failed: '+resp._error); startBtn.disabled = false; }
    else if(resp && resp.ok){ addLog('info','Game started', resp.meta||null); refreshRuntime(); } else { addLog('error','Start failed', resp); alert('Start failed'); startBtn.disabled = false; }
  });

  stopBtn.addEventListener('click', async ()=>{
    stopBtn.disabled = true;
    const r = await api('/api/stop', {method:'POST'});
    if(r && r._error){ addLog('error','Stop failed', r._error); alert('Stop failed: '+r._error); stopBtn.disabled = false; } else { addLog('info','Stop requested', r.meta||null); refreshRuntime(); }
  });

  refreshBtn.addEventListener('click', async ()=>{ await refreshLogs(); await refreshLastRun(); await refreshRuntime(); });

  // Theme handlers: apply body class (diagonal split will reflect chosen theme)
  themeGreen.addEventListener('click', async ()=>{
    document.body.classList.remove('theme-blue'); document.body.classList.add('theme-green');
    themeGreen.classList.add('active'); themeBlue.classList.remove('active');
    const r = await api('/api/set_theme', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({key:'green'})});
    if(r && r._error) addLog('warn','Failed to set theme', r._error);
  });

  themeBlue.addEventListener('click', async ()=>{
    document.body.classList.remove('theme-green'); document.body.classList.add('theme-blue');
    themeBlue.classList.add('active'); themeGreen.classList.remove('active');
    const r = await api('/api/set_theme', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({key:'blue'})});
    if(r && r._error) addLog('warn','Failed to set theme', r._error);
  });

  // init
  loadColor(); refreshLogs(); refreshLastRun(); refreshRuntime();
  setInterval(refreshLogs, 3000); setInterval(refreshLastRun, 3000); setInterval(refreshRuntime, 1500);
});
</script>
</body>
</html>
"""

def check_game_script():
    if not os.path.exists(GAME_PATH):
        append_log("error", f"Game script not found: {GAME_PATH}")
        return False
    return True

@app.route("/", methods=["GET"])
def index():
    return render_template_string(INDEX_HTML, game_script=GAME_SCRIPT)

@app.route("/api/runtime", methods=["GET"])
def api_runtime():
    running = False; pid = None
    proc = runtime.get("proc")
    if proc:
        try:
            if proc.poll() is None:
                running = True; pid = runtime.get("pid")
            else:
                append_log("info", "Game terminated (detected)", {"pid": runtime.get("pid"), "retcode": proc.poll()})
                runtime["proc"] = None; runtime["pid"] = None
                if last_run.get("start_time") and not last_run.get("end_time"):
                    last_run["end_time"] = time.time(); last_run["duration_s"] = int(last_run["end_time"] - last_run["start_time"])
        except Exception:
            running = False
    return jsonify({"running": running, "pid": pid})

@app.route("/api/start", methods=["POST"])
def api_start():
    if not check_game_script():
        return jsonify({"ok": False, "error": "game script not found"}), 400
    proc = runtime.get("proc")
    if proc:
        try:
            if proc.poll() is None:
                return jsonify({"ok": False, "error": "game already running", "meta": {"pid": runtime.get("pid")}}), 400
            else:
                runtime["proc"] = None; runtime["pid"] = None
        except Exception:
            runtime["proc"] = None; runtime["pid"] = None

    data = request.get_json(force=True) if request.data else {}
    lanes = int(data.get("lanes", 3)); lanes = max(2, min(6, lanes))
    mode = data.get("mode", "normal")
    color_hex = selected_color.get("hex")
    args = [sys.executable, GAME_PATH, "--lanes", str(lanes), "--caller", "dashboard"]
    if mode == "hard": args.append("--hard")
    if color_hex: args += ["--car-color", color_hex]

    append_log("info", "Launching game", {"args": args})
    try:
        if os.name == "nt":
            proc = subprocess.Popen(args, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            proc = subprocess.Popen(args, start_new_session=True)
        runtime["proc"] = proc; runtime["pid"] = proc.pid; runtime["start_time"] = time.time(); runtime["args"] = args
        last_run["start_time"] = runtime["start_time"]; last_run["end_time"] = None; last_run["duration_s"] = None; last_run["score"] = None; last_run["lanes"] = lanes
        append_log("info", "Game launched", {"pid": proc.pid, "lanes": lanes, "mode": mode, "color": color_hex})
        return jsonify({"ok": True, "meta": {"pid": proc.pid, "lanes": lanes}})
    except Exception as e:
        append_log("error", "Failed to launch game", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/stop", methods=["POST"])
def api_stop():
    proc = runtime.get("proc")
    if not proc:
        return jsonify({"ok": False, "error": "no running process started via dashboard"}), 400
    try:
        append_log("info", "Stopping game", {"pid": runtime.get("pid")})
        try:
            proc.terminate()
            for _ in range(10):
                if proc.poll() is not None: break
                time.sleep(0.15)
            if proc.poll() is None:
                proc.kill()
        except Exception:
            try: proc.kill()
            except Exception: pass
        ret = proc.poll()
        append_log("info", "Game stopped", {"pid": runtime.get("pid"), "retcode": ret})
        if last_run.get("start_time") and not last_run.get("end_time"):
            last_run["end_time"] = time.time(); last_run["duration_s"] = int(last_run["end_time"] - last_run["start_time"])
        runtime["proc"] = None; runtime["pid"] = None; runtime["start_time"] = None; runtime["args"] = None
        return jsonify({"ok": True, "meta": {"retcode": ret}})
    except Exception as e:
        append_log("error", "Failed to stop game", {"error": str(e)})
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/submit_score", methods=["POST"])
def submit_score():
    try:
        data = request.get_json(force=True)
        score = int(data.get("score", 0)); lanes = int(data.get("lanes", 0))
    except Exception:
        append_log("warn", "submit_score invalid JSON")
        return jsonify({"ok": False, "error": "invalid JSON"}), 400
    append_log("info", "Score submitted by game", {"score": score, "lanes": lanes})
    last_run["score"] = score; last_run["lanes"] = lanes; last_run["end_time"] = time.time()
    if last_run.get("start_time"):
        last_run["duration_s"] = int(last_run["end_time"] - last_run["start_time"])
    return jsonify({"ok": True})

@app.route("/api/last_run", methods=["GET"])
def api_last_run():
    return jsonify({
        "score": last_run.get("score"),
        "lanes": last_run.get("lanes"),
        "start_time": last_run.get("start_time"),
        "end_time": last_run.get("end_time"),
        "duration_s": last_run.get("duration_s")
    })

@app.route("/api/logs", methods=["GET"])
def api_logs():
    launch_count = sum(1 for e in logs if 'launch' in e.get("msg","").lower())
    scored_runs = sum(1 for e in logs if e.get("msg","").lower().startswith("score submitted"))
    return jsonify({"logs": logs[-400:], "stats": {"launch_count": launch_count, "scored_runs": scored_runs}})

@app.route("/api/clear_logs", methods=["POST"])
def api_clear_logs():
    logs.clear(); append_log("info", "In-memory logs cleared by user"); return jsonify({"ok": True})

@app.route("/api/color", methods=["GET"])
def api_color():
    return jsonify(selected_color)

@app.route("/api/set_color", methods=["POST"])
def api_set_color():
    global selected_color
    try:
        data = request.get_json(force=True)
        hexv = data.get("hex"); name = data.get("name","")
        if not hexv: return jsonify({"ok": False, "error": "missing hex"}), 400
        if not (isinstance(hexv, str) and hexv.startswith("#") and len(hexv) in (4,7)):
            return jsonify({"ok": False, "error": "invalid hex"}), 400
        selected_color = {"hex": hexv, "name": name}
        append_log("info", "Color selected on dashboard", {"hex": hexv, "name": name})
        return jsonify({"ok": True, "color": selected_color})
    except Exception as e:
        append_log("error", "Failed to set color", {"error": str(e)}); return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/theme", methods=["GET"])
def api_theme(): return jsonify({"key": theme_key})
@app.route("/api/set_theme", methods=["POST"])
def api_set_theme():
    global theme_key
    try:
        data = request.get_json(force=True)
        key = data.get("key","green")
        if key not in ("green","blue"): key = "green"
        theme_key = key
        append_log("info", "Theme changed", {"theme": key})
        return jsonify({"ok": True, "key": theme_key})
    except Exception as e:
        append_log("error", "Failed to set theme", {"error": str(e)}); return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    append_log("info", f"Dashboard listening on http://127.0.0.1:{APP_PORT} (Asphalt Rush JV)")
    print(f"Starting dashboard on http://127.0.0.1:{APP_PORT}")
    app.run(host="127.0.0.1", port=APP_PORT, debug=False)