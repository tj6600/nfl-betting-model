"""Passing yards model for QB over/under props.

Data: nflverse weekly player stats (stats_player_week_<year>.csv, github.com releases), gross passing yards
like the books use (sacks are not taken off). Only real starts count: 15+ attempts.

Expected yards = ridge regression on the QB's recency-weighted passing yards and attempts in his previous
starts (half-life HALF starts), his team's implied points and expected margin (trailing teams throw more),
and the opponent's passing yards allowed (recency-weighted, vs league). The chance of the Over comes from
the empirical actual / expected ratio in training games, by projection size (same method as yards.py).
"""
import os
import numpy as np, pandas as pd
from .model import G
from .yards import ridge, apply

URL = 'https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{y}.csv'
CACHE = os.environ.get('NFL_STATS_DIR', os.path.join(os.path.dirname(__file__), '..', 'data'))
HALF, DEF_HALF, MIN_ATT = 6.0, 8.0, 15
COLS = ['player_id', 'player_display_name', 'position', 'season', 'week', 'season_type', 'game_id', 'team', 'opponent_team',
        'attempts', 'completions', 'passing_yards', 'sacks_suffered', 'carries']


def load(seasons):
    out = []
    for y in seasons:
        local = os.path.join(CACHE, f'stats_player_week_{y}.csv')
        src = local if os.path.exists(local) else URL.format(y=y)
        d = pd.read_csv(src, usecols=lambda c: c in COLS, low_memory=False)
        out.append(d[(d.season_type == 'REG') & (d.position == 'QB')])
    q = pd.concat(out, ignore_index=True).rename(columns={'player_id': 'pid', 'player_display_name': 'name', 'team': 'posteam', 'opponent_team': 'defteam'})
    q = q.merge(G[['game_id', 'gameday']], on='game_id', how='left')
    return q.sort_values(['gameday', 'game_id']).reset_index(drop=True)


def context(g):
    """Implied points and expected margin per team-game from the closing line (nflverse: spread_line = home margin)."""
    h = pd.DataFrame({'game_id': g.game_id, 'posteam': g.home_team, 'exp_margin': g.spread_line, 'tot': g.total_line})
    a = pd.DataFrame({'game_id': g.game_id, 'posteam': g.away_team, 'exp_margin': -g.spread_line, 'tot': g.total_line})
    c = pd.concat([h, a]); c['imp_pts'] = c.tot / 2 + c.exp_margin / 2
    return c[['game_id', 'posteam', 'imp_pts', 'exp_margin']]


def defense(q):
    """Passing yards each defense allowed (all QBs), EWM before each game ('prior') and through it ('now'), vs league."""
    d = q.groupby(['game_id', 'defteam', 'gameday']).passing_yards.sum().reset_index().sort_values('gameday')
    al = 1 - 0.5 ** (1 / DEF_HALF); grp = d.groupby('defteam').passing_yards
    m = d.passing_yards.mean()
    d['def_prior'] = grp.transform(lambda x: x.shift(1).ewm(alpha=al).mean()) - m
    d['def_now'] = grp.transform(lambda x: x.ewm(alpha=al).mean()) - m
    return d


def features(q):
    """One row per start with the QB's form going in (no leakage)."""
    s = q[q.attempts >= MIN_ATT].copy()
    al = 1 - 0.5 ** (1 / HALF); g = s.groupby('pid')
    for c in ['passing_yards', 'attempts']:
        s[f'h_{c}'] = g[c].transform(lambda x: x.shift(1).ewm(alpha=al).mean())
    s['h_starts'] = g.cumcount()
    s['new_team'] = (g.posteam.shift(1) != s.posteam).astype(float).where(s.h_starts > 0, 0.0)
    s = s.merge(context(G), on=['game_id', 'posteam'], how='left')
    s = s.merge(defense(q)[['game_id', 'defteam', 'def_prior']], on=['game_id', 'defteam'], how='left')
    return s


LEAGUE = 215.0


def design(df):
    hy = df.h_passing_yards.fillna(LEAGUE)
    few = (df.h_starts.fillna(0) < 4).astype(float)
    X = pd.DataFrame({
        'h_yds': hy, 'h_att': df.h_attempts.fillna(32), 'pts': (df.imp_pts - 22) / 5, 'margin': df.exp_margin / 7,
        'def': df.def_prior.fillna(0) / 10, 'few': few, 'few_yds': few * hy, 'new_team': df.new_team.fillna(0)})
    X['yds_x_pts'] = X.h_yds * X.pts / 100
    X['yds_x_margin'] = X.h_yds * X.margin / 100
    return X.fillna(0.0)


class Spread:
    """Empirical actual/expected by projection size."""
    EDGES = [0, 190, 220, 250, 1e9]

    def __init__(self, mu, y):
        b = np.digitize(mu, self.EDGES) - 1
        self.r = {i: np.sort(y[b == i] / mu[b == i]) for i in range(len(self.EDGES) - 1) if (b == i).sum() >= 50}

    def _r(self, bi):
        return self.r[bi] if bi in self.r else self.r[min(self.r, key=lambda k: abs(k - bi))]

    def p_over(self, mu, line):
        mu = np.asarray(mu, float); line = np.asarray(line, float); out = np.empty(len(mu))
        for i, (m, l, bi) in enumerate(zip(mu, line, np.digitize(mu, self.EDGES) - 1)):
            r = self._r(bi); out[i] = 1 - np.searchsorted(r, l / m, side='right') / len(r)
        return out

    def quantile(self, mu, qq):
        mu = np.asarray(mu, float)
        return np.array([m * np.quantile(self._r(bi), qq) for m, bi in zip(mu, np.digitize(mu, self.EDGES) - 1)])


def fit(tr):
    tr = tr.dropna(subset=['imp_pts'])
    y = tr.passing_yards.values.astype(float); X = design(tr); b = ridge(X, y, lam=5.0)
    return b, Spread(apply(b, X), y)


def predict(b, df):
    return apply(b, design(df))


def current(q, season, week, teams, out_names=()):
    """Expected starter per team for (season, week), with form through his latest start.

    Starter = the QB with the most attempts in the team's latest game this season, unless he is ACT-less
    (not on the week's active roster) or named Out; then the team's next most recent starter."""
    from .roster import _load as _load_extra
    ros = _load_extra('roster', season)
    act = ros[(ros.week == week) & (ros.status == 'ACT') & (ros.position == 'QB')][['gsis_id', 'team']].rename(columns={'gsis_id': 'pid', 'team': 'posteam'})
    s = q[q.attempts >= MIN_ATT].copy()
    al = 1 - 0.5 ** (1 / HALF)
    rows = []
    for t in teams:
        tq = s[(s.season == season) & (s.posteam == t)].sort_values('gameday')
        cands = list(dict.fromkeys(tq.pid[::-1]))          # most recent starters first
        okp = set(act[act.posteam == t].pid)
        pick = next((p for p in cands if p in okp and s[s.pid == p].name.iloc[-1] not in out_names), None)
        if pick is None:
            continue
        h = s[s.pid == pick].sort_values('gameday')
        r = dict(pid=pick, name=h.name.iloc[-1], posteam=t,
                 h_passing_yards=h.passing_yards.ewm(alpha=al).mean().iloc[-1], h_attempts=h.attempts.ewm(alpha=al).mean().iloc[-1],
                 h_starts=len(h), new_team=float(h.posteam.iloc[-1] != t),
                 last_start=h.gameday.iloc[-1], team_last=tq.gameday.iloc[-1] if len(tq) else None)
        r['missed_last'] = float(r['last_start'] != r['team_last'])
        rows.append(r)
    return pd.DataFrame(rows)
