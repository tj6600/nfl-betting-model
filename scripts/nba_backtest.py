"""Walk-forward backtest of the NBA game model against market lines.

For every game day in the test seasons, ratings are fit on games before that day only, then compared
with the listed line (ESPN pick center / play-by-play feed: DraftKings in 2025-26 on, consensus before).
Spread picks are graded at -110 (break-even 52.4%).

python scripts/nba_backtest.py            # writes nba_data/backtest_games.csv and prints the summary
"""
import sys, os, json; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
from nbamodel import data as D, games as M

G, P, S = D.load()
G = G[G.home.isin(M.TEAMS) & G.away.isin(M.TEAMS)].sort_values('date').reset_index(drop=True)
MS = M.team_missing(P); REST = M.rest_days(G)
TEST = [int(x) for x in os.environ.get('NBA_TEST', '2024,2025,2026').split(',')]
VARIANTS = {'v1 ratings': dict(use_missing=False), 'v2 + missing players': dict(use_missing=True)}


def run(kw, seasons=TEST):
    out = []
    for d in sorted(G[G.season.isin(seasons)].date.unique()):
        day = G[G.date == d]
        prior = G[(G.date < d) & (G.season == day.season.iloc[0])]
        if len(prior) < 60:   # skip the first ~2 weeks of each season
            continue
        r = M.Ratings(**kw).fit(G, MS, d, rest=REST)
        out.append(r.predict(day, MS))
    pr = pd.concat(out).merge(G[['game_id', 'season', 'stype', 'hs', 'as_', 'spread', 'total', 'provider']], on='game_id')
    return pr.rename(columns={'total_x': 'm_total', 'total_y': 'line_total'})


def grade(pr):
    pr = pr.copy()
    pr['res'] = pr.hs - pr.as_
    pr['edge'] = pr.margin + pr.spread                     # >0: model likes home against the spread
    pr['pick_home'] = pr.edge > 0
    cov = pr.res + pr.spread
    pr['ats_win'] = np.where(cov == 0, np.nan, ((cov > 0) == pr.pick_home).astype(float))
    pr['tedge'] = pr.m_total - pr.line_total
    tot = pr.hs + pr.as_ - pr.line_total
    pr['tot_win'] = np.where((tot == 0) | pr.line_total.isna(), np.nan, ((tot > 0) == (pr.tedge > 0)).astype(float))
    return pr


def summary(pr):
    rows = []
    for th in [0, 1, 2, 3, 4, 6]:
        a = pr[pr.edge.abs() >= th].ats_win.dropna(); t = pr[pr.tedge.abs() >= th].tot_win.dropna()
        rows.append(dict(edge=th, ats_n=len(a), ats=a.mean(), tot_n=len(t), tot=t.mean()))
    return pd.DataFrame(rows)


if __name__ == '__main__':
    res = {}
    for name, kw in VARIANTS.items():
        pr = grade(run(kw))
        mae_m = (pr.res - pr.margin).abs().mean(); mae_l = (pr.res + pr.spread).abs().mean()
        t = pr.dropna(subset=['line_total'])
        print(f'\n== {name}: {len(pr)} games | margin MAE model {mae_m:.2f} vs line {mae_l:.2f} | '
              f'total MAE model {(t.hs + t.as_ - t.m_total).abs().mean():.2f} vs line {(t.hs + t.as_ - t.line_total).abs().mean():.2f} (n={len(t)})')
        print(f'   residual SD margin {(pr.res - pr.margin).std():.2f}, total {(pr.hs + pr.as_ - pr.m_total).std():.2f}')
        print(summary(pr).round(3).to_string(index=False))
        print('   by season (all spread picks):', pr.groupby('season').ats_win.mean().round(3).to_dict())
        res[name] = dict(pr=pr)
    pr = res['v2 + missing players']['pr']
    pr.to_csv(os.path.join(D.DIR, 'backtest_games.csv'), index=False)
