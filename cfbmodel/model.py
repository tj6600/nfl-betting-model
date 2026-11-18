"""College football team ratings: ridge regression on game scores, weighted toward recent games.

Each game gives two rows of points scored: pts = mu + home/2 + off[team] - def[opp] (neutral sites get no home edge).
Margin rating = off + def; expected margin = home edge + rating difference. Teams outside FBS share an "FCS" offset
(their own ratings shrink toward it) because ridge would otherwise pull them to the FBS average.
Older games count less (half-life HL days); last season's games count PREV as much again and carry over as the prior.
"""
import numpy as np, pandas as pd
from math import erf, sqrt


def _cdf(z): return 0.5 * (1 + np.vectorize(erf)(np.asarray(z, dtype=float) / sqrt(2)))

HL, LAM, PREV, CAP, MKT = 120.0, 0.3, 0.5, 99.0, 0.5
SD_MARGIN, SD_TOTAL = 15.5, 14.0      # residual spread of margins / totals around the model (fit on 2024-25)


def fbs_teams(g):
    """Teams in 6+ games of a season's FBS scoreboards are FBS (FCS opponents show up once or twice)."""
    c = pd.concat([g[['season', 'home_id']].rename(columns={'home_id': 't'}), g[['season', 'away_id']].rename(columns={'away_id': 't'})])
    n = c.groupby(['season', 't']).size()
    return set(n[n >= 6].index.get_level_values(1))


class Ratings:
    def __init__(self, hl=HL, lam=LAM, prev=PREV, cap=CAP, mkt=MKT, lines=None):
        self.hl, self.lam, self.prev, self.cap, self.mkt, self.lines = hl, lam, prev, cap, mkt, lines

    def fit(self, g, asof, season):
        """g: finished games (any seasons); fit on those starting before asof (a UTC Timestamp) in this season and the last."""
        g = g[(g.home_pts.notna()) & (pd.to_datetime(g.start, utc=True) < asof) & (g.season >= season - 1)].copy()
        self.fbs = fbs_teams(g) | getattr(self, 'fbs', set())
        days = (asof - pd.to_datetime(g.start, utc=True)).dt.total_seconds() / 86400
        w = np.asarray(0.5 ** (days.values / self.hl) * np.where(g.season < season, self.prev, 1.0))
        teams = sorted(set(g.home_id) | set(g.away_id))
        ix = {t: i for i, t in enumerate(teams)}; n = len(teams)
        rows, y, ww = [], [], []
        hm = np.where(g.neutral, 0.0, 1.0)
        # cap each side's points so a 70-0 blowout counts like a CAP-point win
        hp, ap = g.home_pts.values.astype(float), g.away_pts.values.astype(float)
        mg = np.clip(hp - ap, -self.cap, self.cap); tot = hp + ap
        if self.mkt and self.lines is not None:   # pull each past result toward DraftKings' closing line for it (market ratings)
            ln = g[['espn_id']].merge(self.lines[['espn_id', 'sp_home', 'total']], on='espn_id', how='left')
            has = ln.sp_home.notna().values
            mg = np.where(has, (1 - self.mkt) * mg + self.mkt * -ln.sp_home.fillna(0).values, mg)
            tot = np.where(has, (1 - self.mkt) * tot + self.mkt * ln.total.fillna(0).values, tot)
        hp2, ap2 = (tot + mg) / 2, (tot - mg) / 2
        for k, (h, a) in enumerate(zip(g.home_id, g.away_id)):
            for t, o, pts, sgn in ((h, a, hp2[k], 0.5), (a, h, ap2[k], -0.5)):
                rows.append((ix[t], ix[o], sgn * hm[k], t in self.fbs, o in self.fbs)); y.append(pts); ww.append(w[k])
        m = len(rows)
        # columns: mu, home, fcs_off, fcs_def, off[n], def[n]
        X = np.zeros((m, 4 + 2 * n))
        for r, (t, o, hs, tf, of) in enumerate(rows):
            X[r, 0] = 1; X[r, 1] = hs; X[r, 2] = 0 if tf else 1; X[r, 3] = 0 if of else 1
            X[r, 4 + t] = 1; X[r, 4 + n + o] = -1
        W = np.array(ww); y = np.array(y)
        P = np.diag([0, 0, 0, 0] + [self.lam] * (2 * n))
        A = X.T @ (X * W[:, None]) + P
        b = np.linalg.solve(A, X.T @ (W * y))
        self.mu, self.home, self.fcs_off, self.fcs_def = b[:4]
        self.off = {t: b[4 + i] for i, t in enumerate(teams)}; self.dfn = {t: b[4 + n + i] for i, t in enumerate(teams)}
        self.n_games = pd.concat([g.home_id, g.away_id])[np.concatenate([g.season.values, g.season.values]) == season].value_counts().to_dict()
        return self

    def _o(self, t): return self.off.get(t, 0.0) + (0 if t in self.fbs else self.fcs_off)
    def _d(self, t): return self.dfn.get(t, 0.0) - (0 if t in self.fbs else self.fcs_def)

    def rating(self, t): return self._o(t) + self._d(t)

    def points(self, home, away, neutral):
        h = 0 if neutral else self.home / 2
        return self.mu + h + self._o(home) - self._d(away), self.mu - h + self._o(away) - self._d(home)

    def predict(self, df):
        """Expected home margin and total for rows with home_id, away_id, neutral."""
        p = np.array([self.points(h, a, n) for h, a, n in zip(df.home_id, df.away_id, df.neutral)])
        return p[:, 0] - p[:, 1], p[:, 0] + p[:, 1]


def p_cover(margin, line, sd=SD_MARGIN):
    """Chance the home side covers a home spread `line` (home -7 is line=-7): margin + line > 0. Half-points only."""
    return _cdf((margin + line) / sd)


def p_win(margin, sd=SD_MARGIN): return _cdf(margin / sd)
def p_over(total, line, sd=SD_TOTAL): return 1 - _cdf((line - total) / sd)
