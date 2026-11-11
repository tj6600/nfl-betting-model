import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
from nflmodel.predict import load, fit_predict, legs
ROOT = os.path.join(os.path.dirname(__file__), '..')
df = load(os.path.join(ROOT, 'data', 'features.csv'))
df['gameday'] = pd.to_datetime(df.gameday)

def report(name, d):
    d = d[d.result.notna()]
    print(f'\n== {name}  (n={len(d)})')
    print(f'margin MAE model {abs(d.pred_margin-d.result).mean():.2f} vs line {abs(d.spread_line-d.result).mean():.2f} | '
          f'total MAE model {abs(d.pred_total-d.total).mean():.2f} vs line {abs(d.total_line-d.total).mean():.2f}')
    e = d.pred_margin - d.spread_line; ok = np.sign(e) == np.sign(d.result - d.spread_line); live = d.result != d.spread_line
    et = d.pred_total - d.total_line; okt = np.sign(et) == np.sign(d.total - d.total_line); livet = d.total != d.total_line
    for th in [0, 1.5, 3]:
        m = live & (e.abs() >= th); mt = livet & (et.abs() >= th)
        print(f'  edge>={th}: ATS {ok[m].mean():.3f} (n={m.sum()})   O/U {okt[mt].mean():.3f} (n={mt.sum()})')
    L = legs(d).dropna(subset=['won'])
    for th in [0.0, 0.03, 0.06]:
        b = L[L.ev > th]
        if len(b):
            dec = 1 / b.implied
            print(f'  bets EV>{th:.0%}: n={len(b)} won {b.won.mean():.3f} ROI {(np.where(b.won, dec-1, -1)).mean():+.3f}')
    sec = L[(L.market == 'moneyline') & (L.model_prob >= 0.75)]
    print(f'  secure ML (p>=75%): n={len(sec)} won {sec.won.mean():.3f} ROI {np.where(sec.won, 1/sec.implied-1, -1).mean():+.3f}')

for anchor in [False, True]:
    out = []
    for s in [2023, 2024, 2025]:
        out.append(fit_predict(df, df.gameday < df[df.season == s].gameday.min(), (df.season == s) & (df.week >= 3), anchor))
    report(f'2023-25 walk-forward, market_anchor={anchor}', pd.concat(out))
    wk = df[(df.season == 2026) & (df.week == 9)]
    p9 = fit_predict(df, df.gameday < wk.gameday.min(), (df.season == 2026) & (df.week == 9), anchor)
    report(f'2026 week 9, market_anchor={anchor}', p9)
    if not anchor: p9.to_csv(os.path.join(ROOT, 'output', '2026_week9_epa_predictions.csv'), index=False)
    else: p9.to_csv(os.path.join(ROOT, 'output', '2026_week9_epa_anchored.csv'), index=False)
