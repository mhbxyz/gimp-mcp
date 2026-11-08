# README demo video

The animation at the top of the README is a real, unedited session: Claude Code
gets one prompt ([prompt.txt](prompt.txt)) and drives a real GIMP 3.2 through
the gimp-mcp package published on PyPI. Nothing is scripted on the GIMP side.

```sh
CLAUDE_CODE_OAUTH_TOKEN=... demo/video/record.sh 0.4.0   # token: `claude setup-token`
```

* [Dockerfile](Dockerfile): an Arch Linux snapshot with GIMP, Xvfb, Alacritty and ffmpeg.
* [scene.sh](scene.sh) (runs in the container): starts a virtual 1920×1080 desktop,
  installs the plug-in with `uvx gimp-mcp==VERSION install-plugin` in a fresh profile,
  opens GIMP on the right and Claude Code on the left (fresh HOME, only the gimp server
  through `--strict-mcp-config`, `dontAsk` permissions: no prompt can block the run,
  `Bash`, file-editing and web tools in `--disallowedTools`; Claude Code 2.1.319 still ran one
  read-only `ls` in the 0.4.0 take), types the
  prompt, and records until the export exists and the terminal has been still for 12 s.
  Every 1.5 s it also puts GIMP's window back in its half of the screen and sends
  the "Fit Image in Window" shortcut, so the canvas stays framed. That is the only
  input that doesn't come from the agent.
* [encode.sh](encode.sh): `demo.mp4` (1080p, real time), `demo.webp` (1280×720,
  2× speed, autoplays in the README) and `poster.png`.

The client binary is the host's `claude`, mounted read-only. The token is the
only credential passed in. Outputs land in `demo/video/out/` (ignored by git).

Publishing: `demo.webp` goes to `docs/assets/demo.webp`, and `demo.mp4` is
attached to the release as `gimp-mcp-demo.mp4` (the README links to both).
