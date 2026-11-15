#!/data/data/com.termux/files/usr/bin/bash
# TERMUX_VOICE installer: run inside Termux.
set -e
RAW=https://raw.githubusercontent.com/markoboskoauroville/TERMUX_VOICE/main
pkg install -y python play-audio >/dev/null 2>&1 || pkg install -y python play-audio
mkdir -p ~/.voiced
curl -fsSL "$RAW/voiced.py" -o ~/.voiced/voiced.py
cat > ~/.voiced/start.sh <<'S'
#!/data/data/com.termux/files/usr/bin/bash
# start voiced unless it already answers on :8840
if python3 - <<'P' 2>/dev/null
import socket,sys
s=socket.socket(); s.settimeout(0.5)
sys.exit(0 if s.connect_ex(("127.0.0.1",8840))==0 else 1)
P
then exit 0; fi
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock 2>/dev/null || true
nohup python3 ~/.voiced/voiced.py >/dev/null 2>&1 &
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
if [ -d ~/.termux/boot ]; then
  printf '#!/data/data/com.termux/files/usr/bin/bash\n~/.voiced/start.sh\n' > ~/.termux/boot/voiced
  chmod +x ~/.termux/boot/voiced
fi
~/.voiced/start.sh
sleep 1
echo "voiced ready on :8840"
