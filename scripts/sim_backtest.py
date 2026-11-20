"""Backtest the NFL game simulation's same-game parlay chances (free nflverse data, no odds credits).

Test 1, past games: correlations fit on 2021-2023, tested on every 2024-2025 regular-season game. In each game, random
same-game parlays of 2-4 legs are drawn from the bets that game had: spread and total (closing lines), each regular
player's passing, rushing, receiving yards and receptions over or under a line near his projection (main and alt-style
lines), and anytime TDs. Every leg's own chance is right on average by construction, so the test is only about how the
legs move together: the chance from multiplying the legs (what the builders did) vs the simulation, against how often
those parlays actually hit.

Test 2, real DraftKings lines: the 2025 week 7 and 12 DraftKings player props saved in the project files (no-vig chance
per side) plus closing spreads and totals, correlations fit on 2021-2024, every 2- and 3-leg same-game combo.

  python scripts/sim_backtest.py [--hist /mnt/project-files/nfl-model/hist-dk-props/hist_graded.csv]
"""
import argparse, itertools, json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from nflmodel.sim import ndtri, Phi, joint
import sim_fit as F

ROOT = os.path.join(os.path.dirname(__file__), '..')
OUT = os.path.join(ROOT, 'odds_log', 'backtest', 'sim_backtest.md')


def rho_of(a, b, R):
    """Correlation of two legs' hidden numbers (before Over/Under direction). a, b: dicts stat, pos, pid, team, home, fav."""
    if a['stat'] in ('mar', 'tot') and b['stat'] not in ('mar', 'tot'): a, b = b, a
    if a['stat'] in ('mar', 'tot'):   # game vs game
        if a['stat'] == b['stat']: return 1.0
        m = a if a['stat'] == 'mar' else b
        return R.get('mar:fav|tot|g', 0.0) * (1 if m['fav'] else -1)
    if b['stat'] == 'mar':   # player vs the home margin: the table is from his own team's side
        return R.get(f"{a['stat']}:{a['pos']}|mar|tm", 0.0) * (1 if a['home'] else -1)
    if b['stat'] == 'tot': return R.get(f"{a['stat']}:{a['pos']}|tot|g", 0.0)
    if a['pid'] == b['pid'] and a['stat'] == b['stat']: return 1.0
    ta, tb = f"{a['stat']}:{a['pos']}", f"{b['stat']}:{b['pos']}"
    rel = 'self' if a['pid'] == b['pid'] else 'tm' if a['team'] == b['team'] else 'opp'
    return R.get('|'.join(sorted([ta, tb])) + '|' + rel, 0.0)


def sim_p(legs, R):
    k = len(legs); C = np.eye(k)
    for i, j in itertools.combinations(range(k), 2): C[i, j] = C[j, i] = rho_of(legs[i], legs[j], R)
    return joint([l['p'] for l in legs], [l['dir'] for l in legs], C)


def report(df, title):
    """Calibration table: predicted (multiplied / simulated) vs actual, by predicted chance and by leg count."""
    L = [f'### {title}', '', f'{len(df):,} parlays.', '']
    def ll(p, y): p = np.clip(p, 1e-4, 1 - 1e-4); return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())
    L += ['| | Multiplied (old) | Simulated |', '|---|---|---|',
          f"| Average chance vs actual {df.hit.mean():.1%} | {df.p_ind.mean():.1%} | {df.p_sim.mean():.1%} |",
          f"| Brier score (lower is better) | {((df.p_ind - df.hit) ** 2).mean():.4f} | {((df.p_sim - df.hit) ** 2).mean():.4f} |",
          f"| Log loss (lower is better) | {ll(df.p_ind, df.hit):.4f} | {ll(df.p_sim, df.hit):.4f} |", '']
    L += ['By leg count:', '', '| Legs | Parlays | Actual | Multiplied | Simulated |', '|---|---|---|---|---|']
    for k, d in df.groupby('k'): L.append(f'| {k} | {len(d):,} | {d.hit.mean():.1%} | {d.p_ind.mean():.1%} | {d.p_sim.mean():.1%} |')
    L += ['', 'Where the two disagree most (simulated chance at least 1.3x or under 0.77x the multiplied one):', '',
          '| Group | Parlays | Actual | Multiplied | Simulated |', '|---|---|---|---|---|']
    r = df.p_sim / df.p_ind
    for name, m in [('Simulation says likelier (positively linked legs)', r >= 1.3), ('Simulation says less likely (legs work against each other)', r <= 1 / 1.3), ('About the same', (r > 1 / 1.3) & (r < 1.3))]:
        d = df[m]
        if len(d): L.append(f'| {name} | {len(d):,} | {d.hit.mean():.1%} | {d.p_ind.mean():.1%} | {d.p_sim.mean():.1%} |')
    L += ['', 'Calibration by simulated chance:', '', '| Simulated chance | Parlays | Actual | Simulated | Multiplied |', '|---|---|---|---|---|']
    for lo, hi in [(0, .05), (.05, .1), (.1, .15), (.15, .2), (.2, .3), (.3, .4), (.4, .5), (.5, .65), (.65, 1.01)]:
        d = df[(df.p_sim >= lo) & (df.p_sim < hi)]
        if len(d) >= 30: L.append(f'| {lo:.0%}–{min(hi, 1):.0%} | {len(d):,} | {d.hit.mean():.1%} | {d.p_sim.mean():.1%} | {d.p_ind.mean():.1%} |')
    return L + ['']


def test_past(G, per_game=60, seed=3):
    R, coef, _ = F.fit([2021, 2022, 2023], G)
    R = {k: v[0] for k, v in R.items()}
    P = F.load_players(range(2023, 2026)); g = F.games(G, [2024, 2025])
    V, _ = F.variables(P, g, coef)
    rng = np.random.default_rng(seed); rows = []
    for gid, d in V.groupby('game_id'):
        fav_home = d.spread_line.iloc[0] >= 0; home = d.home_team.iloc[0]
        cand = d.to_dict('records')
        for _ in range(per_game):
            k = int(rng.choice([2, 2, 3, 3, 4]))
            idx = rng.choice(len(cand), k, replace=False); legs = []; seen = set()
            for i in idx:
                v = cand[i]; key = (v['pid'], v['stat'])
                if key in seen: break
                seen.add(key)
                L = dict(stat=v['stat'], pos=v['pos'], pid=v['pid'], team=v['team'], home=v['team'] == home)
                if v['stat'] == 'td':
                    L.update(p=v['p'], dir=1, hit=v['td'] == 1)
                elif v['stat'] in ('mar', 'tot'):
                    s = rng.choice([1, -1]); L.update(p=0.5, dir=s, hit=v['z'] * s > 0, fav=fav_home)   # mar: home side +1
                else:
                    t = float(rng.choice([-0.8, -0.4, 0.0, 0.0, 0.4])); s = int(rng.choice([1, -1]))
                    if s < 0: t = -t
                    p = float(1 - Phi(t)) if s > 0 else float(Phi(t))
                    L.update(p=p, dir=s, hit=(v['z'] > t) if s > 0 else (v['z'] < t))
                legs.append(L)
            if len(legs) < k: continue
            rows.append(dict(k=k, hit=float(all(l['hit'] for l in legs)), p_ind=float(np.prod([l['p'] for l in legs])), p_sim=sim_p(legs, R)))
    return pd.DataFrame(rows)


def test_dk(G, hist):
    R, _, _ = F.fit([2021, 2022, 2023, 2024], G)
    R = {k: v[0] for k, v in R.items()}
    H = pd.read_csv(hist)
    P = F.load_players([2025]); P = P[P.week.isin(H.week.unique())]
    P['k'] = P.player_display_name.str.lower().str.replace(r'[^a-z]', '', regex=True).str.replace(r'(jr|sr|ii|iii|iv)$', '', regex=True)
    H['k2'] = H.player.str.lower().str.replace(r'[^a-z]', '', regex=True).str.replace(r'(jr|sr|ii|iii|iv)$', '', regex=True)
    H = H.merge(P[['week', 'k', 'player_id', 'position', 'team', 'game_id']], left_on=['week', 'k2'], right_on=['week', 'k'], how='inner')
    H = H[H.over_hit.notna() & (H.act != H.point)]
    g = G[(G.season == 2025) & G.week.isin(H.week.unique()) & G.result.notna()].set_index('game_id')
    rows = []
    for gid, d in H.groupby('game_id'):
        if gid not in g.index: continue
        gg = g.loc[gid]; home = gg.home_team; fav = gg.spread_line >= 0
        legs = []
        for r in d.itertuples():
            pos = r.position if r.position in ('QB', 'RB', 'WR', 'TE') else 'WR'
            for s in (1, -1):
                legs.append(dict(stat=r.kind, pos=pos, pid=r.player_id, team=r.team, home=r.team == home, dir=s,
                                 p=float(r.nv_over if s > 0 else 1 - r.nv_over), hit=bool(r.over_hit) if s > 0 else not bool(r.over_hit)))
        mr, tr = gg.result - gg.spread_line, gg.total - gg.total_line
        for s in (1, -1):
            if mr != 0: legs.append(dict(stat='mar', pid='GAME', team=home, home=True, fav=fav, dir=s, p=0.5, hit=mr * s > 0))
            if tr != 0: legs.append(dict(stat='tot', pid='GAME', team=home, home=True, fav=fav, dir=s, p=0.5, hit=tr * s > 0))
        for k in (2, 3):
            combos = [c for c in itertools.combinations(range(len(legs)), k) if len({(legs[i]['pid'], legs[i]['stat']) for i in c}) == k]
            rng = np.random.default_rng(k)
            if len(combos) > 400: combos = [combos[i] for i in rng.choice(len(combos), 400, replace=False)]
            for c in combos:
                ls = [legs[i] for i in c]
                rows.append(dict(k=k, hit=float(all(l['hit'] for l in ls)), p_ind=float(np.prod([l['p'] for l in ls])), p_sim=sim_p(ls, R)))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hist', default='/mnt/project-files/nfl-model/hist-dk-props/hist_graded.csv')
    a = ap.parse_args()
    from nflmodel.model import G
    L = ['# NFL game simulation backtest', '', 'Same-game parlay chances: legs multiplied as if independent (the old builder math) vs the game simulation. '
         'Generated by scripts/sim_backtest.py from free nflverse data; no odds credits.', '']
    A = test_past(G); L += report(A, 'Test 1: every 2024–2025 game, random 2–4 leg same-game parlays (fit on 2021–2023)')
    if os.path.exists(a.hist):
        B = test_dk(G, a.hist); L += report(B, 'Test 2: real DraftKings props, 2025 weeks 7 and 12 (no-vig chances, fit on 2021–2024)')
    open(OUT, 'w').write('\n'.join(L) + '\n'); print('\n'.join(L)); print('wrote', OUT)


if __name__ == '__main__':
    main()
