#!/usr/bin/env bash
# Usage: tools/make_gif.sh <frames_dir> <out.gif> [fps]   -- PNG frames f000.png... -> palette-optimised GIF
set -euo pipefail
FRAMES="$1"; OUT="$2"; FPS="${3:-12}"
ffmpeg -y -loglevel error -framerate "$FPS" -i "$FRAMES/f%03d.png" \
  -vf "scale=640:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=160:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4" \
  -loop 0 "$OUT"
