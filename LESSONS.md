# Lessons

- 15.11.2026: Termux only runs the daemon while Termux is alive; the .bashrc block starts it on every Termux open, Termux:Boot covers reboot.
- 15.11.2026: Marko: send text, not audio; the phone's own daemon talks. adb input text drops the first characters after a space on his keyboard: push a script and type only `bash v.sh` from the cwd, in a NEW Termux session (ctrl+alt+C via `input keycombination 113 57 31`), never the Claude session; never press Back (it leaves Termux).
- 15.11.2026: on the Nothing (Marko using the Claude app) the adb new-Termux-tab method failed: the keys went to the launcher search, not Termux; do not retry it there, give Marko the install line to paste. Pixel works.
