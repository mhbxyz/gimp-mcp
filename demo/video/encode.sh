#!/usr/bin/env bash
# raw.mkv (lossless-ish 1920x1080 capture) -> the files published with the README:
#   demo.mp4   1920x1080, real time, H.264 (plays everywhere)
#   demo.webp  1280x720, SPEEDx faster, animated WebP that autoplays in the README
#   poster.png last frame (the finished thumbnail next to the conversation)
set -euo pipefail
raw=${1:?raw.mkv} out=${2:?output dir}
SPEED=${SPEED:-2}
mkdir -p "$out"
ffmpeg -loglevel error -y -i "$raw" -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p \
  -movflags +faststart -an "$out/demo.mp4"
ffmpeg -loglevel error -y -i "$raw" \
  -vf "setpts=PTS/${SPEED},fps=12,scale=1280:-1:flags=lanczos" \
  -c:v libwebp_anim -lossless 0 -quality 85 -compression_level 6 -loop 0 -an "$out/demo.webp"
ffmpeg -loglevel error -y -sseof -0.5 -i "$raw" -frames:v 1 -update 1 "$out/poster.png"
ls -la "$out"
