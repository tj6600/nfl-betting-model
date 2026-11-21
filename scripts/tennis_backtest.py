"""Tennis model backtest -> output/tennis_backtest.json (shown on the board's Model record tab).

  python scripts/tennis_backtest.py

1. Elo alone, out of sample on ESPN results (2024 onward, ratings warmed up on 2021-23): how often the model's pick wins,
   by how sure the model was, per tour, main draw only (qualifying is left out: DraftKings rarely prices it).
2. Against the betting market, if tennis-data.co.uk files are in tennis_data/odds/ (2023.xlsx, 2024w.xlsx, …; the site
   blocks cloud downloads, so they are added by hand): each match's closing odds (Pinnacle, else the market average) are
   matched to ESPN's match by date and player surnames. It reports the market favourite's record, the model+market blend's
   log loss for several model weights, and what flat $10 bets would have made at the closing price for each rule.
"""
import sys, os, json, glob, re, unicodedata
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
from tennismodel import espn as E, model as M

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
FROM = '2024-01-01'


def ll(p, y):
    p = np.clip(p, 1e-4, 1 - 1e-4); return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


d = E.load()
d['p'] = M.backtest_probs(d)
d['y'] = (d.winner == 1).astype(float)
T = d[d.p.notna() & (d.ts >= FROM) & ~d['round'].str.startswith('Qual')].copy()
T['pick_p'] = np.maximum(T.p, 1 - T.p)
T['hit'] = ((T.p >= 0.5) == (T.y == 1)).astype(int)

BANDS = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]


def bands(x):
    out = []
    for lo, hi in BANDS:
        b = x[(x.pick_p >= lo) & (x.pick_p < hi)]
        if len(b): out.append(dict(band=f'{int(lo * 100)}-{min(int(hi * 100), 100)}%', n=int(len(b)), hit=round(float(b.hit.mean()), 3), avg_p=round(float(b.pick_p.mean()), 3)))
    return out


elo = {}
for tour in ['atp', 'wta', 'all']:
    x = T if tour == 'all' else T[T.tour == tour]
    elo[tour] = dict(n=int(len(x)), hit=round(float(x.hit.mean()), 3), logloss=round(ll(x.p.values, x.y.values), 4), bands=bands(x),
                     by_surface={s: dict(n=int(len(g)), hit=round(float(g.hit.mean()), 3)) for s, g in x.groupby('surface')})
print('Elo pick hit rate (main draw, 2024+):', {k: (v['n'], v['hit'], v['logloss']) for k, v in elo.items()})
OUT = dict(built=pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%d'), since=FROM, elo=elo, market=None)


# ---------- against the market (tennis-data.co.uk) ----------
def norm(s):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z ]', ' ', s).split()


def key_td(name):
    """tennis-data 'De Minaur A.' -> ('deminaur', 'a')"""
    parts = str(name).replace('.', ' ').split()
    if len(parts) < 2: return (''.join(norm(name)), '')
    ini = [p for p in parts if len(p) == 1 or (p.isupper() and len(p) <= 2)]
    sur = [p for p in parts if p not in ini]
    return (''.join(''.join(norm(p)) for p in sur), (ini[0][0].lower() if ini else ''))


def key_espn(name):
    """ESPN 'Alex de Minaur' -> ('deminaur', 'a'); tries every split point because surnames can be 2-3 words."""
    w = norm(name)
    return [(''.join(w[i:]), w[0][0]) for i in range(1, len(w))] if len(w) > 1 else [(''.join(w), '')]


files = sorted(glob.glob(os.path.join(ROOT, 'tennis_data', 'odds', '*.xls*')))
if files:
    rows = []
    for f in files:
        x = pd.read_excel(f)
        x['tour'] = 'wta' if re.search(r'\d{4}w', os.path.basename(f)) or 'WTA' in x.columns or 'Tier' in x.columns else 'atp'
        rows.append(x)
    O = pd.concat(rows, ignore_index=True)
    O['Date'] = pd.to_datetime(O.Date, errors='coerce')
    def col(*c):
        for k in c:
            if k in O.columns: return pd.to_numeric(O[k], errors='coerce')
        return pd.Series(np.nan, index=O.index)
    O['ow'] = col('PSW').fillna(col('AvgW')).fillna(col('B365W'))
    O['ol'] = col('PSL').fillna(col('AvgL')).fillna(col('B365L'))
    O = O[O.ow.notna() & O.ol.notna() & O.Date.notna()]
    O['kw'] = O.Winner.map(key_td); O['kl'] = O.Loser.map(key_td)
    # index ESPN matches by (tour, surname pair) for matching within 4 days
    idx = {}
    D = d[d.p.notna() & ~d['round'].str.startswith('Qual')]
    for i, x in zip(D.index, D.itertuples()):
        for a in key_espn(x.p1_name):
            for b in key_espn(x.p2_name):
                idx.setdefault((x.tour, a[0], b[0]), []).append(i)
    hits = []
    for x in O.itertuples():
        best = None
        for (a, b, flip) in ((x.kw, x.kl, False), (x.kl, x.kw, True)):
            for i in idx.get((x.tour, a[0], b[0]), []):
                if abs((d.at[i, 'ts'].tz_convert(None) - x.Date).days) <= 4:
                    best = (i, flip); break
            if best: break
        if best:
            i, flip = best
            # p1 of the ESPN row is the tennis-data winner unless flipped
            o1, o2 = (x.ol, x.ow) if flip else (x.ow, x.ol)
            hits.append(dict(i=i, o1=o1, o2=o2))
    H = pd.DataFrame(hits).drop_duplicates('i')
    X = d.loc[H.i].copy(); X['o1'] = H.o1.values; X['o2'] = H.o2.values
    X = X[X.ts >= FROM]
    X['pb'] = (1 / X.o1) / (1 / X.o1 + 1 / X.o2)
    print(f'matched {len(H)} of {len(O)} tennis-data matches; {len(X)} since {FROM}')
    res = {}
    for w in [0, 0.1, 0.2, 0.3, 0.5, 1.0]:
        pb = w * X.p + (1 - w) * X.pb
        res[str(w)] = round(ll(pb.values, X.y.values), 4)
    fav = (X.pb >= 0.5) == (X.y == 1)
    # flat bets at the closing price: model+market blend (25% model) picks, by blend chance, and "value" (blend EV 3%+)
    pbl = 0.25 * X.p + 0.75 * X.pb
    side1 = pbl >= 0.5
    price = np.where(side1, X.o1, X.o2); won = np.where(side1, X.y == 1, X.y == 0); pp = np.where(side1, pbl, 1 - pbl)
    rules = {}
    for lo, hi in BANDS:
        m = (pp >= lo) & (pp < hi)
        if m.sum(): rules[f'blend pick {int(lo * 100)}-{min(int(hi * 100), 100)}%'] = dict(n=int(m.sum()), hit=round(float(won[m].mean()), 3), roi=round(float((np.where(won[m], price[m] - 1, -1)).mean()), 3))
    ev1 = pbl * X.o1 - 1; ev2 = (1 - pbl) * X.o2 - 1
    for t in [0.03, 0.05]:
        b1, b2 = ev1 >= t, ev2 >= t
        n = int(b1.sum() + b2.sum())
        if n:
            prof = np.where(X.y[b1] == 1, X.o1[b1] - 1, -1).sum() + np.where(X.y[b2] == 0, X.o2[b2] - 1, -1).sum()
            wins = int((X.y[b1] == 1).sum() + (X.y[b2] == 0).sum())
            rules[f'value EV {int(t * 100)}%+'] = dict(n=n, hit=round(wins / n, 3), roi=round(float(prof / n), 3))
    OUT['market'] = dict(n=int(len(X)), matched=int(len(H)), fav_hit=round(float(fav.mean()), 3), elo_hit=round(float(((X.p >= .5) == (X.y == 1)).mean()), 3),
                         logloss_by_model_weight=res, rules=rules, odds='Pinnacle closing (else market average)')
    print(json.dumps(OUT['market'], indent=1))

os.makedirs(os.path.join(ROOT, 'output'), exist_ok=True)
json.dump(OUT, open(os.path.join(ROOT, 'output', 'tennis_backtest.json'), 'w'), indent=1)
print('-> output/tennis_backtest.json')
