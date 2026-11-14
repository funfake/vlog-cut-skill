#!/bin/zsh
# Set up vlog-cut on a Mac (Apple Silicon): tools, Python packages, local models, both Claude skills, checks.
# Usage: git clone <repo> ~/Dev/movie-making && ~/Dev/movie-making/setup.sh
set -e
[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] || { echo "vlog-cut needs macOS on Apple Silicon (Final Cut Pro + MLX)"; exit 1; }
cd "$(dirname "$0")"
ROOT="$PWD"
need() {  # install a Homebrew formula if its command is missing
  command -v "$1" >/dev/null && return
  brew install "$1" || { echo "brew install $1 failed. If it mentions the Xcode license, run: sudo xcodebuild -license accept"; exit 1; }
}

echo "1/5 tools (Homebrew: ffmpeg, uv)"
command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh"; exit 1; }
need ffmpeg
need uv

echo "2/5 Python packages"
uv sync

echo "3/5 local models (~7 GB, skipped if present)"
[ -f models/Qwen3-VL-8B-Instruct-4bit/config.json ] || ./scripts/download_model.sh mlx-community/Qwen3-VL-8B-Instruct-4bit models/Qwen3-VL-8B-Instruct-4bit
[ -f models/whisper-large-v3-turbo/config.json ] || ./scripts/download_model.sh mlx-community/whisper-large-v3-turbo models/whisper-large-v3-turbo

echo "4/5 Claude skills (/vlog-cut, /vlog-cut-setup, /vlog-cut-switch-aspect)"
mkdir -p ~/.claude/skills
for sk in $(ls skill); do
  if [ -e ~/.claude/skills/$sk ] && [ ! -L ~/.claude/skills/$sk ]; then
    echo "   ~/.claude/skills/$sk exists and is not a link - leaving it alone (remove it to use the repo version)"
  else
    ln -sfn "$ROOT/skill/$sk" ~/.claude/skills/$sk && echo "   linked ~/.claude/skills/$sk"
  fi
done

echo "5/5 checks"
[ -d "/Applications/Final Cut Pro.app" ] && echo "   Final Cut Pro: ok" || echo "   Final Cut Pro not found (needed to import, and for its FCPXML DTD and sound effects)"
[ -d "/Library/Audio/Apple Loops/Apple/Final Cut Pro Sound Effects" ] && echo "   Final Cut sound effects: ok" \
  || echo "   Final Cut sound effects missing: Final Cut Pro > Download Additional Content"
[ -f ~/Library/Fonts/penoftruth.ttf ] && echo "   handwriting font penoftruth: ok" \
  || echo "   handwriting font penoftruth missing: copy penoftruth.ttf into ~/Library/Fonts (or pick another font in the editor)"
[ -f projects/example.json ] && echo "   start a movie: cp projects/example.json projects/<movie>.json, then use /vlog-cut"
echo "done"
