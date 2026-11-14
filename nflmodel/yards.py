"""Rushing and receiving yards model for player over/under props.

Expected yards come from a ridge regression on the player's recent (recency-weighted) yards and
usage, his recent role, his team's implied points and expected margin (teams that lead run more),
the opponent's yards allowed to his position, his offensive snap share (nflverse snap counts: recency-weighted and
his latest game, which catches role changes before targets do) and his share of the team's skill-player usage
among teammates who play (so a teammate ruled out at any position frees up looks). The chance of going over a line comes from the
spread of past outcomes around the prediction: actual / expected ratios from training games,
grouped by how many yards were expected (low projections are much more volatile).
"""
import numpy as np, pandas as pd
from .model import G
from . import touchdowns as T

STATS = {
    'rush': dict(y='rush_yds', vol='h_carries', min_vol=2.0, pos=['RB', 'WR']),   # QB runs (scrambles, sneaks) need their own model
    'rec': dict(y='rec_yds', vol='h_targets', min_vol=1.5, pos=['WR', 'TE', 'RB']),
    # receptions (catches): same features on the catch count; spread buckets are in catches, not yards
    'recs': dict(y='receptions', vol='h_targets', min_vol=1.5, pos=['WR', 'TE', 'RB'], edges=[0, 2, 3, 4, 5, 6, 1e9]),
}
DEF_HALF = 8.0
SNAP_HALF = 4.0     # player games
SNAP_POS = ['WR', 'TE', 'RB', 'FB']


def _nkey(s):
    return s.str.lower().str.replace(r'[^a-z]', '', regex=True)


def snap_table(seasons=range(2021, 2027)):
    """Offensive snap share per player-game: h_snap / last_snap going into the game, now_snap / now_last after it."""
    from .roster import _load
    S = pd.concat([_load('snaps', y) for y in seasons], ignore_index=True)
    S = S[S.position.isin(SNAP_POS)].merge(G[['game_id', 'gameday']], on='game_id')
    S['k'] = _nkey(S.player); S = S.sort_values(['k', 'position', 'gameday'])
    al = 1 - 0.5 ** (1 / SNAP_HALF); g = S.groupby(['k', 'position']).offense_pct
    S['h_snap'] = g.transform(lambda x: x.shift(1).ewm(alpha=al).mean())
    S['last_snap'] = g.shift(1)
    S['now_snap'] = g.transform(lambda x: x.ewm(alpha=al).mean())
    S['now_last'] = S.offense_pct
    return S


def add_snaps(df, S=None, current=False):
    """Snap features for training rows (by game) or, with current=True, for this week's players (latest game)."""
    S = snap_table() if S is None else S
    df = df.copy(); df['k'] = _nkey(df.full_name)
    if current:
        last = S.groupby(['k', 'position']).tail(1)[['k', 'position', 'now_snap', 'now_last']]
        last = last.rename(columns={'now_snap': 'h_snap', 'now_last': 'last_snap'})
        df = df.drop(columns=['h_snap', 'last_snap'], errors='ignore').merge(last, on=['k', 'position'], how='left')
    else:
        df = df.merge(S[['game_id', 'k', 'h_snap', 'last_snap']].drop_duplicates(['game_id', 'k']), on=['game_id', 'k'], how='left')
    return df.drop(columns='k')


def add_room_team(df, by):
    """His share of the usage of the team's skill players in the frame (those who play / are active this week)."""
    df = df.copy()
    df['room_team'] = df.h_opp_share / df.groupby(by).h_opp_share.transform('sum').clip(lower=1e-6)
    return df


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
    # snap share (falls back to a usage-based guess when the snap counts have no row for him)
    guess = (df.h_opp_share * 3).clip(0, 1)
    hs = (df['h_snap'] if 'h_snap' in df else guess).fillna(guess).clip(0, 1)
    ls = (df['last_snap'] if 'last_snap' in df else hs).fillna(hs)
    X['snap'] = hs.values; X['snap_last'] = (ls - hs).values
    rt = (df['room_team'] if 'room_team' in df else df.room_share * 0.3).fillna(0.0)
    X['room_team'] = rt.values; X['yds_x_roomteam'] = X.h_yds * X.room_team
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
    if 'h_snap' not in df:
        df = add_snaps(df)
    if 'room_team' not in df:
        df = add_room_team(df, ['game_id', 'posteam'])
    df = df.merge(team_margin(G), on=['game_id', 'posteam'], how='left')
    d = defense_yards(T.history(), c['y'])
    df = df.merge(d[['game_id', 'defteam', 'position', 'prior']].rename(columns={'prior': 'def_yds'}),
                  on=['game_id', 'defteam', 'position'], how='left')
    return df[df.position.isin(c['pos']) & (df[c['vol']] >= c['min_vol'])]


class Spread:
    """Empirical distribution of actual/expected, by bucket of expected yards."""
    EDGES = [0, 15, 30, 45, 60, 80, 1e9]

    def __init__(self, mu, y, edges=None):
        if edges is not None:
            self.EDGES = edges
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
    return b, Spread(apply(b, X), y, STATS[kind].get('edges'))
