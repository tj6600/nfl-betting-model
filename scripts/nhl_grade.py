"""Grade logged NHL board legs (odds_log/nhl/picks/<day>_<stamp>.csv) against results.

Uses the earliest log of each day, at the DraftKings price it showed, 1 unit per leg.
Game legs grade from final scores (overtime and shootouts count); props grade from box scores, and a player who
doesn't play is void. Writes odds_log/nhl/grade_report.json for the board's Model record tab.

  python scripts/nhl_grade.py
"""
import os, sys, glob, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
from nhlmodel import data as D, odds as O

ROOT = os.path.join(os.path.dirname(__file__), '..')


def dec(a): return 1 + a / 100 if a > 0 else 1 + 100 / -a


def main():
    games, sk, go, tg = D.load()
    logs = {}
    for f in sorted(glob.glob(os.path.join(O.DIR, 'picks', '*.csv'))):
        day = os.path.basename(f)[:10]
        logs.setdefault(day, f)
    rows = []
    for day, f in logs.items():
        L = pd.read_csv(f)
        g = games[games.game_date == day]
        if not len(g):
            continue
        for l in L.itertuples():
            home, away = l.game.split(' @ ')[1], l.game.split(' @ ')[0]
            m = g[(g.home == home) & (g.away == away)]
            if not len(m):
                continue
            m = m.iloc[0]
            res = None
            hs, as_ = m.home_score, m.away_score
            if l.market == 'moneyline':
                res = (hs > as_) if l.side == home else (as_ > hs)
            elif l.market == 'puckline':
                mg = (hs - as_) if l.side == home else (as_ - hs)
                res = mg + l.line > 0
            elif l.market == 'total':
                t = hs + as_
                res = None if t == l.line else (t > l.line) == (l.side == 'Over')
            elif l.market in ('sog', 'saves'):
                src = sk if l.market == 'sog' else go
                col = 'sog' if l.market == 'sog' else 'saves'
                b = src[(src.game_id == m.game_id) & (src.player_id == l.pid)]
                if not len(b) or (l.market == 'saves' and not bool(b.starter.iloc[0])):
                    continue   # void: didn't play (or didn't start)
                v = float(b[col].iloc[0])
                res = (v > l.line) == (l.side == 'Over')
            if res is None:
                continue
            rows.append(dict(day=day, kind=l.kind, cat=l.cat if isinstance(l.cat, str) else '', pick=bool(getattr(l, 'pick', False)),
                             flagged=bool(l.flagged), price=l.price, p=l.p, won=bool(res), units=(dec(l.price) - 1) if res else -1.0))
    R = pd.DataFrame(rows)
    out = dict(days=sorted(R.day.unique().tolist()) if len(R) else [], groups=[])
    if len(R):
        def grp(name, x):
            if not len(x): return
            out['groups'].append(dict(group=name, bets=int(len(x)), won=int(x.won.sum()), lost=int((~x.won).sum()), hit=float(x.won.mean()),
                                      exp_hit=float(x.p.mean()), units=round(float(x.units.sum()), 2), roi=float(x.units.mean())))
        grp('Board winner picks', R[R.pick])
        grp('Value legs', R[R.cat == 'Value'])
        grp('Shots on goal, edge 3+ side', R[(R.kind == 'Shots on goal') & ((R.p - 1 / R.price.map(dec)) >= 0.03)])
        for k in ['Shots on goal', 'Saves', 'Moneyline', 'Puck line', 'Total']:
            grp(f'All {k.lower()} legs', R[R.kind == k])
    json.dump(out, open(os.path.join(O.DIR, 'grade_report.json'), 'w'), indent=1)
    print(f"graded {len(R)} legs over {len(out['days'])} days")


if __name__ == '__main__':
    main()
