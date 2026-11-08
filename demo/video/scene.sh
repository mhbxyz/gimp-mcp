#!/usr/bin/env bash
# Runs INSIDE the gimp-mcp-video container (see record.sh).
#   scene.sh desktop   start Xvfb, GIMP (GUI, fresh profile, plug-in from PyPI) and the terminal
#   scene.sh shot F    screenshot of the virtual desktop to F
#   scene.sh record    type the prompt, record until the export exists, stop
set -euo pipefail

: "${GIMP_MCP_VERSION:?}" "${DEMO_PROMPT:?}" "${DEMO_OUTPUT:?}"
WIDTH=1920 HEIGHT=1080 TERM_WIDTH=780
export DISPLAY=:99
OUT=/out

window() { # window CLASS -> id of its largest visible window
  local best="" area=0
  for id in $(xdotool search --onlyvisible --class "$1" 2>/dev/null); do
    eval "$(xdotool getwindowgeometry --shell "$id")"
    if ((WIDTH * HEIGHT > area)); then area=$((WIDTH * HEIGHT)) best=$id; fi
  done
  WIDTH=1920 HEIGHT=1080
  echo "$best"
}

wait_for() { # wait_for SECONDS CMD...
  local deadline=$((SECONDS + $1)); shift
  until "$@"; do ((SECONDS < deadline)) || { echo "timeout: $*" >&2; return 1; }; sleep 0.5; done
}

desktop() {
  mkdir -p "$XDG_RUNTIME_DIR" "$HOME/out" && chmod 700 "$XDG_RUNTIME_DIR"
  Xvfb :99 -screen 0 ${WIDTH}x${HEIGHT}x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
  wait_for 20 test -e /tmp/.X11-unix/X99

  # The published package, exactly as a user gets it.
  uvx --quiet "gimp-mcp==$GIMP_MCP_VERSION" install-plugin >/tmp/install.log 2>&1
  printf '(show-welcome-dialog no)\n(check-updates no)\n(theme-color-scheme dark)\n' \
    >>"$HOME/.config/GIMP/3.2/gimprc"
  gimp-3.2 --no-splash >/tmp/gimp.log 2>&1 &
  wait_for 120 test -S "$XDG_RUNTIME_DIR/gimp-mcp/bridge.sock"
  wait_for 60 bash -c '[ -n "$(xdotool search --onlyvisible --class gimp 2>/dev/null)" ]'
  sleep 3
  local gimp; gimp=$(window gimp)
  xdotool windowmove "$gimp" "$TERM_WIDTH" 0 windowsize "$gimp" $((WIDTH - TERM_WIDTH)) "$HEIGHT"

  # The AI client: Claude Code, with only the gimp server, in a fresh HOME.
  cat >"$HOME/mcp.json" <<EOF
{"mcpServers": {"gimp": {"command": "uvx", "args": ["gimp-mcp==$GIMP_MCP_VERSION", "serve"]}}}
EOF
  cat >"$HOME/.claude.json" <<EOF
{"hasCompletedOnboarding": true, "theme": "dark", "projects": {"$HOME": {"hasTrustDialogAccepted": true}}}
EOF
  cat >"$HOME/claude.sh" <<'EOF'
#!/usr/bin/env bash
cd "$HOME" # the assets and the output are inside the working directory: no permission prompt
exec claude --strict-mcp-config --mcp-config "$HOME/mcp.json" \
  --permission-mode dontAsk --allowedTools mcp__gimp Read Glob Grep --disallowedTools Bash Edit Write NotebookEdit WebFetch WebSearch
EOF
  chmod +x "$HOME/claude.sh"
  alacritty --config-file /scene/alacritty.toml -e "$HOME/claude.sh" >/tmp/alacritty.log 2>&1 &
  wait_for 30 bash -c '[ -n "$(xdotool search --onlyvisible --class Alacritty 2>/dev/null)" ]'
  sleep 1
  local term; term=$(window Alacritty)
  xdotool windowmove "$term" 0 0 windowsize "$term" "$TERM_WIDTH" "$HEIGHT"
  echo "desktop ready"
}

shot() { ffmpeg -loglevel error -y -f x11grab -video_size ${WIDTH}x${HEIGHT} -i :99 -frames:v 1 "$1"; }

record() {
  local term; term=$(window Alacritty)
  rm -f "$OUT/raw.mkv"
  ffmpeg -loglevel error -y -f x11grab -framerate 30 -video_size ${WIDTH}x${HEIGHT} -draw_mouse 0 -i :99 \
    -c:v libx264 -preset ultrafast -crf 12 -pix_fmt yuv444p "$OUT/raw.mkv" </dev/null &
  local ffmpeg_pid=$!
  xdotool mousemove 4 $((HEIGHT - 4)) # no pointer, no tooltip over GIMP
  sleep 2
  xdotool windowfocus --sync "$term"
  xdotool type --delay 28 --window "$term" "$DEMO_PROMPT"
  sleep 0.8
  xdotool key --window "$term" Return
  # Keep GIMP framed: it grows its window to the image when a display opens, and the
  # image changes size; so put the window back and fit the image (View > Zoom > Fit
  # Image in Window) regularly.
  (
    sleep 3
    local gimp; gimp=$(window gimp)
    while true; do
      xdotool windowmove "$gimp" "$TERM_WIDTH" 0 windowsize "$gimp" $((WIDTH - TERM_WIDTH)) "$HEIGHT"
      xdotool windowfocus --sync "$gimp" key --clearmodifiers shift+ctrl+j
      sleep 1.5
    done
  ) &
  local fit_pid=$!
  # Finished = the export exists and the client printed its final answer (screen stops changing).
  wait_for 900 test -s "$HOME/out/$DEMO_OUTPUT"
  local last="" same=0
  while ((same < 12)); do
    sleep 1
    local now; now=$(ffmpeg -loglevel error -f x11grab -video_size ${TERM_WIDTH}x${HEIGHT} -i :99 -frames:v 1 -f rawvideo - | md5sum)
    if [ "$now" = "$last" ]; then same=$((same + 1)); else same=0 last=$now; fi
  done
  sleep 2
  kill "$fit_pid" 2>/dev/null || true
  kill -INT "$ffmpeg_pid"; wait "$ffmpeg_pid" || true
  cp "$HOME/out/$DEMO_OUTPUT" "$OUT/$DEMO_OUTPUT"
  echo "recorded $OUT/raw.mkv"
}

"$@"
