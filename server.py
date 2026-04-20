"""
WAVELINK Server — TCP audio streaming with SSL/SHA-256
  • Serves .wav files from ./music
  • Max 5 concurrent clients
  • Flask-based monitor UI
  • Genre tagging via song_tags.json
"""

import subprocess, sys

def _install(pkg):
    subprocess.run([sys.executable, "-m", "pip", "install", pkg], check=True)

for _pkg in ["flask", "cryptography"]:
    try:
        __import__(_pkg)
    except ImportError:
        _install(_pkg)

import os, socket, wave, threading, struct, time, ssl, webbrowser, select
import collections, json
from flask import Flask, jsonify, send_file, request, render_template_string

# ── CONFIG ────────────────────────────────────────────────────────────────────
STREAM_PORT  = 9893
WEB_PORT     = 9894
CHUNK_SIZE   = 4096
MUSIC_FOLDER = "music"
TAGS_FILE    = "song_tags.json"
MAX_CLIENTS  = 5

# ── SSL CERTIFICATE (SHA-256) ─────────────────────────────────────────────────
def ensure_ssl():
    if os.path.exists("server.crt") and os.path.exists("server.key"):
        return
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import datetime

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WavelinkServer")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    with open("server.key", "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
    with open("server.crt", "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

ensure_ssl()

ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ssl_ctx.load_cert_chain("server.crt", "server.key")

# ── MUSIC LIBRARY ─────────────────────────────────────────────────────────────
if not os.path.isdir(MUSIC_FOLDER):
    print(f"ERROR: '{MUSIC_FOLDER}' folder not found."); sys.exit(1)

songs = sorted(f for f in os.listdir(MUSIC_FOLDER) if f.lower().endswith(".wav"))
if not songs:
    print("ERROR: No .wav files in music folder."); sys.exit(1)

song_durations = {}
song_has_art   = {}
for s in songs:
    song_durations[s] = 0.0
    song_has_art[s]   = False
    try:
        wf = wave.open(os.path.join(MUSIC_FOLDER, s), "rb")
        song_durations[s] = round(wf.getnframes() / wf.getframerate(), 2)
        wf.close()
    except Exception:
        pass
    base = os.path.splitext(s)[0]
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        if os.path.exists(os.path.join(MUSIC_FOLDER, base + ext)):
            song_has_art[s] = True
            break

# ── TAGS ──────────────────────────────────────────────────────────────────────
def load_tags():
    if os.path.exists(TAGS_FILE):
        try:
            with open(TAGS_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_tags(tags):
    with open(TAGS_FILE, "w") as f:
        json.dump(tags, f, indent=2)

song_tags = load_tags()
tags_lock = threading.Lock()

# ── SHARED STATE ──────────────────────────────────────────────────────────────
state_lock       = threading.Lock()
active_streams   = {}     # addr_str -> info dict
finished_streams = []     # completed stream reports
log_entries      = []     # server log lines
client_states    = {}     # addr_str -> {"skip", "disconnect"}
client_count     = 0      # current connected client count

def slog(msg):
    ts = time.strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    with state_lock:
        log_entries.append(entry)
        if len(log_entries) > 300:
            log_entries.pop(0)
    print(entry)

# ── PACKET HELPERS ────────────────────────────────────────────────────────────
def send_packet(conn, data):
    conn.sendall(struct.pack("!I", len(data)) + data)

def send_end(conn):
    conn.sendall(struct.pack("!I", 0))

def send_control(conn, msg):
    enc = msg.encode()
    conn.sendall(struct.pack("!I", 0xFFFFFFFF) + struct.pack("!I", len(enc)) + enc)

# ── CLIENT HANDLER ────────────────────────────────────────────────────────────
def handle_client(conn, addr):
    global client_count
    addr_str = f"{addr[0]}:{addr[1]}"
    slog(f"Connected: {addr_str}")

    # TCP keepalive
    try:
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if hasattr(socket, "TCP_KEEPIDLE"):
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 5)
        if hasattr(socket, "TCP_KEEPINTVL"):
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 2)
        if hasattr(socket, "TCP_KEEPCNT"):
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
    except Exception:
        pass

    with state_lock:
        client_states[addr_str] = {"skip": False, "disconnect": False}

    wf = None
    try:
        while True:
            # Wait for READY
            conn.settimeout(30)
            ready_buf = b""
            try:
                while b"READY" not in ready_buf:
                    chunk = conn.recv(32)
                    if not chunk:
                        raise ConnectionResetError("client gone")
                    ready_buf += chunk
                    if len(ready_buf) > 128:
                        ready_buf = ready_buf[-128:]
            except socket.timeout:
                slog(f"Timeout waiting for READY: {addr_str}")
                return
            conn.settimeout(None)

            # Send song list
            song_data = []
            for i, s in enumerate(songs):
                dur = song_durations.get(s, 0.0)
                art = 1 if song_has_art.get(s, False) else 0
                song_data.append(f"{i+1}|{s}|{dur}|{art}")
            conn.sendall(("\n".join(song_data) + "\nCHOOSE:").encode())

            # Wait for choice
            conn.settimeout(300)
            choice_raw = b""
            timeout_count = 0
            while True:
                try:
                    chunk = conn.recv(64)
                    if not chunk:
                        raise ConnectionResetError
                    choice_raw += chunk
                    if b"\n" in choice_raw or len(choice_raw) >= 10:
                        break
                except socket.timeout:
                    timeout_count += 1
                    if timeout_count >= 2:
                        slog(f"Client idle too long, disconnecting: {addr_str}")
                        return
                    continue
            conn.settimeout(None)

            try:
                index = int(choice_raw.decode().strip()) - 1
                if not (0 <= index < len(songs)):
                    slog(f"Invalid choice from {addr_str}: {index+1}")
                    continue
            except ValueError:
                slog(f"Non-numeric choice from {addr_str}")
                continue

            song_name = songs[index]
            song_path = os.path.join(MUSIC_FOLDER, song_name)
            duration  = song_durations.get(song_name, 0.0)
            slog(f"Streaming '{song_name}' → {addr_str}")

            with state_lock:
                client_states[addr_str]["skip"]       = False
                client_states[addr_str]["disconnect"]  = False

            # Send metadata
            wf        = wave.open(song_path, "rb")
            channels  = wf.getnchannels()
            rate      = wf.getframerate()
            sampwidth = wf.getsampwidth()
            meta      = f"{channels}|{rate}|{sampwidth}|{duration}|{song_name}"
            conn.sendall(struct.pack("!I", len(meta)) + meta.encode())

            with state_lock:
                active_streams[addr_str] = {
                    "song": song_name, "client": addr_str,
                    "start": time.time(), "chunks": 0, "bytes": 0,
                    "throughput": 0, "duration": duration,
                    "chunk_history": [], "send_buf": 0,
                }

            # Stream audio
            frames_per_chunk = CHUNK_SIZE // (channels * sampwidth)
            chunk_duration   = frames_per_chunk / rate
            SEND_BUF_MAX     = 16

            send_queue   = collections.deque()
            total_chunks = 0
            total_bytes  = 0
            start_time   = time.time()
            skipped      = False

            def prefill():
                while len(send_queue) < SEND_BUF_MAX:
                    frame = wf.readframes(frames_per_chunk)
                    if not frame:
                        break
                    send_queue.append(frame)

            prefill()
            chunk_send_time = time.time()

            while send_queue:
                with state_lock:
                    do_skip       = client_states[addr_str]["skip"]
                    do_disconnect = client_states[addr_str]["disconnect"]

                if do_disconnect:
                    slog(f"Disconnect: {addr_str}")
                    try:
                        send_control(conn, "DISCONNECTED")
                    except Exception:
                        pass
                    with state_lock:
                        active_streams.pop(addr_str, None)
                    return

                if do_skip:
                    slog(f"Skip: {addr_str}")
                    try:
                        send_control(conn, "SKIP")
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                    skipped = True
                    break

                # Detect client-initiated skip (client sent READY during stream)
                try:
                    has_data = getattr(conn, 'pending', lambda: 0)() > 0
                    if not has_data:
                        rd, _, _ = select.select([conn], [], [], 0)
                        has_data = bool(rd)
                    if has_data:
                        slog(f"Client skip (data received): {addr_str}")
                        skipped = True
                        break
                except Exception:
                    pass

                data = send_queue.popleft()
                prefill()

                now_t   = time.time()
                sleep_t = chunk_send_time - now_t
                if sleep_t > 0:
                    time.sleep(sleep_t)
                chunk_send_time = max(chunk_send_time, time.time()) + chunk_duration

                try:
                    send_packet(conn, data)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    slog(f"Client gone: {addr_str}")
                    with state_lock:
                        active_streams.pop(addr_str, None)
                    return

                total_chunks += 1
                total_bytes  += len(data)
                elapsed = time.time() - start_time
                tp = round((total_bytes / elapsed) / 1024, 1) if elapsed > 0 else 0

                with state_lock:
                    if addr_str in active_streams:
                        s = active_streams[addr_str]
                        s["chunks"]     = total_chunks
                        s["bytes"]      = total_bytes
                        s["throughput"] = tp
                        s["send_buf"]   = len(send_queue)
                        ch = s["chunk_history"]
                        ch.append(time.time())
                        if len(ch) > 40:
                            ch.pop(0)

            if not skipped:
                try:
                    send_end(conn)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

            wf.close()
            wf = None

            elapsed = time.time() - start_time
            tp = (total_bytes / elapsed) / 1024 if elapsed > 0 else 0
            with state_lock:
                finished_streams.append({
                    "song": song_name, "client": addr_str,
                    "duration": round(elapsed, 2), "chunks": total_chunks,
                    "bytes_kb": round(total_bytes / 1024, 1),
                    "throughput": round(tp, 1),
                    "skipped": skipped, "time": time.strftime("%H:%M:%S"),
                })
                if len(finished_streams) > 100:
                    finished_streams.pop(0)
                active_streams.pop(addr_str, None)

            slog(f"Done: '{song_name}' → {addr_str} | {round(elapsed,1)}s | {round(tp,1)} KB/s")

            with state_lock:
                if client_states.get(addr_str, {}).get("disconnect"):
                    break

    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
        slog(f"Client disconnected: {addr_str}")
    except ssl.SSLError as e:
        slog(f"SSL error {addr_str}: {e}")
    finally:
        if wf:
            try:
                wf.close()
            except Exception:
                pass
        with state_lock:
            active_streams.pop(addr_str, None)
            client_states.pop(addr_str, None)
            client_count -= 1
        try:
            conn.close()
        except Exception:
            pass
        slog(f"Connection closed: {addr_str} (clients: {client_count})")


# ── FLASK MONITOR UI ──────────────────────────────────────────────────────────
app = Flask(__name__)

MONITOR_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><title>Wavelink Server</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0a0a0a;--s1:#111111;--s2:#181818;--s3:#1e1e1e;
  --border:#2a2a2a;--accent:#1DB954;--amber:#f0a030;
  --green:#1DB954;--red:#f03060;--muted:#6a6a6a;
  --cream:#e0e0e0;--mono:'JetBrains Mono','Courier New',monospace;
}
html,body{height:100%;overflow:hidden}
body{background:var(--bg);color:var(--cream);font-family:'Segoe UI',system-ui,sans-serif;font-size:13px;display:flex;flex-direction:column}
nav{height:48px;background:var(--s1);border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 20px;gap:16px;flex-shrink:0}
.brand{font-weight:800;font-size:15px;letter-spacing:2px;color:var(--accent)}
.pill{background:var(--s3);border:1px solid var(--border);border-radius:20px;padding:3px 10px;font-size:11px;color:var(--muted)}
.pill span{color:var(--cream);font-weight:600}
.dot{width:7px;height:7px;border-radius:50%;background:var(--green);display:inline-block;margin-right:5px;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.layout{flex:1;display:grid;grid-template-columns:220px 1fr 260px;overflow:hidden}
.sidebar{background:var(--s1);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}
.sb-sec{padding:14px;border-bottom:1px solid var(--border)}
.sb-label{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:10px}
.stat-row{display:flex;justify-content:space-between;align-items:center;padding:4px 0}
.stat-row .lbl{font-size:11px;color:var(--muted)}.stat-row .val{font-family:var(--mono);font-size:13px;font-weight:700}
.lib-list{flex:1;overflow-y:auto;padding:8px 0}
.lib-row{padding:6px 14px;display:flex;align-items:center;gap:8px;cursor:default}
.lib-row:hover{background:var(--s2)}
.lib-num{font-family:var(--mono);font-size:10px;color:var(--muted);width:16px;text-align:right;flex-shrink:0}
.lib-name{font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.lib-genre{font-size:9px;color:var(--accent);background:rgba(29,185,84,.12);border-radius:4px;padding:1px 5px;flex-shrink:0}
.center{display:flex;flex-direction:column;overflow:hidden}
.active-panel{padding:14px 18px;border-bottom:1px solid var(--border);flex-shrink:0;max-height:52%}
.active-scroll{overflow-y:auto;max-height:calc(52vh - 80px)}
.stream-card{background:var(--s2);border:1px solid var(--border);border-left:3px solid var(--green);border-radius:8px;padding:12px 14px;margin-bottom:8px}
.sc-addr{font-family:var(--mono);font-size:10px;color:var(--amber);margin-bottom:2px}
.sc-song{font-size:13px;margin-bottom:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sc-stats{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;margin-bottom:8px}
.sc-stat{background:var(--s3);border-radius:5px;padding:5px 8px}
.sc-stat .sl{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.7px}
.sc-stat .sv{font-family:var(--mono);font-size:12px}
.sc-bar-wrap{margin-bottom:8px}
.sc-bar-lbl{font-size:9px;color:var(--muted);margin-bottom:3px;display:flex;justify-content:space-between}
.sc-bar-track{height:5px;background:var(--s3);border-radius:3px;overflow:hidden}
.sc-bar-fill{height:100%;border-radius:3px;transition:width .4s}
.sc-prog{height:3px;background:var(--border);border-radius:2px;margin-bottom:8px;overflow:hidden}
.sc-prog-fill{height:100%;background:linear-gradient(90deg,var(--accent),var(--amber));border-radius:2px;transition:width .8s linear}
.btn-row{display:flex;gap:6px}
.btn{background:transparent;border:1px solid var(--border);border-radius:5px;padding:4px 12px;font-size:11px;font-weight:600;cursor:pointer;color:var(--muted);font-family:inherit;transition:all .15s}
.btn:hover{border-color:var(--accent);color:var(--accent)}
.btn-red:hover{border-color:var(--red);color:var(--red)}
.no-streams{font-size:12px;color:var(--muted);padding:4px 0}
.log-panel{flex:1;display:flex;flex-direction:column;overflow:hidden;padding:14px 18px}
.log-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-shrink:0}
.log-box{flex:1;background:#060606;border:1px solid var(--border);border-radius:8px;padding:10px 12px;overflow-y:auto;font-family:var(--mono);font-size:11px;line-height:1.8}
.ll{white-space:pre}
.ll.c-connect{color:var(--green)}.ll.c-stream{color:var(--amber)}.ll.c-error{color:var(--red)}.ll.c-info{color:var(--muted)}
.tags-panel{background:var(--s1);border-left:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden}
.tags-head{padding:14px;border-bottom:1px solid var(--border);flex-shrink:0;display:flex;align-items:center;justify-content:space-between}
.tags-scroll{flex:1;overflow-y:auto;padding:10px}
.tag-row{background:var(--s2);border:1px solid var(--border);border-radius:7px;padding:10px 12px;margin-bottom:8px}
.tag-song{font-size:11px;margin-bottom:7px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tag-input-wrap{display:flex;gap:6px;align-items:center}
.tag-input{flex:1;background:var(--s3);border:1px solid var(--border);border-radius:5px;padding:5px 8px;font-size:11px;color:var(--cream);font-family:inherit;outline:none;transition:border .15s}
.tag-input:focus{border-color:var(--accent)}
.tag-save{background:transparent;border:1px solid var(--border);border-radius:5px;padding:5px 10px;font-size:10px;font-weight:700;cursor:pointer;color:var(--muted);font-family:inherit;transition:all .15s;white-space:nowrap}
.tag-save:hover{border-color:var(--green);color:var(--green)}
.tag-saved{border-color:var(--green)!important;color:var(--green)!important}
.hist-wrap{border-top:1px solid var(--border);padding:10px}
.hcard{background:var(--s2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;margin-bottom:6px}
.hcard-song{font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:3px}
.hcard-meta{font-size:10px;color:var(--muted);line-height:1.7}.hcard-meta span{color:var(--amber)}
.badge{display:inline-block;padding:1px 6px;border-radius:3px;font-size:9px;font-weight:700}
.badge-done{background:rgba(29,185,84,.1);color:var(--green)}
.badge-skip{background:rgba(240,160,48,.1);color:var(--amber)}
::-webkit-scrollbar{width:3px;height:3px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
</style>
</head>
<body>
<nav>
  <div class="brand">WAVELINK<span style="color:var(--muted);font-weight:400;font-size:12px;margin-left:4px">SERVER</span></div>
  <div class="pill"><span class="dot"></span><span id="n-active">0</span> active</div>
  <div class="pill">IP <span>{{ my_ip }}</span></div>
  <div class="pill">stream :<span>{{ stream_port }}</span></div>
  <div class="pill">ui :<span>{{ web_port }}</span></div>
  <div class="pill">library <span>{{ songs|length }}</span> tracks</div>
  <div class="pill">max <span>{{ max_clients }}</span> clients</div>
</nav>
<div class="layout">
  <aside class="sidebar">
    <div class="sb-sec">
      <div class="sb-label">Overview</div>
      <div class="stat-row"><span class="lbl">Active streams</span><span class="val" id="n-active2">0</span></div>
      <div class="stat-row"><span class="lbl">Total served</span><span class="val" id="n-total">0</span></div>
      <div class="stat-row"><span class="lbl">Throughput KB/s</span><span class="val" id="n-tp">0</span></div>
    </div>
    <div class="sb-sec" style="flex:1;overflow:hidden;display:flex;flex-direction:column;border-bottom:none">
      <div class="sb-label">Library</div>
      <div class="lib-list" id="lib-list">
        {% for song in songs %}
        <div class="lib-row">
          <span class="lib-num">{{ loop.index }}</span>
          <span class="lib-name">{{ song | replace('.wav','') }}</span>
          <span class="lib-genre" id="lg-{{ loop.index0 }}"></span>
        </div>
        {% endfor %}
      </div>
    </div>
  </aside>
  <div class="center">
    <div class="active-panel">
      <div class="sb-label" style="margin-bottom:10px">Active Streams</div>
      <div class="active-scroll" id="active-area"><div class="no-streams">No active streams.</div></div>
    </div>
    <div class="log-panel">
      <div class="log-head">
        <div class="sb-label" style="margin:0">Server Log</div>
        <button class="btn" onclick="document.getElementById('logbox').scrollTop=999999">↓ Bottom</button>
      </div>
      <div class="log-box" id="logbox"></div>
    </div>
  </div>
  <div class="tags-panel">
    <div class="tags-head">
      <div class="sb-label" style="margin:0">Song Tags</div>
      <span style="font-size:10px;color:var(--muted)">genre + language</span>
    </div>
    <div class="tags-scroll" id="tags-scroll">
      {% for song in songs %}
      <div class="tag-row">
        <div class="tag-song" title="{{ song | replace('.wav','') }}">{{ song | replace('.wav','') }}</div>
        <div class="tag-input-wrap">
          <input class="tag-input" id="ti-{{ loop.index0 }}" type="text" placeholder="Genre…" data-song="{{ song }}" style="flex:1" />
          <input class="tag-input" id="tl-{{ loop.index0 }}" type="text" placeholder="Lang…" data-song="{{ song }}" style="flex:1" />
          <button class="tag-save" onclick="saveTag({{ loop.index0 }})">Save</button>
        </div>
      </div>
      {% endfor %}
    </div>
    <div class="hist-wrap">
      <div class="sb-label" style="margin-bottom:8px">Stream History</div>
      <div id="hist-area" style="max-height:160px;overflow-y:auto">
        <div style="font-size:11px;color:var(--muted)">No streams yet.</div>
      </div>
    </div>
  </div>
</div>
<script>
const songs={{ songs_json }};
let tags={},lastLogLen=0;
async function loadTags(){const r=await fetch('/tags');tags=await r.json();songs.forEach((s,i)=>{const gi=document.getElementById('ti-'+i);const li=document.getElementById('tl-'+i);const lbl=document.getElementById('lg-'+i);if(gi&&tags[s])gi.value=tags[s].genre||'';if(li&&tags[s])li.value=tags[s].language||'';if(lbl)lbl.textContent=(tags[s]&&tags[s].genre)?tags[s].genre:''})}
async function saveTag(i){const gi=document.getElementById('ti-'+i);const li=document.getElementById('tl-'+i);const btn=gi.parentElement.querySelector('.tag-save');const song=gi.dataset.song;const genre=gi.value.trim();const language=li?li.value.trim():'';await fetch('/tags/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({song,genre,language})});const lbl=document.getElementById('lg-'+i);if(lbl)lbl.textContent=genre;btn.classList.add('tag-saved');btn.textContent='Saved ✓';setTimeout(()=>{btn.classList.remove('tag-saved');btn.textContent='Save'},1500)}
document.querySelectorAll('.tag-input').forEach((inp)=>{const idx=parseInt(inp.id.split('-')[1]);inp.addEventListener('keydown',e=>{if(e.key==='Enter')saveTag(idx)})});
function logClass(l){if(l.includes('Connected')||l.includes('opened'))return'c-connect';if(l.includes('Streaming')||l.includes('Done'))return'c-stream';if(l.includes('SSL')||l.includes('error'))return'c-error';return'c-info'}
function fmt(sec){sec=Math.floor(sec);return Math.floor(sec/60)+':'+String(sec%60).padStart(2,'0')}
function poll(){fetch('/api/state').then(r=>r.json()).then(d=>{document.getElementById('n-active').textContent=d.active_count;document.getElementById('n-active2').textContent=d.active_count;document.getElementById('n-total').textContent=d.total_count;document.getElementById('n-tp').textContent=d.total_throughput.toFixed(1);const aa=document.getElementById('active-area');if(!Object.keys(d.active).length){aa.innerHTML='<div class="no-streams">No active streams.</div>'}else{aa.innerHTML=Object.entries(d.active).map(([addr,s])=>{const elapsed=(Date.now()/1000)-s.start;const pct=s.duration>0?Math.min(100,(elapsed/s.duration)*100):0;const bufPct=Math.min(100,(s.send_buf/16)*100).toFixed(1);const tpPct=Math.min(100,(s.throughput/400)*100).toFixed(1);return`<div class="stream-card"><div class="sc-addr">${addr}</div><div class="sc-song">${s.song.replace(/\\.wav$/i,'')}</div><div class="sc-stats"><div class="sc-stat"><div class="sl">Chunks</div><div class="sv">${s.chunks}</div></div><div class="sc-stat"><div class="sl">KB/s</div><div class="sv">${s.throughput}</div></div><div class="sc-stat"><div class="sl">Buffer</div><div class="sv">${s.send_buf}/16</div></div></div><div class="sc-bar-wrap"><div class="sc-bar-lbl"><span>Send Buffer</span><span>${bufPct}%</span></div><div class="sc-bar-track"><div class="sc-bar-fill" style="width:${bufPct}%;background:var(--accent)"></div></div></div><div class="sc-bar-wrap"><div class="sc-bar-lbl"><span>Throughput</span><span>${tpPct}%</span></div><div class="sc-bar-track"><div class="sc-bar-fill" style="width:${tpPct}%;background:var(--amber)"></div></div></div><div class="sc-prog"><div class="sc-prog-fill" style="width:${pct.toFixed(1)}%"></div></div><div class="btn-row"><button class="btn" onclick="ctrl('${addr}','skip')">Skip</button><button class="btn btn-red" onclick="ctrl('${addr}','disconnect')">Disconnect</button></div></div>`}).join('')}
if(d.logs.length!==lastLogLen){const box=document.getElementById('logbox');const atBot=box.scrollHeight-box.scrollTop-box.clientHeight<60;box.innerHTML=d.logs.map(l=>`<div class="ll ${logClass(l)}">${l}</div>`).join('');lastLogLen=d.logs.length;if(atBot)box.scrollTop=box.scrollHeight}
if(d.history.length){document.getElementById('hist-area').innerHTML=[...d.history].reverse().slice(0,8).map(r=>`<div class="hcard"><div class="hcard-song">${r.song.replace(/\\.wav$/i,'')}</div><div class="hcard-meta"><span>${r.bytes_kb} KB</span> · <span>${r.throughput} KB/s</span> · ${fmt(r.duration)} <span class="badge ${r.skipped?'badge-skip':'badge-done'}">${r.skipped?'SKIPPED':'DONE'}</span></div></div>`).join('')}
}).catch(()=>{});setTimeout(poll,700)}
function ctrl(addr,action){fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({addr,action})})}
loadTags();poll();
</script>
</body>
</html>
"""

@app.route("/")
def index():
    import json as _json
    from markupsafe import Markup
    return render_template_string(
        MONITOR_HTML,
        songs=songs,
        songs_json=Markup(_json.dumps(songs)),
        stream_port=STREAM_PORT,
        web_port=WEB_PORT,
        my_ip=my_ip,
        max_clients=MAX_CLIENTS,
    )

@app.route("/tags")
def get_tags():
    with tags_lock:
        return jsonify(dict(song_tags))

@app.route("/tags/save", methods=["POST"])
def save_tag_route():
    data  = request.json
    song  = data.get("song", "")
    genre = data.get("genre", "").strip()
    language = data.get("language", "").strip()
    if song in songs:
        with tags_lock:
            existing = song_tags.get(song, {})
            if genre is not None:
                existing["genre"] = genre
            if language is not None:
                existing["language"] = language
            song_tags[song] = existing
            save_tags(song_tags)
    return jsonify({"ok": True})

@app.route("/art/<path:song_name>")
def serve_art(song_name):
    base = os.path.splitext(os.path.basename(song_name))[0]
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        path = os.path.join(MUSIC_FOLDER, base + ext)
        if os.path.exists(path):
            return send_file(path)
    letter = song_name[0].upper() if song_name else "?"
    colors = ["#1DB954", "#f0a030", "#30c880", "#f03060", "#30a0f0"]
    color  = colors[hash(song_name) % len(colors)]
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'>"
           f"<rect width='200' height='200' fill='{color}' opacity='.15'/>"
           f"<text x='100' y='118' text-anchor='middle' font-family='Segoe UI,sans-serif' "
           f"font-size='90' font-weight='700' fill='{color}'>{letter}</text></svg>")
    return app.response_class(svg, mimetype="image/svg+xml")

@app.route("/api/state")
def api_state():
    with state_lock:
        active_copy = {}
        for k, v in active_streams.items():
            c = dict(v)
            c["chunk_history"] = list(v.get("chunk_history", []))
            active_copy[k] = c
        return jsonify({
            "active":           active_copy,
            "active_count":     len(active_streams),
            "total_count":      len(finished_streams),
            "total_throughput": sum(s.get("throughput", 0) for s in active_streams.values()),
            "logs":             list(log_entries),
            "history":          list(finished_streams),
        })

@app.route("/api/control", methods=["POST"])
def api_control():
    data   = request.json
    addr   = data.get("addr", "")
    action = data.get("action", "")
    with state_lock:
        if addr in client_states:
            if action == "skip":
                client_states[addr]["skip"] = True
            if action == "disconnect":
                client_states[addr]["disconnect"] = True
    return jsonify({"ok": True})

def run_flask():
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False, use_reloader=False)


# ── START ─────────────────────────────────────────────────────────────────────
slog(f"Library: {len(songs)} songs")

raw_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
raw_srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
raw_srv.bind(("0.0.0.0", STREAM_PORT))
raw_srv.listen(10)
raw_srv.settimeout(1.0)

my_ip = socket.gethostbyname(socket.gethostname())
slog(f"Stream port : {STREAM_PORT}")
slog(f"Web UI      : http://{my_ip}:{WEB_PORT}")
slog(f"Max clients : {MAX_CLIENTS}")

flask_t = threading.Thread(target=run_flask, daemon=True)
flask_t.start()
time.sleep(0.5)
webbrowser.open(f"http://localhost:{WEB_PORT}")

try:
    while True:
        try:
            raw_conn, addr = raw_srv.accept()
        except socket.timeout:
            continue

        # Enforce max client limit
        with state_lock:
            if client_count >= MAX_CLIENTS:
                slog(f"Rejected {addr[0]}:{addr[1]} — max {MAX_CLIENTS} clients reached")
                try:
                    raw_conn.close()
                except Exception:
                    pass
                continue

        try:
            raw_conn.settimeout(10)
            conn = ssl_ctx.wrap_socket(raw_conn, server_side=True)
            conn.settimeout(None)
        except (ssl.SSLError, socket.timeout, OSError) as e:
            slog(f"SSL handshake failed from {addr}: {e}")
            try:
                raw_conn.close()
            except Exception:
                pass
            continue

        with state_lock:
            client_count += 1

        t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        t.start()

except KeyboardInterrupt:
    slog("Server shutting down.")
    raw_srv.close()
