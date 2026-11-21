"""NBA player-based game model: team strength = the players expected to play, weighted by their minutes.

Each player gets a rating (points of team margin per 48 minutes on the floor). It is fit by ridge regression
on game margins: margin = home court + b2b terms + beta * (box-score form of each side's players, minute-weighted)
+ sum of player adjustments, minute-weighted. The box-score term means a player with few games starts at his
box-score value, and the per-player adjustment (shrunk to 0) learns what the box score misses (defense, spacing).
Ratings follow a player across teams, so trades and signings carry over on day one of a new season.

For a game being predicted, each side is the players expected to play with their recent minutes (EWM),
scaled so the team plays 240 minutes. Who plays: live, the roster minus the injury report's Out list;
in the backtest, either who actually played ('actual', what an injury report + lineup news gives at tip)
or who played the team's previous game ('prev', what a stale run knows).
"""
import numpy as np, pandas as pd
from nbamodel import games as M

HL_DAYS, LAM = 240.0, 10.0   # tuned 2026-11-12: lam 10 best of 10/25/60/150; hl 240 best of 120/240/500


def form(P):
    """Pre-game form for every player-game row: EWM minutes and box-score value a minute (no leakage)."""
    p = M.player_form(P)
    p['played'] = (~p.dnp) & (p['min'] > 0)
    p['bx'] = (p.gsm - M.REP).fillna(0.0)          # box value a minute above replacement, going in
    p.loc[p.n_prev < 1, 'bx'] = 0.0
    return p


class PlayerModel:
    def __init__(self, hl=HL_DAYS, lam=LAM):
        self.hl, self.lam = hl, lam

    def fit(self, G, F, asof, rest):
        g = G[(G.date < asof) & G.hs.notna()]
        g = g[g.season >= g.season.max() - 2]
        age = (pd.Timestamp(asof) - pd.to_datetime(g.date)).dt.days.values
        w = 0.5 ** (age / self.hl)
        f = F[F.game_id.isin(g.game_id) & F.played]
        pids = np.sort(f.pid.unique()); self.pix = {p: i for i, p in enumerate(pids)}
        gix = {gid: i for i, gid in enumerate(g.game_id)}
        n, k = len(g), len(pids)
        home_of = dict(zip(g.game_id, g.home))
        sgn = np.where(f.team.values == f.game_id.map(home_of).values, 1.0, -1.0)
        x = sgn * f['min'].values / 48.0
        rows = f.game_id.map(gix).values; cols = f.pid.map(self.pix).values
        X = np.zeros((n, k)); np.add.at(X, (rows, cols), x)
        box = np.zeros(n); np.add.at(box, rows, x * f.bx.values * 48 / 5)   # side box value per 48, per player-slot
        rh = np.array([rest.get((a, b), 4) for a, b in zip(g.game_id, g.home)]) == 1
        ra = np.array([rest.get((a, b), 4) for a, b in zip(g.game_id, g.away)]) == 1
        Z = np.c_[np.ones(n), rh.astype(float) - ra, box]                                 # unpenalized: home court, b2b, box
        A = np.c_[Z, X]; y = (g.hs - g.as_).values.astype(float)
        pen = np.r_[np.full(Z.shape[1], 1e-6), np.full(k, self.lam)]
        b = np.linalg.solve(A.T @ (A * w[:, None]) + np.diag(pen), A.T @ (y * w))
        self.hca, self.b2b, self.beta = b[:3]; self.adj = b[3:]
        self.rest = rest
        return self

    def rating(self, pid, bx):
        """Margin a 48 minutes for one player: box part + learned adjustment (0 for unseen players)."""
        i = self.pix.get(pid)
        return self.beta * bx * 48 / 5 + (self.adj[i] if i is not None else 0.0)

    def side(self, rows):
        """rows: DataFrame of expected players for one team with pid, bx, mpg. Returns minute-weighted strength."""
        r = rows[rows.mpg.notna() & (rows.mpg > 0)]
        if not len(r): return 0.0
        m = r.mpg.values * 240.0 / max(240.0, r.mpg.sum()) if r.mpg.sum() > 240 else r.mpg.values
        # fewer than 240 known minutes: the rest is played by replacement-level players (rating 0 + box 0)
        return float(sum(mi / 48.0 * self.rating(p, b) for mi, p, b in zip(m, r.pid, r.bx)))

    def predict(self, games, lineups):
        """lineups: {(game_id, team): DataFrame of expected players}. Returns home margin."""
        out = games[['game_id', 'date', 'home', 'away']].copy()
        sh = np.array([self.side(lineups.get((a, b), pd.DataFrame(columns=['pid', 'bx', 'mpg']))) for a, b in zip(games.game_id, games.home)])
        sa = np.array([self.side(lineups.get((a, b), pd.DataFrame(columns=['pid', 'bx', 'mpg']))) for a, b in zip(games.game_id, games.away)])
        rh = np.array([self.rest.get((a, b), 4) for a, b in zip(games.game_id, games.home)]) == 1
        ra = np.array([self.rest.get((a, b), 4) for a, b in zip(games.game_id, games.away)]) == 1
        out['pm_margin'] = self.hca + self.b2b * (rh.astype(float) - ra) + sh - sa
        out['str_home'], out['str_away'] = sh, sa
        return out


def backtest_lineups(F, games, mode='actual'):
    """Expected players for each (game, team) as of tip: 'actual' = who played, 'prev' = who played the team's last game."""
    f = F[F.game_id.isin(games.game_id)]
    out = {}
    if mode == 'actual':
        for (gid, t), d in f[f.played].groupby(['game_id', 'team']):
            out[(gid, t)] = d[['pid', 'bx', 'mpg']]
        return out
    # 'prev': players who played the team's previous game, with their form going into this game
    allg = F[['game_id', 'team', 'date']].drop_duplicates().sort_values('date')
    allg['prev'] = allg.groupby('team').game_id.shift(1)
    prev = allg.set_index(['game_id', 'team']).prev.to_dict()
    played = F[F.played].groupby(['game_id', 'team']).pid.apply(set).to_dict()
    for (gid, t), d in f.groupby(['game_id', 'team']):
        pg = prev.get((gid, t))
        keep = played.get((pg, t), set()) if pg == pg and pg is not None else set()
        out[(gid, t)] = d[d.pid.isin(keep)][['pid', 'bx', 'mpg']]
    return out
