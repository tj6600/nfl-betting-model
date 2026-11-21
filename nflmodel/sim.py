"""Game simulation for same-game parlays (NFL, NHL): a Gaussian copula fit on free game data.

Each bet in a game is driven by one hidden "game outcome" number: the home team's margin against the spread, the
total against the line, or a player's stat against what was expected of him going in (passing, rushing, receiving
yards, receptions, anytime TD; NHL goals, shots on goal). Those numbers are drawn together, with the correlations
measured on past games (sim_fit.py), so a QB's yards and his top receiver's yards rise and fall together, a big win
goes with more rushing, and so on. Each leg hits when its number lands past the point that matches its own chance,
so every leg keeps exactly the chance the board gives it; only how the legs move together changes.

The page runs the same simulation (board/site/sim.js, 20,000 seeded draws per game). Legs from different games are
independent. numpy only (scheduled runs can't always install scipy).
"""
import math
import numpy as np

SQ2 = math.sqrt(2.0)


def _erf(x):
    """Vectorized erf (Abramowitz-Stegun 7.1.26 |error| < 1.5e-7)."""
    x = np.asarray(x, dtype=float); s = np.sign(x); x = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * x)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * np.exp(-x * x)
    return s * y


def Phi(x):
    return 0.5 * (1.0 + _erf(np.asarray(x, dtype=float) / SQ2))


def phi(x):
    x = np.asarray(x, dtype=float)
    return np.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def ndtri(p):
    """Inverse standard normal CDF (Acklam's rational approximation, |error| < 1.2e-9 after one Newton step)."""
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    q = np.where(p < 0.5, p, 1 - p)
    lo = q < 0.02425
    t = np.sqrt(-2 * np.log(np.where(lo, q, 0.5)))
    x_lo = (((((c[0] * t + c[1]) * t + c[2]) * t + c[3]) * t + c[4]) * t + c[5]) / ((((d[0] * t + d[1]) * t + d[2]) * t + d[3]) * t + 1)
    r = (q - 0.5) ** 2; u = q - 0.5
    x_mid = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * u / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    x = np.where(lo, x_lo, x_mid)   # value for q (<= 0.5), negative
    e = Phi(x) - q; x = x - e / np.maximum(phi(x), 1e-300)
    return np.where(p < 0.5, x, -x)


_GL = np.polynomial.legendre.leggauss(40)


def bvn_upper(a, b, rho):
    """P(X > a, Y > b) for standard bivariate normals with correlation rho (vectorized, Gauss-Legendre over x)."""
    a, b, rho = np.broadcast_arrays(np.asarray(a, float), np.asarray(b, float), np.asarray(rho, float))
    lo = np.clip(a, -8, 8); hi = 8.0
    xs, ws = _GL
    x = (hi - lo)[..., None] / 2 * xs + (hi + lo)[..., None] / 2   # nodes on [a, 8]
    s = np.sqrt(np.maximum(1 - rho * rho, 1e-12))[..., None]
    f = phi(x) * (1 - Phi((b[..., None] - rho[..., None] * x) / s))
    return ((hi - lo) / 2) * (f * ws).sum(-1)


def nearest_pd(C, floor=1e-4):
    """Make a correlation matrix positive definite (clip eigenvalues, rescale the diagonal to 1)."""
    C = (C + C.T) / 2
    w, V = np.linalg.eigh(C)
    if w.min() >= floor: return C
    C2 = V @ np.diag(np.maximum(w, floor)) @ V.T
    d = np.sqrt(np.diag(C2)); return C2 / np.outer(d, d)


_Z = {}


def draws(k, n=20000, seed=7):
    if (k, n) not in _Z: _Z[(k, n)] = np.random.default_rng(seed + k).standard_normal((n, k))
    return _Z[(k, n)]


def joint(ps, dirs, C, n=20000):
    """Chance that every leg hits. ps: each leg's own chance; dirs: +1 when the leg hits on a high draw (Over, Yes,
    the home side), -1 on a low one; C: correlation matrix of the legs' hidden numbers (before the direction)."""
    ps = np.asarray(ps, float); dirs = np.asarray(dirs, float); k = len(ps)
    if k == 1: return float(ps[0])
    C = nearest_pd(np.asarray(C, float) * np.outer(dirs, dirs) + np.eye(k) * 0)
    np.fill_diagonal(C, 1.0)
    if k == 2: return float(bvn_upper(ndtri(1 - ps[0]), ndtri(1 - ps[1]), C[0, 1]))
    L = np.linalg.cholesky(nearest_pd(C))
    Z = draws(k, n) @ L.T
    return float((Z > ndtri(1 - ps)).all(1).mean())
