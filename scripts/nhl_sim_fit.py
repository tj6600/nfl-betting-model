"""Fit and backtest the NHL game simulation (same model as the NFL one, nflmodel/sim.py). No odds credits.

Hidden numbers per game, from the free box scores (nhl_data) and the DraftKings lines ESPN carried (odds_log/nhl/espn_lines.csv):
  mar    home goal difference minus the one DraftKings' moneyline implies, as a normal score
  tot    total goals minus the DraftKings total
  sog    a regular skater's shots on goal minus what was expected (recency-weighted average, his team's implied goals), F or D
  saves  the starting goalie's saves minus what was expected (recency-weighted average, the opponent's implied goals)
Every pair in a game is grouped (same team / opponents, positions) and correlated, as in scripts/sim_fit.py.

Backtest: fit on games before --split, test on the rest with random 2-4 leg same-game parlays (each leg's own chance right
on average by construction), comparing multiplied chances with simulated ones against how often they hit.

  python scripts/nhl_sim_fit.py                 # fit on everything -> board/site/sim_tables.js (nhl) + nflmodel/sim_nhl.json
  python scripts/nhl_sim_fit.py --backtest      # also writes odds_log/backtest/nhl_sim_backtest.md
"""
import argparse, json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import sim_fit as F
from sim_backtest import report, sim_p
from nflmodel.sim import ndtri, Phi
from nhlmodel.data import load

ROOT = os.path.join(os.path.dirname(__file__), '..')
HALF = 10.0


def lines():
    L = pd.read_csv(os.path.join(ROOT, 'odds_log', 'nhl', 'espn_lines.csv')).dropna(subset=['ml_home', 'ml_away', 'total'])
    ip = lambda a: np.where(a < 0, -a / (np.abs(a) + 100), 100 / (np.abs(a) + 100))
    ph = ip(L.ml_home.values); pa = ip(L.ml_away.values); L['p_home'] = ph / (ph + pa)
    L['exp_margin'] = ndtri(L.p_home.values) * 2.3          # goal difference sd about 2.3
    return L.drop_duplicates(['game_date', 'home', 'away'])[['game_date', 'home', 'away', 'exp_margin', 'total']].rename(columns={'total': 'total_line'})


def variables(cutoff=None, before=True):
    g, sk, go, tg = load()
    L = lines()
    g = g.merge(L, on=['game_date', 'home', 'away'], how='inner')
    g['result'] = g.home_score - g.away_score; g['tot'] = g.home_score + g.away_score
    al = 1 - 0.5 ** (1 / HALF)
    sk = sk.sort_values(['game_date', 'game_id']).copy(); grp = sk.groupby('player_id')
    for c in ['sog', 'toi']: sk[f'h_{c}'] = grp[c].transform(lambda x: x.shift(1).ewm(alpha=al).mean())
    sk['n'] = grp.cumcount()
    go = go[go.starter == True].sort_values(['game_date', 'game_id']).copy(); gg = go.groupby('player_id')
    go['h_saves'] = gg.saves.transform(lambda x: x.shift(1).ewm(alpha=al).mean()); go['n'] = gg.cumcount()
    ctx = pd.concat([pd.DataFrame({'game_id': g.game_id, 'team': g.home, 'imp': g.total_line / 2 + g.exp_margin / 2, 'opp_imp': g.total_line / 2 - g.exp_margin / 2}),
                     pd.DataFrame({'game_id': g.game_id, 'team': g.away, 'imp': g.total_line / 2 - g.exp_margin / 2, 'opp_imp': g.total_line / 2 + g.exp_margin / 2})])
    s = sk.merge(ctx, on=['game_id', 'team']); s = s[(s.n >= 5) & (s.h_toi >= 12)]
    s['pos'] = np.where(s.position == 'D', 'D', 'F')
    o = go.merge(ctx, on=['game_id', 'team']); o = o[o.n >= 3]
    rows = []
    for pos, d in s.groupby('pos'):
        X = np.c_[np.ones(len(d)), d.h_sog, d.h_sog * (d.imp - 3) / 3]
        res = d.sog.values - X @ F.ols(X, d.sog.values)
        dec = pd.Series(pd.qcut(X[:, 1], 6, labels=False, duplicates='drop'), index=d.index)
        rows.append(pd.DataFrame({'game_id': d.game_id.values, 'game_date': d.game_date.values, 'team': d.team.values, 'pid': d.player_id.values, 'pos': pos, 'stat': 'sog', 'z': F.nscore(res, dec)}))
    X = np.c_[np.ones(len(o)), o.h_saves, (o.opp_imp - 3)]
    res = o.saves.values - X @ F.ols(X, o.saves.values)
    rows.append(pd.DataFrame({'game_id': o.game_id.values, 'game_date': o.game_date.values, 'team': o.team.values, 'pid': o.player_id.values, 'pos': 'G', 'stat': 'saves', 'z': F.nscore(res)}))
    gm = pd.DataFrame({'game_id': g.game_id, 'game_date': g.game_date, 'team': g.home, 'pid': 'GAME', 'pos': '', 'stat': 'mar', 'z': F.nscore(g.result.values - g.exp_margin.values)})
    gt = gm.assign(stat='tot', z=F.nscore(g.tot.values - g.total_line.values))
    V = pd.concat(rows + [gm, gt], ignore_index=True)
    V = V.merge(g[['game_id', 'home', 'exp_margin']].rename(columns={'home': 'home_team', 'exp_margin': 'spread_line'}), on='game_id')
    V['home'] = V.team == V.home_team; V['td'] = np.nan; V['c'] = np.nan
    return V


def fit(V):
    return F.fit_rho(F.pairs(V))


def backtest(V, split, per_game=60, seed=5):
    R = {k: v[0] for k, v in fit(V[V.game_date < split]).items()}
    T = V[V.game_date >= split]; rng = np.random.default_rng(seed); rows = []
    for gid, d in T.groupby('game_id'):
        fav = d.spread_line.iloc[0] >= 0; home = d.home_team.iloc[0]; cand = d.to_dict('records')
        if len(cand) < 4: continue
        for _ in range(per_game):
            k = int(rng.choice([2, 2, 3, 3, 4])); idx = rng.choice(len(cand), k, replace=False)
            legs = []
            for i in idx:
                v = cand[i]; s = int(rng.choice([1, -1]))
                t = 0.0 if v['stat'] in ('mar', 'tot') else float(rng.choice([-0.8, -0.4, 0.0, 0.4]))
                if s < 0: t = -t
                legs.append(dict(stat=v['stat'], pos=v['pos'], pid=v['pid'], team=v['team'], home=v['team'] == home, fav=fav, dir=s,
                                 p=float(1 - Phi(t)) if s > 0 else float(Phi(t)), hit=(v['z'] > t) if s > 0 else (v['z'] < t)))
            rows.append(dict(k=k, hit=float(all(l['hit'] for l in legs)), p_ind=float(np.prod([l['p'] for l in legs])), p_sim=sim_p(legs, R)))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--backtest', action='store_true'); ap.add_argument('--split', default='2026-03-15')
    a = ap.parse_args()
    V = variables()
    R = fit(V)
    doc = {'seasons': sorted(V.game_date.str[:4].unique().tolist()), 'games': int(V.game_id.nunique()), 'rho': {k: v[0] for k, v in sorted(R.items())}, 'n': {k: v[1] for k, v in sorted(R.items())}}
    json.dump(doc, open(os.path.join(ROOT, 'nflmodel', 'sim_nhl.json'), 'w'), indent=0)
    print(len(R), 'pair groups from', doc['games'], 'games')
    for k in sorted(R, key=lambda k: -abs(R[k][0])): print(f'  {k:24s} {R[k][0]:+.3f}  n={R[k][1]}')
    F.write_js(os.path.join(ROOT, 'board', 'site', 'sim_tables.js'), nhl=doc)
    if a.backtest:
        B = backtest(V, a.split)
        L = ['# NHL game simulation backtest', '', f'Fit on games before {a.split}, tested on the rest (games with DraftKings lines on ESPN). '
             'Generated by scripts/nhl_sim_fit.py --backtest; no odds credits.', ''] + report(B, f'Random 2–4 leg same-game parlays, games from {a.split} on')
        out = os.path.join(ROOT, 'odds_log', 'backtest', 'nhl_sim_backtest.md'); open(out, 'w').write('\n'.join(L) + '\n'); print('\n'.join(L))


if __name__ == '__main__':
    main()
