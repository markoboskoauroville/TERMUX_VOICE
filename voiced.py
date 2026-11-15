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
    except Exception as e:
        log("ensure_scripts: %s" % e)

def notify(nid, title, content, buttons=False, ongoing=True):
    exe = shutil.which("termux-notification")
    if not exe:
        return
    cmd = ["timeout", "-k", "3", "20", exe, "--id", nid, "--title", title, "--content", content, "--alert-once", "--priority", "high"]
    if ongoing:
        cmd.append("--ongoing")
    if buttons:
        post = lambda p: "%s -s -XPOST http://127.0.0.1:%d/%s" % (CURL, PORT, p)
        cmd += ["--button1", "\u23f8 pause", "--button1-action", post("pause"),
                "--button2", "\u21bb repeat", "--button2-action", post("repeat"),
                "--button3", "\u23f9 stop", "--button3-action", post("stop")]
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

def play_file(path, frm, text):
    cmd = player(path)
    if not cmd:
        log("no player found")
        return
    threading.Thread(target=notify, args=("voiced", "\U0001f50a %s speaking" % DEVICE,
                     ("from %s: %s" % (frm, text))[:300], True), daemon=True).start()
    with LOCK:
        CUR["p"] = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        STATE["paused"] = False
    p = CUR["p"]
    log("playing %s (from %s)" % (path, frm))
    p.wait()
    log("done %s rc=%s" % (path, p.returncode))

def worker():
    while True:
        item = Q.get()
        frm, text = item.get("from", "unknown"), item.get("text", "")
        try:
            path = item.get("path")
            if item["kind"] == "say":
                path = speak(item["text"], item["lang"])
            if path:
                keep = os.path.join(TMP, "voiced_last.mp3")
                try:
                    shutil.copyfile(path, keep)
                    STATE["last"] = {"path": keep, "from": frm, "text": text}
                except Exception:
                    pass
                play_file(path, frm, text)
                if item["kind"] != "repeat":
                    try:
                        os.remove(path)
                    except Exception:
                        pass
        except Exception as e:
            log("worker error %s" % e)
        if Q.empty():
            threading.Thread(target=unnotify, args=("voiced",), daemon=True).start()

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
            self.send(200, {"ok": True, "device": DEVICE, "proot": HOME == "/root", "queued": Q.qsize(), "player": (player("x") or [None])[0]})
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
                code = urllib.request.urlopen(RAW, timeout=20).read()
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
            with LOCK:
                p = CUR["p"]
                if p and p.poll() is None:
                    import signal
                    STATE["paused"] = not STATE["paused"]
                    os.kill(p.pid, signal.SIGSTOP if STATE["paused"] else signal.SIGCONT)
            self.send(200, {"ok": True, "paused": STATE["paused"]})
        elif self.path.startswith("/repeat"):
            last = STATE["last"]
            if not last:
                return self.send(404, {"ok": False, "error": "nothing to repeat"})
            Q.put({"kind": "repeat", "path": last["path"], "from": last["from"], "text": last["text"]})
            self.send(200, {"ok": True})
        elif self.path.startswith("/next"):
            with LOCK:
                p = CUR["p"]
                if p and p.poll() is None:
                    import signal
                    os.kill(p.pid, signal.SIGCONT)
                    p.terminate()
            self.send(200, {"ok": True})
        elif self.path.startswith("/stop"):
            while not Q.empty():
                try:
                    it = Q.get_nowait()
                    if it.get("kind") == "play":
                        os.remove(it["path"])
                except Exception:
                    pass
            with LOCK:
                p = CUR["p"]
                if p and p.poll() is None:
                    import signal
                    os.kill(p.pid, signal.SIGCONT)
                    p.terminate()
            self.send(200, {"ok": True})
        else:
            self.send(404, {"ok": False})

class S(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

if __name__ == "__main__":
    ensure_scripts()
    threading.Thread(target=worker, daemon=True).start()
    try:
        srv = S(("0.0.0.0", PORT), H)
    except OSError as e:
        log("cannot bind: %s" % e)
        sys.exit(1)
    log("voiced up on :%d" % PORT)
    srv.serve_forever()
