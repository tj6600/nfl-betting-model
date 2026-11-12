"""NHL game model: moneyline and puck line (±1.5) chances.

1. A Poisson regression gives each team's expected regulation goals, not counting empty-net goals, from
   rolling xG and goals for and against, the opposing starting goalie's save rate, home ice and rest.
2. The two Poisson counts give the regulation margin before empty-net goals.
3. An empirical table, learned from past games, shows how empty-net goals move that margin. A one-goal lead
   turned into two about 40% of the time in 2024-26, which matters a lot for puck lines.
4. Ties go to overtime/shootout and finish with a one-goal margin.
"""
import numpy as np
import pandas as pd
from nhlmodel.features import team_form, league_means, opp_view, goalie_features
from nhlmodel.stats import poisson_glm

GAME_X = ['c', 'lg_xg', 'lg_g', 'opp_gk', 'is_home', 'b2b', 'opp_b2b']
MAXG = 12


def frame(games, go, tg):
    tf = team_form(tg)
    lm = league_means(tg)
    o = opp_view(tf)
    d = tf.merge(o[['game_id', 'opp', 'ot_xga', 'ot_ga', 'orest']], on=['game_id', 'opp'], how='left')
    st, _ = goalie_features(go, tg)
    gk = st[['game_id', 'team', 'sv_hat', 'player_id', 'full_name']].drop_duplicates(['game_id', 'team'])
    d = d.merge(gk.rename(columns={'team': 'opp', 'sv_hat': 'opp_sv', 'player_id': 'opp_gk_id', 'full_name': 'opp_gk_name'}),
                on=['game_id', 'opp'], how='left')
    d['lg_sv'] = st.lg_sv.iloc[0]
    # league scoring drifts between seasons, so rates are compared to the league's last ~40 days, not all-time
    day = tg.groupby('game_date')[['xgf', 'gf']].agg(['sum', 'count'])
    roll = lambda c: (day[(c, 'sum')].rolling(40, min_periods=5).sum().shift(1) /
                      day[(c, 'count')].rolling(40, min_periods=5).sum().shift(1))
    d['lg_xgf_now'] = d.game_date.map(roll('xgf')).fillna(lm['xgf'])
    d['lg_gf_now'] = d.game_date.map(roll('gf')).fillna(lm['gf'])
    return d, lm


def design(d, lm):
    X = pd.DataFrame(index=d.index)
    X['c'] = 1.0
    # attack x opposing defence, each relative to the current league rate (one coefficient each, to avoid overfitting)
    X['lg_xg'] = np.log(d.t_xgf.fillna(d.lg_xgf_now) / d.lg_xgf_now) + np.log(d.ot_xga.fillna(d.lg_xgf_now) / d.lg_xgf_now)
    X['lg_g'] = np.log(d.t_gf.fillna(d.lg_gf_now).clip(lower=1) / d.lg_gf_now) + np.log(d.ot_ga.fillna(d.lg_gf_now).clip(lower=1) / d.lg_gf_now)
    # goals allowed scale with (1 - save%): an .890 goalie allows ~10% more than a .900 one
    X['opp_gk'] = np.log((1 - d.opp_sv.fillna(d.lg_sv)) / (1 - d.lg_sv))
    X['is_home'] = d.is_home
    X['b2b'] = (d.rest == 1).astype(int)
    X['opp_b2b'] = (d.orest == 1).astype(int)
    return X[GAME_X]


def en_table(tg, mask):
    """P(final margin | regulation margin before empty-net goals), margins from the home side, -4..4."""
    t = tg[mask]
    h = t[t.is_home == 1].merge(t[t.is_home == 0][['game_id', 'gf_reg']], on='game_id', suffixes=('', '_a'))
    h = h[h.ot == 0]
    h['m0'] = h.gf_reg - h.gf_reg_a
    h['mf'] = h.gf - h.ga
    T = {}
    for m in range(-4, 5):
        if m == 0:
            continue
        s = h[h.m0 == m].mf
        T[m] = (s.value_counts() / len(s)).to_dict() if len(s) >= 30 else {m: 1.0}
    return T


class GameModel:
    def fit(self, games, go, tg, mask_season):
        self.d, self.lm = frame(games, go, tg)
        X = design(self.d, self.lm)
        ok = self.d.season.isin(mask_season) & (self.d.n_team >= 10) & X.notna().all(axis=1)
        # offset: the league's current non-empty-net regulation scoring rate
        self.reg_share = float(tg.gf_reg.sum() / tg.gf.sum())
        off = np.log(self.d.lg_gf_now * self.reg_share)
        self.b = poisson_glm(X[ok].values, self.d.gf_reg[ok].values, offset=off[ok].values)
        self.T = en_table(tg, tg.season.isin(mask_season))
        self.shared = 0.0
        self._fit_shared(ok)
        self.cal = (0.0, 1.0)
        self._fit_cal(ok)
        g = games[games.season.isin(mask_season)]
        self.ot_home = float((g[g.ot == 1].home_score > g[g.ot == 1].away_score).mean())
        return self

    def _fit_shared(self, ok):
        """Pick the shared share that best fits the training seasons' regulation margins (before empty nets)."""
        d = self.d[ok]
        lam = self.lam(d)
        h = d.assign(lam=lam)[d.is_home == 1][['game_id', 'lam', 'gf_reg']].merge(
            d.assign(lam=lam)[d.is_home == 0][['game_id', 'lam', 'gf_reg']], on='game_id', suffixes=('_h', '_a'))
        m0 = (h.gf_reg_h - h.gf_reg_a).values
        best = None
        for c in np.arange(0, 0.61, 0.05):
            self.shared = c
            ll = 0.0
            for lh, la, m in zip(h.lam_h.values, h.lam_a.values, m0):
                sh = c * min(lh, la)
                ll += np.log(max(self._skellam(lh - sh, la - sh).get(int(m), 1e-9), 1e-9))
            if best is None or ll > best[1]:
                best = (c, ll)
        self.shared = float(best[0])

    def _fit_cal(self, ok):
        """Logistic recalibration of the 'wins by 2+' chance, fit on the training seasons.
        The raw simulation overstates two-goal wins by ~3 points even in-sample."""
        self.ot_home = 0.53
        d = self.d[ok]
        lam = self.lam(d)
        h = d.assign(lam=lam)[d.is_home == 1][['game_id', 'lam', 'gf', 'ga']].merge(
            d.assign(lam=lam)[d.is_home == 0][['game_id', 'lam']], on='game_id', suffixes=('_h', '_a'))
        xs, ys = [], []
        for lh, la, mg in zip(h.lam_h, h.lam_a, h.gf - h.ga):
            f = self._raw(lh, la)
            for side, y in ((sum(p for m, p in f.items() if m >= 2), mg >= 2), (sum(p for m, p in f.items() if m <= -2), mg <= -2)):
                xs.append(np.log(side / (1 - side))); ys.append(float(y))
        x, y = np.array(xs), np.array(ys)
        a, b = 0.0, 1.0
        for _ in range(100):   # Newton steps for logistic regression on the logit
            p = 1 / (1 + np.exp(-(a + b * x)))
            g = np.array([np.sum(y - p), np.sum((y - p) * x)])
            w = p * (1 - p)
            H = np.array([[w.sum(), (w * x).sum()], [(w * x).sum(), (w * x * x).sum()]])
            a, b = np.array([a, b]) + np.linalg.solve(H, g)
        self.cal = (float(a), float(b))

    def _cal2(self, p):
        a, b = self.cal
        return 1 / (1 + np.exp(-(a + b * np.log(p / (1 - p)))))

    @staticmethod
    def _skellam(lh, la):
        from math import lgamma
        k = np.arange(MAXG + 1)
        lf = np.array([lgamma(i + 1) for i in k])
        ph = np.exp(k * np.log(lh) - lh - lf); pa = np.exp(k * np.log(la) - la - lf)
        j = np.outer(ph, pa); out = {}
        for i in k:
            for q in k:
                out[i - q] = out.get(i - q, 0) + j[i, q]
        return out

    def lam(self, d):
        off = np.log(d.lg_gf_now * self.reg_share).values
        return np.exp(design(d, self.lm).fillna(0).values @ self.b + off)

    def margin_pmf(self, lh, la):
        return self._raw(lh, la)

    def _raw(self, lh, la):
        # bivariate Poisson: a shared component (score effects push games toward ties) cancels in the margin,
        # so the margin is Skellam on the two rates minus the shared part
        sh = self.shared * min(lh, la)
        lh, la = lh - sh, la - sh
        k = np.arange(MAXG + 1)
        from math import lgamma
        lf = np.array([lgamma(i + 1) for i in k])
        ph = np.exp(k * np.log(lh) - lh - lf); pa = np.exp(k * np.log(la) - la - lf)
        joint = np.outer(ph, pa)
        m0 = {}
        for i in k:
            for j in k:
                m0[i - j] = m0.get(i - j, 0) + joint[i, j]
        final = {}
        for m, p in m0.items():
            if m == 0:
                final[1] = final.get(1, 0) + p * self.ot_home
                final[-1] = final.get(-1, 0) + p * (1 - self.ot_home)
            elif abs(m) <= 4:
                for mf, q in self.T[m].items():
                    final[mf] = final.get(mf, 0) + p * q
            else:
                final[m] = final.get(m, 0) + p
        return final

    def probs(self, lh, la):
        f = self.margin_pmf(lh, la)
        win = sum(p for m, p in f.items() if m > 0)
        cover_m15 = float(self._cal2(sum(p for m, p in f.items() if m >= 2)))          # home -1.5
        cover_p15 = 1 - float(self._cal2(sum(p for m, p in f.items() if m <= -2)))     # home +1.5
        return {'home_win': win, 'home_-1.5': cover_m15, 'home_+1.5': cover_p15,
                'total_mean': lh + la}
