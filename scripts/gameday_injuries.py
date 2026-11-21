"""Game-day injury check: pull ESPN's injury report and re-price only the games it changes.

Runs Sunday morning (before the 1 PM kickoffs) without spending Odds API credits: it uses the odds already saved by
Saturday's refresh. Steps:
1. Refresh odds_log/injury_overrides.csv with scripts/nfl_injuries.py.
2. Compare this week's skill-player rows (QB, RB, WR, TE) before and after: a player newly Out/Doubtful/IR, one whose
   status changed, or one no longer listed. Their teams' games are the affected games.
3. If no game is affected, or every affected game has kicked off, stop: the picks files and board are left alone.
4. Otherwise re-run td_picks.py and yards_picks.py, then keep their new rows only for affected games; every other
   game's rows (and their per-book prices) are put back exactly as they were. Then rebuild the board (td_board.py).

python scripts/gameday_injuries.py            # prints a summary for the run's final message
python scripts/gameday_injuries.py --dry-run  # only report what changed
"""
import sys, os, subprocess, argparse; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pandas as pd

ROOT = os.path.join(os.path.dirname(__file__), '..')
OV = os.path.join(ROOT, 'odds_log', 'injury_overrides.csv')
PICKS = os.path.join(ROOT, 'odds_log', 'picks')
SKILL = r'\((?:QB|RB|WR|TE|FB)\)'
# picks files with a 'game' column, and the per-book price files that hang off them by pid
GAME_FILES = ['td', 'td_picks', 'td_page', 'yards', 'milestones']
BOOK_FILES = {'yards_books': 'yards', 'milestones_books': 'milestones'}


def week_rows(df, season, week):
    if df is None or df.empty:
        return set()
    d = df[(df.season == season) & (df.week == week)]
    d = d[d.note.fillna('').str.contains(SKILL) | ~d.note.fillna('').str.startswith('ESPN')]   # hand-entered rows count too
    return set(zip(d.team, d.player, d.status))


def run(script):
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', script)], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f'{script} failed:\n{r.stdout[-2000:]}\n{r.stderr[-3000:]}')
    return r.stdout


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--dry-run', action='store_true'); args = ap.parse_args()
    from nflmodel.model import G
    from nflmodel import record as REC
    # same current week as nfl_injuries.py: the first regular-season week with games not yet final
    today = pd.Timestamp.now(tz='UTC').tz_localize(None).normalize()
    up = G[(G.game_type == 'REG') & G.result.isna() & (pd.to_datetime(G.gameday) >= today - pd.Timedelta(days=1))]
    season = int(up.season.min()); week = int(up[up.season == season].week.min())
    raw = open(OV).read() if os.path.exists(OV) else None
    before = pd.read_csv(OV) if raw is not None else None
    log = run('nfl_injuries.py').strip(); print(log)
    q = log.split('Questionable skill players', 1)[-1] if 'Questionable skill players' in log else ''
    after = pd.read_csv(OV)
    if args.dry_run and raw is not None:
        open(OV, 'w').write(raw)          # dry run: leave the overrides file as it was

    b, a = week_rows(before, season, week), week_rows(after, season, week)
    changes = []
    for team, player, status in sorted(a - b):
        old = next((s for t, p, s in b if t == team and p == player), None)
        changes.append((team, player, f'{old} -> {status}' if old else f'newly {status}'))
    for team, player, status in sorted(b - a):
        if not any(t == team and p == player for t, p, _ in a):
            now = 'now Questionable' if f'{player} ({team}' in q else 'no longer listed'
            changes.append((team, player, f'{now} (was {status})'))
    teams = {c[0] for c in changes}

    wk = G[(G.season == season) & (G.week == week)]
    gone = REC.started(season, week)
    games = {f'{r.away_team} @ {r.home_team}' for r in wk.itertuples() if r.home_team in teams or r.away_team in teams}
    started = {g for g in games if g in gone}
    games -= started
    print(f'\nGame-day injury changes ({season} week {week}): {len(changes)}')
    for c in changes:
        print(f'  {c[1]} ({c[0]}): {c[2]}')
    if started:
        print('Already kicked off, left as is:', ', '.join(sorted(started)))
    if not games:
        print('No upcoming game affected: picks and board left unchanged.')
        return
    print('Re-pricing only:', ', '.join(sorted(games)))
    if args.dry_run:
        return

    old = {}
    for k in GAME_FILES + list(BOOK_FILES):
        p = os.path.join(PICKS, f'{season}_wk{week:02d}_{k}.csv')
        old[k] = pd.read_csv(p) if os.path.exists(p) else None
    run('td_picks.py'); run('yards_picks.py')
    new_pids = {}
    for k in GAME_FILES:
        p = os.path.join(PICKS, f'{season}_wk{week:02d}_{k}.csv')
        if not os.path.exists(p):
            continue
        n = pd.read_csv(p); o = old[k]
        keep_new = n[n.game.isin(games)]
        merged = keep_new if o is None else pd.concat([o[~o.game.isin(games)], keep_new], ignore_index=True)
        merged.to_csv(p, index=False)
        new_pids[k] = (set(keep_new.pid) if 'pid' in n else set(), set(o[~o.game.isin(games)].pid) if o is not None and 'pid' in o else set())
        print(f'  {k}: {len(keep_new)} rows re-priced, {len(merged) - len(keep_new)} kept as they were')
    for k, parent in BOOK_FILES.items():
        p = os.path.join(PICKS, f'{season}_wk{week:02d}_{k}.csv')
        if not os.path.exists(p) or parent not in new_pids:
            continue
        n = pd.read_csv(p); o = old[k]; np_, op_ = new_pids[parent]
        merged = n[n.pid.isin(np_)] if o is None else pd.concat([o[o.pid.isin(op_) & ~o.pid.isin(np_)], n[n.pid.isin(np_)]], ignore_index=True)
        merged.to_csv(p, index=False)
    run('td_board.py')
    print('Board rebuilt (board/site/index.html).')


if __name__ == '__main__':
    main()
