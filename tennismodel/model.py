"""Tennis match model: Elo ratings per player, overall and per surface (the FiveThirtyEight / Sackmann approach).

- K shrinks with experience: K = k0 / (matches + offset) ** shape, so a new player's rating moves fast and a veteran's slowly.
- A match updates both the overall rating and the surface rating; a prediction blends them (SURF_W on the surface one).
- Walkovers are skipped. Retirements count, at half weight (the loser was often hurt, not beaten).
- Best-of-five (men's majors, main draw) stretches the gap: the better player wins more often over five sets.
- Each tour is rated separately; a new player starts at START (below the tour average, since most start in qualifying).

Elo.fit(matches) walks the matches in time order; p() gives P(player 1 beats player 2) BEFORE each match, so a backtest on the
same pass is out of sample.
"""
import math
import numpy as np, pandas as pd

START = 1500.0
PARAMS = dict(k0=200.0, offset=20.0, shape=0.4, surf_w=0.3, bo5=1.15, ret_w=0.5)


def p_elo(d):
    return 1.0 / (1.0 + 10 ** (-d / 400.0))


class Elo:
    def __init__(self, **kw):
        self.k = dict(PARAMS, **kw)
        self.r, self.rs, self.n, self.ns = {}, {}, {}, {}
        self.last = {}

    def _k(self, n):
        return self.k['k0'] / (n + self.k['offset']) ** self.k['shape']

    def diff(self, a, b, surface):
        ra, rb = self.r.get(a, START), self.r.get(b, START)
        sa, sb = self.rs.get((a, surface), ra), self.rs.get((b, surface), rb)
        w = self.k['surf_w']
        return (1 - w) * (ra - rb) + w * (sa - sb)

    def p(self, a, b, surface, bo5=False):
        d = self.diff(a, b, surface)
        return p_elo(d * (self.k['bo5'] if bo5 else 1.0))

    def update(self, a, b, surface, a_won, weight=1.0):
        for key, R, N in ((None, self.r, self.n), (surface, self.rs, self.ns)):
            ka, kb = (a, key) if key else a, (b, key) if key else b
            ra = R.get(ka, self.r.get(a, START) if key else START)
            rb = R.get(kb, self.r.get(b, START) if key else START)
            e = p_elo(ra - rb)
            s = 1.0 if a_won else 0.0
            R[ka] = ra + weight * self._k(N.get(ka, 0)) * (s - e)
            R[kb] = rb + weight * self._k(N.get(kb, 0)) * ((1 - s) - (1 - e))
            N[ka] = N.get(ka, 0) + 1; N[kb] = N.get(kb, 0) + 1

    def fit(self, M, record=False):
        """Walk matches M (one tour, time order). With record=True returns the pre-match P(p1 wins) for each row."""
        out = np.full(len(M), np.nan)
        for i, x in enumerate(M.itertuples(index=False)):
            if x.status == 'STATUS_WALKOVER' or x.winner not in (1, 2):
                continue
            bo5 = is_bo5(x)
            if record:
                out[i] = self.p(x.p1, x.p2, x.surface, bo5)
            self.update(x.p1, x.p2, x.surface, x.winner == 1, self.k['ret_w'] if x.status == 'STATUS_RETIRED' else 1.0)
            self.last[x.p1] = self.last[x.p2] = x.ts
        return out if record else self

    def rating(self, a, surface=None):
        r = self.r.get(a, START)
        if surface is None: return r
        w = self.k['surf_w']
        return (1 - w) * r + w * self.rs.get((a, surface), r)


def is_bo5(x):
    return bool(x.major) and x.tour == 'atp' and not str(x.round).startswith('Qualifying') and 'Olympic' not in str(x.event)


def fit_all(M, **kw):
    """One Elo per tour, fit on all of M. Returns {tour: Elo}."""
    return {t: Elo(**kw).fit(M[M.tour == t]) for t in M.tour.unique()}


def backtest_probs(M, **kw):
    """Pre-match P(p1 wins) for every row of M, each tour walked separately (out of sample)."""
    p = pd.Series(np.nan, index=M.index)
    for t in M.tour.unique():
        m = M[M.tour == t]
        p.loc[m.index] = Elo(**kw).fit(m, record=True)
    return p
