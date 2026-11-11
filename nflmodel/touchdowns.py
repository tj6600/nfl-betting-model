"""Anytime-touchdown model: the chance each RB/WR/TE/QB scores a rushing or receiving TD.

For every player-game it uses only earlier games (recency-weighted, half-life of HALF player games):
  - share of the team's red-zone (inside the 20) and goal-line (inside the 10) carries and targets
  - carries and targets per game, and rushing/receiving TDs per game
  - the team's implied points from the betting line (total/2 +/- spread/2), so a player on a team
    expected to score 30 gets more chances than the same player on a team expected to score 17
  - position (QB, RB, WR, TE)
A logistic regression turns these into P(scores at least one TD).
"""
import os
import numpy as np, pandas as pd
from .model import G

PBP_DIR = os.environ.get('NFL_PBP_DIR', '/home/user/pbp')
EXTRA = os.environ.get('NFL_EXTRA_DIR', os.path.join(PBP_DIR, 'extra'))
CACHE = os.path.join(os.path.dirname(__file__), '..', 'data', 'td_player_games.csv')
HALF = 6.0
POS = ['QB', 'RB', 'WR', 'TE']
COLS = ['game_id', 'season', 'week', 'season_type', 'posteam', 'defteam', 'yardline_100', 'play_type',
        'rusher_player_id', 'receiver_player_id', 'td_player_id', 'td_team', 'rush_touchdown', 'pass_touchdown',
        'two_point_attempt', 'rush_attempt', 'pass_attempt']


def _player_games(seasons):
    out = []
    for y in seasons:
        p = pd.read_csv(os.path.join(PBP_DIR, f'pbp_{y}.csv.gz'), usecols=lambda c: c in COLS, low_memory=False)
        p = p[(p.season_type == 'REG') & (p.two_point_attempt != 1) & p.posteam.notna()]
        ru = p[p.rush_attempt == 1].assign(pid=lambda d: d.rusher_player_id, kind='rush')
        rc = p[(p.pass_attempt == 1) & p.receiver_player_id.notna()].assign(pid=lambda d: d.receiver_player_id, kind='tgt')
        opp = pd.concat([ru, rc])
        opp = opp[opp.pid.notna()]
        opp['rz'] = (opp.yardline_100 <= 20).astype(int)
        opp['gl'] = (opp.yardline_100 <= 10).astype(int)
        opp['td'] = ((opp.td_player_id == opp.pid) & (opp.td_team == opp.posteam)
                     & ((opp.rush_touchdown == 1) | (opp.pass_touchdown == 1))).astype(int)
        opp['carry'] = (opp.kind == 'rush').astype(int); opp['target'] = (opp.kind == 'tgt').astype(int)
        pg = opp.groupby(['game_id', 'season', 'week', 'posteam', 'pid']).agg(
            carries=('carry', 'sum'), targets=('target', 'sum'), rz=('rz', 'sum'), gl=('gl', 'sum'), tds=('td', 'sum')).reset_index()
        team = opp.groupby(['game_id', 'posteam']).agg(team_rz=('rz', 'sum'), team_gl=('gl', 'sum'),
                                                       team_opps=('rz', 'size')).reset_index()
        out.append(pg.merge(team, on=['game_id', 'posteam']))
    pg = pd.concat(out, ignore_index=True)
    pg['rz_share'] = pg.rz / pg.team_rz.clip(lower=1)
    pg['gl_share'] = pg.gl / pg.team_gl.clip(lower=1)
    pg['opp_share'] = (pg.carries + pg.targets) / pg.team_opps.clip(lower=1)
    return pg


def _positions(seasons):
    r = pd.concat([pd.read_csv(os.path.join(EXTRA, f'roster_{y}.csv'), usecols=['season', 'gsis_id', 'position', 'full_name'],
                               low_memory=False) for y in seasons])
    r = r.dropna(subset=['gsis_id']).drop_duplicates(['gsis_id'], keep='last')
    r['position'] = r.position.replace({'FB': 'RB', 'HB': 'RB'})
    return r.rename(columns={'gsis_id': 'pid'})[['pid', 'position', 'full_name']]


def implied_points(g):
    """Each team's implied points from the closing spread (home margin) and total."""
    h = g.total_line / 2 + g.spread_line / 2
    return pd.concat([pd.DataFrame({'game_id': g.game_id, 'posteam': g.home_team, 'imp_pts': h}),
                      pd.DataFrame({'game_id': g.game_id, 'posteam': g.away_team, 'imp_pts': g.total_line - h})])


ROLL = ['rz_share', 'gl_share', 'opp_share', 'carries', 'targets', 'tds', 'rz', 'gl']


def history(seasons=range(2021, 2027)):
    if os.path.exists(CACHE):
        return pd.read_csv(CACHE)
    pg = _player_games(seasons).merge(_positions(seasons), on='pid', how='left')
    pg = pg[pg.position.isin(POS)]
    pg = pg.merge(G[['game_id', 'gameday']], on='game_id').sort_values(['pid', 'gameday'])
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    pg.to_csv(CACHE, index=False)
    return pg


def _ewm_prior(pg):
    """Recency-weighted averages of each stat over the player's earlier games (excludes the current game)."""
    a = 1 - 0.5 ** (1 / HALF)
    g = pg.groupby('pid')
    prior = pd.DataFrame(index=pg.index)
    for c in ROLL:
        prior[f'h_{c}'] = g[c].transform(lambda s: s.shift(1).ewm(alpha=a, adjust=True).mean())
    prior['h_games'] = g.cumcount()
    return prior


def design(df):
    X = pd.DataFrame({
        'rz_share': df.h_rz_share, 'gl_share': df.h_gl_share, 'opp_share': df.h_opp_share,
        'carries': df.h_carries / 10, 'targets': df.h_targets / 5, 'tds': df.h_tds, 'gl': df.h_gl,
        'imp_pts': (df.imp_pts - 22) / 5, 'few_games': (df.h_games < 4).astype(float),
    })
    for p in ['QB', 'TE', 'WR']:          # RB is the baseline
        X[f'pos_{p}'] = (df.position == p).astype(float)
    X['gl_x_pts'] = X.gl_share * X.imp_pts
    return X.fillna(0.0)


def fit(X, y, lam=1.0):
    X1 = np.column_stack([X.values, np.ones(len(X))]); b = np.zeros(X1.shape[1])
    P = np.eye(X1.shape[1]) * lam; P[-1, -1] = 0
    for _ in range(30):
        q = 1 / (1 + np.exp(-X1 @ b)); W = q * (1 - q)
        b -= np.linalg.solve(X1.T @ (X1 * W[:, None]) + P, X1.T @ (q - y) + P @ b)
    return b


def predict(b, X):
    return 1 / (1 + np.exp(-np.column_stack([X.values, np.ones(len(X))]) @ b))


def training_frame():
    pg = history()
    pg = pd.concat([pg, _ewm_prior(pg)], axis=1)
    pg = pg.merge(implied_points(G), on=['game_id', 'posteam'], how='left')
    pg = pg[(pg.h_games >= 1) & pg.imp_pts.notna()]
    pg['scored'] = (pg.tds > 0).astype(float)
    return pg


def _key(s):
    return (s.str.lower().str.replace(r'\b(jr|sr|ii|iii|iv|v)\b\.?', '', regex=True)
            .str.replace(r'[^a-z]', '', regex=True))


def upcoming(season, week, implied, overrides=None):
    """Rows for players expected to play in `week`, with their prior history as features.

    implied: DataFrame game_id, posteam, imp_pts for this week's games.
    A player is included when he is ACT on his team's roster for this week and had a touch in one of
    the team's last 3 games. Players named in the injury overrides with status Out are dropped.
    """
    pg = history()
    pg = pd.concat([pg, _ewm_prior(pg)], axis=1)
    a = 1 - 0.5 ** (1 / HALF)
    last = pg.groupby('pid').tail(1).copy()
    # fold the latest game into the averages so the features cover every game played so far
    for c in ROLL:
        last[f'h_{c}'] = pg.groupby('pid')[c].apply(lambda s: s.ewm(alpha=a, adjust=True).mean().iloc[-1]).reindex(last.pid).values
    last['h_games'] = last.h_games + 1
    ros = pd.read_csv(os.path.join(EXTRA, f'roster_{season}.csv'), low_memory=False)
    ros = ros[(ros.week == week) & (ros.status == 'ACT')][['gsis_id', 'team']].rename(columns={'gsis_id': 'pid'})
    last = last.merge(ros, on='pid')
    tg = pg[pg.season == season].groupby('posteam').game_id.unique()
    recent = {t: set(sorted(g)[-3:]) for t, g in tg.items()}
    played = pg[pg.season == season].groupby('pid').game_id.apply(set)
    last = last[[bool(played.get(r.pid, set()) & recent.get(r.team, set())) for r in last.itertuples()]]
    last = last.drop(columns=['posteam', 'game_id']).rename(columns={'team': 'posteam'})
    last = last.merge(implied, on='posteam')
    if overrides is not None and len(overrides):
        out = overrides[(overrides.season == season) & (overrides.week == week) & overrides.status.isin(['Out', 'Doubtful'])]
        last = last[~_key(last.full_name).isin(set(_key(out.player)))]
    return last
