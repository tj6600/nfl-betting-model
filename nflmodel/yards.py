"""Rushing and receiving yards model for player over/under props.

Expected yards come from a ridge regression on the player's recent (recency-weighted) yards and
usage, his recent role, his team's implied points and expected margin (teams that lead run more),
and the opponent's yards allowed to his position. The chance of going over a line comes from the
spread of past outcomes around the prediction: actual / expected ratios from training games,
grouped by how many yards were expected (low projections are much more volatile).
"""
import numpy as np, pandas as pd
from .model import G
from . import touchdowns as T

STATS = {
    'rush': dict(y='rush_yds', vol='h_carries', min_vol=2.0, pos=['RB', 'WR']),   # QB runs (scrambles, sneaks) need their own model
    'rec': dict(y='rec_yds', vol='h_targets', min_vol=1.5, pos=['WR', 'TE', 'RB']),
}
DEF_HALF = 8.0


def team_margin(g):
    """Expected margin for each team from the spread (nflverse spread_line = home margin)."""
    return pd.concat([pd.DataFrame({'game_id': g.game_id, 'posteam': g.home_team, 'exp_margin': g.spread_line}),
                      pd.DataFrame({'game_id': g.game_id, 'posteam': g.away_team, 'exp_margin': -g.spread_line})])


def defense_yards(pg, col):
    """Opponent yards allowed per game to each position, recency-weighted, vs the league average."""
    pg = T._with_def(pg)
    games = pg[['game_id', 'defteam', 'gameday']].drop_duplicates()
    full = games.assign(k=1).merge(pd.DataFrame({'position': T.POS, 'k': 1}), on='k').drop(columns='k')
    a = pg.groupby(['game_id', 'defteam', 'position'])[col].sum().reset_index()
    d = full.merge(a, on=['game_id', 'defteam', 'position'], how='left').fillna({col: 0}).sort_values('gameday')
    al = 1 - 0.5 ** (1 / DEF_HALF)
    grp = d.groupby(['defteam', 'position'])[col]
    d['prior'] = grp.transform(lambda x: x.shift(1).ewm(alpha=al).mean())
    d['now'] = grp.transform(lambda x: x.ewm(alpha=al).mean())
    mean = d.groupby('position')[col].mean()
    d['prior'] -= d.position.map(mean); d['now'] -= d.position.map(mean)
    return d


def design(df, kind):
    c = STATS[kind]; h = 'h_' + c['y']
    X = pd.DataFrame({
        'h_yds': df[h], 'vol': df[c['vol']], 'opp_share': df.h_opp_share, 'last_share': df.last_share.fillna(df.h_opp_share),
        'room': df.room_share, 'pts': (df.imp_pts - 22) / 5, 'margin': df.exp_margin / 7, 'def': df.def_yds / 10,
        'missed': df.missed_last, 'few': (df.h_games < 4).astype(float),
    })
    X['yds_x_pts'] = X.h_yds * X.pts
    X['yds_x_margin'] = X.h_yds * X.margin
    X['yds_x_room'] = X.h_yds * X.room
    for p in ['QB', 'WR', 'TE']:
        X['pos_' + p] = (df.position == p).astype(float)
    return X.fillna(0.0)


def ridge(X, y, lam=5.0):
    X1 = np.column_stack([X.values, np.ones(len(X))]); P = np.eye(X1.shape[1]) * lam; P[-1, -1] = 0
    return np.linalg.solve(X1.T @ X1 + P, X1.T @ y)


def apply(b, X):
    return np.clip(np.column_stack([X.values, np.ones(len(X))]) @ b, 1.0, None)


def frame(kind, df=None):
    """Training rows for one stat: player-games of regulars at the usual positions, with defense and margin."""
    c = STATS[kind]
    df = T.training_frame() if df is None else df
    df = df.merge(team_margin(G), on=['game_id', 'posteam'], how='left')
    d = defense_yards(T.history(), c['y'])
    df = df.merge(d[['game_id', 'defteam', 'position', 'prior']].rename(columns={'prior': 'def_yds'}),
                  on=['game_id', 'defteam', 'position'], how='left')
    return df[df.position.isin(c['pos']) & (df[c['vol']] >= c['min_vol'])]


class Spread:
    """Empirical distribution of actual/expected, by bucket of expected yards."""
    EDGES = [0, 15, 30, 45, 60, 80, 1e9]

    def __init__(self, mu, y):
        b = np.digitize(mu, self.EDGES) - 1
        self.r = {i: np.sort(y[b == i] / mu[b == i]) for i in range(len(self.EDGES) - 1) if (b == i).sum() >= 50}

    def _r(self, bi):
        return self.r[bi] if bi in self.r else self.r[min(self.r, key=lambda k: abs(k - bi))]

    def p_over(self, mu, line):
        mu = np.asarray(mu, float); line = np.asarray(line, float); out = np.empty(len(mu))
        b = np.digitize(mu, self.EDGES) - 1
        for i, (m, l, bi) in enumerate(zip(mu, line, b)):
            r = self._r(bi)
            out[i] = 1 - np.searchsorted(r, l / m, side='right') / len(r)
        return out

    def quantile(self, mu, q):
        mu = np.asarray(mu, float); b = np.digitize(mu, self.EDGES) - 1
        return np.array([m * np.quantile(self._r(bi), q) for m, bi in zip(mu, b)])


def fit(kind, tr):
    y = tr[STATS[kind]['y']].values
    X = design(tr, kind); b = ridge(X, y)
    return b, Spread(apply(b, X), y)
