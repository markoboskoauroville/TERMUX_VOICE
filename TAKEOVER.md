# TERMUX_VOICE

A small voice daemon (voiced.py, Python stdlib) that runs inside Termux on an Android phone, so a Claude session on the Mac can make the phone speak. Written 15.11.2026 after Marko asked: "As soon as I start Termux, voice daemon should be there."

- voiced.py: HTTP on 0.0.0.0:8840, only Tailscale (100.64.0.0/10) and 127.0.0.1 clients (403 otherwise). GET /health, POST /say (JSON {"text","lang":"en|hr"} or plain text; the phone renders the speech itself: optional ~/.voiced/speechify.key for English, else edge-tts en-US-AvaNeural / hr-HR-GabrijelaNeural, else termux-tts-speak), POST /play (audio bytes, compatibility), POST /stop, GET /log (last 30 lines, Tailscale only). Player: play-audio, else termux-media-player, else mpv. Log ~/.voiced.log.
- install.sh: run in Termux: `curl -fsSL https://raw.githubusercontent.com/markoboskoauroville/TERMUX_VOICE/main/install.sh | bash`. Installs python and play-audio, copies to ~/.voiced/, adds an idempotent block to ~/.bashrc (starts the daemon when Termux opens), a Termux:Boot script if ~/.termux/boot exists.
- mac/phonesay: copy at ~/.local/bin/phonesay. `phonesay nothing|pixel|both "text"` sends TEXT only to /say (`phonesay pixel hr "..."` for Croatian); only if the daemon does not answer in 3 s does it render an mp3 with langsay and fall back to adb push + VIEW intent. `phonesay log <phone>` shows the daemon log. `phonesay status` shows /health of both.
- Phones: Nothing 100.67.149.40, Pixel 7 100.70.23.53 (Tailscale).

- Re-run install.sh any time to update in place (it restarts the daemon).
