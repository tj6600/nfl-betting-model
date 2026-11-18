"""Grade logged college football board legs (odds_log/cfb/picks/<week>_<stamp>.csv) against final scores.

Each leg is graded once, at the first DraftKings line and price the board showed for it that week (the spread model's
edge is against fresh lines, so the record follows the earliest price). Scores come from ESPN's scoreboard (free).
Writes odds_log/cfb/grade_report.json for the Model record tab and odds_log/cfb/leg_results.json for the Bank Builder.

  python scripts/cfb_grade.py [--no-fetch]
"""
import os, sys, glob, json, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pandas as pd
from cfbmodel import espn as E
import parlays as PZ, calib as CAL

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DIR = os.path.join(ROOT, 'odds_log', 'cfb')
ET = 'America/New_York'


def dec(a): return 1 + a / 100 if a > 0 else 1 + 100 / -a


SEC = {'moneyline': ('Moneyline picks', 'The team the board gave the better chance to win, every game.'),
       'spread': ('Spreads', 'The side the board favored on each DraftKings spread (half model, half DraftKings).'),
       'total': ('Totals', 'Over or Under, whichever DraftKings\' no-vig price favored (the board uses DraftKings\' chances for totals).')}


def main(fetch=True):
    if fetch:
        try: E.season(E.CURRENT)
        except Exception as e: print('ESPN refresh failed, grading from saved scores:', e)
    G = E.load([E.CURRENT]).set_index('espn_id')
    first = {}     # (week, leg id) -> the first logged row
    for f in sorted(glob.glob(os.path.join(DIR, 'picks', '*.csv'))):
        wk = os.path.basename(f).rsplit('_', 1)[0]
        for r in pd.read_csv(f, dtype={'gid': str}).to_dict('records'):
            first.setdefault((wk, r['id']), r)
    rows, results, wait = [], {}, []
    for (wk, lid), l in first.items():
        l['week'] = wk
        l['day'] = pd.Timestamp(l['start']).tz_convert(ET).strftime('%Y-%m-%d')
        g = G.loc[l['gid']] if l['gid'] in G.index else None
        if g is None or g.home_pts != g.home_pts:
            if g is not None and str(g.status) in ('STATUS_CANCELED', 'STATUS_POSTPONED'): results[(wk, lid)] = 'void'
            else: wait.append(l)
            continue
        mg = g.home_pts - g.away_pts
        if l['market'] == 'moneyline': x = mg if l['side'] == 'home' else -mg
        elif l['market'] == 'spread': x = (mg if l['side'] == 'home' else -mg) + l['line']
        else: x = (g.home_pts + g.away_pts - l['line']) * (1 if l['side'] == 'Over' else -1)
        if x == 0:
            results[(wk, lid)] = 'push'; continue
        won = x > 0
        results[(wk, lid)] = 'win' if won else 'loss'
        rows.append(dict(l, won=bool(won), units=(dec(l['price']) - 1) if won else -1.0))
    ALL = pd.DataFrame(rows)
    leg_day = {(r['week'], r['id']): r['day'] for r in first.values()}
    when = lambda wk, s: max((leg_day.get((wk, L['id'])) or '') for L in s) or None

    def fkey(r): return (r['week'], r['gid'], r['market'], abs(r['line']) if r['market'] == 'spread' else 0)

    def groups_of(r, R=None):
        g = []
        if r['pick']: g.append('Board winner picks')
        if r['cat'] == 'Value': g.append('Value spreads (model 3+ points off the line)')
        return g

    def report(days=None):
        R = ALL if days is None or not len(ALL) else ALL[ALL.day.isin(days)]
        out = dict(days=sorted(R.day.unique().tolist()) if len(R) else [], groups=[])
        if len(R):
            rr = R.to_dict('records')
            fav = CAL.favored(rr, fkey); favid = {id(x) for x in fav}
            buckets = {}
            for r in rr:
                for n in groups_of(r): buckets.setdefault(n, []).append(r)
            for r in fav:
                if r['market'] == 'spread': buckets.setdefault('Spread side the board favored (every game)', []).append(r)
            for n in ['Board winner picks', 'Value spreads (model 3+ points off the line)', 'Spread side the board favored (every game)']:
                x = buckets.get(n)
                if not x: continue
                w = sum(r['won'] for r in x); u = sum(r['units'] for r in x)
                out['groups'].append(dict(group=n, bets=len(x), won=w, lost=len(x) - w, hit=w / len(x), exp_hit=sum(r['p'] for r in x) / len(x), units=round(u, 2), roi=u / len(x)))
            out['cal_sections'] = CAL.sections(*[(SEC[m][0], [r for r in fav if r['market'] == m], SEC[m][1], True) for m in ('moneyline', 'spread', 'total')])
        out['parlays'] = PZ.grade(DIR, results, dates=days, when=when)
        return out

    out = report()
    out['by_period'] = CAL.by_period(ALL.day.tolist() if len(ALL) else [], report)
    # waiting bets for the page's Refresh results button (graded in the browser from ESPN)
    since = (pd.Timestamp.now(tz=ET).normalize() - pd.Timedelta(days=10)).strftime('%Y-%m-%d')
    PD = CAL.Pending(push_counts=False)
    W = [r for r in wait if r['day'] >= since]
    gx = lambda r: dict(ev=str(r['gid']), m={'moneyline': 'ml', 'spread': 'sp', 'total': 'tot'}[r['market']], sd=r['side'],
                        ln=None if r['line'] != r['line'] else float(r['line']))
    wfav = {id(r) for r in CAL.favored(W, fkey)}
    for r in W:
        cal = ('cal_sections', SEC[r['market']][0], True, SEC[r['market']][1]) if id(r) in wfav else None
        gs = [('groups', n) for n in groups_of(r)] + ([('groups', 'Spread side the board favored (every game)')] if id(r) in wfav and r['market'] == 'spread' else [])
        PD.add_leg(f"{r['week']}|{r['id']}", r['day'], gx(r), r['price'], r['p'], gs, cal)
    byid = {(r['week'], r['id']): r for r in wait}
    PZ.pending(DIR, results, PD, leg_key=lambda wk, L: f"{wk}|{L['id']}", when=when, since=since,
               add_leg=lambda wk, L: PD.add_leg(f"{wk}|{L['id']}", byid[(wk, L['id'])]['day'], gx(byid[(wk, L['id'])]), L['price'], L['p']) if (wk, L['id']) in byid else None)
    out['pending'] = PD.out()
    lr = {}
    for (w, i), r in results.items(): lr.setdefault(w, {})[i] = r
    os.makedirs(DIR, exist_ok=True)
    json.dump(lr, open(os.path.join(DIR, 'leg_results.json'), 'w'))
    json.dump(out, open(os.path.join(DIR, 'grade_report.json'), 'w'), indent=1)
    print(f"CFB: graded {len(ALL)} legs over {len(out['days'])} game days; {len(W)} waiting")


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--no-fetch', action='store_true')
    main(not ap.parse_args().no_fetch)
