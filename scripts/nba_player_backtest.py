"""Walk-forward backtest of the player-based game model (nbamodel/players.py) against DraftKings/consensus lines.

Refits every REFIT days on games before that day. Compares with the team-ratings model on the same games.
python scripts/nba_player_backtest.py      # writes nba_data/backtest_players.csv
"""
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
from nbamodel import data as D, games as M, players as PM

G, P, S = D.load()
G = G[G.home.isin(M.TEAMS) & G.away.isin(M.TEAMS)].sort_values('date').reset_index(drop=True)
REST = M.rest_days(G); F = PM.form(P); MS = M.team_missing(P)
TEST = [int(x) for x in os.environ.get('NBA_TEST', '2024,2025,2026,2027').split(',')]
REFIT = int(os.environ.get('REFIT', 7))
kw = dict(hl=float(os.environ.get('HL', PM.HL_DAYS)), lam=float(os.environ.get('LAM', PM.LAM)))

out = []; pm = tm = None; last = None
days = sorted(G[G.season.isin(TEST) & G.hs.notna()].date.unique())
for d in days:
    day = G[G.date == d]
    if (G[(G.date < d) & (G.season == day.season.iloc[0])]).shape[0] < 60: continue
    if last is None or (pd.Timestamp(d) - pd.Timestamp(last)).days >= REFIT or day.season.iloc[0] != G[G.date == last].season.iloc[0]:
        pm = PM.PlayerModel(**kw).fit(G, F, d, REST); last = d
    tm = M.Ratings().fit(G, MS, d, rest=REST)
    a = pm.predict(day, PM.backtest_lineups(F, day, 'actual')).rename(columns={'pm_margin': 'pm_act'})
    b = pm.predict(day, PM.backtest_lineups(F, day, 'prev'))[['game_id', 'pm_margin']].rename(columns={'pm_margin': 'pm_prev'})
    t = tm.predict(day, MS)[['game_id', 'margin']].rename(columns={'margin': 'team'})
    out.append(a.merge(b, on='game_id').merge(t, on='game_id'))
R = pd.concat(out).merge(G[['game_id', 'season', 'hs', 'as_', 'spread']], on='game_id').dropna(subset=['spread'])
R['res'] = R.hs - R.as_
R.to_csv(os.environ.get('OUT', os.path.join(D.DIR, 'backtest_players.csv')), index=False)


def ats(m, sub=None, th=0):
    r = R if sub is None else R[sub]
    e = r[m] + r.spread; cov = r.res + r.spread
    k = (cov != 0) & (e.abs() >= th)
    w = ((cov > 0) == (e > 0))[k]
    return f"{w.mean():.1%} ({w.sum()}-{(~w).sum()})"


print(f"{len(R)} games, line MAE {(R.res + R.spread).abs().mean():.2f}")
for m in ['team', 'pm_prev', 'pm_act']:
    print(f"{m:8s} MAE {(R.res - R[m]).abs().mean():.2f} | ATS all {ats(m)} | edge>=3 {ats(m, th=3)} | by season",
          {s: ats(m, R.season == s) for s in sorted(R.season.unique())})
for wt in [0.25, 0.5]:
    R['bl'] = wt * R.pm_act + (1 - wt) * (-R.spread)
    print(f"blend {wt} pm_act w/ line: MAE {(R.res - R.bl).abs().mean():.2f}")
