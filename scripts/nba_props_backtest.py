"""Props check without historical prop lines (they cost ~10x on The Odds API).

1. Accuracy: projection MAE vs his season-to-date average and last-10 average (2024-25 and 2025-26).
2. Calibration: over chances fit on 2022-23 to 2024-25, tested on 2025-26 against a stand-in line
   (season-to-date average rounded to the half point). Real book lines are sharper than this stand-in,
   so the lean hit rate here overstates what to expect against DraftKings.
Writes nba_data/backtest_props.json for the board.
"""
import sys, os, json; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
from nbamodel import data as D, props as PR, games as M

G, P, S = D.load()
G = G[G.home.isin(M.TEAMS) & G.away.isin(M.TEAMS)]; P = P[P.team.isin(M.TEAMS)]
f = PR.features(P, G)
e = f[PR.eligible(f) & f.played].sort_values('date')
out = {'mae': [], 'cal': []}
for k in PR.STATS:
    naive = e.groupby(['pid', 'season'])[k].transform(lambda x: x.shift(1).expanding().mean())
    l10 = e.groupby('pid')[k].transform(lambda x: x.shift(1).rolling(10, min_periods=3).mean())
    ok = naive.notna() & l10.notna() & (e.season >= 2025)
    out['mae'].append(dict(stat=PR.LABEL[k], n=int(ok.sum()), model=round(float((e[k] - e[f'{k}_proj'])[ok].abs().mean()), 2),
                           season_avg=round(float((e[k] - naive)[ok].abs().mean()), 2), last10=round(float((e[k] - l10)[ok].abs().mean()), 2)))
sp = PR.Spread().fit(f[f.season.between(2023, 2025)])
te = e[e.season == 2026]
for k in PR.STATS:
    avg = te.groupby('pid')[k].transform(lambda x: x.shift(1).expanding(min_periods=5).mean())
    line = np.floor(avg) + 0.5; ok = line.notna()
    po = 0.5 + 0.85 * (sp.p_over(k, te[f'{k}_proj'][ok], line[ok]) - 0.5)
    hit = (te[k][ok] > line[ok]).values
    lean = np.abs(po - 0.5) >= 0.07
    side_hit = ((po > 0.5) == hit)
    out['cal'].append(dict(stat=PR.LABEL[k], n=int(lean.sum()), hit=round(float(side_hit[lean].mean()), 3),
                           pred=round(float(np.where(po > 0.5, po, 1 - po)[lean].mean()), 3),
                           overs=round(float((po > 0.5)[lean].mean()), 3)))
print(pd.DataFrame(out['mae']).to_string(index=False)); print(pd.DataFrame(out['cal']).to_string(index=False))
json.dump(out, open(os.path.join(D.DIR, 'backtest_props.json'), 'w'), indent=1)
