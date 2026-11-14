#!/bin/zsh
# Download a Hugging Face model repo with plain curl (no Python needed).
# Usage: scripts/download_model.sh <repo_id> <dest_dir>
set -euo pipefail
REPO="$1"; DEST="$2"
mkdir -p "$DEST"
curl -sf "https://huggingface.co/api/models/$REPO/tree/main" \
  | grep -o '"path":"[^"]*"' | cut -d'"' -f4 \
  | xargs -P 4 -I{} sh -c 'curl -sfL --retry 3 -C - -o "$1/$2" "https://huggingface.co/$0/resolve/main/$2" && echo "done $2"' "$REPO" "$DEST" {}
echo "MODEL DOWNLOAD COMPLETE: $REPO"
