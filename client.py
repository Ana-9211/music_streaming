"""
WAVELINK Client — connects to server over SSL/TCP, streams audio via sounddevice
  • Flask-based browser UI (Spotify green+black)
  • Buffering with demo/smooth modes
  • Playlist, queue, shuffle, loop, prev/next
  • Live stats: latency, throughput, chunks, underruns
"""

import subprocess, sys

def _install(pkg):
    subprocess.run([sys.executable, "-m", "pip", "install", pkg], check=True)

for _pkg in ["sounddevice", "numpy", "flask"]:
    try:
        __import__(_pkg)
    except ImportError:
        _install(_pkg)

_pycaw = False
if sys.platform == "win32":
    try:
        from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
        _pycaw = True
    except ImportError:
        try:
            _install("pycaw"); _install("comtypes")
            from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
            _pycaw = True
        except Exception:
            pass

import os, socket, ssl, struct, time, threading, collections, json, random, webbrowser
import sounddevice as sd
import numpy as np
from flask import Flask, jsonify, send_from_directory, request as freq

STREAM_PORT = 9893
WEB_PORT    = 9895
PL_DIR      = "playlists"
os.makedirs(PL_DIR, exist_ok=True)

# ── PLAYLIST PERSISTENCE ──────────────────────────────────────────────────────
def load_playlists():
    out = {}
    for f in os.listdir(PL_DIR):
        if f.endswith(".json"):
            try:
                with open(os.path.join(PL_DIR, f)) as fp:
                    d = json.load(fp)
                    out[d["name"]] = d.get("songs", [])
            except Exception:
                pass
    return out

def save_playlist(name, songs_list):
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
    with open(os.path.join(PL_DIR, safe + ".json"), "w") as f:
        json.dump({"name": name, "songs": songs_list}, f)

def delete_playlist_file(name):
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
    try:
        os.remove(os.path.join(PL_DIR, safe + ".json"))
    except Exception:
        pass

# ── WINDOWS VOLUME ────────────────────────────────────────────────────────────
def set_win_volume(level):
    if not _pycaw:
        return
    try:
        for s in AudioUtilities.GetAllSessions():
            if s.Process and s.Process.pid == os.getpid():
                s._ctl.QueryInterface(ISimpleAudioVolume).SetMasterVolume(
                    max(0.0, min(1.0, level)), None
                )
    except Exception:
        pass

# ── SHARED STATE ──────────────────────────────────────────────────────────────
lock = threading.Lock()
P = {
    "screen":          "connect",
    "server_ip":       "",
    "connecting":      False,
    "connect_error":   "",
    "songs":           [],
    "song_tags":       {},
    "song":            None,
    "status":          "idle",
    "progress":        0.0,
    "duration":        0.0,
    "paused":          False,
    "volume":          0.7,
    "muted":           False,
    "shuffle":         False,
    "loop":            False,
    "chunks":          0,
    "recv_buf":        0,
    "buffer_history":  [],
    "underruns":       0,
    "avg_latency":     0.0,
    "throughput":      0.0,
    "queue":           [],
    "playlists":       load_playlists(),
    "active_playlist": None,
    "history":         [],
    "logs":            [],
    "song_started":    False,
    "cmd_choose":      None,
    "cmd_skip":        False,
    "demo_mode":       True,
    "error_msg":       "",
}

def add_log(msg):
    ts = time.strftime("%H:%M:%S")
    with lock:
        P["logs"].append(f"[{ts}] {msg}")
        if len(P["logs"]) > 100:
            P["logs"].pop(0)

# ── FLASK APP ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
_HERE = os.path.dirname(os.path.abspath(__file__))

@app.route("/player")
def player_page():
    return send_from_directory(_HERE, "index.html")

@app.route("/style.css")
def serve_css():
    return send_from_directory(_HERE, "style.css")

@app.route("/app.js")
def serve_js():
    return send_from_directory(_HERE, "app.js")

@app.route("/player/state")
def player_state():
    with lock:
        return jsonify(dict(P))

@app.route("/player/connect", methods=["POST"])
def player_connect():
    data = freq.json or {}
    with lock:
        P["server_ip"]     = data.get("ip", "").strip()
        P["connecting"]    = True
        P["connect_error"] = ""
    return jsonify({"ok": True})

@app.route("/player/stop", methods=["POST"])
def player_stop():
    with lock:
        P["cmd_skip"] = True
        P["status"]   = "idle"
    return jsonify({"ok": True})

@app.route("/player/pause", methods=["POST"])
def player_pause():
    with lock:
        P["paused"] = not P["paused"]
    return jsonify({"ok": True})

@app.route("/player/choose", methods=["POST"])
def player_choose():
    data = freq.json or {}
    with lock:
        P["cmd_choose"] = data.get("choice")
        P["cmd_skip"]   = True
        P["paused"]     = False
        P["status"]     = "buffering"
    return jsonify({"ok": True})

@app.route("/player/skip", methods=["POST"])
def player_skip():
    with lock:
        P["cmd_skip"] = True
        P["paused"]   = False
    return jsonify({"ok": True})

@app.route("/player/prev", methods=["POST"])
def player_prev():
    with lock:
        P["cmd_choose"] = "__prev__"
        P["cmd_skip"]   = True
        P["paused"]     = False
    return jsonify({"ok": True})

@app.route("/player/loop", methods=["POST"])
def player_loop():
    with lock:
        P["loop"] = not P["loop"]
    return jsonify({"loop": P["loop"]})

@app.route("/player/shuffle", methods=["POST"])
def player_shuffle():
    with lock:
        P["shuffle"] = not P["shuffle"]
    return jsonify({"shuffle": P["shuffle"]})

@app.route("/player/volume", methods=["POST"])
def player_volume():
    vol = float((freq.json or {}).get("volume", 1.0))
    vol = max(0.0, min(1.0, vol))
    with lock:
        P["volume"] = vol
    set_win_volume(vol)
    return jsonify({"volume": vol})

@app.route("/player/mute", methods=["POST"])
def player_mute():
    with lock:
        P["muted"] = not P["muted"]
        set_win_volume(0.0 if P["muted"] else P["volume"])
    return jsonify({"muted": P["muted"]})

@app.route("/player/demo_mode", methods=["POST"])
def player_demo_mode():
    with lock:
        P["demo_mode"] = not P["demo_mode"]
    return jsonify({"demo_mode": P["demo_mode"]})

@app.route("/player/queue_add", methods=["POST"])
def queue_add():
    idx = (freq.json or {}).get("index")
    with lock:
        if idx is not None and idx not in P["queue"]:
            P["queue"].append(idx)
    return jsonify({"queue": list(P["queue"])})

@app.route("/player/queue_remove", methods=["POST"])
def queue_remove():
    pos = (freq.json or {}).get("pos", -1)
    with lock:
        if 0 <= pos < len(P["queue"]):
            P["queue"].pop(pos)
    return jsonify({"queue": list(P["queue"])})

@app.route("/player/playlist_create", methods=["POST"])
def playlist_create():
    name = ((freq.json or {}).get("name", "")).strip()
    if name:
        with lock:
            if name not in P["playlists"]:
                P["playlists"][name] = []
            save_playlist(name, P["playlists"][name])
    with lock:
        return jsonify({"playlists": dict(P["playlists"])})

@app.route("/player/playlist_delete", methods=["POST"])
def playlist_delete():
    name = (freq.json or {}).get("name", "")
    with lock:
        P["playlists"].pop(name, None)
        if P["active_playlist"] == name:
            P["active_playlist"] = None
        delete_playlist_file(name)
    return jsonify({"playlists": dict(P["playlists"])})

@app.route("/player/playlist_add_song", methods=["POST"])
def playlist_add_song():
    data = freq.json or {}
    name = data.get("playlist", "")
    idx  = data.get("song_index")
    with lock:
        if name in P["playlists"] and idx is not None:
            P["playlists"][name].append(idx)
            save_playlist(name, P["playlists"][name])
    return jsonify({"playlists": dict(P["playlists"])})

@app.route("/player/playlist_remove_song", methods=["POST"])
def playlist_remove_song():
    data = freq.json or {}
    name = data.get("playlist", "")
    pos  = data.get("pos", -1)
    with lock:
        if name in P["playlists"] and 0 <= pos < len(P["playlists"][name]):
            P["playlists"][name].pop(pos)
            save_playlist(name, P["playlists"][name])
    return jsonify({"playlists": dict(P["playlists"])})

@app.route("/player/playlist_activate", methods=["POST"])
def playlist_activate():
    name  = (freq.json or {}).get("name", "")
    first = None
    with lock:
        P["active_playlist"] = name
        sl = list(P["playlists"].get(name, []))
        if sl:
            first = sl[0]
            P["queue"] = sl[1:]
        else:
            P["queue"] = []
    return jsonify({"first_index": first, "queue": list(P["queue"])})

@app.route("/player/reset", methods=["POST"])
def player_reset():
    with lock:
        P["cmd_skip"]      = True
        P["screen"]        = "connect"
        P["server_ip"]     = ""
        P["connecting"]    = False
        P["connect_error"] = ""
        P["songs"]         = []
        P["song"]          = None
        P["status"]        = "idle"
        P["song_started"]  = False
        P["cmd_choose"]    = None
    return jsonify({"ok": True})

# ── PACKET HELPERS ────────────────────────────────────────────────────────────
def recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        c = sock.recv(n - len(buf))
        if not c:
            return None
        buf += c
    return buf

def recv_packet(sock):
    hdr = recv_exact(sock, 4)
    if not hdr:
        return None, "end"
    length = struct.unpack("!I", hdr)[0]
    if length == 0:
        return None, "end"
    if length == 0xFFFFFFFF:
        sh = recv_exact(sock, 4)
        if not sh:
            return None, "end"
        sz  = struct.unpack("!I", sh)[0]
        msg = recv_exact(sock, sz)
        return (msg.decode() if msg else None), "control"
    data = recv_exact(sock, length)
    return data, "data"

# ── MAIN STREAMING THREAD ────────────────────────────────────────────────────
def run_client():
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode    = ssl.CERT_NONE

    def wait_for_ip():
        while True:
            with lock:
                if P["connecting"] and P["server_ip"]:
                    return P["server_ip"]
            time.sleep(0.2)

    def try_connect(ip):
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        c   = ssl_ctx.wrap_socket(raw, server_hostname=ip)
        try:
            c.settimeout(5)
            c.connect((ip, STREAM_PORT))
            c.settimeout(None)
            add_log(f"Connected to {ip}")
            with lock:
                P["connecting"]    = False
                P["connect_error"] = ""
            return c
        except Exception as e:
            try:
                raw.close()
            except Exception:
                pass
            add_log(f"Connect failed: {e}")
            with lock:
                P["connect_error"] = f"Could not connect to {ip}. Check IP and try again."
                P["connecting"]    = False
                P["server_ip"]     = ""
            return None

    def reset_state():
        with lock:
            P["screen"]          = "connect"
            P["status"]          = "idle"
            P["song"]            = None
            P["songs"]           = []
            P["server_ip"]       = ""
            P["connecting"]      = False
            P["song_started"]    = False
            P["cmd_choose"]      = None
            P["cmd_skip"]        = False
            P["paused"]          = False
            P["error_msg"]       = ""
            P["active_playlist"] = None
            P["progress"]        = 0.0
            P["duration"]        = 0.0
            P["chunks"]          = 0
            P["recv_buf"]        = 0
            P["buffer_history"]  = []
            P["underruns"]       = 0
            P["avg_latency"]     = 0.0
            P["throughput"]      = 0.0

    # Outer loop: reconnect on every disconnect
    while True:
        server_ip = wait_for_ip()
        client = try_connect(server_ip)
        if client is None:
            reset_state()
            continue

        song_history    = []
        history_pos     = -1
        last_choice_int = 1
        disconnected    = False

        # Inner loop: one connection, many songs
        while not disconnected:
            try:
                client.sendall(b"READY\n")
            except (BrokenPipeError, ConnectionResetError, OSError):
                add_log("Server gone sending READY.")
                disconnected = True
                break

            # Receive song list
            message = b""
            try:
                client.settimeout(None)
                while True:
                    chunk = client.recv(4096)
                    if not chunk:
                        disconnected = True
                        break
                    message += chunk
                    if b"CHOOSE:" in message:
                        break
                    if len(message) > 32768:
                        message = message[-32768:]
            except (ConnectionResetError, BrokenPipeError, OSError) as e:
                add_log(f"Server closed: {e}")
                disconnected = True

            if disconnected:
                break
            if b"CHOOSE:" not in message:
                add_log("No CHOOSE: received.")
                disconnected = True
                break

            choose_pos = message.rfind(b"CHOOSE:")
            raw_list   = message[:choose_pos].decode(errors="ignore")
            song_list  = []
            for line in raw_list.split("\n"):
                line = line.strip()
                if "|" in line and line and line[0].isdigit():
                    parts = line.split("|")
                    if len(parts) >= 4:
                        try:
                            song_list.append({
                                "name":     parts[1],
                                "duration": float(parts[2]),
                                "has_art":  parts[3] == "1",
                            })
                        except Exception:
                            continue

            if not song_list:
                add_log("Empty song list.")
                disconnected = True
                break

            with lock:
                P["songs"]    = song_list
                P["screen"]   = "library" if P["screen"] == "connect" else P["screen"]
                # If cmd_choose is already set (mid-switch), stay "buffering" not "idle"
                if P["cmd_choose"] is None:
                    P["status"] = "idle"
                P["cmd_skip"] = False

            # Fetch tags from server web UI (only on first connect, skip during song switches)
            with lock:
                have_tags = bool(P["song_tags"])
            if not have_tags:
                try:
                    import urllib.request
                    with lock:
                        sip = P["server_ip"]
                    tag_url  = f"http://{sip}:9894/tags"
                    req      = urllib.request.urlopen(tag_url, timeout=2)
                    tag_data = json.loads(req.read())
                    with lock:
                        P["song_tags"] = tag_data
                except Exception:
                    pass

            with lock:
                P["paused"] = False

            # Wait for song choice
            while True:
                with lock:
                    if P["screen"] == "connect" and not P["connecting"]:
                        disconnected = True
                        break
                    if P["cmd_skip"]:
                        P["cmd_skip"] = False
                    choice = P["cmd_choose"]
                if choice is not None:
                    break
                time.sleep(0.1)

            if disconnected:
                break

            with lock:
                choice_copy     = P["cmd_choose"]
                P["cmd_choose"] = None
                P["cmd_skip"]   = False

            # Resolve choice
            if choice_copy == "__prev__":
                if song_history and history_pos > 0:
                    history_pos -= 1
                    choice_int  = song_history[history_pos] + 1
                elif song_history:
                    choice_int = song_history[0] + 1
                else:
                    choice_int = last_choice_int
                # Don't modify song_history for prev navigation
            elif choice_copy == "__shuffle__":
                choice_int = random.randint(1, len(song_list))
                song_history = song_history[:history_pos + 1]
                song_history.append(choice_int - 1)
                history_pos = len(song_history) - 1
            else:
                try:
                    ci = int(choice_copy)
                    if 1 <= ci <= len(song_list):
                        choice_int = ci
                    else:
                        with lock:
                            P["cmd_choose"] = None
                        continue
                except (ValueError, TypeError):
                    with lock:
                        P["cmd_choose"] = None
                    continue
                song_history = song_history[:history_pos + 1]
                song_history.append(choice_int - 1)
                history_pos = len(song_history) - 1

            last_choice_int = choice_int

            with lock:
                if P["queue"] and P["queue"][0] == choice_int - 1:
                    P["queue"].pop(0)

            try:
                client.sendall(f"{choice_int}\n".encode())
            except (BrokenPipeError, ConnectionResetError, OSError):
                add_log("Server gone.")
                disconnected = True
                break

            # Receive metadata
            try:
                size_hdr  = recv_exact(client, 4)
                if not size_hdr:
                    raise ConnectionResetError("no meta header")
                meta_size = struct.unpack("!I", size_hdr)[0]
                meta_raw  = recv_exact(client, meta_size)
                if not meta_raw:
                    raise ConnectionResetError("empty meta")
                parts     = meta_raw.decode().split("|")
                channels  = int(parts[0])
                rate      = int(parts[1])
                sampwidth = int(parts[2])
                duration  = float(parts[3])
                song_name = parts[4] if len(parts) > 4 else "Unknown"
            except Exception as e:
                add_log(f"Metadata error: {e}")
                disconnected = True
                break

            add_log(f"Streaming: {song_name}")

            with lock:
                P["song"]           = song_name
                P["song_started"]   = True
                P["status"]         = "buffering"
                P["screen"]         = "nowplaying"
                P["duration"]       = duration
                P["progress"]       = 0.0
                P["chunks"]         = 0
                P["recv_buf"]       = 0
                P["buffer_history"] = []
                P["underruns"]      = 0
                P["avg_latency"]    = 0.0
                P["throughput"]     = 0.0
                P["paused"]         = False
                P["cmd_skip"]       = False

            # Audio setup
            dtype_map = {1: np.uint8, 2: np.int16, 4: np.int32}
            dtype     = dtype_map.get(sampwidth, np.int16)

            with lock:
                demo = P["demo_mode"]
            BUFFER_MIN = 12 if demo else 3

            recv_buf     = collections.deque()
            recv_lock    = threading.Lock()
            recv_done    = threading.Event()
            stream_ended = False
            skip_done    = False
            total_chunks = 0
            total_bytes  = 0
            chunk_times  = []
            start_time   = time.time()

            def receiver():
                nonlocal total_chunks, total_bytes, stream_ended, skip_done
                while True:
                    with lock:
                        if P["cmd_skip"]:
                            skip_done = True
                            recv_done.set()
                            return
                    try:
                        data, kind = recv_packet(client)
                    except Exception:
                        stream_ended = True
                        recv_done.set()
                        return

                    if kind == "control":
                        if data == "SKIP":
                            skip_done = True
                        elif data == "DISCONNECTED":
                            with lock:
                                P["screen"]       = "connect"
                                P["status"]       = "idle"
                                P["song"]         = None
                                P["songs"]        = []
                                P["server_ip"]    = ""
                                P["connecting"]   = False
                                P["song_started"] = False
                        recv_done.set()
                        return

                    if kind == "end" or data is None:
                        stream_ended = True
                        recv_done.set()
                        return

                    t_recv = time.time()
                    with recv_lock:
                        recv_buf.append((data, t_recv))
                    total_chunks += 1
                    total_bytes  += len(data)
                    elapsed = time.time() - start_time
                    tp = (total_bytes / elapsed) / 1024 if elapsed > 0 else 0
                    with lock:
                        P["chunks"]     = total_chunks
                        P["recv_buf"]   = len(recv_buf)
                        P["throughput"] = round(tp, 1)
                        P["buffer_history"].append(len(recv_buf))
                        if len(P["buffer_history"]) > 30:
                            P["buffer_history"].pop(0)

            recv_thread = threading.Thread(target=receiver, daemon=True)
            recv_thread.start()

            audio = sd.RawOutputStream(samplerate=rate, channels=channels, dtype=dtype)
            audio.start()

            playing        = False
            underruns      = 0
            play_start     = None
            pause_wall     = None
            paused_elapsed = 0.0

            try:
                while True:
                    with lock:
                        paused   = P["paused"]
                        skip_now = P["cmd_skip"]

                    if skip_now:
                        break

                    if paused:
                        if pause_wall is None:
                            pause_wall = time.time()
                            if play_start:
                                paused_elapsed = min(duration, time.time() - play_start)
                            with lock:
                                P["status"]   = "paused"
                                P["progress"] = paused_elapsed
                        time.sleep(0.03)
                        continue
                    else:
                        if pause_wall is not None:
                            if play_start:
                                play_start += time.time() - pause_wall
                            pause_wall = None
                            with lock:
                                P["status"] = "playing" if playing else "buffering"

                    with recv_lock:
                        buf_len = len(recv_buf)
                    with lock:
                        P["recv_buf"] = buf_len

                    if not playing:
                        if buf_len >= BUFFER_MIN or recv_done.is_set():
                            playing    = True
                            play_start = time.time()
                            with lock:
                                P["status"] = "playing"
                        else:
                            time.sleep(0.005)
                            continue

                    with recv_lock:
                        item = recv_buf.popleft() if recv_buf else None

                    if item is None:
                        if recv_done.is_set():
                            break
                        underruns += 1
                        playing    = False
                        add_log(f"Buffer underrun #{underruns}")
                        with lock:
                            P["status"]    = "buffering"
                            P["underruns"] = underruns
                        time.sleep(0.005)
                        continue

                    chunk_data, t_recv = item
                    chunk_times.append(time.time() - t_recv)

                    with lock:
                        vol   = P["volume"]
                        muted = P["muted"]

                    if muted:
                        if dtype == np.uint8:
                            silence = b'\x80' * len(chunk_data)
                        else:
                            silence = b'\x00' * len(chunk_data)
                        audio.write(silence)
                    else:
                        if not _pycaw and vol != 1.0:
                            arr = np.frombuffer(chunk_data, dtype=dtype)
                            if dtype == np.uint8:
                                farr = (arr.astype(np.float32) - 128.0) * vol + 128.0
                                chunk_data = np.clip(farr, 0, 255).astype(np.uint8).tobytes()
                            else:
                                farr = arr.astype(np.float32) * vol
                                chunk_data = np.clip(
                                    farr, np.iinfo(dtype).min, np.iinfo(dtype).max
                                ).astype(dtype).tobytes()
                        audio.write(chunk_data)

                    if play_start:
                        elapsed_play = time.time() - play_start
                        lat = (sum(chunk_times[-50:]) / len(chunk_times[-50:])) * 1000
                        with lock:
                            P["progress"]    = min(duration, elapsed_play)
                            P["avg_latency"] = round(lat, 2)

            except Exception as e:
                add_log(f"Playback error: {e}")
                with lock:
                    P["screen"]    = "error"
                    P["error_msg"] = f"Playback error: {e}"
            finally:
                client.settimeout(0.5)
                recv_done.wait(timeout=2.0)
                recv_thread.join(timeout=2.0)
                # Drain stale data from socket buffer (prevents protocol desync after skip)
                client.setblocking(False)
                try:
                    while True:
                        _discard = client.recv(4096)
                        if not _discard:
                            break
                except (BlockingIOError, ssl.SSLWantReadError, OSError):
                    pass
                client.setblocking(True)
                client.settimeout(None)
                if recv_thread.is_alive():
                    add_log("Receiver thread stuck — reconnecting")
                    disconnected = True
                try:
                    audio.stop()
                    audio.close()
                except Exception:
                    pass

            elapsed = time.time() - start_time
            with lock:
                P["history"].append({
                    "song":       song_name,
                    "duration":   round(elapsed, 2),
                    "chunks":     total_chunks,
                    "throughput": round((total_bytes / elapsed) / 1024, 1) if elapsed > 0 else 0,
                })
                if len(P["history"]) > 50:
                    P["history"].pop(0)

            add_log(f"Done: {song_name} | {elapsed:.1f}s | {total_chunks} chunks")

            with lock:
                if P["screen"] == "connect":
                    disconnected = True
                    continue

            # Auto-advance (only if user hasn't already chosen)
            if stream_ended and not skip_done:
                with lock:
                    loop_on      = P["loop"]
                    queue_list   = list(P["queue"])
                    shuf_on      = P["shuffle"]
                    user_chose   = P["cmd_choose"] is not None

                if user_chose:
                    pass  # User already picked a song, don't override
                elif loop_on:
                    with lock:
                        if P["cmd_choose"] is None:
                            P["cmd_choose"] = last_choice_int
                            P["cmd_skip"]   = False
                            P["status"]     = "buffering"
                elif queue_list:
                    with lock:
                        if P["queue"]:
                            nxt = P["queue"].pop(0)
                        else:
                            nxt = None
                    if nxt is not None:
                        with lock:
                            if P["cmd_choose"] is None:
                                P["cmd_choose"] = nxt + 1
                                P["cmd_skip"]   = False
                                P["status"]     = "buffering"
                    else:
                        with lock:
                            P["status"]   = "ended"
                            P["progress"] = duration
                elif shuf_on:
                    with lock:
                        if P["cmd_choose"] is None:
                            P["cmd_choose"] = "__shuffle__"
                            P["cmd_skip"]   = False
                else:
                    with lock:
                        P["status"]   = "ended"
                        P["progress"] = duration

        # Connection lost
        try:
            client.close()
        except Exception:
            pass
        reset_state()
        add_log("Disconnected. Enter server IP to reconnect.")


# ── ENTRY POINT ───────────────────────────────────────────────────────────────
def run_flask():
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False, use_reloader=False)

print("=== WAVELINK ===")
print(f"Open http://localhost:{WEB_PORT}/player in your browser.")

flask_t = threading.Thread(target=run_flask, daemon=True)
flask_t.start()
time.sleep(0.5)
webbrowser.open(f"http://localhost:{WEB_PORT}/player")
run_client()
