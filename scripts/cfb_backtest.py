"""Walk-forward backtest of the college football model against DraftKings (free ESPN lines, 2026 season).

For each week, ratings are fit only on games before that week's first kickoff (2025 + 2026 to date), then compared
with DraftKings' opening and closing spread, total and moneyline. Writes output/cfb_backtest.json.

  python scripts/cfb_backtest.py [--grid]
"""
import sys, os, json, argparse, itertools
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
from cfbmodel import espn as E, model as M

ap = argparse.ArgumentParser(); ap.add_argument('--grid', action='store_true'); ap.add_argument('--first', type=int, default=1)
args = ap.parse_args()


def dec(a): return 1 + a / 100 if a > 0 else 1 + 100 / -a
def imp(a): return 1 / dec(a)


G = E.load([2024, 2025, 2026])
L = E.load_lines()
T = G[(G.season == 2026) & G.home_pts.notna()].merge(L, on='espn_id')


def predict(hl, lam, prev, cap, weeks, mkt=0.0):
    out = []
    for w in weeks:
        wk = T[(T.week == w) & (T.season_type == 2)]
        if not len(wk): continue
        asof = pd.to_datetime(wk.start, utc=True).min()
        R = M.Ratings(hl, lam, prev, cap, mkt, L).fit(G, asof, 2026)
        m, t = R.predict(wk)
        x = wk.copy(); x['m'] = m; x['t'] = t
        x['n_h'] = [R.n_games.get(i, 0) for i in x.home_id]; x['n_a'] = [R.n_games.get(i, 0) for i in x.away_id]
        out.append(x)
    return pd.concat(out)


def ats(x, line_col, edge_min=0.0):
    """Bet the side the model likes vs line_col (home spread); graded at -110-ish DK closing price on the result."""
    e = x.m + x[line_col]                     # >0: model likes home
    res = x.home_pts - x.away_pts + x[line_col]
    s = x[(e.abs() >= edge_min) & (res != 0)]
    win = np.sign(s.m + s[line_col]) == np.sign(s.home_pts - s.away_pts + s[line_col])
    return dict(n=int(len(s)), hit=round(float(win.mean()), 4) if len(s) else None)


def summary(x):
    mg = x.home_pts - x.away_pts
    r = dict(games=int(len(x)), weeks=sorted(int(w) for w in x.week.unique()))
    r['margin_mae'] = dict(model=round(float((x.m - mg).abs().mean()), 2), dk_close=round(float((-x.sp_home - mg).abs().mean()), 2),
                           dk_open=round(float((-x.open_sp_home - mg).abs().mean()), 2))
    r['total_mae'] = dict(model=round(float((x.t - x.home_pts - x.away_pts).abs().mean()), 2),
                          dk_close=round(float((x.total - x.home_pts - x.away_pts).abs().mean()), 2))
    r['ats_close'] = {f'edge>={k}': ats(x, 'sp_home', k) for k in (0, 3, 5, 7)}
    r['ats_open'] = {f'edge>={k}': ats(x, 'open_sp_home', k) for k in (0, 3, 5, 7)}
    # line moved toward the model between open and close (closing line value)
    mv = x[(x.sp_home != x.open_sp_home)]
    side = np.sign(mv.m + mv.open_sp_home)
    r['clv_open'] = dict(n=int(len(mv)), toward_model=round(float((np.sign(mv.open_sp_home - mv.sp_home) == side).mean()), 4) if len(mv) else None)
    # totals
    to = x[(x.home_pts + x.away_pts) != x.total]
    hit = np.sign(to.t - to.total) == np.sign(to.home_pts + to.away_pts - to.total)
    r['totals_close'] = dict(n=int(len(to)), hit=round(float(hit.mean()), 4))
    big = to[(to.t - to.total).abs() >= 4]
    r['totals_close_edge4'] = dict(n=int(len(big)), hit=round(float((np.sign(big.t - big.total) == np.sign(big.home_pts + big.away_pts - big.total)).mean()), 4) if len(big) else None)
    # moneyline: log loss of model, DK no-vig and blends; straight-up winner accuracy
    ml = x[x.ml_home.notna() & x.ml_away.notna()].copy()
    ml['pb'] = [imp(h) / (imp(h) + imp(a)) for h, a in zip(ml.ml_home, ml.ml_away)]
    ml['pm'] = M.p_win(ml.m).clip(0.005, 0.995)
    y = (ml.home_pts > ml.away_pts).astype(float)
    ll = lambda p: float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())
    r['moneyline'] = dict(n=int(len(ml)), logloss={f'w{w}': round(ll(w * ml.pm + (1 - w) * ml.pb), 4) for w in (0, 0.25, 0.5, 1)})
    pick_model = (ml.pm >= 0.5) == (y == 1); pick_dk = (ml.pb >= 0.5) == (y == 1)
    r['winners'] = dict(model=round(float(pick_model.mean()), 4), dk_favorite=round(float(pick_dk.mean()), 4),
                        agree=round(float(pick_dk[(ml.pm >= .5) == (ml.pb >= .5)].mean()), 4), agree_n=int(((ml.pm >= .5) == (ml.pb >= .5)).sum()))
    # favorites -110 to -300 (no heavy juice): how often they win, and whether the model adds anything to picking among them
    ml['fav_px'] = np.where(ml.pb >= 0.5, ml.ml_home, ml.ml_away); ml['fav_won'] = np.where(ml.pb >= 0.5, y == 1, y == 0)
    ml['fav_pm'] = np.where(ml.pb >= 0.5, ml.pm, 1 - ml.pm); ml['fav_pb'] = np.maximum(ml.pb, 1 - ml.pb)
    band = ml[(ml.fav_px <= -110) & (ml.fav_px >= -300)]
    prof = lambda s: round(float(np.where(s.fav_won, [dec(p) - 1 for p in s.fav_px], -1).mean()), 4) if len(s) else None
    r['fav_-110_to_-300'] = dict(n=int(len(band)), hit=round(float(band.fav_won.mean()), 4), roi=prof(band),
                                model_likes=dict(n=int((band.fav_pm > band.fav_pb + .03).sum()), hit=round(float(band[band.fav_pm > band.fav_pb + .03].fav_won.mean()), 4),
                                                 roi=prof(band[band.fav_pm > band.fav_pb + .03])),
                                model_doubts=dict(n=int((band.fav_pm < band.fav_pb - .03).sum()), hit=round(float(band[band.fav_pm < band.fav_pb - .03].fav_won.mean()), 4),
                                                  roi=prof(band[band.fav_pm < band.fav_pb - .03])))
    r['ml_value'] = {}
    for w in (0.25, 0.5):
        for thr in (0.0, 0.03):
            rows = []
            for k in ml.itertuples():
                for p, px, won in ((w * k.pm + (1 - w) * k.pb, k.ml_home, k.home_pts > k.away_pts), (1 - (w * k.pm + (1 - w) * k.pb), k.ml_away, k.away_pts > k.home_pts)):
                    if p * dec(px) - 1 >= thr and px >= -300: rows.append(dec(px) - 1 if won else -1)
            r['ml_value'][f'w{w}_ev>={thr}'] = dict(n=len(rows), roi=round(float(np.mean(rows)), 4) if rows else None)
    # residual spread (for the cover/win model)
    r['sd_margin'] = round(float((x.m - mg).std()), 2); r['sd_total'] = round(float((x.t - x.home_pts - x.away_pts).std()), 2)
    # best blend of model and DK close for the margin
    best = min(((w, float(((w * x.m - (1 - w) * x.sp_home) - mg).abs().mean())) for w in np.arange(0, 1.01, .05)), key=lambda z: z[1])
    r['best_margin_weight'] = dict(w=round(best[0], 2), mae=round(best[1], 2))
    return r


weeks = list(range(args.first, 12))
if args.grid:
    res = []
    for hl, lam, prev, mkt in itertools.product([120, 240, 480], [0.3, 1, 3], [0.5, 1.0], [0, 0.5, 0.8, 1.0]):
        x = predict(hl, lam, prev, 99, range(4, 12), mkt)
        res.append((hl, lam, prev, mkt, round(float((x.m - (x.home_pts - x.away_pts)).abs().mean()), 3), ats(x, 'sp_home')['hit'], ats(x, 'open_sp_home')['hit']))
        print(res[-1], flush=True)
    res.sort(key=lambda r: r[4]); print('best by MAE:', res[:5]); sys.exit()

x = predict(M.HL, M.LAM, M.PREV, M.CAP, weeks, M.MKT)
out = dict(params=dict(hl=M.HL, lam=M.LAM, prev=M.PREV, cap=M.CAP, mkt=M.MKT), all=summary(x), weeks_1_3=summary(x[x.week <= 3]), weeks_4_on=summary(x[x.week >= 4]))
os.makedirs('output', exist_ok=True)
json.dump(out, open(os.path.join(os.path.dirname(__file__), '..', 'output', 'cfb_backtest.json'), 'w'), indent=1)
print(json.dumps(out, indent=1))
