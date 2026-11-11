"""Normal distribution helpers without scipy (scheduled runs can't always install it)."""
import math
import numpy as np

_erf = np.frompyfunc(math.erf, 1, 1)


class norm:
    @staticmethod
    def cdf(x, loc=0.0, scale=1.0):
        z = (np.asarray(x, dtype=float) - np.asarray(loc, dtype=float)) / (np.asarray(scale, dtype=float) * math.sqrt(2))
        out = 0.5 * (1 + np.asarray(_erf(z), dtype=float))
        return out if np.ndim(out) else float(out)
