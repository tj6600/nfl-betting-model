"""Test betting early (opening-style) lines instead of closing lines.

nflverse's only free early-line data is `sc_lines.csv` (spreads, 2013-2020; its source is not documented).
These lines differ from the closing line by about a point and predict results a little worse,
which is what opening lines look like. Our features start in 2019, so the test seasons are 2019 and 2020.

The ridge model is fit on every other season (leave-one-season-out), so the weights see later seasons,
but every feature is still built only from games before the one being predicted.
Only v2 features (EPA + QB) are used: injury reports come out late in the week, after openers are posted.
Bets are graded at -110.
"""
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
from nflmodel.predict import load, fit_predict, BASE_MARGIN_X as ALL_MX, BASE_TOTAL_X as ALL_TX
NO_QB = '--no-qb' in sys.argv
BASE_MARGIN_X = [c for c in ALL_MX if not (NO_QB and c == 'd_qb')]
BASE_TOTAL_X = [c for c in ALL_TX if not (NO_QB and c == 's_qb')]
ROOT = os.path.join(os.path.dirname(__file__), '..')

df = load(os.path.join(ROOT, 'data', 'features.csv')); df['gameday'] = pd.to_datetime(df.gameday)
sc = pd.read_csv(os.path.join(ROOT, 'data', 'sc_lines.csv'))
sc = sc[sc.side == sc.home_team].assign(open_spread=lambda x: -x.line)[['season', 'week', 'home_team', 'away_team', 'open_spread']]
df = df.merge(sc, on=['season', 'week', 'home_team', 'away_team'], how='left')

rows = []
for s in [2019, 2020]:
    test = (df.season == s) & (df.week >= 3) & df.open_spread.notna()
    rows.append(fit_predict(df, (df.season != s) & df.result.notna(), test, False, BASE_MARGIN_X, BASE_TOTAL_X))
d = pd.concat(rows)
d = d[d.result.notna()]
print(f'games: {len(d)}   opener vs close differ by {abs(d.open_spread - d.spread_line).mean():.2f} pts on average')
print(f'MAE: model {abs(d.pred_margin - d.result).mean():.2f}  opener {abs(d.open_spread - d.result).mean():.2f}  close {abs(d.spread_line - d.result).mean():.2f}')

def grade(line_col, label):
    e = d.pred_margin - d[line_col]
    live = d.result != d[line_col]
    ok = np.sign(e) == np.sign(d.result - d[line_col])
    print(f'\n-- betting the {label}')
    for th in [0, 1.5, 3, 4.5]:
        m = live & (e.abs() >= th)
        hit = ok[m].mean(); roi = (hit * 100 / 110) - (1 - hit)
        print(f'  edge >= {th}: n={m.sum():3d}  hit {hit:.3f}  ROI {roi:+.3f}')
    return e

e_open = grade('open_spread', 'opening line')
grade('spread_line', 'closing line')
# closing line value: did the market move toward the model's side after the open?
move = d.spread_line - d.open_spread
print('\n-- closing line value of opener bets (line moved toward the model side, in points)')
for th in [0, 1.5, 3]:
    m = (e_open.abs() >= th) & (move != 0)
    toward = np.sign(move[m]) == np.sign(e_open[m])
    clv = (np.sign(e_open[m]) * move[m]).mean()
    print(f'  edge >= {th}: n={m.sum():3d}  moved our way {toward.mean():.3f}  avg CLV {clv:+.2f} pts')
