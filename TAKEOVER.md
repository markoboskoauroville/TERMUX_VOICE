# TERMUX_VOICE

A small voice daemon (voiced.py, Python stdlib) that runs inside Termux on an Android phone, so a Claude session on the Mac can make the phone speak. Written 15.11.2026 after Marko asked: "As soon as I start Termux, voice daemon should be there."

- voiced.py: HTTP on 0.0.0.0:8840, only Tailscale (100.64.0.0/10) and 127.0.0.1 clients (403 otherwise). GET /health, POST /play (mp3/wav bytes, queued), POST /stop. Player: play-audio, else termux-media-player, else mpv. Log ~/.voiced.log.
- install.sh: run in Termux: `curl -fsSL https://raw.githubusercontent.com/markoboskoauroville/TERMUX_VOICE/main/install.sh | bash`. Installs python and play-audio, copies to ~/.voiced/, adds an idempotent block to ~/.bashrc (starts the daemon when Termux opens), a Termux:Boot script if ~/.termux/boot exists.
- mac/phonesay: copy at ~/.local/bin/phonesay. `phonesay nothing|pixel|both "text"` renders with langsay and POSTs to the phone; falls back to adb push + VIEW intent if the daemon does not answer in 3 s. `phonesay status` shows /health of both.
- Phones: Nothing 100.67.149.40, Pixel 7 100.70.23.53 (Tailscale).
