#!/usr/bin/env python3
"""voiced: tiny voice daemon for Termux. Plays audio POSTed from the Mac. Stdlib only."""
import base64, re, stat, http.server, ipaddress, json, os, queue, shutil, socket, subprocess, sys, threading, time, urllib.request, urllib.error

PORT = 8840
HOME = os.path.expanduser("~")
PREFIX = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
TMP = os.path.join(PREFIX, "tmp")
LOG = os.path.join(HOME, ".voiced.log")
TS = ipaddress.ip_network("100.64.0.0/10")
Q = queue.Queue()
CUR = {"p": None}
LOCK = threading.Lock()

def log(m):
    try:
        with open(LOG, "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + m + "\n")
    except Exception:
        pass

def player(path):
    if shutil.which("play-audio"):
        return ["play-audio", path]
    if shutil.which("termux-media-player"):
        return ["termux-media-player", "play", path]
    if shutil.which("mpv"):
        return ["mpv", "--no-video", "--really-quiet", path]
    return None

VOICES = {"en": "en-US-AvaNeural", "hr": "hr-HR-GabrijelaNeural"}
KEYFILE = os.path.join(HOME, ".voiced", "speechify.keys")
OLDKEY = os.path.join(HOME, ".voiced", "speechify.key")
RAW = "https://raw.githubusercontent.com/markoboskoauroville/TERMUX_VOICE/main/voiced.py"
SPEECHIFY = "https://api.sws.speechify.com/v1/audio/speech"
MODEL, VOICE_ID = "simba-3.2", "beatrice_32"   # same as langsay on the Mac
DEAD = set()
BIN = os.path.join(PREFIX, "bin")
CURL = os.path.join(BIN, "curl")
STATE = {"paused": False, "last": None, "cur": None}

def device_name():
    try:
        f = os.path.join(HOME, ".voiced", "device")
        if os.path.exists(f):
            return open(f).read().strip()
        g = lambda k: subprocess.run(["getprop", k], capture_output=True, text=True, timeout=5).stdout.strip()
        man, model = g("ro.product.manufacturer"), g("ro.product.model")
        if "nothing" in man.lower():
            return "Nothing Phone"
        return model or socket.gethostname()
    except Exception:
        return socket.gethostname()

DEVICE = device_name()
START_SH = '#!/data/data/com.termux/files/usr/bin/bash\n# start voiced natively unless a native one already answers on :8840\nh=$(curl -s -m 2 http://127.0.0.1:8840/health)\nif [ -n "$h" ]; then\n  if echo "$h" | grep -q \'"proot": true\' && [ "$HOME" != /root ]; then\n    curl -s -m 2 -XPOST http://127.0.0.1:8840/quit >/dev/null; sleep 1.5   # replace a PRoot-hosted daemon\n  else exit 0; fi\nfi\n# inside PRoot ($HOME=/root) a daemon would die with the PRoot: only a native Termux shell or Termux:Boot starts it\n[ "$HOME" = /root ] && exit 0\ncommand -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock 2>/dev/null || true\nnohup /data/data/com.termux/files/usr/bin/python3 ~/.voiced/voiced.py >/dev/null 2>&1 &\n'
BOOT_SH = '#!/data/data/com.termux/files/usr/bin/bash\ntermux-wake-lock\n~/.voiced/start.sh\n'

VSAY = '#!/data/data/com.termux/files/usr/bin/python3\n# vsay: the ONLY way a session on this phone speaks. It goes into voiced\'s queue: one voice at a time.\n# usage: vsay [-l hr|en] [-f "from"] text...        (stdin if no text)\nimport json, os, subprocess, sys, urllib.request\na = sys.argv[1:]; lang = "en"; frm = None\nwhile a and a[0] in ("-l", "-f") and len(a) > 1:\n    if a[0] == "-l": lang = a[1]\n    else: frm = a[1]\n    a = a[2:]\ntext = " ".join(a) or sys.stdin.read()\nif not text.strip():\n    sys.exit("vsay: nothing to say")\nbase = "http://127.0.0.1:8840"\nif frm is None:\n    try: frm = json.load(urllib.request.urlopen(base + "/health", timeout=3))["device"] + " \\u00b7 Claude"\n    except Exception: frm = "phone \\u00b7 Claude"\nreq = urllib.request.Request(base + "/say", json.dumps({"text": text, "lang": lang, "from": frm}).encode(), {"Content-Type": "application/json"})\ntry:\n    print(urllib.request.urlopen(req, timeout=5).read().decode())\nexcept Exception as e:\n    sys.exit("vsay: voiced does not answer (%s). Start it: ~/.voiced/start.sh" % e)\n'
CLAUDE_BLOCK = '\n# >>> voiced (TERMUX_VOICE)\nSpeaking aloud on this phone: ONLY with `vsay "text"` (Croatian: `vsay -l hr "text"`). It puts the line into the voice daemon\'s queue, so there is one voice at a time and the top notification says who speaks. Never call termux-tts-speak, mpv, termux-media-player or `talk` to speak: two voices at once is exactly what Marko complained about (15.11.2026).\n# <<< voiced\n'

def ensure_scripts():
    """start.sh and the Termux:Boot script are kept current by the daemon itself (so /update fixes them too)"""
    try:
        d = os.path.join(HOME, ".voiced")
        os.makedirs(d, exist_ok=True)
        os.makedirs(os.path.join(HOME, ".termux", "boot"), exist_ok=True)
        for path, body in ((os.path.join(d, "start.sh"), START_SH), (os.path.join(HOME, ".termux", "boot", "voiced"), BOOT_SH)):
            if not os.path.exists(path) or open(path).read() != body:
                open(path, "w").write(body)
            os.chmod(path, 0o755)
        for d2 in (BIN, os.path.join(HOME, ".local", "bin")):
            try:
                os.makedirs(d2, exist_ok=True)
                p = os.path.join(d2, "vsay")
                if not os.path.exists(p) or open(p).read() != VSAY:
                    open(p, "w").write(VSAY)
                os.chmod(p, 0o755)
            except Exception:
                pass
        cm = os.path.join(HOME, ".claude", "CLAUDE.md")
        if os.path.isdir(os.path.dirname(cm)):
            cur = open(cm).read() if os.path.exists(cm) else ""
            if "# >>> voiced (TERMUX_VOICE)" in cur:
                a, b = cur.index("# >>> voiced (TERMUX_VOICE)"), cur.index("# <<< voiced") + len("# <<< voiced\n")
                new = cur[:a].rstrip("\n") + "\n" + CLAUDE_BLOCK.lstrip("\n") + cur[b:]
            else:
                new = cur.rstrip("\n") + "\n" + CLAUDE_BLOCK
            if new != cur:
                open(cm, "w").write(new)
    except Exception as e:
        log("ensure_scripts: %s" % e)

def notify(nid, title, content, buttons=None, ongoing=True, priority="high"):
    exe = shutil.which("termux-notification")
    if not exe:
        return
    cmd = ["timeout", "-k", "3", "20", exe, "--id", nid, "--title", title, "--content", content, "--alert-once", "--priority", priority]
    if ongoing:
        cmd.append("--ongoing")
    for i, (label, path) in enumerate((buttons or [])[:3], 1):
        cmd += ["--button%d" % i, label, "--button%d-action" % i, "%s -s -XPOST http://127.0.0.1:%d/%s" % (CURL, PORT, path)]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25)
    except Exception as e:
        log("notify failed: %s" % e)

def unnotify(nid):
    exe = shutil.which("termux-notification-remove")
    if exe:
        try:
            subprocess.run(["timeout", "-k", "3", "15", exe, nid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        except Exception:
            pass

def load_keys():
    out = []
    for f in (KEYFILE, OLDKEY):
        try:
            for k in re.findall(r"\bsk_[A-Za-z0-9_-]{40,}", open(f).read()):
                if k not in out:
                    out.append(k)
        except OSError:
            pass
    return out

def render_speechify(text, out):
    keys = load_keys()
    for i, key in enumerate(keys):
        if key in DEAD:
            continue
        body = json.dumps({"input": text, "voice_id": VOICE_ID, "model": MODEL, "audio_format": "mp3"}).encode()
        req = urllib.request.Request(SPEECHIFY, body, {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                data = json.loads(r.read())
            open(out, "wb").write(base64.b64decode(data["audio_data"]))
            log("speechify key %d of %d" % (i + 1, len(keys)))
            return True
        except urllib.error.HTTPError as e:
            if e.code in (401, 402, 403, 429):
                DEAD.add(key)
                log("speechify key %d of %d refused (%d)" % (i + 1, len(keys), e.code))
                continue
            raise
    return False

def render_edge(text, lang, out):
    code = "import asyncio,edge_tts,sys\nasyncio.run(edge_tts.Communicate(sys.argv[1],sys.argv[2]).save(sys.argv[3]))"
    r = subprocess.run([sys.executable, "-c", code, text, VOICES.get(lang, VOICES["en"]), out],
                       capture_output=True, timeout=45)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode()[-200:])
    return True

def speak(text, lang):
    os.makedirs(TMP, exist_ok=True)
    out = os.path.join(TMP, "say_%d.mp3" % int(time.time() * 1000))
    engines = []
    if lang == "en":
        engines.append(("speechify", lambda: render_speechify(text, out)))
    engines.append(("edge-tts", lambda: render_edge(text, lang, out)))
    for name, fn in engines:
        try:
            if fn() and os.path.exists(out) and os.path.getsize(out) > 0:
                log("rendered by %s (%d bytes): %s" % (name, os.path.getsize(out), text[:60]))
                return out
        except Exception as e:
            log("%s failed: %s" % (name, e))
    if shutil.which("termux-tts-speak"):
        log("termux-tts-speak: " + text[:60])
        subprocess.run(["termux-tts-speak", "-l", "hr" if lang == "hr" else "en", text], timeout=120)
    else:
        log("no engine could speak: " + text[:60])
    return None

SPEEDS = [0.75, 0.9, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0]
SETTINGS = os.path.join(HOME, ".voiced", "settings.json")
SOCK = os.path.join(TMP, "voiced-mpv.sock")
STATE.update({"speed": 1.0, "action": None, "proc": None, "engine": None, "msg": None, "lastitem": None, "idle": True})
KICK = threading.Event()

def load_settings():
    try:
        v = float(json.load(open(SETTINGS)).get("speed", 1.0))
        if 0.5 <= v <= 3.0:
            STATE["speed"] = v
    except Exception:
        pass

def save_settings():
    try:
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        json.dump({"speed": STATE["speed"]}, open(SETTINGS, "w"))
    except Exception:
        pass

def mpv_ipc(*cmd):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(1.0)
    try:
        s.connect(SOCK)
        s.sendall((json.dumps({"command": list(cmd)}) + "\n").encode())
        return json.loads(s.recv(4096).decode().splitlines()[0])
    finally:
        s.close()

def proc_alive():
    p = STATE["proc"]
    return p if p and p.poll() is None else None

def set_speed(v):
    v = max(0.5, min(3.0, float(v)))
    STATE["speed"] = round(v, 2)
    save_settings()
    p = proc_alive()
    if p and STATE["engine"] == "mpv":
        try:
            mpv_ipc("set_property", "speed", STATE["speed"])
        except Exception as e:
            log("mpv speed ipc failed: %s" % e)
    log("speed %.2f" % STATE["speed"])
    KICK.set()

def step_speed(direction):
    cur = STATE["speed"]
    if direction > 0:
        nxt = next((x for x in SPEEDS if x > cur + 0.001), SPEEDS[-1])
    else:
        nxt = next((x for x in reversed(SPEEDS) if x < cur - 0.001), SPEEDS[0])
    set_speed(nxt)

def toggle_pause():
    import signal
    STATE["paused"] = not STATE["paused"]
    p = proc_alive()
    if p:
        try:
            if STATE["engine"] == "mpv":
                mpv_ipc("set_property", "pause", STATE["paused"])
            else:
                os.kill(p.pid, signal.SIGSTOP if STATE["paused"] else signal.SIGCONT)
        except Exception as e:
            log("pause failed: %s" % e)
    log("paused" if STATE["paused"] else "resumed")
    KICK.set()

def split_sentences(text):
    return [x for x in re.split(r"(?<=[.!?])\s+", text.strip()) if x] or [text]

def play_sentence(path):
    """play one clip; returns None when finished, or the action that cut it short"""
    import signal
    mpv = shutil.which("mpv") if not STATE.get("mpv_bad") else None
    if mpv:
        try:
            os.remove(SOCK)
        except OSError:
            pass
        cmd = [mpv, "--no-video", "--really-quiet", "--no-terminal", "--speed=%s" % STATE["speed"],
               "--input-ipc-server=" + SOCK] + (["--pause"] if STATE["paused"] else []) + [path]
        STATE["engine"] = "mpv"
    else:
        cmd = player(path)
        STATE["engine"] = "play-audio"
        if not cmd:
            log("no player found")
            return None
    t0 = time.time()
    errf = os.path.join(TMP, "voiced-player.err")
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=open(errf, "w"))
    STATE["proc"] = p
    if STATE["paused"] and STATE["engine"] != "mpv":
        os.kill(p.pid, signal.SIGSTOP)
    while p.poll() is None:
        act = STATE["action"]
        if act:
            try:
                os.kill(p.pid, signal.SIGCONT)
            except Exception:
                pass
            p.terminate()
            p.wait()
            return act
        time.sleep(0.05)
    try:
        err = open(errf).read().strip()[-200:]
    except Exception:
        err = ""
    log("played %s rc=%s %.1fs %s" % (STATE["engine"], p.returncode, time.time() - t0, err))
    if STATE["engine"] == "mpv" and p.returncode not in (0, 4) and time.time() - t0 < 1.5:
        STATE["mpv_bad"] = True
        log("mpv is broken, using play-audio (speed from the next render is not applied)")
        return play_sentence(path)
    return None

def run_message(item):
    frm = item.get("from", "unknown")
    if item["kind"] == "play":
        sents, files = ["(audio)"], [item["path"]]
        evs = [threading.Event()]
        evs[0].set()
        cancel = threading.Event()
    else:
        sents = split_sentences(item["text"])
        files = [None] * len(sents)
        evs = [threading.Event() for _ in sents]
        cancel = threading.Event()
        def render():
            for i, t in enumerate(sents):
                if cancel.is_set():
                    break
                try:
                    files[i] = speak(t, item["lang"])
                except Exception as e:
                    log("render error %s" % e)
                evs[i].set()
        threading.Thread(target=render, daemon=True).start()
        STATE["lastitem"] = item
    STATE["msg"] = {"from": frm, "sents": sents, "idx": 0}
    idx = 0
    while idx < len(sents):
        evs[idx].wait()
        STATE["msg"]["idx"] = idx
        KICK.set()
        act = play_sentence(files[idx]) if files[idx] else None
        if act:
            STATE["action"] = None
        if act == "restart":
            idx = 0
            continue
        if act in ("skip", "stop"):
            break
        idx += 1
    cancel.set()
    for f in files:
        if f and item["kind"] != "repeat":
            try:
                os.remove(f)
            except Exception:
                pass
    STATE["msg"] = None
    KICK.set()

def worker():
    while True:
        item = Q.get()
        STATE["idle"] = False
        try:
            run_message(item)
        except Exception as e:
            log("worker error %s" % e)
            STATE["msg"] = None
        STATE["idle"] = Q.empty()
        KICK.set()

def notifier():
    last_b = None
    shown = False
    while True:
        KICK.wait()
        KICK.clear()
        time.sleep(0.15)
        m = STATE["msg"]
        if m or STATE["paused"] and m:
            sents, i = m["sents"], m["idx"]
            content = sents[i] + (("\n\u25b8 " + sents[i + 1]) if i + 1 < len(sents) else "")
            threading.Thread(target=notify, args=("voiced", "\U0001f50a %s \u00b7 from %s" % (DEVICE, m["from"]), content[:400],
                [("\u25b6 resume" if STATE["paused"] else "\u23f8 pause", "pause"), ("\u23f9 stop", "stop"), ("\u21bb restart", "restart")]), daemon=True).start()
            b = "Speed %.2f\u00d7 \u00b7 queue %d%s \u00b7 sentence %d of %d" % (STATE["speed"], Q.qsize(), " \u00b7 paused" if STATE["paused"] else "", i + 1, len(sents))
            if b != last_b:
                last_b = b
                threading.Thread(target=notify, args=("voiced-ctl", "Voice controls", b,
                    [("\u2212 slower", "speeddown"), ("+ faster", "speedup"), ("\u23ed next", "next")], True, "low"), daemon=True).start()
            shown = True
        elif shown and Q.empty():
            shown = False
            last_b = None
            unnotify("voiced")
            unnotify("voiced-ctl")

def mpv_works():
    exe = shutil.which("mpv")
    if not exe:
        return False
    r = subprocess.run([exe, "--version"], capture_output=True, text=True)
    return r.returncode == 0

def ensure_mpv():
    if HOME == "/root" or not shutil.which("pkg"):
        return
    if not shutil.which("mpv"):
        log("installing mpv")
        r = subprocess.run(["pkg", "install", "-y", "mpv"], capture_output=True, text=True)
        log("pkg install mpv rc=%s" % r.returncode)
    if not mpv_works():
        log("mpv does not start (libraries out of step): pkg upgrade -y")
        r = subprocess.run(["pkg", "upgrade", "-y", "-o", "Dpkg::Options::=--force-confnew"], capture_output=True, text=True)
        log("pkg upgrade rc=%s, mpv works: %s" % (r.returncode, mpv_works()))
    STATE["mpv_bad"] = not mpv_works()

def allowed(ip):
    try:
        a = ipaddress.ip_address(ip)
        return a.is_loopback or a in TS
    except Exception:
        return False

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def guard(self):
        if not allowed(self.client_address[0]):
            log("403 " + self.client_address[0])
            self.send(403, {"ok": False, "error": "forbidden"})
            return False
        return True
    def do_GET(self):
        if not self.guard():
            return
        if self.path.startswith("/health"):
            m = STATE["msg"]
            self.send(200, {"ok": True, "device": DEVICE, "proot": HOME == "/root", "queued": Q.qsize(), "speaking": bool(m),
                            "paused": STATE["paused"], "speed": STATE["speed"], "engine": STATE["engine"], "mpv": bool(shutil.which("mpv")),
                            "sentence": (m["sents"][m["idx"]] if m else None), "index": (m["idx"] + 1 if m else 0), "of": (len(m["sents"]) if m else 0),
                            "from": (m["from"] if m else None)})
        elif self.path.startswith("/log"):
            try:
                lines = open(LOG).read().splitlines()[-30:]
            except Exception:
                lines = []
            self.send(200, {"ok": True, "log": lines})
        else:
            self.send(404, {"ok": False})
    def do_POST(self):
        if not self.guard():
            return
        if self.path.startswith("/play"):
            n = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(n) if n else b""
            if not data:
                return self.send(400, {"ok": False, "error": "empty"})
            ext = ".wav" if data[:4] == b"RIFF" else ".mp3"
            os.makedirs(TMP, exist_ok=True)
            path = os.path.join(TMP, "voiced_%d%s" % (int(time.time() * 1000), ext))
            with open(path, "wb") as f:
                f.write(data)
            Q.put({"kind": "play", "path": path, "from": self.headers.get("X-From", "unknown"), "text": "audio"})
            log("queued %s (%d bytes)" % (path, len(data)))
            self.send(200, {"ok": True, "queued": Q.qsize(), "bytes": len(data)})
        elif self.path.startswith("/say"):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            text, lang, frm = raw.decode("utf-8", "replace").strip(), "en", "unknown"
            if text.startswith("{"):
                try:
                    j = json.loads(text)
                    text, lang, frm = str(j.get("text", "")).strip(), j.get("lang", "en"), str(j.get("from") or "unknown")[:60]
                except Exception:
                    pass
            if not text:
                return self.send(400, {"ok": False, "error": "empty"})
            Q.put({"kind": "say", "text": text, "lang": "hr" if lang == "hr" else "en", "from": frm})
            log("say queued [%s] from %s: %s" % (lang, frm, text[:60]))
            self.send(200, {"ok": True, "queued": Q.qsize()})
        elif self.path.startswith("/keys"):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n).decode("utf-8", "replace") if n else ""
            ks = []
            for k in re.findall(r"\bsk_[A-Za-z0-9_-]{40,}", raw):
                if k not in ks:
                    ks.append(k)
            if not ks:
                return self.send(400, {"ok": False, "error": "no keys found"})
            os.makedirs(os.path.dirname(KEYFILE), exist_ok=True)
            with open(KEYFILE, "w") as f:
                f.write("\n".join(ks) + "\n")
            os.chmod(KEYFILE, stat.S_IRUSR | stat.S_IWUSR)
            DEAD.clear()
            log("keys stored: %d" % len(ks))
            self.send(200, {"ok": True, "keys": len(ks)})
        elif self.path.startswith("/update"):
            try:
                code = urllib.request.urlopen(RAW + "?t=%d" % time.time(), timeout=20).read()
                compile(code, "voiced.py", "exec")
                me = os.path.abspath(__file__)
                with open(me + ".new", "wb") as f:
                    f.write(code)
                os.replace(me + ".new", me)
            except Exception as e:
                log("update failed: %s" % e)
                return self.send(500, {"ok": False, "error": str(e)[:100]})
            log("updated (%d bytes), restarting" % len(code))
            self.send(200, {"ok": True, "bytes": len(code), "restarting": True})
            threading.Timer(0.7, lambda: os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)])).start()
        elif self.path.startswith("/quit"):
            self.send(200, {"ok": True})
            log("quit requested")
            threading.Timer(0.3, lambda: os._exit(0)).start()
        elif self.path.startswith("/now"):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                j = json.loads(self.rfile.read(n).decode("utf-8", "replace")) if n else {}
            except Exception:
                j = {}
            who, frm = str(j.get("device") or "another device")[:40], str(j.get("from") or "unknown")[:60]
            log("now: %s speaking (from %s)" % (who, frm))
            def small():
                notify("voiced-other", "%s speaking" % who, "from %s" % frm, False, False)
                time.sleep(10)
                unnotify("voiced-other")
            threading.Thread(target=small, daemon=True).start()
            self.send(200, {"ok": True})
        elif self.path.startswith("/pause"):
            if STATE["msg"] or STATE["paused"]:
                toggle_pause()
            self.send(200, {"ok": True, "paused": STATE["paused"]})
        elif self.path.startswith("/restart") or self.path.startswith("/repeat"):
            if STATE["msg"]:
                STATE["paused"] = False
                STATE["action"] = "restart"
            elif STATE["lastitem"]:
                Q.put(dict(STATE["lastitem"]))
            else:
                return self.send(404, {"ok": False, "error": "nothing to restart"})
            KICK.set()
            self.send(200, {"ok": True})
        elif self.path.startswith("/next"):
            STATE["paused"] = False
            if STATE["msg"]:
                STATE["action"] = "skip"
            self.send(200, {"ok": True})
        elif self.path.startswith("/speeddown") or self.path.startswith("/speedup"):
            step_speed(1 if self.path.startswith("/speedup") else -1)
            self.send(200, {"ok": True, "speed": STATE["speed"]})
        elif self.path.startswith("/speed"):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                j = json.loads(self.rfile.read(n).decode("utf-8", "replace")) if n else {}
            except Exception:
                j = {}
            if "value" in j:
                set_speed(j["value"])
            elif j.get("step") in ("+", "-"):
                step_speed(1 if j["step"] == "+" else -1)
            else:
                return self.send(400, {"ok": False, "error": "value or step"})
            self.send(200, {"ok": True, "speed": STATE["speed"]})
        elif self.path.startswith("/stop"):
            while not Q.empty():
                try:
                    it = Q.get_nowait()
                    if it.get("kind") == "play":
                        os.remove(it["path"])
                except Exception:
                    pass
            STATE["paused"] = False
            if STATE["msg"]:
                STATE["action"] = "stop"
            KICK.set()
            self.send(200, {"ok": True})
        else:
            self.send(404, {"ok": False})

class S(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

if __name__ == "__main__":
    ensure_scripts()
    load_settings()
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=notifier, daemon=True).start()
    threading.Thread(target=ensure_mpv, daemon=True).start()
    try:
        srv = S(("0.0.0.0", PORT), H)
    except OSError as e:
        log("cannot bind: %s" % e)
        sys.exit(1)
    log("voiced up on :%d" % PORT)
    srv.serve_forever()
