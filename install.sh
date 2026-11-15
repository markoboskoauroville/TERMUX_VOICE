#!/data/data/com.termux/files/usr/bin/bash
# TERMUX_VOICE installer: run inside Termux.
set -e
RAW=https://raw.githubusercontent.com/markoboskoauroville/TERMUX_VOICE/main
pkg install -y python play-audio termux-api >/dev/null 2>&1 || pkg install -y python play-audio termux-api
(pip install -q edge-tts >/dev/null 2>&1 || { pkg install -y python-aiohttp >/dev/null 2>&1; pip install -q edge-tts; }) || echo "edge-tts not installed (termux-tts-speak fallback only)"
mkdir -p ~/.voiced
[ "$HOME" = /root ] || { pkill -f '.voiced/voiced.py' 2>/dev/null || true; sleep 1; }
curl -fsSL "$RAW/voiced.py" -o ~/.voiced/voiced.py
cat > ~/.voiced/start.sh <<'S'
#!/data/data/com.termux/files/usr/bin/bash
# start voiced natively unless a native one already answers on :8840
h=$(curl -s -m 2 http://127.0.0.1:8840/health)
if [ -n "$h" ]; then
  if echo "$h" | grep -q '"proot": true' && [ "$HOME" != /root ]; then
    curl -s -m 2 -XPOST http://127.0.0.1:8840/quit >/dev/null; sleep 1.5   # replace a PRoot-hosted daemon
  else exit 0; fi
fi
# inside PRoot ($HOME=/root) a daemon would die with the PRoot: only a native Termux shell or Termux:Boot starts it
[ "$HOME" = /root ] && exit 0
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock 2>/dev/null || true
nohup /data/data/com.termux/files/usr/bin/python3 ~/.voiced/voiced.py >/dev/null 2>&1 &
S
chmod +x ~/.voiced/start.sh
touch ~/.bashrc
if ! grep -q '# >>> voiced' ~/.bashrc; then
cat >> ~/.bashrc <<'B'
# >>> voiced
~/.voiced/start.sh >/dev/null 2>&1
# <<< voiced
B
fi
mkdir -p ~/.termux/boot
printf '#!/data/data/com.termux/files/usr/bin/bash\ntermux-wake-lock\n~/.voiced/start.sh\n' > ~/.termux/boot/voiced
chmod +x ~/.termux/boot/voiced
~/.voiced/start.sh
sleep 1
echo "voiced ready on :8840"
