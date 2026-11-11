"""Does requiring the plain and the market-anchored model to agree raise the hit rate?

plain    = v2 model (EPA + QB) predicting the margin on its own
anchored = same features, fit on top of the betting line (only moves off the line where the features say so)
A pick "agrees" when both put the same side of the line, and the plain edge is at least MIN_EDGE points.
"""
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
from nflmodel.predict import load, fit_predict, BASE_MARGIN_X, BASE_TOTAL_X
ROOT = os.path.join(os.path.dirname(__file__), '..')
df = load(os.path.join(ROOT, 'data', 'features.csv')); df['gameday'] = pd.to_datetime(df.gameday)
NOQB = [c for c in BASE_MARGIN_X if c != 'd_qb']


def table(d, line, label):
    live = d.result != d[line]
    out = []
    for name, side_ok, m in [
        ('plain model, edge >= 0', None, live),
        ('plain model, edge >= 2', None, live & ((d.plain - d[line]).abs() >= 2)),
        ('both agree, edge >= 0', 'agree', live),
        ('both agree, edge >= 2', 'agree', live & ((d.plain - d[line]).abs() >= 2)),
        ('both agree, edge >= 3', 'agree', live & ((d.plain - d[line]).abs() >= 3)),
    ]:
        if side_ok:
            m = m & (np.sign(d.plain - d[line]) == np.sign(d.anch - d[line])) & (d.anch != d[line])
        hit = (np.sign(d.plain - d[line]) == np.sign(d.result - d[line]))[m].mean()
        out.append(f'  {name:26s} n={m.sum():4d}  hit {hit:.3f}  ROI {hit * 100 / 110 - (1 - hit):+.3f}')
    print(f'\n-- {label}'); print('\n'.join(out))


# 1) 2023-25 walk-forward against the closing line
rows = []
for s in [2023, 2024, 2025]:
    tr, te = df.gameday < df[df.season == s].gameday.min(), (df.season == s) & (df.week >= 3)
    p = fit_predict(df, tr, te, False, BASE_MARGIN_X, BASE_TOTAL_X)
    a = fit_predict(df, tr, te, True, BASE_MARGIN_X, BASE_TOTAL_X)
    rows.append(p.assign(plain=p.pred_margin, anch=a.pred_margin.values))
table(pd.concat(rows).query('result == result'), 'spread_line', '2023-25 walk-forward, closing line')

# 2) 2019-20 opener test (no QB feature), anchored on the opening line
sc = pd.read_csv(os.path.join(ROOT, 'data', 'sc_lines.csv'))
sc = sc[sc.side == sc.home_team].assign(open_spread=lambda x: -x.line)[['season', 'week', 'home_team', 'away_team', 'open_spread']]
dd = df.merge(sc, on=['season', 'week', 'home_team', 'away_team'], how='left')
rows = []
for s in [2019, 2020]:
    te = (dd.season == s) & (dd.week >= 3) & dd.open_spread.notna()
    tr = (dd.season != s) & dd.result.notna()
    p = fit_predict(dd, tr, te, False, NOQB, BASE_TOTAL_X)
    # anchor on the opener: swap it in as the line the anchored model builds on
    d2 = dd.copy(); d2.loc[te, 'spread_line'] = d2.loc[te, 'open_spread']
    a = fit_predict(d2, tr, te, True, NOQB, BASE_TOTAL_X)
    rows.append(p.assign(plain=p.pred_margin, anch=a.pred_margin.values))
table(pd.concat(rows).query('result == result'), 'open_spread', '2019-20, betting the opener (no QB feature)')
