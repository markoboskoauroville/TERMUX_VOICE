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

def worker():
    while True:
        path = Q.get()
        if isinstance(path, tuple):
            try:
                path = speak(*path)
            except Exception as e:
                log("speak error %s" % e)
                path = None
            if not path:
                continue
        cmd = player(path)
        if not cmd:
            log("no player found")
        else:
            try:
                with LOCK:
                    CUR["p"] = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                p = CUR["p"]
                log("playing " + path)
                p.wait()
                log("done %s rc=%s" % (path, p.returncode))
            except Exception as e:
                log("play error %s" % e)
        try:
            os.remove(path)
        except Exception:
            pass

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
            self.send(200, {"ok": True, "device": socket.gethostname(), "queued": Q.qsize(), "player": (player("x") or [None])[0]})
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
            Q.put(path)
            log("queued %s (%d bytes)" % (path, len(data)))
            self.send(200, {"ok": True, "queued": Q.qsize(), "bytes": len(data)})
        elif self.path.startswith("/say"):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b""
            text, lang = raw.decode("utf-8", "replace").strip(), "en"
            if text.startswith("{"):
                try:
                    j = json.loads(text)
                    text, lang = str(j.get("text", "")).strip(), j.get("lang", "en")
                except Exception:
                    pass
            if not text:
                return self.send(400, {"ok": False, "error": "empty"})
            Q.put((text, "hr" if lang == "hr" else "en"))
            log("say queued [%s]: %s" % (lang, text[:60]))
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
        elif self.path.startswith("/stop"):
            while not Q.empty():
                try:
                    os.remove(Q.get_nowait())
                except Exception:
                    pass
            with LOCK:
                p = CUR["p"]
                if p and p.poll() is None:
                    p.terminate()
            self.send(200, {"ok": True})
        else:
            self.send(404, {"ok": False})

class S(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    try:
        srv = S(("0.0.0.0", PORT), H)
    except OSError as e:
        log("cannot bind: %s" % e)
        sys.exit(1)
    log("voiced up on :%d" % PORT)
    srv.serve_forever()
