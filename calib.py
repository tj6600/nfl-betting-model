"""Calibration sections for the Model record tabs (NFL, NBA, NHL), one section per leg type (Thomas, 2026-11-17).

Each section answers: when the board gave a side a chance of 50-60%, 60-70%, ... how often did that side win?
The page draws one bar per chance bucket (the actual hit rate) with a dashed line at the chance the board gave.

rows: dicts with p (the chance the board gave the side it chose), won (True/False; pushes and voids are left out)
and units (profit for 1 unit at the logged DraftKings price).
"""

# a chosen side is the one the board gave 50%+, so its buckets start at 50%; one-sided bets (anytime TDs, alt rungs)
# can be any chance, so they use the full range
BINS_PICK = [(0, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01)]
BINS_ALL = [(0, .1), (.1, .2), (.2, .3), (.3, .4), (.4, .5), (.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01)]


def section(name, rows, note=None, picked=True):
    """One section: totals plus a bucket per 10 points of chance. picked=True: every row is the side the board favored."""
    rows = [r for r in rows if r.get('won') is not None and r.get('p') == r.get('p') and r.get('p') is not None]
    if not rows: return None
    bins = BINS_PICK if picked else BINS_ALL
    buckets = []
    for lo, hi in bins:
        x = [r for r in rows if lo <= r['p'] < hi]
        if not x: continue
        w = sum(bool(r['won']) for r in x)
        buckets.append(dict(label=f'{50 if picked and lo == 0 else round(lo * 100)}–{min(100, round(hi * 100))}%', n=len(x), won=w, lost=len(x) - w,
                            said=round(float(sum(r['p'] for r in x)) / len(x), 4), hit=round(w / len(x), 4), units=round(float(sum(r['units'] for r in x)), 2)))
    w = sum(bool(r['won']) for r in rows); u = float(sum(r['units'] for r in rows))
    return dict(name=name, note=note, n=len(rows), won=w, lost=len(rows) - w, said=round(float(sum(r['p'] for r in rows)) / len(rows), 4),
                hit=round(w / len(rows), 4), units=round(u, 2), roi=round(u / len(rows), 4), buckets=buckets)


def favored(rows, key):
    """Keep the side the board gave the bigger chance in each group of rows sharing key(row) (both sides of a line are logged)."""
    best = {}
    for r in rows:
        k = key(r)
        if k not in best or r['p'] > best[k]['p']: best[k] = r
    return list(best.values())


def sections(*specs):
    """specs: (name, rows, note, picked) tuples -> the non-empty sections, in order."""
    return [s for s in (section(*sp) for sp in specs) if s]


def dec(a): return 1 + a / 100 if a > 0 else 1 + 100 / -a
