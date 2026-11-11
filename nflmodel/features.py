"""Pre-game features built only from games played before the target week."""
import numpy as np, pandas as pd
from .model import G, TEAMS, TI, N, fit as fit_points, predict as predict_points
from .pbp import cached
from .roster import cached as roster_cached, GROUPS

TG, QB = cached()
GD = G[['game_id', 'gameday', 'home_team', 'away_team', 'location']]
TG = TG.merge(GD, on='game_id')
TG['is_home'] = np.where(TG.location != 'Home', 0.0, np.where(TG.posteam == TG.home_team, 1.0, -1.0))
QB = QB.merge(GD[['game_id', 'gameday']], on='game_id')

QB_PRIOR, QB_K = -0.10, 120.0   # unknown QB ~ replacement level, shrink with 120 dropbacks of prior


def _weights(dates, season, asof, half_life):
    age = (asof - dates).dt.days.values
    cur = asof.year if asof.month >= 6 else asof.year - 1
    return 0.5 ** (age / half_life) * np.where(season.values < cur, 0.6, 1.0)


def epa_ratings(asof, half_life=150, alpha=30.0):
    """Opponent-adjusted offense and defense ratings for pass EPA, rush EPA and success rate."""
    tr = TG[TG.gameday < asof]
    w = _weights(tr.gameday, tr.season, asof, half_life) * tr.plays.values / 60
    o = tr.posteam.map(TI).values; dd = tr.defteam.map(TI).values; n = len(tr)
    X = np.zeros((n, 2 * N + 2)); r = np.arange(n)
    X[r, o] = 1; X[r, N + dd] = 1; X[:, 2 * N] = tr.is_home.values; X[:, 2 * N + 1] = 1
    P = np.eye(2 * N + 2) * alpha; P[-2:, -2:] = 0
    out = {}
    for col in ['pass_epa', 'rush_epa', 'succ']:
        y = tr[col].fillna(tr[col].mean()).values
        b = np.linalg.solve(X.T @ (X * w[:, None]) + P, X.T @ (w * y))
        out[col] = (b[:N], b[N:2 * N])   # offense produced, defense allowed
    return out


def qb_values(asof, half_life=365):
    q = QB[QB.gameday < asof]
    w = 0.5 ** ((asof - q.gameday).dt.days.values / half_life) * q.n.values
    s = pd.DataFrame({'id': q.id, 'wx': w * q.qb_epa.values, 'w': w}).groupby('id').sum()
    return ((s.wx + QB_K * QB_PRIOR) / (s.w + QB_K)).to_dict()


def team_recent_qb(asof, lookback=4):
    """Dropback-weighted QB value the team has used in its recent games (already priced into ratings)."""
    q = QB[QB.gameday < asof].sort_values('gameday')
    return q, lookback


def build(target):
    """Features for every game in `target` (a slice of G within one week)."""
    asof = target.gameday.min()
    ep = epa_ratings(asof)
    qv = qb_values(asof)
    q = QB[QB.gameday < asof]
    pts = predict_points(fit_points(G[G.gameday < asof], asof, half_life=150, alpha=8.0), target)
    rows = []
    for _, g in pts.iterrows():
        h, a = TI[g.home_team], TI[g.away_team]
        f = {'game_id': g.game_id, 'pts_margin': g.pred_margin, 'pts_total': g.pred_total}
        for col, (off, de) in ep.items():
            net_h, net_a = off[h] + de[a], off[a] + de[h]
            f[f'd_{col}'] = net_h - net_a; f[f's_{col}'] = net_h + net_a
        # QB change: starter today vs the QBs who took the team's dropbacks in its last 4 games
        adj = {}
        for side, team, qid in [('h', g.home_team, g.home_qb_id), ('a', g.away_team, g.away_qb_id)]:
            recent = q[q.posteam == team]
            recent = recent[recent.game_id.isin(recent.drop_duplicates('game_id').tail(4).game_id)]
            base = np.average([qv.get(i, QB_PRIOR) for i in recent.id], weights=recent.n) if len(recent) else QB_PRIOR
            adj[side] = qv.get(qid, QB_PRIOR) - base
        f['d_qb'] = adj['h'] - adj['a']; f['s_qb'] = adj['h'] + adj['a']
        f['home'] = 1.0 if g.location == 'Home' else 0.0
        f['rest'] = (g.home_rest - g.away_rest) if pd.notna(g.home_rest) else 0.0
        f['dome'] = 1.0 if g.roof in ('dome', 'closed') else 0.0
        f['wind'] = g.wind if pd.notna(g.wind) else 0.0
        rows.append(f)
    return pd.DataFrame(rows)


def add_roster(feat):
    """Home-minus-away and home-plus-away roster availability and coaching features."""
    r = roster_cached()
    g = G[['game_id', 'home_team', 'away_team']]
    cols = [f'net_{grp}' for grp in GROUPS] + ['new_hc', 'interim_hc']
    h = g.merge(r, left_on=['game_id', 'home_team'], right_on=['game_id', 'team'])[['game_id'] + cols]
    a = g.merge(r, left_on=['game_id', 'away_team'], right_on=['game_id', 'team'])[['game_id'] + cols]
    m = h.merge(a, on='game_id', suffixes=('_h', '_a'))
    out = pd.DataFrame({'game_id': m.game_id})
    for c in cols:
        out[f'd_{c}'] = m[f'{c}_h'] - m[f'{c}_a']
        out[f's_{c}'] = m[f'{c}_h'] + m[f'{c}_a']
    return feat.merge(out, on='game_id', how='left').fillna({f'{p}_{c}': 0.0 for p in 'ds' for c in cols})


def all_features(seasons):
    out = []
    for s in seasons:
        for wk in sorted(G[G.season == s].week.unique()):
            t = G[(G.season == s) & (G.week == wk)]
            if len(t): out.append(build(t))
    return add_roster(pd.concat(out, ignore_index=True))
