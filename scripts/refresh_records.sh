#!/usr/bin/env bash
# Refresh the Model records from the site's "Refresh results" button (Thomas, 2026-11-18).
# Run by .github/workflows/refresh-records.yml (on main), on a checkout of epa-model. Grades every finished game with
# free data only (hoopR / fastRhockey / nflverse mirrors, ESPN) and rebuilds the pages with --no-log, then pushes.
# It never spends Odds API credits: no odds module is run and no API key is given to the job.
#   scripts/refresh_records.sh [all|nba|nhl|nfl]
set -u
SPORT="${1:-all}"
unset ODDS_API_KEY THE_ODDS_API_KEY
FAILED=()
step() { echo "::group::$*"; "$@"; local rc=$?; echo "::endgroup::"; [ $rc -eq 0 ] || { echo "::warning::step failed: $*"; FAILED+=("$*"); }; return $rc; }
YDAY=$(TZ=America/New_York date -d yesterday +%F); TODAY=$(TZ=America/New_York date +%F)

grade() {
  if [ "$SPORT" = all ] || [ "$SPORT" = nba ]; then
    step python scripts/nba_board.py --update --no-log && step python scripts/nba_grade.py && step python scripts/nba_board.py --no-log
  fi
  if [ "$SPORT" = all ] || [ "$SPORT" = nhl ]; then
    step python -m nhlmodel.data; step python -m nhlmodel.espn history "$YDAY" "$TODAY"
    step python scripts/nhl_grade.py && step python scripts/nhl_board.py --no-log
  fi
  if [ "$SPORT" = all ] || [ "$SPORT" = nfl ]; then
    if [ ! -f /tmp/nfldata/data/games.csv ]; then GIT_LFS_SKIP_SMUDGE=1 git clone -q --depth 1 https://github.com/nflverse/nfldata /tmp/nfldata || true; fi
    if [ -f /tmp/nfldata/data/games.csv ]; then export NFL_GAMES_CSV=/tmp/nfldata/data/games.csv
    else export NFL_GAMES_CSV=https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv; fi
    step python scripts/td_board.py && step python scripts/td_grade.py
  fi
}

git config user.name "GoonerGamble refresh"; git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
for attempt in 1 2 3; do
  grade
  git add nba_data nhl_data odds_log board
  if git diff --cached --quiet; then echo "Nothing new to grade."; break; fi
  git commit -q -m "Refresh records: $TODAY ($SPORT)"
  for try in 1 2 3 4; do
    git push origin HEAD:epa-model && { echo "Pushed."; break 2; }
    git pull --rebase -q origin epa-model || break
    sleep $((try * 5))
  done
  # a scheduled run pushed the same files meanwhile: start over from its version and grade again
  git rebase --abort 2>/dev/null; git fetch -q origin epa-model; git reset -q --hard origin/epa-model; FAILED=()
  [ $attempt = 3 ] && { echo "::error::could not push after 3 attempts"; exit 1; }
done
[ ${#FAILED[@]} -eq 0 ] || { printf '::warning::%s\n' "Some steps failed (the rest were saved): ${FAILED[*]}"; }
exit 0
