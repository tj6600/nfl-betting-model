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
    rows, results = [], {}
    for day, f in logs.items():
        L = pd.read_csv(f)
        # the lean is the side of each bet with the bigger edge (both sides are logged)
        L['key'] = L.gid.astype(str) + '|' + L.market.astype(str) + '|' + L.pid.fillna(0).astype(int).astype(str)
        alt = L['alt'].fillna(False).astype(bool) if 'alt' in L else pd.Series(False, index=L.index)
        L['key'] = L['key'] + alt.map({True: '|alt', False: ''})
        L['lean'] = (L.edge == L.groupby('key').edge.transform('max')) & ~alt   # alt rungs are parlay legs, not leans
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
                    results[(day, l.id)] = 'void'
                    continue   # void: didn't play (or didn't start)
                v = float(b[col].iloc[0])
                res = (v > l.line) == (l.side == 'Over')
            if res is None:
                results[(day, l.id)] = 'push'
                continue
            results[(day, l.id)] = 'win' if res else 'loss'
            rows.append(dict(day=day, kind=l.kind, lean=bool(l.lean), cat=l.cat if isinstance(l.cat, str) else '', pick=bool(getattr(l, 'pick', False)),
                             flagged=bool(l.flagged), price=l.price, p=l.p, edge=l.edge, won=bool(res), units=(dec(l.price) - 1) if res else -1.0,
                             gid=l.gid, market=l.market, line=l.line, pid=l.pid if l.pid == l.pid else 0, alt=bool(alt.loc[l.Index])))
    R = pd.DataFrame(rows)
    out = dict(days=sorted(R.day.unique().tolist()) if len(R) else [], groups=[])
    if len(R):
        def grp(name, x):
            if not len(x): return
            out['groups'].append(dict(group=name, bets=int(len(x)), won=int(x.won.sum()), lost=int((~x.won).sum()), hit=float(x.won.mean()),
                                      exp_hit=float(x.p.mean()), units=round(float(x.units.sum()), 2), roi=float(x.units.mean())))
        # leans count only when the board saw an edge (Thomas, 2026-11-16: most logged leans had none, so they weren't real picks)
        R['plus'] = R.lean & (R.edge > 0)
        props = R[R.plus & R.kind.isin(['Shots on goal', 'Saves'])]
        grp('Board winner picks', R[R.pick])
        grp('Value legs', R[R.cat == 'Value'])
        grp('Prop leans with an edge (shots + saves)', props)
        for k in ['Shots on goal', 'Saves', 'Puck line', 'Total']:
            grp(f'{k} leans with an edge', R[R.plus & (R.kind == k)])
        last = R.day.max()
        lp = props[props.day == last]; lw = R[R.pick & (R.day == last)]
        out['latest_day'] = dict(day=last, props_won=int(lp.won.sum()), props_lost=int((~lp.won).sum()),
                                 picks_won=int(lw.won.sum()), picks_lost=int((~lw.won).sum()))
    import parlays as PZ
    if len(R): out['calibration'] = PZ.calibration(R.p.tolist(), R.won.astype(int).tolist())
    # calibration by leg type: the side the board favored (the board only logs games not yet started), at the logged DraftKings price
    import calib as CAL
    if len(R):
        rr = R.to_dict('records')
        main = [r for r in rr if not r['alt']]
        fav = CAL.favored(main, lambda r: (r['day'], r['gid'], r['market'], r['pid'], abs(r['line']) if r['market'] == 'puckline' else r['line'] if r['market'] != 'moneyline' else 0))
        out['cal_sections'] = CAL.sections(
            ('Moneyline picks', [r for r in fav if r['market'] == 'moneyline'], 'The team the board gave the better chance to win, every game (overtime and shootouts count).', True),
            ('Puck lines', [r for r in fav if r['market'] == 'puckline'], 'The side the board favored on each DraftKings puck line.', True),
            ('Totals', [r for r in fav if r['market'] == 'total'], 'Over or Under, whichever the board favored.', True),
            ('Shots on goal', [r for r in fav if r['market'] == 'sog'], 'Over or Under on the main DraftKings line, whichever the board favored.', True),
            ('Saves', [r for r in fav if r['market'] == 'saves'], 'Over or Under on the main DraftKings line, whichever the board favored.', True),
            ('Alt lines', [r for r in rr if r['alt']], 'Every alt-line rung offered as a parlay leg (overs only, so chances run the full range).', False))
    out['parlays'] = PZ.grade(O.DIR, results)
    _lr = {}   # leg results for the Bank Builder record (bank.py)
    for (d, i), r in results.items(): _lr.setdefault(d, {})[i] = r
    json.dump(_lr, open(os.path.join(O.DIR, 'leg_results.json'), 'w'))
    json.dump(out, open(os.path.join(O.DIR, 'grade_report.json'), 'w'), indent=1)
    print(f"graded {len(R)} legs over {len(out['days'])} days")


if __name__ == '__main__':
    main()
