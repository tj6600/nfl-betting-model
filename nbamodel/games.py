"""NBA game model: recency-weighted ridge ratings on points scored, with rest and missing-player terms.

Each team-game is a row: points = league mean + offense(team) + defense(opponent) + home
+ own/opponent back-to-back + own/opponent missing-player value. Ratings use only games before the
target date. Margin and total are treated as normal (SDs from the backtest) to get cover, over and win chances.

Missing players: a player's value is his recent minutes times his box-score impact (game score a minute)
above replacement. Training rows use who actually sat; for a game being predicted we only know who sat
the team's previous game, so that proxy is used in the backtest and live (injury reports are not in our data).
"""
import numpy as np, pandas as pd
from nflmodel.stats import norm

TEAMS = ['ATL', 'BKN', 'BOS', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GS', 'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA',
         'MIL', 'MIN', 'NO', 'NY', 'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SA', 'SAC', 'TOR', 'UTAH', 'WSH']
TI = {t: i for i, t in enumerate(TEAMS)}
NT = len(TEAMS)
SD_MARGIN, SD_TOTAL = 12.6, 18.0   # residual SDs, refit by scripts/nba_backtest.py
HL, PRIOR_SEASON_W, LAM, REP = 45.0, 0.35, 8.0, 0.25


def game_score(p):
    return (p.pts + 0.4 * p.fgm - 0.7 * p.fga - 0.4 * (p.fta - p.ftm) + 0.7 * p.oreb + 0.3 * (p.reb - p.oreb)
            + p.stl + 0.7 * p.ast + 0.7 * p.blk - p.tov)


def player_form(P):
    """Each player-game row gets the player's form going into it (EWM over his previous games played)."""
    p = P.sort_values(['pid', 'date']).copy()
    played = (~p.dnp) & (p['min'] > 0)
    p['gs'] = game_score(p).where(played)
    p['m'] = p['min'].where(played)
    g = p.groupby('pid')
    p['mpg'] = g.m.transform(lambda s: s.shift(1).ewm(halflife=8, ignore_na=True).mean())
    p['gs_sum'] = g.gs.transform(lambda s: s.shift(1).ewm(halflife=8, ignore_na=True).mean())
    p['gsm'] = (p.gs_sum + REP * 3 / max(1, 1)) / (p.mpg + 3)   # shrink a little toward replacement
    p['n_prev'] = g.m.transform(lambda s: s.shift(1).notna().cumsum())
    return p


def team_missing(P):
    """Per (game_id, team): value of regulars who sat (not coach's decision) and the same for the team's previous game."""
    p = player_form(P)
    out = p.dnp & ~p.reason.fillna('').str.contains('COACH', case=False) & (p.mpg >= 15) & (p.n_prev >= 3)
    p['val'] = np.where(out, p.mpg * (p.gsm - REP), 0.0)
    t = p.groupby(['game_id', 'team', 'date']).val.sum().reset_index().sort_values('date')
    t['prev'] = t.groupby('team').val.shift(1).fillna(0)
    t = t.set_index(['game_id', 'team'])
    return {'val': t.val.to_dict(), 'prev': t.prev.to_dict()}


def rest_days(G):
    long = pd.concat([G[['game_id', 'date', 'home']].rename(columns={'home': 't'}),
                      G[['game_id', 'date', 'away']].rename(columns={'away': 't'})])
    long['d'] = pd.to_datetime(long.date); long = long.sort_values('d')
    long['rest'] = long.groupby('t').d.diff().dt.days.clip(upper=4).fillna(4)
    return long.set_index(['game_id', 't']).rest.to_dict()


def design(G, rest, mh, ma):
    n = len(G)
    X = np.zeros((2 * n, 2 * NT + 5))
    h = G.home.map(TI).values; a = G.away.map(TI).values; i = np.arange(n)
    X[i, h] = 1; X[i, NT + a] = 1; X[i, -5] = 1                       # home team's points
    X[n + i, a] = 1; X[n + i, NT + h] = 1                              # away team's points
    rh = np.array([rest.get((g, t), 4) for g, t in zip(G.game_id, G.home)]) == 1
    ra = np.array([rest.get((g, t), 4) for g, t in zip(G.game_id, G.away)]) == 1
    X[i, -4], X[n + i, -4] = rh, ra                                    # own back-to-back
    X[i, -3], X[n + i, -3] = ra, rh                                    # opponent back-to-back
    X[i, -2], X[n + i, -2] = mh, ma                                    # own missing value
    X[i, -1], X[n + i, -1] = ma, mh                                    # opponent missing value
    return X


class Ratings:
    def __init__(self, hl=HL, lam=LAM, prior_w=PRIOR_SEASON_W, use_missing=True):
        self.hl, self.lam, self.prior_w, self.use_missing = hl, lam, prior_w, use_missing

    def fit(self, G, M, asof, rest=None):
        g = G[G.date < asof]
        cur = g.season.max(); g = g[g.season >= cur - 1]
        age = (pd.Timestamp(asof) - pd.to_datetime(g.date)).dt.days.values
        w = 0.5 ** (age / self.hl) * np.where(g.season.values == cur, 1.0, self.prior_w)
        self.rest = rest if rest is not None else rest_days(G)
        mh, ma = self._miss(g, M, 'val')
        X = design(g, self.rest, mh, ma)
        y = np.r_[g.hs.values, g.as_.values].astype(float); W = np.r_[w, w]
        self.mu = np.average(y, weights=W)
        pen = np.full(X.shape[1], self.lam); pen[-5:] = 1.0
        self.b = np.linalg.solve(X.T @ (X * W[:, None]) + np.diag(pen), X.T @ ((y - self.mu) * W))
        return self

    def _miss(self, g, M, col):
        if not self.use_missing or M is None:
            return np.zeros(len(g)), np.zeros(len(g))
        d = M[col]; f = lambda t: np.array([d.get((a, b), 0.0) for a, b in zip(g.game_id, t)])
        return f(g.home), f(g.away)

    def predict(self, games, M=None, miss=None):
        """miss: optional {team: value} for upcoming games; otherwise the previous-game proxy from M."""
        if miss is not None:
            mh, ma = games.home.map(miss).fillna(0).values, games.away.map(miss).fillna(0).values
        else:
            mh, ma = self._miss(games, M, 'prev')
        if not self.use_missing:
            mh, ma = mh * 0, ma * 0
        pts = self.mu + design(games, self.rest, mh, ma) @ self.b
        n = len(games)
        out = games[['game_id', 'date', 'home', 'away']].copy()
        out['p_home'], out['p_away'] = pts[:n], pts[n:]
        out['margin'] = out.p_home - out.p_away; out['total'] = out.p_home + out.p_away
        out['miss_home'], out['miss_away'] = mh, ma
        return out

    def team_table(self):
        off = self.b[:NT]; de = self.b[NT:2 * NT]
        return pd.DataFrame(dict(team=TEAMS, off=off, deff=de, net=off - de)).sort_values('net', ascending=False)


def probs(margin, total, spread, line_total):
    """Home cover chance (home margin + spread > 0), over chance, home win chance."""
    cover = 1 - norm.cdf(-np.asarray(spread, float), margin, SD_MARGIN)
    over = 1 - norm.cdf(np.asarray(line_total, float), total, SD_TOTAL)
    win = 1 - norm.cdf(0.0, margin, SD_MARGIN)
    return cover, over, win
