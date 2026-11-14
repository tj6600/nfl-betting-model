"""Suggested parlays, logged when a board builds and graded later as whole parlays.

The board pages build their suggestions in the browser (board/nba_app.js, board/nhl_app.js); suggest() is the
same rule in Python so each day's suggestions can be saved and graded:
  * pools: 'value' = the board's pool (Value legs by edge, then near-value);
           'likely' = legs 55%+ to hit that still pay more than they risk (edge 1+ pt), no flags, by chance.
  * a slip takes the best remaining legs: one per player, up to perGame legs a game (1 unless the slate is too
    small to fill the slip), no leg reused across the 6 suggestions, and legs in no_sgp markets never share a game.
  * best = the leg count whose first suggestion has the highest Kelly growth with each chance cut 2 pts
    (1 = straight bet when no parlay grows a bankroll).

Grading: a parlay loses if any leg loses; otherwise it wins at the product of its winning legs' DraftKings prices
(push and void legs drop out, as books do). Units are per 1 unit staked.
"""
import os, json, glob, math

SIZES = [1, 2, 3, 4, 5, 6, 11]


def dec(a): return 1 + a / 100 if a > 0 else 1 + 100 / -a


def growth(slip):
    p = math.prod(max(0.01, L['p'] - 0.02) for L in slip); b = math.prod(dec(L['price']) for L in slip) - 1
    f = (b * p - (1 - p)) / b
    return 0.0 if f <= 0 else p * math.log(1 + f * b) + (1 - p) * math.log(1 - f)


def build(pool, size, n=6, no_sgp=()):
    out, used = [], set()
    for _ in range(n):
        nG = len({L['game'] for L in pool})
        per = min(3, max(3 if size > 6 else 1, math.ceil(size / max(1, nG))))
        slip, g, pl = [], {}, set()
        for L in pool:
            if L['id'] in used or g.get(L['game'], 0) >= per or (L.get('pid') and L['pid'] in pl): continue
            if g.get(L['game'], 0) and (L['kind'] in no_sgp or any(x['game'] == L['game'] and x['kind'] in no_sgp for x in slip)): continue
            slip.append(L); g[L['game']] = g.get(L['game'], 0) + 1
            if L.get('pid'): pl.add(L['pid'])
            if len(slip) >= size: break
        if len(slip) < size: break
        used.update(L['id'] for L in slip); out.append(slip)
    return out


def suggest(legs, pool_ids, likely, no_sgp=()):
    """legs: the board's legs; pool_ids: the value pool in order; likely(L) -> bool for the likely pool."""
    by = {L['id']: L for L in legs}
    pools = {'value': [by[i] for i in pool_ids if i in by],
             'likely': sorted([L for L in legs if likely(L)], key=lambda L: (-L['p'], -L['edge']))}
    return _pack(pools, lambda pool, k: build(pool, k, no_sgp=no_sgp))


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
    # 3+ leg slips lead with alternate lines that are 70%+ and fairly priced, likeliest first (Thomas, 2026-11-13: bigger
    # 'Most likely to hit' parlays should be built from alt lines so each leg is likely to hit); the mode's own pool fills in after them
    pools['_alt_first'] = sorted([L for L in legs if L.get('alt') and ok(L) and L['p'] >= ALT_FIRST_P and L['edge'] >= 0], key=lambda L: (-L['p'], -L['edge']))
    return pools


ALT_FIRST_P, ALT_FIRST_SIZE = 0.70, 3


def nfl_build(pool, size, n=6):
    out, used = [], set()
    nG = len({L['game'] for L in pool}); one = nG == 1
    per = size if one else min(3, max(3 if size > 6 else 1, math.ceil(size / max(1, nG))))
    for _ in range(n):
        pick, g, gl, team = [], {}, set(), {}
        for L in pool:
            if len(pick) >= size: break
            if L['id'] in used or g.get(L['game'], 0) >= per: continue
            if any(x['key'] == L['key'] or (x['kind'] != 'Game' and L['kind'] != 'Game' and x['who'] == L['who']) for x in pick): continue
            if L['kind'] == 'Game':
                if L['game'] in gl: continue
                gl.add(L['game'])
            elif one and size <= 3:
                t = L.get('team') or ''
                if team.get(t, 0) >= 2: continue
                team[t] = team.get(t, 0) + 1
            pick.append(L); g[L['game']] = g.get(L['game'], 0) + 1
        if len(pick) < size: break
        used.update(L['id'] for L in pick); out.append(pick)
    return out


def nfl_suggest(legs):
    pools = nfl_pools(legs); alt_first = pools.pop('_alt_first')
    def builder(pool, size, n=6):
        if pool is pools['likely'] and size >= ALT_FIRST_SIZE:   # Most likely to hit only; Best value is unchanged
            seen = set(); pool = [L for L in alt_first + pool if not (L['id'] in seen or seen.add(L['id']))]
        return nfl_build(pool, size, n)
    return _pack(pools, builder)


def _name(L): return L['label'] if L['kind'] == 'Game' or not L.get('who') else f"{L['who']} {L['label']}"


def _pack(pools, builder):
    out = {}
    for mode, pool in pools.items():
        slips = {k: builder(pool, k) for k in SIZES}
        sizes = [k for k in SIZES if slips[k]]
        ps = [k for k in sizes if k > 1 and growth(slips[k][0]) > 0]
        best = max(ps, key=lambda k: growth(slips[k][0])) if ps else (1 if 1 in sizes else None)
        out[mode] = dict(best=best, slips={str(k): [[dict(id=L['id'], label=_name(L), game=L['game'], price=int(L['price']), p=L['p']) for L in s]
                                                    for s in slips[k]] for k in sizes})
    return out


def log(dirpath, day, stamp, legs, pool_ids=None, likely=None, no_sgp=(), nfl=False):
    """Write <dirpath>/parlays/<day>_<stamp>.json once per odds snapshot (NFL: day = '2026_wk10')."""
    d = os.path.join(dirpath, 'parlays'); os.makedirs(d, exist_ok=True)
    f = os.path.join(d, f'{day}_{stamp}.json')
    if not os.path.exists(f):
        json.dump(nfl_suggest(legs) if nfl else suggest(legs, pool_ids, likely, no_sgp), open(f, 'w'))
    return f


def grade(dirpath, results):
    """results: {(day, leg_id): 'win'|'loss'|'push'|'void'} for graded legs.
    Uses the earliest parlay log of each day. Returns a report dict for the Model record tab."""
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
            grp(f'{name}: {"straight" if k == 1 else f"{k}-leg"} (all 6 suggestions)', [r for r in rows if r['mode'] == mode and r['size'] == k])
    return dict(days=sorted(logs), groups=groups)
