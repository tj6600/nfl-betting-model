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
from .pbp import PBP_URL
from .roster import _load as _load_extra

PBP_DIR = os.environ.get('NFL_PBP_DIR', os.path.join(os.path.dirname(__file__), '..', 'data'))
CACHE = os.path.join(os.path.dirname(__file__), '..', 'data', 'td_player_games.csv')
HALF = 6.0
POS = ['QB', 'RB', 'WR', 'TE']
COLS = ['game_id', 'season', 'week', 'season_type', 'posteam', 'defteam', 'yardline_100', 'play_type',
        'rusher_player_id', 'receiver_player_id', 'td_player_id', 'td_team', 'rush_touchdown', 'pass_touchdown',
        'two_point_attempt', 'rush_attempt', 'pass_attempt', 'rushing_yards', 'receiving_yards', 'complete_pass']


def _player_games(seasons):
    out = []
    for y in seasons:
        local = os.path.join(PBP_DIR, f'pbp_{y}.csv.gz')
        p = pd.read_csv(local if os.path.exists(local) else PBP_URL.format(y=y), usecols=lambda c: c in COLS, low_memory=False)
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
        opp['rush_yds'] = np.where(opp.kind == 'rush', opp.rushing_yards.fillna(0), 0.0)
        opp['rec_yds'] = np.where(opp.kind == 'tgt', opp.receiving_yards.fillna(0), 0.0)
        opp['rec'] = np.where(opp.kind == 'tgt', opp.complete_pass.fillna(0), 0)
        pg = opp.groupby(['game_id', 'season', 'week', 'posteam', 'pid']).agg(
            carries=('carry', 'sum'), targets=('target', 'sum'), rz=('rz', 'sum'), gl=('gl', 'sum'), tds=('td', 'sum'),
            rush_yds=('rush_yds', 'sum'), rec_yds=('rec_yds', 'sum'), receptions=('rec', 'sum')).reset_index()
        team = opp.groupby(['game_id', 'posteam']).agg(team_rz=('rz', 'sum'), team_gl=('gl', 'sum'),
                                                       team_opps=('rz', 'size')).reset_index()
        out.append(pg.merge(team, on=['game_id', 'posteam']))
    pg = pd.concat(out, ignore_index=True)
    pg['rz_share'] = pg.rz / pg.team_rz.clip(lower=1)
    pg['gl_share'] = pg.gl / pg.team_gl.clip(lower=1)
    pg['opp_share'] = (pg.carries + pg.targets) / pg.team_opps.clip(lower=1)
    return pg


def _positions(seasons):
    r = pd.concat([_load_extra('roster', y)[['season', 'gsis_id', 'position', 'full_name']] for y in seasons])
    r = r.dropna(subset=['gsis_id']).drop_duplicates(['gsis_id'], keep='last')
    r['position'] = r.position.replace({'FB': 'RB', 'HB': 'RB'})
    return r.rename(columns={'gsis_id': 'pid'})[['pid', 'position', 'full_name']]


def implied_points(g):
    """Each team's implied points from the closing spread (home margin) and total."""
    h = g.total_line / 2 + g.spread_line / 2
    return pd.concat([pd.DataFrame({'game_id': g.game_id, 'posteam': g.home_team, 'imp_pts': h}),
                      pd.DataFrame({'game_id': g.game_id, 'posteam': g.away_team, 'imp_pts': g.total_line - h})])


ROLL = ['rz_share', 'gl_share', 'opp_share', 'carries', 'targets', 'tds', 'rz', 'gl', 'rush_yds', 'rec_yds', 'receptions']


def history(seasons=range(2021, 2027)):
    if os.path.exists(CACHE):
        return pd.read_csv(CACHE)
    pg = _player_games(seasons).merge(_positions(seasons), on='pid', how='left')
    pg = pg[pg.position.isin(POS)]
    pg = pg.merge(G[['game_id', 'gameday']], on='game_id').sort_values(['pid', 'gameday'])
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    pg.to_csv(CACHE, index=False)
    return pg


TEAM_PEN = 1.0   # weight multiplier for games a player played for a different team than the one being predicted
SEASON_PEN = 1.0  # weight multiplier for games from earlier seasons


def _team_weights(n, teams, ref, r, include_last):
    """Recency weights over a player's games, scaled by TEAM_PEN for games with another team than `ref`."""
    age = np.arange(n)[::-1] if include_last else np.arange(n)[::-1] - 1
    w = r ** age.astype(float)
    return w * np.where(teams != ref, TEAM_PEN, 1.0)


def _ewm_prior(pg):
    """Recency-weighted averages of each stat over the player's earlier games (excludes the current game).

    Games played for another team count TEAM_PEN times as much (a new team usually means a new role)."""
    a = 1 - 0.5 ** (1 / HALF)
    g = pg.groupby('pid')
    prior = pd.DataFrame(index=pg.index)
    if TEAM_PEN == 1.0 and SEASON_PEN == 1.0:
        for c in ROLL:
            prior[f'h_{c}'] = g[c].transform(lambda s: s.shift(1).ewm(alpha=a, adjust=True).mean())
    else:
        r = 1 - a; V = pg[ROLL].to_numpy(float); out = np.full(V.shape, np.nan); team = pg.posteam.to_numpy(); sea = pg.season.to_numpy()
        for idx in g.indices.values():
            idx = np.sort(idx); n = len(idx)
            if n < 2: continue
            v = V[idx]; t = team[idx]; se = sea[idx]
            ii, jj = np.meshgrid(np.arange(n), np.arange(n), indexing='ij')
            W = np.where(jj < ii, r ** (ii - 1 - jj).astype(float), 0.0) * np.where(t[None, :] != t[:, None], TEAM_PEN, 1.0) * np.where(se[None, :] != se[:, None], SEASON_PEN, 1.0)
            ok = ~np.isnan(v); num = W @ np.nan_to_num(v); den = W @ ok
            with np.errstate(invalid='ignore', divide='ignore'):
                out[idx] = num / den
        for k, c in enumerate(ROLL):
            prior[f'h_{c}'] = out[:, k]
    prior['h_games'] = g.cumcount()
    return prior


def _ewm_now(pg):
    """Recency-weighted averages over every game played so far, relative to each player's latest team."""
    a = 1 - 0.5 ** (1 / HALF); r = 1 - a; rows = {}
    for pid, x in pg.groupby('pid'):
        t = x.posteam.to_numpy(); se = x.season.to_numpy(); w = _team_weights(len(x), t, t[-1], r, True) * np.where(se != se[-1], SEASON_PEN, 1.0)
        v = x[ROLL].to_numpy(float); ok = ~np.isnan(v)
        rows[pid] = (w @ np.nan_to_num(v)) / np.maximum(w @ ok, 1e-12)
    return pd.DataFrame.from_dict(rows, orient='index', columns=[f'h_{c}' for c in ROLL])


def design(df, extended=True):
    X = pd.DataFrame({
        'rz_share': df.h_rz_share, 'gl_share': df.h_gl_share, 'opp_share': df.h_opp_share,
        'carries': df.h_carries / 10, 'targets': df.h_targets / 5, 'tds': df.h_tds, 'gl': df.h_gl,
        'imp_pts': (df.imp_pts - 22) / 5, 'few_games': (df.h_games < 4).astype(float),
    })
    for p in ['QB', 'TE', 'WR']:          # RB is the baseline
        X[f'pos_{p}'] = (df.position == p).astype(float)
    X['gl_x_pts'] = X.gl_share * X.imp_pts
    if extended:
        X['room_share'] = df.room_share          # his share of the touches among teammates at his position who play
        X['last_share'] = df.last_share          # share of team touches in his most recent game
        X['missed_last'] = df.missed_last        # missed the team's previous game (injury, benching)
        X['def_td'] = df.def_td                  # opponent's TDs allowed per game to this position, vs league average
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


def _with_def(pg):
    """Attach defteam and gameday to player-games."""
    g = G[['game_id', 'home_team', 'away_team', 'gameday']]
    pg = pg.drop(columns=[c for c in ['gameday'] if c in pg]).merge(g, on='game_id')
    pg['defteam'] = np.where(pg.posteam == pg.home_team, pg.away_team, pg.home_team)
    return pg.drop(columns=['home_team', 'away_team'])


DEF_HALF = 8.0


def defense_table(pg):
    """Per defense, game and position: TDs allowed, and the recency-weighted average before that game."""
    pg = _with_def(pg)
    games = pg[['game_id', 'defteam', 'gameday']].drop_duplicates()
    full = games.assign(k=1).merge(pd.DataFrame({'position': POS, 'k': 1}), on='k').drop(columns='k')
    tda = pg.groupby(['game_id', 'defteam', 'position']).tds.sum().reset_index()
    d = full.merge(tda, on=['game_id', 'defteam', 'position'], how='left').fillna({'tds': 0})
    d = d.sort_values('gameday')
    a = 1 - 0.5 ** (1 / DEF_HALF)
    grp = d.groupby(['defteam', 'position']).tds
    d['def_prior'] = grp.transform(lambda x: x.shift(1).ewm(alpha=a).mean())
    d['def_now'] = grp.transform(lambda x: x.ewm(alpha=a).mean())
    mean = d.groupby('position').tds.mean()
    d['def_prior'] -= d.position.map(mean); d['def_now'] -= d.position.map(mean)
    return d


def _room(df):
    tot = df.groupby(['game_id', 'posteam', 'position']).h_opp_share.transform('sum')
    df['room_share'] = df.h_opp_share / tot.where(tot > 0, 1)
    return df


def training_frame():
    pg = history()
    pg = pd.concat([pg, _ewm_prior(pg)], axis=1)
    pg['last_share'] = pg.groupby('pid').opp_share.shift(1)
    # did he miss his team's previous game? (compare with the team's game sequence)
    tseq = pg[['game_id', 'posteam', 'gameday']].drop_duplicates().sort_values('gameday')
    tseq['team_prev'] = tseq.groupby('posteam').game_id.shift(1)
    pg = pg.merge(tseq[['game_id', 'posteam', 'team_prev']], on=['game_id', 'posteam'], how='left')
    pg['prev_game'] = pg.groupby('pid').game_id.shift(1)
    pg['missed_last'] = ((pg.prev_game != pg.team_prev) & pg.prev_game.notna()).astype(float)
    pg = _room(pg)
    d = defense_table(pg)
    pg = _with_def(pg).merge(d[['game_id', 'defteam', 'position', 'def_prior']], on=['game_id', 'defteam', 'position'], how='left')
    pg = pg.rename(columns={'def_prior': 'def_td'})
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
    A player is included when he is ACT on his team's roster for this week and has a touch this season
    (missed_last flags players who sat out the team's latest game). Players named in the injury overrides with status Out are dropped.
    """
    pg = history()
    pg = pd.concat([pg, _ewm_prior(pg)], axis=1)
    last = pg.groupby('pid').tail(1).copy()
    # fold the latest game into the averages so the features cover every game played so far
    now = _ewm_now(pg).reindex(last.pid)
    for c in ROLL:
        last[f'h_{c}'] = now[f'h_{c}'].values
    last['h_games'] = last.h_games + 1
    ros = _load_extra('roster', season)
    ros = ros[(ros.week == week) & (ros.status == 'ACT')][['gsis_id', 'team']].rename(columns={'gsis_id': 'pid'})
    last = last.merge(ros, on='pid')
    last['last_share'] = last.opp_share
    tseq = pg[pg.season == season][['game_id', 'posteam', 'gameday']].drop_duplicates().sort_values('gameday')
    team_last = tseq.groupby('posteam').game_id.last()
    played = pg[pg.season == season].groupby('pid').game_id.apply(set)
    # anyone ACT with a touch this season; a starter back from injury competes for touches again
    last = last[[len(played.get(r.pid, set())) > 0 for r in last.itertuples()]]
    last['missed_last'] = [float(team_last.get(r.team) not in played.get(r.pid, set())) for r in last.itertuples()]
    tgames = tseq.groupby('posteam').game_id.apply(list)
    def streak(r):
        n = 0
        for gid in reversed(tgames.get(r.team, [])):
            if gid in played.get(r.pid, set()): break
            n += 1
        return n
    last['missed_n'] = [streak(r) for r in last.itertuples()]
    last = last.drop(columns=['posteam', 'game_id']).rename(columns={'team': 'posteam'})
    last = last.merge(implied, on='posteam')
    if overrides is not None and len(overrides):
        out = overrides[(overrides.season == season) & (overrides.week == week) & overrides.status.isin(['Out', 'Doubtful'])]
        last = last[~_key(last.full_name).isin(set(_key(out.player)))]
    last = _room(last)
    d = defense_table(pg)
    dn = d.sort_values('gameday').groupby(['defteam', 'position']).def_now.last().rename('def_td').reset_index()
    opp = implied.merge(implied[['game_id', 'posteam']].rename(columns={'posteam': 'defteam'}), on='game_id')
    opp = opp[opp.posteam != opp.defteam][['posteam', 'defteam']]
    last = last.merge(opp, on='posteam', how='left').merge(dn, on=['defteam', 'position'], how='left')
    return last


# ---- depth charts (nflverse, ESPN snapshots; daily format from 2025) ----
DC_URL = 'https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_{y}.csv'
DC_DIR = os.environ.get('NFL_DC_DIR', os.path.join(os.path.dirname(__file__), '..', 'data'))
DEPTH_SEASONS = [2025, 2026]


def depth_snapshots(seasons=DEPTH_SEASONS):
    out = []
    for y in seasons:
        local = os.path.join(DC_DIR, f'depth_charts_{y}.csv')
        d = pd.read_csv(local if os.path.exists(local) else DC_URL.format(y=y),
                        usecols=['dt', 'team', 'gsis_id', 'pos_abb', 'pos_rank'], low_memory=False)
        d = d[d.pos_abb.isin(POS) & d.gsis_id.notna()]
        out.append(d)
    d = pd.concat(out, ignore_index=True)
    d['dt'] = pd.to_datetime(d.dt, utc=True).dt.tz_localize(None)
    d = d.sort_values('pos_rank').drop_duplicates(['dt', 'team', 'gsis_id'])   # a player listed twice keeps his best rank
    return d.rename(columns={'gsis_id': 'pid'})


def _tier(pos, rank):
    """1 = starter, 2 = first backup, 3 = deeper; WRs count the top two as starters. 0 = not on the chart."""
    r = np.asarray(rank, float); wr = np.asarray(pos) == 'WR'
    adj = np.where(wr, r - 1, r)
    t = np.where(np.isnan(r), 0, np.where(adj <= 1, 1, np.where(adj <= 2, 2, 3)))
    return t.astype(int)


def rank_at(rows, snaps, when_col):
    """Player's depth rank in his team's latest snapshot before `when_col` (NaN if not listed)."""
    team_dt = snaps[['team', 'dt']].drop_duplicates().sort_values('dt')
    q = rows[['team', when_col]].drop_duplicates().sort_values(when_col)
    q = pd.merge_asof(q, team_dt.rename(columns={'dt': 'snap'}), left_on=when_col, right_on='snap', by='team', direction='backward')
    out = rows.merge(q, on=['team', when_col], how='left')
    return out.merge(snaps.rename(columns={'dt': 'snap'})[['snap', 'team', 'pid', 'pos_rank']], on=['snap', 'team', 'pid'], how='left').pos_rank.values


def add_depth(df, snaps, now=None):
    """Adds depth tier now and at his previous game, plus promoted/demoted flags.

    Training rows: rank before each game's kickoff. Upcoming rows (now given): rank in the latest snapshot.
    """
    df = df.copy()
    ko = pd.to_datetime(df.gameday) + pd.Timedelta(hours=12)
    df['_ko'] = ko if now is None else pd.Timestamp(now)
    df['team'] = df.posteam
    df['dc_rank'] = rank_at(df, snaps, '_ko')
    if now is None:
        df = df.sort_values(['pid', 'gameday'])
        df['dc_prev'] = df.groupby('pid').dc_rank.shift(1)
    else:   # rank before his most recent game
        df['_last'] = pd.to_datetime(df.gameday) + pd.Timedelta(hours=12)
        df['dc_prev'] = rank_at(df, snaps, '_last')
    df['dc_tier'] = _tier(df.position, df.dc_rank)
    prev = _tier(df.position, df.dc_prev)
    has = (df.dc_tier > 0) & (prev > 0)
    df['dc_demoted'] = (has & (df.dc_tier > prev)).astype(float)
    df['dc_promoted'] = (has & (df.dc_tier < prev)).astype(float)
    return df.drop(columns=['_ko', 'team'] + (['_last'] if '_last' in df else []))


def depth_design(df):
    X = pd.DataFrame({'tier2': (df.dc_tier == 2).astype(float), 'tier3': (df.dc_tier == 3).astype(float),
                      'off_chart': (df.dc_tier == 0).astype(float), 'demoted': df.dc_demoted, 'promoted': df.dc_promoted})
    return X


def fit_offset(X, y, offset, lam=1.0):
    """Logistic regression on top of a fixed base logit (offset)."""
    X1 = np.column_stack([X.values, np.ones(len(X))]); b = np.zeros(X1.shape[1])
    P = np.eye(X1.shape[1]) * lam; P[-1, -1] = 0
    for _ in range(30):
        q = 1 / (1 + np.exp(-(X1 @ b + offset))); W = q * (1 - q)
        b -= np.linalg.solve(X1.T @ (X1 * W[:, None]) + P, X1.T @ (q - y) + P @ b)
    return b


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6); return np.log(p / (1 - p))
