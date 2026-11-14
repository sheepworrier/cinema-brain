#!/bin/zsh
# Daily job: refresh IMDb ratings only (no Chrome), commit and push if anything changed.
set -uo pipefail
cd "$(dirname "$0")"
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:$PATH"
LOG="$HOME/Library/Logs/cinemabrain.log"
exec >>"$LOG" 2>&1
echo "===== ratings $(date '+%a %d %b %Y %H:%M') ====="
.venv/bin/python -m cinemabrain.refresh_ratings || { echo "Ratings refresh failed"; exit 1; }
git add docs/data.json
if ! git diff --cached --quiet; then
  git commit -q -m "Refresh IMDb ratings $(date +%Y-%m-%d)"
  git remote get-url origin >/dev/null 2>&1 && git push -q origin HEAD || echo "git push failed"
fi
echo "Done."
