"""Suggested parlays, logged when a board builds and graded later as whole parlays.

The board pages build their suggestions in the browser (board/nba_app.js, board/nhl_app.js); suggest() is the
same rule in Python so each day's suggestions can be saved and graded:
  * pools: 'value' = the board's pool (Value legs by edge, then near-value);
           'likely' = legs 55%+ to hit that still pay more than they risk (edge 1+ pt), no flags, by chance.
  * a slip takes the best remaining legs: one per player, up to perGame legs a game (1 unless the slate is too
    small to fill the slip), at most half the slip from one market family when the pool allows, and legs in no_sgp
    markets never share a game. Legs are used once across the 6 suggestions; when that runs out a leg may appear in up
    to 3, so each size shows 6 different slips whenever the pool allows (see many()).
  * best = the leg count whose first suggestion has the highest Kelly growth with each chance cut 2 pts
    (1 = straight bet when no parlay grows a bankroll).

Grading: a parlay loses if any leg loses; otherwise it wins at the product of its winning legs' DraftKings prices
(push and void legs drop out, as books do). Units are per 1 unit staked.
"""
import os, json, glob, math

SIZES = [1, 2, 3, 4, 5, 6, 11]
# NBA/NHL (Thomas, 2026-11-16): live grading had 3+ leg NBA parlays 0 for ~200 and every leg's chance overrated, so
# NBA/NHL suggestions stop at 3 legs, no leg is heavier than -200, and 'likely' legs are judged on their chance at a
# normal price (edge >= -3 pts, i.e. no worse than DraftKings' usual juice) instead of a model edge
SHORT_SIZES = [1, 2, 3]
MAX_JUICE = -200


def likely(L):
    """NBA/NHL Most likely to hit pool: 55%+ to hit, -200 or longer, normal juice at most, no flags (NHL adds winner picks)."""
    return L['p'] >= 0.55 and L['price'] >= MAX_JUICE and L['edge'] >= -3 and not L['flags']


def dec(a): return 1 + a / 100 if a > 0 else 1 + 100 / -a


def growth(slip):
    p = math.prod(max(0.01, L['p'] - 0.02) for L in slip); b = math.prod(dec(L['price']) for L in slip) - 1
    f = (b * p - (1 - p)) / b
    return 0.0 if f <= 0 else p * math.log(1 + f * b) + (1 - p) * math.log(1 - f)


def fam(L):
    """Market family, for mixing markets within a slip (alt and main lines of a stat are the same family)."""
    if L['kind'] == 'Milestone': return L['key'].rsplit('-', 1)[-1].lower()             # NFL alt ladders: key 'pid-Rec'
    k = L['kind'].lower(); k = k[4:] if k.startswith('alt ') else k
    return 'shots' if k == 'shots on goal' else k


def many(pool, size, n, pick):
    """Up to n slips. Each slip mixes markets (at most half its legs from one market family) when the pool allows it.
    Legs are used once across the n suggestions first; when that runs out, a leg may appear in up to 3 suggestions
    (least-used legs first) so each size still shows n different slips when the pool allows (Thomas, 2026-11-14).
    pick(pool, size, allowed(L) -> bool, cap) returns a slip (list of legs) or None."""
    out, uses, seen = [], {}, set()
    cap = size if size < 2 else math.ceil(size / 2)
    for _ in range(n):
        slip = None
        for mx, c in ((0, cap), (0, size), (1, cap), (1, size), (2, cap), (2, size)):
            cand = sorted(pool, key=lambda L: uses.get(L['id'], 0)) if mx else pool
            s = pick(cand, size, lambda L, mx=mx: uses.get(L['id'], 0) <= mx, c)
            if s and frozenset(L['id'] for L in s) not in seen:
                slip = s; break
        if not slip: break
        seen.add(frozenset(L['id'] for L in slip)); out.append(slip)
        for L in slip: uses[L['id']] = uses.get(L['id'], 0) + 1
    return out


def build(pool, size, n=6, no_sgp=()):
    nG = len({L['game'] for L in pool})
    per = min(3, max(3 if size > 6 else 1, math.ceil(size / max(1, nG))))

    def pick(pool, size, allowed, cap):
        slip, g, pl, fm = [], {}, set(), {}
        for L in pool:
            if not allowed(L) or g.get(L['game'], 0) >= per or (L.get('pid') and L['pid'] in pl) or fm.get(fam(L), 0) >= cap: continue
            if g.get(L['game'], 0) and (L['kind'] in no_sgp or any(x['game'] == L['game'] and x['kind'] in no_sgp for x in slip)): continue
            slip.append(L); g[L['game']] = g.get(L['game'], 0) + 1; fm[fam(L)] = fm.get(fam(L), 0) + 1
            if L.get('pid'): pl.add(L['pid'])
            if len(slip) >= size: return slip
        return None
    return many(pool, size, n, pick)


SECURE = 0.60   # an Over main line under 60% gives way to the same player's likeliest fairly priced alt line at 60%+ (as for NFL)


def _alt_tools(legs):
    """NBA/NHL alt lines (alt=True, Over only, edge in points): the safer() swap and the 70%+ alt-first list."""
    alts = {}
    for L in legs:
        if L.get('alt') and not L.get('flags') and L['p'] >= SECURE and L['edge'] >= -3 and L['price'] >= MAX_JUICE:
            alts.setdefault((L.get('pid'), L.get('market')), []).append(L)
    for xs in alts.values(): xs.sort(key=lambda x: -x['p'])

    def safer(L):
        if L.get('alt') or L.get('side') != 'Over' or L['p'] >= SECURE: return L
        return next((a for a in alts.get((L.get('pid'), L.get('market')), []) if a['p'] > L['p']), L)
    first = sorted([L for L in legs if L.get('alt') and not L.get('flags') and L['p'] >= ALT_FIRST_P and L['edge'] >= -ALT_JUICE_PTS and L['price'] >= MAX_JUICE],
                   key=lambda L: (-L['p'], -L['edge']))
    return safer, first


def _dedupe(xs):
    seen = set(); return [L for L in xs if not (L['id'] in seen or seen.add(L['id']))]


def suggest(legs, pool_ids, likely, no_sgp=()):
    """legs: the board's legs; pool_ids: the value pool in order; likely(L) -> bool for the likely pool.
    Same as the page (board/nba_app.js, nhl_app.js): shaky Overs swap to a safer alt line, and Most likely to hit
    slips of 3+ legs lead with alt lines that are 70%+ (up to 3 pts juice, -500 or longer)."""
    by = {L['id']: L for L in legs}
    safer, first = _alt_tools(legs)
    pools = {'value': _dedupe([safer(by[i]) for i in pool_ids if i in by]),
             'likely': _dedupe([safer(L) for L in sorted([L for L in legs if likely(L)], key=lambda L: (-L['p'], -L['edge']))])}
    pools = {k: [L for L in v if L['price'] >= MAX_JUICE] for k, v in pools.items()}   # no leg heavier than -200

    def builder(pool, k):
        if pool is pools['likely'] and k >= ALT_FIRST_SIZE: pool = _dedupe(first + pool)
        return build(pool, k, no_sgp=no_sgp)
    return _pack(pools, builder, SHORT_SIZES)


# ---- NFL: the same rules as board/app.js (sugPool, safer, buildSlips) for the whole week and every market ----
def nfl_pools(legs):
    legs = [dict(L, price=L['offers']['DraftKings']) for L in legs if 'DraftKings' in L['offers']]
    ok = lambda L: not L.get('flag')
    alts = {}
    for L in legs:
        if L.get('alt') and ok(L) and L['p'] >= 0.55 and L['edge'] >= -0.02: alts.setdefault(L['key'], []).append(L)
    for xs in alts.values(): xs.sort(key=lambda x: -x['p'])

    def safer(L):   # a shaky Over (under 60%) gives way to the same player's 60%+ fairly priced alt line
        if L.get('alt') or L['kind'] not in ('Rush', 'Rec', 'Recs', 'Pass') or L['sl'] != 'Over' or L['p'] >= 0.6: return L
        return next((a for a in alts.get(L['key'], []) if a['p'] >= 0.6 and a['edge'] >= 0 and a['p'] > L['p']), L)

    def dedupe(xs):
        seen = set(); return [L for L in xs if not (L['id'] in seen or seen.add(L['id']))]
    likely = sorted([safer(L) for L in legs if ok(L) and L['p'] >= 0.55 and (L['edge'] >= 0 if L.get('alt') else L['edge'] >= 0.01)],
                    key=lambda L: (-L['p'], -L['edge']))
    v = sorted([L for L in legs if ok(L) and L['p'] >= 0.55 and L['edge'] >= 0.03], key=lambda L: -L['edge'])
    nv = sorted([L for L in legs if ok(L) and not (L['p'] >= 0.55 and L['edge'] >= 0.03) and L['p'] >= 0.52 and L['edge'] >= 0.015], key=lambda L: -L['edge'])
    pools = {'value': dedupe([safer(L) for L in v + nv]), 'likely': dedupe(likely)}
    # 3+ leg slips lead with alternate lines that are 70%+ (up to 3 pts juice, -500 or longer), likeliest first (Thomas, 2026-11-13: bigger
    # 'Most likely to hit' parlays should be built from alt lines so each leg is likely to hit); the mode's own pool fills in after them
    pools['_alt_first'] = sorted([L for L in legs if L.get('alt') and ok(L) and L['p'] >= ALT_FIRST_P and L['edge'] >= -ALT_JUICE_PTS / 100 and L['price'] >= ALT_MIN_PRICE], key=lambda L: (-L['p'], -L['edge']))
    return pools


ALT_FIRST_P, ALT_FIRST_SIZE = 0.70, 3
# Thomas, 2026-11-15: DraftKings' 70%+ alt rungs are almost never fairly priced, so allow up to 3 pts of juice
# (NBA/NHL edges are in points, NFL's are fractions), but no shorter than -500 so each rung still adds payout
ALT_JUICE_PTS, ALT_MIN_PRICE = 3, -500


def nfl_build(pool, size, n=6):
    nG = len({L['game'] for L in pool}); one = nG == 1
    per = size if one else min(3, max(3 if size > 6 else 1, math.ceil(size / max(1, nG))))

    def pick(pool, size, allowed, cap):
        out, g, gl, team, fm = [], {}, set(), {}, {}
        for L in pool:
            if not allowed(L) or g.get(L['game'], 0) >= per or fm.get(fam(L), 0) >= cap: continue
            if any(x['key'] == L['key'] or (x['kind'] != 'Game' and L['kind'] != 'Game' and x['who'] == L['who']) for x in out): continue
            if L['kind'] == 'Game':
                if L['game'] in gl: continue
                gl.add(L['game'])
            elif one and size <= 3:
                t = L.get('team') or ''
                if team.get(t, 0) >= 2: continue
                team[t] = team.get(t, 0) + 1
            out.append(L); g[L['game']] = g.get(L['game'], 0) + 1; fm[fam(L)] = fm.get(fam(L), 0) + 1
            if len(out) >= size: return out
        return None
    return many(pool, size, n, pick)


def nfl_suggest(legs):
    pools = nfl_pools(legs); alt_first = pools.pop('_alt_first')
    def builder(pool, size, n=6):
        if pool is pools['likely'] and size >= ALT_FIRST_SIZE:   # Most likely to hit only; Best value is unchanged
            seen = set(); pool = [L for L in alt_first + pool if not (L['id'] in seen or seen.add(L['id']))]
        return nfl_build(pool, size, n)
    return _pack(pools, builder)


def _name(L): return L['label'] if L['kind'] == 'Game' or not L.get('who') else f"{L['who']} {L['label']}"


def _pack(pools, builder, sizes_=SIZES):
    out = {}
    for mode, pool in pools.items():
        slips = {k: builder(pool, k) for k in sizes_}
        sizes = [k for k in sizes_ if slips[k]]
        ps = [k for k in sizes if k > 1 and growth(slips[k][0]) > 0]
        best = max(ps, key=lambda k: growth(slips[k][0])) if ps else (1 if 1 in sizes else None)
        out[mode] = dict(best=best, slips={str(k): [[dict(id=L['id'], label=_name(L), game=L['game'], price=int(L['price']), p=L['p']) for L in s]
                                                    for s in slips[k]] for k in sizes})
    return out


CAL_BINS = [(0, .45), (.45, .5), (.5, .55), (.55, .6), (.6, .65), (.65, .7), (.7, .8), (.8, .9), (.9, 1.01)]


def calibration(ps, wins):
    """Do the board's chances match what happened? ps: chances given, wins: 1/0 results (graded legs, both sides of
    every line). One row per chance bucket; a well calibrated board hits about as often as it said (Thomas, 2026-11-16)."""
    out = []
    for lo, hi in CAL_BINS:
        xs = [(p, w) for p, w in zip(ps, wins) if lo <= p < hi]
        if xs:
            out.append(dict(bucket=f'{round(lo * 100)}-{min(100, round(hi * 100))}%', n=len(xs), said=sum(p for p, _ in xs) / len(xs),
                            hit=sum(w for _, w in xs) / len(xs)))
    return out


def log(dirpath, day, stamp, legs, pool_ids=None, likely=None, no_sgp=(), nfl=False):
    """Write <dirpath>/parlays/<day>_<stamp>.json once per odds snapshot (NFL: day = '2026_wk10')."""
    d = os.path.join(dirpath, 'parlays'); os.makedirs(d, exist_ok=True)
    f = os.path.join(d, f'{day}_{stamp}.json')
    if not os.path.exists(f):
        json.dump(nfl_suggest(legs) if nfl else suggest(legs, pool_ids, likely, no_sgp), open(f, 'w'))
    return f


def grade(dirpath, results, dates=None, when=None):
    """results: {(day, leg_id): 'win'|'loss'|'push'|'void'} for graded legs.
    Uses the earliest parlay log of each day. Returns a report dict for the Model record tab.
    dates: keep only parlays whose date is in this set (the Model record's day/week/month menus); the date is
    when(day, slip) if given (NFL: the day of the slip's last game), else the log's day."""
    logs = {}
    for f in sorted(glob.glob(os.path.join(dirpath, 'parlays', '*.json'))):
        logs.setdefault(os.path.basename(f).rsplit('_', 1)[0], f)
    rows = []
    for day, f in logs.items():
        S = json.load(open(f))
        for mode, m in S.items():
            for k, slips in m['slips'].items():
                for i, s in enumerate(slips):
                    res = [results.get((day, L['id'])) for L in s]
                    if 'loss' in res: out, units = 'lost', -1.0
                    elif any(r is None for r in res): continue          # not graded yet
                    else:
                        live = [L for L, r in zip(s, res) if r == 'win']
                        out, units = ('push', 0.0) if not live else ('won', math.prod(dec(L['price']) for L in live) - 1)
                    if dates is not None and (when(day, s) if when else day) not in dates: continue
                    rows.append(dict(day=day, mode=mode, size=int(k), idx=i, best=int(k) == m['best'], result=out, units=units,
                                     p=math.prod(L['p'] for L in s), payout=math.prod(dec(L['price']) for L in s) - 1))
    groups = []

    def grp(name, x):
        x = [r for r in x if r['result'] != 'push']
        if not x: return
        w = sum(r['result'] == 'won' for r in x); u = sum(r['units'] for r in x)
        groups.append(dict(group=name, bets=len(x), won=w, lost=len(x) - w, hit=w / len(x), exp_hit=sum(r['p'] for r in x) / len(x),
                           units=round(u, 2), roi=u / len(x)))
    for mode, name in [('value', 'Best value'), ('likely', 'Most likely to hit')]:
        grp(f'{name}: ★ suggestion', [r for r in rows if r['mode'] == mode and r['best'] and r['idx'] == 0])
        for k in SIZES:
            grp(f'{name}: {"straight" if k == 1 else f"{k}-leg"} (all suggestions)', [r for r in rows if r['mode'] == mode and r['size'] == k])
    return dict(days=sorted({r['day'] for r in rows}) if dates is not None else sorted(logs), groups=groups)
