"""Calibration check on 2021-25 walk-forward games, plus the Platt constants used in weekly_picks."""
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..')); os.chdir(os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
from nflmodel.predict import load, fit_predict, BASE_MARGIN_X, BASE_TOTAL_X
from nflmodel.stats import norm
df = load('data/features.csv'); df['gameday'] = pd.to_datetime(df.gameday)
rows = []
for s in [2021, 2022, 2023, 2024, 2025]:
    tr, te = df.gameday < df[df.season == s].gameday.min(), (df.season == s) & (df.week >= 3)
    rows.append(fit_predict(df, tr, te, False, BASE_MARGIN_X, BASE_TOTAL_X))
p = pd.concat(rows).query('result == result')
# win probability calibration (favorite's side)
pw = np.where(p.p_home_win >= .5, p.p_home_win, 1 - p.p_home_win)
won = np.where(p.p_home_win >= .5, p.result > 0, p.result < 0)
b = pd.cut(pw, [.5, .6, .7, .8, .9, 1.0])
w = pd.DataFrame({'bin': b, 'pred': pw, 'won': won}).groupby('bin', observed=True).agg(n=('won', 'size'), predicted=('pred', 'mean'), actual=('won', 'mean'))
print('WIN PROB (model favorite)\n', w.round(3))
# cover probability calibration vs closing spread
ch = 1 - norm.cdf(p.spread_line, p.pred_margin, p.sd_margin)
pc = np.where(ch >= .5, ch, 1 - ch); cov = np.where(ch >= .5, p.result > p.spread_line, p.result < p.spread_line)
live = p.result != p.spread_line
c = pd.DataFrame({'bin': pd.cut(pc, [.5, .55, .6, .65, .7, 1]), 'pred': pc, 'cov': cov})[live.values].groupby('bin', observed=True).agg(n=('cov', 'size'), predicted=('pred', 'mean'), actual=('cov', 'mean'))
print('\nCOVER PROB vs closing line\n', c.round(3))
# market comparison: win prob from no-vig moneyline
print('\nBrier model', round(np.mean((p.p_home_win - (p.result > 0)) ** 2), 4))
ml = p.dropna(subset=['home_moneyline', 'away_moneyline'])
dec = lambda o: np.where(o < 0, -o / (-o + 100), 100 / (o + 100))
mh = dec(ml.home_moneyline); ma = dec(ml.away_moneyline); mp = mh / (mh + ma)
print('Brier market', round(np.mean((mp - (ml.result > 0)) ** 2), 4), 'Brier model same games', round(np.mean((ml.p_home_win - (ml.result > 0)) ** 2), 4))
# Platt scaling for home win prob: fit y ~ a*logit(p)+b by Newton
x = np.log(p.p_home_win / (1 - p.p_home_win)).values; y = (p.result > 0).astype(float).values
a, b0 = 1.0, 0.0
for _ in range(50):
    z = a * x + b0; q = 1 / (1 + np.exp(-z)); W = q * (1 - q)
    H = np.array([[np.sum(W * x * x), np.sum(W * x)], [np.sum(W * x), np.sum(W)]]); gr = np.array([np.sum((q - y) * x), np.sum(q - y)])
    a, b0 = np.array([a, b0]) - np.linalg.solve(H, gr)
print('\nPlatt a, b:', round(a, 3), round(b0, 3))
for pr in [.70, .714, .735, .772, .807, .828, .839, .867]:
    print(pr, '->', round(1 / (1 + np.exp(-(a * np.log(pr / (1 - pr)) + b0))), 3))
