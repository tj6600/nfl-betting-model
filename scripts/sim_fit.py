"""Fit the NFL game simulation's correlations from free nflverse data (no odds credits).

For every past regular-season game, each bet type gets its hidden "game outcome" number (nflmodel/sim.py):
  mar  home margin minus the closing spread (nflverse spread_line), turned into a normal score
  tot  total points minus the closing total
  pass / rush / rec / recs  a player's yards or receptions minus what was expected of him going in (his recency-weighted
       average, adjusted for his team's implied points and expected margin), as a normal score within his projection size
  td   anytime TD (rushing or receiving), with his pregame chance from a small logistic model
Then every pair of those numbers in the same game is grouped by bet types, positions and how the two are related
(same player, teammates, opponents) and their correlation is measured: plain correlation of normal scores for two
yards/receptions/margin/total numbers, and a probit fit with each player's own TD chance whenever a TD is involved.
Small groups are shrunk toward 0.

  python scripts/sim_fit.py                       # 2021-2025 -> nflmodel/sim_nfl.json + board/site/sim_tables.js
  python scripts/sim_fit.py --seasons 2021 2022 2023 --out /tmp/x.json   (backtests fit on earlier seasons)
"""
import argparse, json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from nflmodel.sim import ndtri, Phi, bvn_upper

ROOT = os.path.join(os.path.dirname(__file__), '..')
URL = 'https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{y}.csv'
CACHE = os.environ.get('NFL_STATS_DIR', os.path.join(ROOT, 'data'))
HALF = 6.0
COLS = ['player_id', 'player_display_name', 'position', 'season', 'week', 'season_type', 'game_id', 'team', 'opponent_team',
        'attempts', 'passing_yards', 'carries', 'rushing_yards', 'rushing_tds', 'targets', 'receptions', 'receiving_yards', 'receiving_tds']
STATS = {'pass': 'passing_yards', 'rush': 'rushing_yards', 'rec': 'receiving_yards', 'recs': 'receptions'}


def load_players(seasons):
    out = []
    for y in seasons:
        local = os.path.join(CACHE, f'stats_player_week_{y}.csv')
        d = pd.read_csv(local if os.path.exists(local) else URL.format(y=y), usecols=lambda c: c in COLS, low_memory=False)
        out.append(d[d.season_type == 'REG'])
    d = pd.concat(out, ignore_index=True).fillna(0)
    d['position'] = d.position.replace({'FB': 'RB', 'HB': 'RB'})
    d['td'] = ((d.rushing_tds + d.receiving_tds) > 0).astype(float)
    d['touch'] = d.carries + d.targets
    return d.sort_values(['season', 'week']).reset_index(drop=True)


def games(G, seasons):
    g = G[G.season.isin(seasons) & (G.game_type == 'REG') & G.result.notna()].copy()
    return g[['game_id', 'season', 'week', 'home_team', 'away_team', 'result', 'total', 'spread_line', 'total_line']]


def nscore(x, by=None, rng=None):
    """Normal scores (ranks -> inverse normal), ties broken at random, optionally within groups."""
    rng = rng or np.random.default_rng(0)
    x = pd.Series(np.asarray(x, float) + rng.uniform(-1e-6, 1e-6, len(x)), index=by.index if by is not None else None)
    r = x.groupby(by).rank() if by is not None else x.rank()
    n = x.groupby(by).transform('size') if by is not None else len(x)
    return ndtri(np.asarray((r - 0.5) / n, float))


def ols(X, y):
    return np.linalg.lstsq(X, y, rcond=None)[0]


def logit_fit(X, y, it=25):
    b = np.zeros(X.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-X @ b)); W = p * (1 - p) + 1e-9
        b = b + np.linalg.solve(X.T @ (X * W[:, None]) + np.eye(len(b)) * 1e-6, X.T @ (y - p))
    return b


def variables(P, g, coef=None):
    """Long table of hidden numbers: game_id, team, pid, pos, stat, z (normal score; NaN for td), td, c (td threshold).
    coef: expectation/TD models fit on other seasons (backtests); None fits them here. Returns (V, coef)."""
    al = 1 - 0.5 ** (1 / HALF)
    P = P.copy(); grp = P.groupby('player_id')
    for c in ['attempts', 'carries', 'targets', 'touch', 'td'] + list(STATS.values()):
        P[f'h_{c}'] = grp[c].transform(lambda x: x.shift(1).ewm(alpha=al).mean())
    P['n_prior'] = grp.cumcount()
    ctx = pd.concat([pd.DataFrame({'game_id': g.game_id, 'team': g.home_team, 'exp_margin': g.spread_line, 'imp': g.total_line / 2 + g.spread_line / 2, 'home': 1.0}),
                     pd.DataFrame({'game_id': g.game_id, 'team': g.away_team, 'exp_margin': -g.spread_line, 'imp': g.total_line / 2 - g.spread_line / 2, 'home': 0.0})])
    P = P.merge(ctx, on=['game_id', 'team'], how='inner')
    P = P[P.n_prior >= 2]
    qb = (P.position == 'QB') & (P.h_attempts >= 20)
    elig = {'pass': qb,
            'rush': ((P.position == 'RB') & (P.h_carries >= 4)) | (qb & (P.h_carries >= 2.5)),
            'rec': P.position.isin(['RB', 'WR', 'TE']) & (P.h_targets >= 2.5),
            'td': (P.position.isin(['RB', 'WR', 'TE']) & (P.h_touch >= 3)) | (qb & (P.h_carries >= 2.5))}
    elig['recs'] = elig['rec']
    coef = {} if coef is None else coef; fit = not coef
    rows = []
    for st, m in elig.items():
        d = P[m].copy()
        for pos, dp in d.groupby('position'):
            k = f'{st}:{pos}'
            if st == 'td':
                X = np.c_[np.ones(len(dp)), np.log(np.clip(dp.h_td, 0.01, 0.9) / (1 - np.clip(dp.h_td, 0.01, 0.9))), np.log1p(dp.h_touch), (dp.imp - 22) / 10]
                if fit: coef[k] = logit_fit(X, dp.td.values).tolist()
                if k not in coef: continue
                p = np.clip(1 / (1 + np.exp(-X @ np.array(coef[k]))), 0.01, 0.95)
                rows.append(pd.DataFrame({'game_id': dp.game_id.values, 'team': dp.team.values, 'pid': dp.player_id.values, 'pos': pos, 'stat': st,
                                          'z': np.nan, 'td': dp.td.values, 'c': ndtri(1 - p), 'p': p}))
            else:
                h = dp[f'h_{STATS[st]}'].values
                X = np.c_[np.ones(len(dp)), h, h * (dp.imp - 22) / 10, h * dp.exp_margin / 10]
                if fit: coef[k] = ols(X, dp[STATS[st]].values).tolist()
                if k not in coef: continue
                pred = X @ np.array(coef[k])
                res = dp[STATS[st]].values - pred
                dec = pd.Series(pd.qcut(pred, 8, labels=False, duplicates='drop'), index=dp.index)
                rows.append(pd.DataFrame({'game_id': dp.game_id.values, 'team': dp.team.values, 'pid': dp.player_id.values, 'pos': pos, 'stat': st,
                                          'z': nscore(res, dec), 'td': np.nan, 'c': np.nan, 'p': np.nan}))
    V = pd.concat(rows, ignore_index=True)
    gm = pd.DataFrame({'game_id': g.game_id, 'team': g.home_team, 'pid': 'GAME', 'pos': '', 'stat': 'mar',
                       'z': nscore(g.result.values - g.spread_line.values), 'td': np.nan, 'c': np.nan, 'p': np.nan})
    gt = gm.assign(stat='tot', z=nscore(g.total.values - g.total_line.values))
    V = pd.concat([V, gm, gt], ignore_index=True).merge(g[['game_id', 'home_team', 'spread_line']], on='game_id')
    V['home'] = V.team == V.home_team
    return V, coef


def tok(stat, pos): return f'{stat}:{pos}'


def pairs(V):
    """Every pair of hidden numbers in the same game, with its group key and both values oriented for that key."""
    pl = V[~V.stat.isin(['mar', 'tot'])].reset_index(drop=True); pl['i'] = np.arange(len(pl))
    A = pl.merge(pl, on='game_id', suffixes=('_a', '_b'))
    A = A[A.i_a < A.i_b]
    ta = A.stat_a + ':' + A.pos_a; tb = A.stat_b + ':' + A.pos_b
    rel = np.where(A.pid_a == A.pid_b, 'self', np.where(A.team_a == A.team_b, 'tm', 'opp'))
    sw = ta > tb
    A['key'] = np.where(sw, tb, ta) + '|' + np.where(sw, ta, tb) + '|' + rel
    for c in ['z', 'td', 'c']:
        a, b = A[f'{c}_a'].values, A[f'{c}_b'].values
        A[f'{c}1'] = np.where(sw, b, a); A[f'{c}2'] = np.where(sw, a, b)
    out = [A[['key', 'z1', 'td1', 'c1', 'z2', 'td2', 'c2']]]
    gv = V[V.stat.isin(['mar', 'tot'])].pivot(index='game_id', columns='stat', values='z')
    pg = pl.join(gv, on='game_id')
    sign = np.where(pg.home, 1.0, -1.0)   # margin from the player's team's side
    t = pg.stat + ':' + pg.pos
    out.append(pd.DataFrame({'key': t + '|mar|tm', 'z1': pg.z, 'td1': pg.td, 'c1': pg.c, 'z2': pg.mar * sign, 'td2': np.nan, 'c2': np.nan}))
    out.append(pd.DataFrame({'key': t + '|tot|g', 'z1': pg.z, 'td1': pg.td, 'c1': pg.c, 'z2': pg.tot, 'td2': np.nan, 'c2': np.nan}))
    gg = V[V.stat == 'mar'].drop_duplicates('game_id').set_index('game_id')
    fav = np.where(gg.spread_line >= 0, 1.0, -1.0)   # margin from the favorite's side
    out.append(pd.DataFrame({'key': 'mar:fav|tot|g', 'z1': gv.loc[gg.index, 'mar'].values * fav, 'td1': np.nan, 'c1': np.nan,
                             'z2': gv.loc[gg.index, 'tot'].values, 'td2': np.nan, 'c2': np.nan}))
    return pd.concat(out, ignore_index=True)


GRID = np.round(np.arange(-0.6, 0.951, 0.025), 3)


def rho_cont_td(z, td, c):
    s = np.sqrt(1 - GRID ** 2)[:, None]
    p = 1 - Phi((c[None, :] - GRID[:, None] * z[None, :]) / s)
    p = np.clip(p, 1e-9, 1 - 1e-9)
    ll = (td * np.log(p) + (1 - td) * np.log(1 - p)).sum(1)
    return GRID[ll.argmax()]


def rho_td_td(t1, c1, t2, c2):
    p1, p2 = 1 - Phi(c1), 1 - Phi(c2); best = (-np.inf, 0.0)
    for r in GRID:
        p11 = np.clip(bvn_upper(c1, c2, r), 1e-9, None)
        p10 = np.clip(p1 - p11, 1e-9, None); p01 = np.clip(p2 - p11, 1e-9, None); p00 = np.clip(1 - p1 - p2 + p11, 1e-9, None)
        ll = (t1 * t2 * np.log(p11) + t1 * (1 - t2) * np.log(p10) + (1 - t1) * t2 * np.log(p01) + (1 - t1) * (1 - t2) * np.log(p00)).sum()
        if ll > best[0]: best = (ll, r)
    return best[1]


def fit_rho(A, min_n=60, max_td=60000, rng=None):
    rng = rng or np.random.default_rng(1)
    out = {}
    for key, d in A.groupby('key'):
        n = len(d)
        if n < min_n: continue
        has1, has2 = d.td1.notna().all(), d.td2.notna().all()
        if not has1 and not has2:
            r = float(np.corrcoef(d.z1, d.z2)[0, 1]); r *= n / (n + 30)
        else:
            if n > max_td: d = d.iloc[rng.choice(n, max_td, replace=False)]
            if has1 and has2: r = rho_td_td(d.td1.values, d.c1.values, d.td2.values, d.c2.values)
            elif has1: r = rho_cont_td(d.z2.values, d.td1.values, d.c1.values)
            else: r = rho_cont_td(d.z1.values, d.td2.values, d.c2.values)
            r = float(r) * n / (n + 250)
        out[key] = (round(float(np.clip(r, -0.9, 0.95)), 3), n)
    return out


def fit(seasons, G=None):
    if G is None:
        from nflmodel.model import G
    P = load_players(range(min(seasons) - 1, max(seasons) + 1))   # one earlier season to warm up the averages
    g = games(G, seasons)
    V, coef = variables(P, g)
    return fit_rho(pairs(V)), coef, V


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', nargs='+', type=int, default=[2021, 2022, 2023, 2024, 2025])
    ap.add_argument('--out', default=os.path.join(ROOT, 'nflmodel', 'sim_nfl.json'))
    ap.add_argument('--js', default=os.path.join(ROOT, 'board', 'site', 'sim_tables.js'))
    a = ap.parse_args()
    R, coef, V = fit(a.seasons)
    doc = {'seasons': a.seasons, 'games': int(V.game_id.nunique()), 'rho': {k: v[0] for k, v in sorted(R.items())},
           'n': {k: v[1] for k, v in sorted(R.items())}, 'coef': coef}
    json.dump(doc, open(a.out, 'w'), indent=0)
    print(len(R), 'pair groups from', doc['games'], 'games ->', a.out)
    for k in sorted(R, key=lambda k: -abs(R[k][0]))[:40]: print(f'  {k:28s} {R[k][0]:+.3f}  n={R[k][1]}')
    if a.js: write_js(a.js, nfl=doc)


def write_js(path, **sports):
    """board/site/sim_tables.js: window.SIM_TABLES[sport] = {rho}, read by board/site/sim.js. Keeps other sports' tables."""
    cur = {}
    if os.path.exists(path):
        s = open(path).read(); i = s.find('{')
        if i >= 0: cur = json.loads(s[i:s.rfind('}') + 1])
    for k, v in sports.items(): cur[k] = {'rho': v['rho'], 'seasons': v['seasons'], 'games': v['games']}
    open(path, 'w').write('// Generated by scripts/sim_fit.py and scripts/nhl_sim_fit.py: correlations for the game simulation (sim.js)\n'
                          'window.SIM_TABLES = ' + json.dumps(cur, separators=(',', ':')) + ';\n')
    print('wrote', path)


if __name__ == '__main__':
    main()
