#!/bin/zsh
# Weekly job: rebuild listings, commit and push to GitHub Pages, notify.
set -uo pipefail
cd "$(dirname "$0")"
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:$PATH"
LOG="$HOME/Library/Logs/cinemabrain.log"
exec >>"$LOG" 2>&1
echo "===== $(date '+%a %d %b %Y %H:%M') ====="
PAGES_URL=$(grep -E '^PAGES_URL=' .env 2>/dev/null | cut -d= -f2-)

notify() { osascript -e "display notification \"$2\" with title \"$1\" sound name \"Glass\"" >/dev/null 2>&1 || true; }

if ! .venv/bin/python -m cinemabrain.build; then
  notify "CinemaBrain: update failed" "See ~/Library/Logs/cinemabrain.log"
  exit 1
fi

git add docs/ overrides.json
if ! git diff --cached --quiet; then
  git commit -q -m "Listings update $(date +%Y-%m-%d)"
fi
if git remote get-url origin >/dev/null 2>&1; then
  if ! git push -q origin HEAD; then
    notify "CinemaBrain: publish failed" "Built OK but git push failed. See the log."
    exit 1
  fi
fi
notify "CinemaBrain updated" "$(cat cache/last_summary.txt) ${PAGES_URL}"
echo "Done."
