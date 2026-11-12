"""Does game-time weather move player props beyond what the models already expect?

Fits each prop model (rush/rec yards, receptions, passing yards, anytime TD) on earlier seasons and predicts the next
(2023-2026), then compares actual vs predicted by weather bucket (Open-Meteo archive, 3 hours from kickoff, see
nflmodel/weather.py; domes and closed roofs are the 'indoor' baseline). It also fits a small multiplier model per stat:
log(actual sum / predicted sum) on wind above 12 mph, rain (1+ mm over the game window) and cold (below 40F),
and reports bootstrap intervals by game so only effects that hold up are used.

Writes odds_log/weather_props.json, which nflmodel/weather.py reads to adjust projections.
"""
import sys, os, json; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
ROOT = os.path.join(os.path.dirname(__file__), '..')
import numpy as np, pandas as pd
from nflmodel.model import G
from nflmodel import touchdowns as T, yards as Y, passing as PY, weather as W

TEST = [2023, 2024, 2025, 2026]
wx = pd.read_csv(W.CACHE)
g = G[['game_id', 'roof']].merge(wx[['game_id', 'wx_wind', 'wx_precip', 'wx_temp']], on='game_id', how='left')
g['indoor'] = g.roof.isin(W.INDOOR)
g.loc[g.indoor, ['wx_wind', 'wx_precip', 'wx_temp']] = [0.0, 0.0, 70.0]


def feats(df):
    d = df.merge(g, on='game_id', how='left')
    d = d[d.wx_wind.notna()].copy()
    d['wind12'] = (d.wx_wind - 12).clip(lower=0) / 5          # per 5 mph above 12
    d['rain'] = (d.wx_precip >= 1.0).astype(float)
    d['cold'] = (40 - d.wx_temp).clip(lower=0) / 10            # per 10F below 40
    d['bucket'] = np.select([d.indoor, d.rain == 1, d.wx_wind >= 15, d.wx_wind >= 10, d.wx_temp < 35],
                            ['indoor', 'rain', 'wind 15+', 'wind 10-15', 'cold <35F'], 'outdoor fair')
    return d


rows = []
base = T.training_frame()
for kind in ['rush', 'rec', 'recs']:
    fr = Y.frame(kind, base)
    for y in TEST:
        tr, te = fr[fr.season < y], fr[fr.season == y]
        if te.empty: continue
        b, _ = Y.fit(kind, tr)
        rows.append(pd.DataFrame({'stat': kind, 'game_id': te.game_id.values, 'pred': Y.apply(b, Y.design(te, kind)), 'actual': te[Y.STATS[kind]['y']].values}))
qs = PY.features(PY.load(range(2021, 2027)))
for y in TEST:
    tr, te = qs[qs.season < y], qs[(qs.season == y) & qs.imp_pts.notna()]
    if te.empty: continue
    b, _ = PY.fit(tr)
    rows.append(pd.DataFrame({'stat': 'pass', 'game_id': te.game_id.values, 'pred': PY.predict(b, te), 'actual': te.passing_yards.values}))
for y in TEST:
    tr, te = base[base.season < y], base[base.season == y]
    if te.empty: continue
    b = T.fit(T.design(tr), tr.scored.values)
    rows.append(pd.DataFrame({'stat': 'td', 'game_id': te.game_id.values, 'pred': T.predict(b, T.design(te)), 'actual': te.scored.values}))
R = feats(pd.concat(rows, ignore_index=True))

rng = np.random.default_rng(0)
out = {}
for stat, d in R.groupby('stat'):
    tab = d.groupby('bucket').agg(n=('pred', 'size'), games=('game_id', 'nunique'), pred=('pred', 'sum'), actual=('actual', 'sum'))
    tab['ratio'] = tab.actual / tab.pred
    # multiplier model on game-level sums: log(actual/pred) ~ wind12 + rain + cold, weighted by predicted volume
    gg = d.groupby('game_id').agg(pred=('pred', 'sum'), actual=('actual', 'sum'), wind12=('wind12', 'first'), rain=('rain', 'first'), cold=('cold', 'first'))
    gg = gg[(gg.pred > 0) & (gg.actual > 0)]
    def coef(x):
        X = np.column_stack([x.wind12, x.rain, x.cold, np.ones(len(x))]); yv = np.log(x.actual / x.pred); w = x.pred
        return np.linalg.lstsq(X * np.sqrt(w.values)[:, None], yv.values * np.sqrt(w.values), rcond=None)[0][:3]
    c = coef(gg)
    boots = np.array([coef(gg.iloc[rng.integers(0, len(gg), len(gg))]) for _ in range(300)])
    lo, hi = np.percentile(boots, 5, axis=0), np.percentile(boots, 95, axis=0)
    out[stat] = dict(buckets={k: dict(n=int(v.n), games=int(v.games), ratio=round(float(v.ratio), 3)) for k, v in tab.iterrows()},
                     coef={n: dict(est=round(float(c[i]), 4), lo=round(float(lo[i]), 4), hi=round(float(hi[i]), 4),
                                   use=bool(lo[i] > 0 or hi[i] < 0)) for i, n in enumerate(['wind12', 'rain', 'cold'])})
    print(f'\n== {stat} ==')
    print(tab.round(3).to_string())
    for n, v in out[stat]['coef'].items():
        print(f"  {n}: {v['est']:+.3f} (90% {v['lo']:+.3f} to {v['hi']:+.3f}){'  USED' if v['use'] else ''}")
json.dump(out, open(os.path.join(ROOT, 'odds_log', 'weather_props.json'), 'w'), indent=1)
print('wrote odds_log/weather_props.json')
