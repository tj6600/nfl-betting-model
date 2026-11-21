"""Small numeric helpers (no scipy in scheduled runs): Poisson GLM by IRLS, negative binomial and Poisson tails, odds math."""
import math
import numpy as np


def poisson_glm(X, y, w=None, ridge=1e-4, iters=50, offset=None):
    """Log-link Poisson regression. X must include an intercept column. Returns coefficients."""
    X = np.asarray(X, float); y = np.asarray(y, float)
    w = np.ones(len(y)) if w is None else np.asarray(w, float)
    off = np.zeros(len(y)) if offset is None else np.asarray(offset, float)
    b = np.zeros(X.shape[1]); b[0] = math.log(max(y.mean(), 1e-6)) - off.mean()
    for _ in range(iters):
        eta = X @ b + off
        mu = np.exp(np.clip(eta, -20, 20))
        z = X @ b + (y - mu) / mu
        W = w * mu
        A = X.T @ (X * W[:, None]) + ridge * np.eye(X.shape[1])
        nb = np.linalg.solve(A, X.T @ (W * z))
        if np.max(np.abs(nb - b)) < 1e-8:
            b = nb; break
        b = nb
    return b


def nb_size(y, mu):
    """Method-of-moments negative binomial size r (var = mu + mu^2 / r). Large r = Poisson."""
    y = np.asarray(y, float); mu = np.asarray(mu, float)
    excess = np.mean((y - mu) ** 2 - mu)
    return float(np.sum(mu ** 2) / len(mu) / excess) if excess > 0 else 1e6


def nb_cdf(k, mu, r):
    """P(X <= k) for X ~ NB(mean mu, size r). Vectorised over mu, scalar k and r."""
    mu = np.atleast_1d(np.asarray(mu, float))
    out = np.zeros_like(mu)
    k = int(math.floor(k))
    if k < 0:
        return out
    p = r / (r + mu)                     # success prob
    lp0 = r * np.log(p)
    term = np.exp(lp0)
    out = term.copy()
    for i in range(1, k + 1):
        term = term * (i - 1 + r) / i * (1 - p)
        out = out + term
    return np.clip(out, 0, 1)


def p_over(line, mu, r):
    """P(X > line) for a half-point line (e.g. 2.5 -> P(X >= 3))."""
    return 1 - nb_cdf(math.floor(line), mu, r)


def am_to_prob(a):
    a = np.asarray(a, float)
    return np.where(a < 0, -a / (-a + 100), 100 / (a + 100))


def am_to_dec(a):
    a = np.asarray(a, float)
    return np.where(a < 0, 1 + 100 / -a, 1 + a / 100)


def novig(p1, p2):
    s = p1 + p2
    return p1 / s, p2 / s
