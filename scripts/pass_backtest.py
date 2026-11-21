"""Backtest of the passing yards model (nflmodel/passing.py), season by season: fit on earlier seasons, test on the next.

1. Accuracy: MAE vs the QB's season-to-date average and his last-5 average.
2. Calibration: chance of the Over against a stand-in line (season-to-date average rounded to the half point,
   3+ starts). Real book lines are sharper than this, so the hit rate on leans overstates what to expect.
python scripts/pass_backtest.py      # writes odds_log/backtest/passing.json
"""
import sys, os, json; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
from nflmodel import passing as PY

q = PY.load(range(2021, 2027)); f = PY.features(q).dropna(subset=['imp_pts'])
f['sta'] = f.groupby(['pid', 'season']).passing_yards.transform(lambda x: x.shift(1).expanding().mean())
f['n_sta'] = f.groupby(['pid', 'season']).cumcount()
f['l5'] = f.groupby('pid').passing_yards.transform(lambda x: x.shift(1).rolling(5, min_periods=3).mean())
res = {'mae': [], 'cal': []}
for ys in [2024, 2025, 2026]:
    tr = f[(f.season < ys) & (f.h_starts >= 1)]; te = f[(f.season == ys) & (f.h_starts >= 1)].copy()
    b, sp = PY.fit(tr)
    te['mu'] = PY.predict(b, te)
    ok = te.sta.notna() & te.l5.notna() & (te.n_sta >= 3)
    t = te[ok]
    res['mae'].append(dict(season=ys, n=int(len(t)), model=round(float((t.passing_yards - t.mu).abs().mean()), 1),
                           season_avg=round(float((t.passing_yards - t.sta).abs().mean()), 1), last5=round(float((t.passing_yards - t.l5).abs().mean()), 1),
                           bias=round(float((t.passing_yards - t.mu).mean()), 1)))
    line = np.floor(t.sta) + 0.5
    po = 0.5 + 0.85 * (sp.p_over(t.mu, line) - 0.5)
    hit = (t.passing_yards > line).values
    for th in [0.0, 0.05, 0.1]:
        lean = np.abs(po - 0.5) >= th
        res['cal'].append(dict(season=ys, lean=th, n=int(lean.sum()), hit=round(float(((po > 0.5) == hit)[lean].mean()), 3),
                               pred=round(float(np.where(po > 0.5, po, 1 - po)[lean].mean()), 3), overs=round(float((po > 0.5)[lean].mean()), 3)))
print(pd.DataFrame(res['mae']).to_string(index=False)); print(pd.DataFrame(res['cal']).to_string(index=False))
os.makedirs(os.path.join(os.path.dirname(__file__), '..', 'odds_log', 'backtest'), exist_ok=True)
json.dump(res, open(os.path.join(os.path.dirname(__file__), '..', 'odds_log', 'backtest', 'passing.json'), 'w'), indent=1)
