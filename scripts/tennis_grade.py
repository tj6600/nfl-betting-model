"""Grade logged tennis board picks and legs (odds_log/tennis/picks/<day>_<stamp>.csv) against ESPN results (free).

Each row is graded once, from the first log of its day (the earliest price the board showed). Walkovers and retirements
are left out (void): a match that never really finished says nothing about the pick.
Groups: every match's board pick (priced or not: free hit-rate tracking), board picks DraftKings priced (graded at that
price), Value legs, plus the suggested parlays. Writes odds_log/tennis/grade_report.json and leg_results.json.

  python scripts/tennis_grade.py [--no-fetch]
"""
import os, sys, glob, json, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pandas as pd
from tennismodel import espn as E
import parlays as PZ, calib as CAL

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DIR = os.path.join(ROOT, 'odds_log', 'tennis')
ET = 'America/New_York'


def dec(a): return 1 + a / 100 if a > 0 else 1 + 100 / -a


GROUPS = ['Board picks (every match)', 'Board picks, main draw', 'Board picks DraftKings priced', 'Value legs (blend EV 3%+)']


def main(fetch=True):
    if fetch:
        try: E.history()
        except Exception as e: print('ESPN refresh failed, grading from saved results:', e)
    if not glob.glob(os.path.join(DIR, 'picks', '*.csv')):
        print('Tennis: nothing logged yet'); return
    R = E.load().drop_duplicates('mid').set_index('mid')
    first = {}
    for f in sorted(glob.glob(os.path.join(DIR, 'picks', '*.csv'))):
        day = os.path.basename(f).rsplit('_', 1)[0]
        for r in pd.read_csv(f, dtype={'gid': str}).to_dict('records'):
            first.setdefault((day, r['id'], r['market']), dict(r, day=day))
    rows, results = [], {}
    for (day, lid, mk), r in first.items():
        if r['gid'] not in R.index: continue
        x = R.loc[r['gid']]
        if x.status != 'STATUS_FINAL' or x.winner not in (1, 2):
            if mk != 'pick': results[(day, lid)] = 'void'
            continue
        won = (x.winner == 1) == (r['side'] == 'p1')
        price = r['price'] if r['price'] == r['price'] else None
        if mk != 'pick': results[(day, lid)] = 'win' if won else 'loss'
        rows.append(dict(r, won=bool(won), units=((dec(price) - 1) if won else -1.0) if price else 0.0, priced=price is not None,
                         qual=str(r.get('round', '')).startswith('Qual')))
    ALL = pd.DataFrame(rows)

    def groups_of(r):
        g = []
        if r['market'] == 'pick':
            g.append('Board picks (every match)')
            if not r['qual']: g.append('Board picks, main draw')
            if r['priced']: g.append('Board picks DraftKings priced')
        elif r.get('cat') == 'Value': g.append('Value legs (blend EV 3%+)')
        return g

    def report(days=None):
        X = ALL if days is None or not len(ALL) else ALL[ALL.day.isin(days)]
        out = dict(days=sorted(X.day.unique().tolist()) if len(X) else [], groups=[])
        if len(X):
            buckets = {}
            for r in X.to_dict('records'):
                for n in groups_of(r): buckets.setdefault(n, []).append(r)
            for n in GROUPS:
                x = buckets.get(n)
                if not x: continue
                w = sum(r['won'] for r in x); u = sum(r['units'] for r in x)
                priced = [r for r in x if r['priced']]
                out['groups'].append(dict(group=n, bets=len(x), won=w, lost=len(x) - w, hit=w / len(x), exp_hit=sum(r['p'] for r in x) / len(x),
                                          units=round(u, 2) if priced else None, roi=(u / len(priced)) if priced else None))
            pk = [r for r in X.to_dict('records') if r['market'] == 'pick']
            out['cal_sections'] = CAL.sections(('Board picks', pk, 'The player the board gave the better chance, every match.', True))
        out['parlays'] = PZ.grade(DIR, results, dates=days)
        return out

    out = report()
    out['by_period'] = CAL.by_period(ALL.day.tolist() if len(ALL) else [], report)
    lr = {}
    for (d, i), r in results.items(): lr.setdefault(d, {})[i] = r
    json.dump(lr, open(os.path.join(DIR, 'leg_results.json'), 'w'))
    json.dump(out, open(os.path.join(DIR, 'grade_report.json'), 'w'), indent=1)
    print(f"Tennis: graded {len(ALL)} rows over {len(out['days'])} days")


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--no-fetch', action='store_true')
    main(not ap.parse_args().no_fetch)
