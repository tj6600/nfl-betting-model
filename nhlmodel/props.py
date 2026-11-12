"""Shots-on-goal and goalie-saves projections.

Both are count models: a Poisson regression gives the expected count, and a negative binomial with a fitted
size gives the chance of going over a line. Fit on earlier seasons, predict forward.
"""
import re, unicodedata
import numpy as np
import pandas as pd
from nhlmodel.features import skater_features, sog_design, goalie_features, saves_design, SOG_X, SAVE_X
from nhlmodel.stats import poisson_glm, nb_size


def norm_name(s):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'[^a-z ]', '', s.replace('-', ' '))
    s = re.sub(r'\b(jr|sr|ii|iii)\b', '', s)
    return ' '.join(s.split())


class SogModel:
    def fit(self, sk_feat, lm, mask):
        X = sog_design(sk_feat, lm)
        ok = mask & (sk_feat.n_prior >= 10) & (sk_feat.toi >= 5) & X.notna().all(axis=1)
        self.b = poisson_glm(X[ok].values, sk_feat.sog[ok].values)
        mu = np.exp(X[ok].values @ self.b)
        self.r = nb_size(sk_feat.sog[ok].values, mu)
        self.lm = lm
        return self

    def mu(self, sk_feat):
        X = sog_design(sk_feat, self.lm).fillna(0)
        return np.exp(X.values @ self.b)


class SavesModel:
    """Expected saves = expected shots against x projected save rate, then a pull-risk haircut."""
    def fit(self, st, lm, mask):
        X = saves_design(st, lm)
        ok = mask & (st.n_starts >= 3) & X.notna().all(axis=1)
        # shots against for full games only, so pulls don't bias the shot model
        full = ok & (st.toi >= 55)
        self.b = poisson_glm(X[full].values, st.shots_against[full].values)
        self.lm = lm
        mu = self._mu(st)
        self.r = nb_size(st.saves[ok].values, mu[ok.values])
        return self

    def _mu(self, st):
        X = saves_design(st, self.lm).fillna(0)
        shots = np.exp(X.values @ self.b)
        pull = st.g_pull.fillna(0.1).clip(0, 0.4).values
        return shots * st.sv_hat.values * (1 - 0.45 * pull)   # a pulled starter keeps ~55% of his saves

    def mu(self, st):
        return self._mu(st)
