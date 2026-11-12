"""Backtest the NHL game model on 2025-26 DraftKings moneylines and puck lines (5 PM ET snapshots).

The model is fit on 2024-25 only. Starting goalies come from the box score, which matches what is known
at 5 PM ET on most nights, since starters are usually confirmed after the morning skate.

  python scripts/nhl_game_backtest.py      # writes output/nhl_game_backtest.json
"""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np
import pandas as pd
from nhlmodel.data import load
from nhlmodel.games import GameModel
from nhlmodel.odds import history_game_rows
from nhlmodel.stats import am_to_prob, am_to_dec, novig

OUT = os.path.join(os.path.dirname(__file__), '..', 'output', 'nhl_game_backtest.json')


def market_table(games):
    r = history_game_rows()
    r = r[r.book == 'draftkings']
    r['game_date'] = pd.to_datetime(r.start).dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d')
    rows = []
    for (gd, h, a), e in r.groupby(['game_date', 'home', 'away']):
        row = {'game_date': gd, 'home': h, 'away': a}
        ml = e[e.market == 'h2h']
        if len(ml) == 2:
            row['ml_home'] = ml[ml.side == h].price.iloc[0]; row['ml_away'] = ml[ml.side == a].price.iloc[0]
        sp = e[(e.market == 'spreads') & (e.side == h)]
        if len(sp):
            row['pl_home_pt'] = sp.point.iloc[0]; row['pl_home'] = sp.price.iloc[0]
            row['pl_away'] = e[(e.market == 'spreads') & (e.side == a)].price.iloc[0]
        rows.append(row)
    m = pd.DataFrame(rows)
    return m.merge(games[['game_id', 'game_date', 'home', 'away', 'home_score', 'away_score']], on=['game_date', 'home', 'away'])


def bet_report(p, pa, pb, win_a, label):
    """p = model chance side A wins; pa/pb American prices; win_a = 1 if side A won."""
    da, db = am_to_dec(pa), am_to_dec(pb)
    pm = novig(am_to_prob(pa), am_to_prob(pb))[0]
    y = win_a.astype(int)
    eps = 1e-6
    ll = lambda q: float(-np.mean(y * np.log(np.clip(q, eps, 1)) + (1 - y) * np.log(np.clip(1 - q, eps, 1))))
    out = {'n': int(len(y)), 'logloss': {'model': ll(p), 'market': ll(pm), 'blend_50': ll(.5 * p + .5 * pm)}}
    print(f'\n== {label}: {len(y)} games   log loss model {ll(p):.4f} market {ll(pm):.4f} blend {ll(.5*p+.5*pm):.4f}')
    for name, q in [('model', p), ('blend_50', .5 * p + .5 * pm)]:
        evA, evB = q * da - 1, (1 - q) * db - 1
        sideA = evA >= evB
        ev = np.where(sideA, evA, evB)
        win = np.where(sideA, y == 1, y == 0)
        price = np.where(sideA, pa, pb)
        prof = np.where(win, np.where(sideA, da, db) - 1, -1)
        res = {}
        for th in [0.0, 0.03, 0.05, 0.08]:
            m = ev >= th
            mj = m & (price >= -150)
            res[f'ev>={th:.2f}'] = {'bets': int(m.sum()), 'hit': float(win[m].mean()) if m.any() else None,
                                    'roi': float(prof[m].mean()) if m.any() else None,
                                    'no_heavy_juice': {'bets': int(mj.sum()), 'hit': float(win[mj].mean()) if mj.any() else None,
                                                       'roi': float(prof[mj].mean()) if mj.any() else None}}
            if m.any():
                print(f"  {name:9s} ev>={th:.2f}: {m.sum():4d} bets hit {win[m].mean():.3f} roi {prof[m].mean():+.3f}"
                      f" | -150 or better: {mj.sum()} roi {prof[mj].mean() if mj.any() else float('nan'):+.3f}")
        out[name] = res
    return out


def main():
    games, sk, go, tg = load()
    gm = GameModel().fit(games, go, tg, [20242025])
    d = gm.d
    d['lam'] = gm.lam(d)
    h = d[d.is_home == 1][['game_id', 'lam']].merge(d[d.is_home == 0][['game_id', 'lam']], on='game_id', suffixes=('_h', '_a'))
    pr = pd.DataFrame([gm.probs(a, b) for a, b in zip(h.lam_h, h.lam_a)])
    h = pd.concat([h.reset_index(drop=True), pr], axis=1)
    m = market_table(games).merge(h, on='game_id')
    m['margin'] = m.home_score - m.away_score
    print('games with lines:', len(m), '| OT home win share', round(gm.ot_home, 3), '| shared share', gm.shared)
    rep = {'games': int(len(m)), 'shared': gm.shared, 'en_table': {str(k): v for k, v in gm.T.items()}}
    ml = m.dropna(subset=['ml_home', 'ml_away'])
    rep['moneyline'] = bet_report(ml.home_win.values, ml.ml_home.values, ml.ml_away.values, (ml.margin > 0).values, 'Moneyline')
    pl = m.dropna(subset=['pl_home', 'pl_away'])
    pl = pl[pl.pl_home_pt.abs() == 1.5]
    p_home = np.where(pl.pl_home_pt < 0, pl['home_-1.5'], pl['home_+1.5'])
    cover = np.where(pl.pl_home_pt < 0, pl.margin >= 2, pl.margin >= -1)
    rep['puck_line'] = bet_report(p_home, pl.pl_home.values, pl.pl_away.values, cover, 'Puck line')
    # calibration of the favorite -1.5 chance (the plus-money side of the puck line)
    fav = (pl.pl_home_pt < 0).values
    p_fav = np.where(fav, pl['home_-1.5'], 1 - pl['home_+1.5'])
    fav_cover = np.where(fav, pl.margin >= 2, pl.margin <= -2)
    rep['calibration_fav_-1.5'] = [{'bucket': str(k), 'n': int(len(v)), 'model': float(v.p.mean()), 'actual': float(v.y.mean())}
                                    for k, v in pd.DataFrame({'p': p_fav, 'y': fav_cover}).groupby(pd.cut(p_fav, [0, .25, .3, .35, .4, .45, .5, 1]), observed=True)]
    print(pd.DataFrame(rep['calibration_fav_-1.5']))
    json.dump(rep, open(OUT, 'w'), indent=1)
    m.to_csv(OUT.replace('.json', '.csv'), index=False)


if __name__ == '__main__':
    main()
