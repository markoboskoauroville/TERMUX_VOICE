# TERMUX_VOICE

A small voice daemon (voiced.py, Python stdlib) that runs inside Termux on an Android phone, so a Claude session on the Mac can make the phone speak. Written 15.11.2026 after Marko asked: "As soon as I start Termux, voice daemon should be there."

- voiced.py: HTTP on 0.0.0.0:8840, only Tailscale (100.64.0.0/10) and 127.0.0.1 clients (403 otherwise). GET /health, POST /say (JSON {"text","lang":"en|hr"} or plain text; the phone renders the speech itself: optional ~/.voiced/speechify.key for English, else edge-tts en-US-AvaNeural / hr-HR-GabrijelaNeural, else termux-tts-speak), POST /play (audio bytes, compatibility), POST /stop, GET /log (last 30 lines, Tailscale only). Player: play-audio, else termux-media-player, else mpv. Log ~/.voiced.log.
- install.sh: run in Termux: `curl -fsSL https://raw.githubusercontent.com/markoboskoauroville/TERMUX_VOICE/main/install.sh | bash`. Installs python and play-audio, copies to ~/.voiced/, adds an idempotent block to ~/.bashrc (starts the daemon when Termux opens), a Termux:Boot script if ~/.termux/boot exists.
- mac/phonesay: copy at ~/.local/bin/phonesay. `phonesay nothing|pixel|both "text"` sends TEXT only to /say (`phonesay pixel hr "..."` for Croatian); only if the daemon does not answer in 3 s does it render an mp3 with langsay and fall back to adb push + VIEW intent. `phonesay log <phone>` shows the daemon log. `phonesay status` shows /health of both.
- Phones: Nothing 100.67.149.40, Pixel 7 100.70.23.53 (Tailscale).

- Re-run install.sh any time to update in place (it restarts the daemon).

- Speechify on the phone (15.11.2026): keys in ~/.voiced/speechify.keys (chmod 600, one per line, rotated on 401/402/403/429, same voice/model as langsay: beatrice_32, simba-3.2), Edge TTS when none works. `phonesay keys nothing|pixel|both` sends the keys by shape from the Mac's key file through stdin to POST /keys (the daemon answers only the count); `phonesay update ...` calls POST /update, which pulls the latest voiced.py from this repo and restarts the daemon, so no more typing in Termux. A daemon older than this version has no /update: run install.sh once.

- 15.11.2026 boot + who speaks + one voice: see MANTRA_MANIFEST modules/termux-voice.md. voiced.py now has: `from` on /say, ongoing notification with pause/repeat/stop (termux-notification), POST /now, /pause, /repeat, /next, /quit, /health (device, proot, queued, speaking, paused), one worker thread = strictly serial playback, vsay wrapper and boot/start scripts written by the daemon itself (ensure_scripts), CLAUDE.md block on phones. Termux:Boot installed on both phones (Pixel GitHub build, Nothing F-Droid build), wake lock via the boot script. `phonesay --from "Mac · session"`, `phonesay both` also sends /now to the other phone.
