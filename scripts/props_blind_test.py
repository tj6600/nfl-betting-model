"""Blind test of the touchdown and yards models on a finished week.

Everything is fit only on games before the week, and players are priced the way they would have been
that week (active roster, betting-line implied points). Then the predictions are compared with what
happened. No prop lines are used. Yards picks are graded against a stand-in line: the player's
season average before the week, rounded to .5, which is roughly where books start.

Usage: python scripts/props_blind_test.py 2026 9
"""
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
ROOT = os.path.join(os.path.dirname(__file__), '..')
import numpy as np, pandas as pd
from nflmodel.model import G
from nflmodel import touchdowns as T, yards as Y

season, week = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (2026, 9)
target = G[(G.season == season) & (G.week == week) & (G.game_type == 'REG')]
start = pd.to_datetime(target.gameday).min()
full = T.history()
actual = full[full.game_id.isin(target.game_id)][['pid', 'tds', 'rush_yds', 'rec_yds', 'carries', 'targets']]
cut = full[pd.to_datetime(full.gameday) < start].copy()
T.history = lambda seasons=None: cut          # every model function now sees only earlier games

lines = target[['game_id', 'home_team', 'away_team', 'spread_line', 'total_line']]
P = T.upcoming(season, week, T.implied_points(lines))
P = P.merge(Y.team_margin(lines), on='posteam', how='left', suffixes=('', '_m'))
base = T.training_frame()
b = T.fit(T.design(base), base.scored.values)
P['p_td'] = T.predict(b, T.design(P))
for kind in Y.STATS:
    c = Y.STATS[kind]
    bm, sp = Y.fit(kind, Y.frame(kind, base))
    d = Y.defense_yards(cut, c['y'])
    dn = d.sort_values('gameday').groupby(['defteam', 'position']).now.last().rename('def_yds').reset_index()
    Q = P.drop(columns=[x for x in ['def_yds'] if x in P]).merge(dn, on=['defteam', 'position'], how='left')
    mu = Y.apply(bm, Y.design(Q, kind))
    P[f'{kind}_proj'] = mu
    P[f'{kind}_median'] = sp.quantile(mu, .5)
    # stand-in line: season average before the week (players with a regular role at the usual positions)
    season_rows = cut[(cut.season == season)]
    avg = season_rows.groupby('pid')[c['y']].mean()
    P[f'{kind}_line'] = np.floor(P.pid.map(avg).fillna(np.nan)) + 0.5
    P[f'{kind}_pover'] = np.where(P[f'{kind}_line'].notna(), sp.p_over(mu, P[f'{kind}_line'].fillna(1)), np.nan)
    P[f'{kind}_eligible'] = P.position.isin(c['pos']) & (P[c['vol']] >= {'rush': 8, 'rec': 3}[kind])

R = P.merge(actual, on='pid', how='left', suffixes=('', '_act'))
R['played'] = R.tds_act.notna() if 'tds_act' in R else R['tds'].notna()
tds = R['tds_act'] if 'tds_act' in R else R['tds']
R['scored'] = (tds.fillna(0) > 0)
# sportsbooks void a prop when the player doesn't play, so those players are left out of the grading
# (here "played" means he had at least one carry or target)
R = R[R.played]
out = []
# --- touchdowns ---
td = R.copy()
td['pick'] = np.select([td.p_td >= 0.5, td.p_td >= 0.35], ['Likely (50%+)', 'Good chance (35-50%)'], '')
for name, m in [('Likely (50%+)', td.pick == 'Likely (50%+)'), ('Good chance (35-50%)', td.pick == 'Good chance (35-50%)')]:
    g = td[m]
    out.append(dict(test='Touchdowns', group=name, picks=len(g), right=int(g.scored.sum()), wrong=int((~g.scored).sum()),
                    expected=round(g.p_td.sum(), 1)))
# --- yards (stand-in line) ---
ylog = []
for kind, label in [('rush', 'Rushing yards'), ('rec', 'Receiving yards')]:
    c = Y.STATS[kind]
    y = R[R[f'{kind}_eligible'] & R[f'{kind}_line'].notna()].copy()
    yact = y[c['y'] + '_act'] if c['y'] + '_act' in y else y[c['y']]
    y['actual'] = yact.fillna(0)
    y['lean'] = np.where(y[f'{kind}_pover'] >= 0.5, 'Over', 'Under')
    y['p_lean'] = np.where(y.lean == 'Over', y[f'{kind}_pover'], 1 - y[f'{kind}_pover'])
    y['right'] = np.where(y.lean == 'Over', y.actual > y[f'{kind}_line'], y.actual < y[f'{kind}_line'])
    for name, m in [('All leans', y.p_lean >= 0.5), ('Confident leans (57%+)', y.p_lean >= 0.57)]:
        g = y[m]
        out.append(dict(test=label, group=name, picks=len(g), right=int(g.right.sum()), wrong=int((~g.right).sum()),
                        expected=round(g.p_lean.sum(), 1)))
    ylog.append(y.assign(market=label)[['market', 'full_name', 'posteam', 'position', f'{kind}_line', f'{kind}_proj', f'{kind}_median', 'lean', 'p_lean', 'actual', 'right']]
                .rename(columns={f'{kind}_line': 'line', f'{kind}_proj': 'projection', f'{kind}_median': 'median'}))
    print(f'{label}: projection MAE {np.abs(y[f"{kind}_proj"] - y.actual).mean():.1f} vs season average {np.abs(y[f"{kind}_line"] - y.actual).mean():.1f}')
S = pd.DataFrame(out); S['hit'] = (S.right / S.picks).round(3)
os.makedirs(os.path.join(ROOT, 'odds_log', 'blind'), exist_ok=True)
tag = f'{season}_wk{week:02d}'
S.to_csv(os.path.join(ROOT, 'odds_log', 'blind', f'{tag}_summary.csv'), index=False)
td[['full_name', 'posteam', 'position', 'game_id', 'p_td', 'pick', 'scored', 'played']].sort_values('p_td', ascending=False).to_csv(
    os.path.join(ROOT, 'odds_log', 'blind', f'{tag}_td.csv'), index=False)
pd.concat(ylog).to_csv(os.path.join(ROOT, 'odds_log', 'blind', f'{tag}_yards.csv'), index=False)
print(S.to_string(index=False))
print(td.sort_values('p_td', ascending=False).head(15)[['full_name', 'posteam', 'p_td', 'scored', 'played']].round(3).to_string(index=False))
