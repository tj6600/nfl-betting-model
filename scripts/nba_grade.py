"""Grade the NBA board's logged legs against results and DraftKings closing lines.

For each slate day, the earliest pick log (odds_log/nba/picks/<day>_<stamp>.csv) is the set of bets as offered.
  * Result: props from the box score (a player who doesn't play is void), game legs from the final score.
    Profit is in units at the logged DraftKings price (1 unit risked per leg).
  * Closing line value: the last DraftKings snapshot of that day taken after the pick log (props_<day>_*.json,
    games_*.json). A leg "beat the close" when the line moved its way (Over: line went up; Under: down; spread:
    the team's number got worse) or, at the same line, its no-vig chance rose by 0.5 pts or more.
Writes odds_log/nba/grade_report.json and grade_report.md.

python scripts/nba_grade.py      # run after python scripts/nba_board.py --update (needs the box scores)
"""
import sys, os, glob, json; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
from nbamodel import data as D, odds as O

BOOK = 'DraftKings'
G, P, S = D.load()
P = P.copy(); P['pra'] = P.pts + P.reb + P.ast


def dec(a): return 1 + a / 100 if a > 0 else 1 + 100 / -a
def imp(a): return 1 / dec(a)
def stamp_of(f): return f.rsplit('_', 1)[-1].replace('.json', '').replace('.csv', '')


def closing_props(day, after):
    fs = [f for f in sorted(glob.glob(os.path.join(O.DIR, f'props_{day}_*.json'))) if stamp_of(f) > after]
    if not fs: return None
    R = O.prop_rows(json.load(open(fs[-1])))
    return R[R.book == BOOK] if len(R) else None


def closing_games(day, after):
    fs = [f for f in sorted(glob.glob(os.path.join(O.DIR, 'games_*.json'))) if stamp_of(f) > after]
    out = None
    for f in fs[::-1]:
        R = O.game_rows(json.load(open(f)))
        if len(R):
            R['day'] = pd.to_datetime(R.tip).dt.tz_convert('America/New_York').dt.date.astype(str)
            R = R[(R.day == day) & (R.book == BOOK)]
            if len(R): out = R; break
    return out


def nv_side(q, side):
    a = q[q.side == side]; b = q[q.side != side]
    if not len(a) or not len(b): return None
    return imp(a.price.iloc[0]) / (imp(a.price.iloc[0]) + imp(b.price.iloc[0]))


key = lambda s: s.str.lower().str.replace(r'[^a-z]', '', regex=True).str.replace(r'(jr|sr|ii|iii|iv)$', '', regex=True)
logs = {}
for f in sorted(glob.glob(os.path.join(O.DIR, 'picks', '*.csv'))):
    day = os.path.basename(f)[:10]
    logs.setdefault(day, f)          # earliest log of the day
rows = []
names = P.drop_duplicates('pid').set_index('pid').name
for day, f in logs.items():
    L = pd.read_csv(f); st = stamp_of(f)
    cp = closing_props(day, st); cg = closing_games(day, st)
    if cp is not None and len(cp): cp = cp.assign(k=key(cp.player))
    for l in L.itertuples():
        r = dict(day=day, id=l.id, kind=l.kind, label=l.label, price=l.price, p=l.p, edge=l.edge, cat=l.cat if isinstance(l.cat, str) else '',
                 suggested=bool(l.suggested), flagged=bool(l.flagged), result=None, profit=None, clv=None, nv_move=None, close_line=None)
        g = G[G.game_id == l.gid]
        if l.market in ('pts', 'reb', 'ast', 'fg3m', 'pra'):
            pr = P[(P.game_id == l.gid) & (P.pid == l.pid)]
            if len(g):
                if not len(pr) or pr.dnp.iloc[0] or not (pr['min'].iloc[0] > 0):
                    r['result'] = 'void'
                else:
                    a = float(pr[l.market].iloc[0])
                    r['result'] = 'push' if a == l.line else ('win' if (a > l.line) == (l.side == 'Over') else 'loss')
            if cp is not None and len(cp) and not bool(getattr(l, 'alt', False) == True):   # alt rungs have no closing main line to compare
                q = cp[(cp.k == key(pd.Series([names.get(l.pid, '')])).iloc[0]) & (cp.stat == l.market)]
                if len(q):
                    cl = q.point.mode().iloc[0]; r['close_line'] = float(cl)
                    if cl != l.line:
                        r['clv'] = 'beat' if (cl > l.line) == (l.side == 'Over') else 'lost'
                    else:
                        nv0 = l.pb if l.pb == l.pb else None
                        nv1 = nv_side(q[q.point == cl], l.side)
                        if nv0 is not None and nv1 is not None:
                            r['nv_move'] = round((nv1 - nv0) * 100, 1)
                            r['clv'] = 'beat' if nv1 - nv0 >= 0.005 else 'lost' if nv0 - nv1 >= 0.005 else 'flat'
        else:
            if len(g):
                g = g.iloc[0]; home = g.home; m = (g.hs - g.as_) * (1 if l.side == home else -1)
                if l.market == 'spread':
                    v = m + l.line
                elif l.market == 'total':
                    v = (g.hs + g.as_ - l.line) * (1 if l.side == 'Over' else -1)
                else:
                    v = m
                r['result'] = 'push' if v == 0 else 'win' if v > 0 else 'loss'
            if cg is not None:
                gg = G[G.game_id == l.gid]
                if len(gg):
                    h, a_ = gg.home.iloc[0], gg.away.iloc[0]
                else:
                    sc = S[S.game_id == l.gid]; h, a_ = (sc.home.iloc[0], sc.away.iloc[0]) if len(sc) else (None, None)
                mk = {'spread': 'spreads', 'total': 'totals', 'moneyline': 'h2h'}[l.market]
                q = cg[(cg.home == h) & (cg.away == a_) & (cg.market == mk)]
                qs = q[q.side == l.side]
                if len(qs):
                    cl = qs.point.iloc[0]
                    if l.market != 'moneyline' and cl == cl and cl != l.line:
                        r['close_line'] = float(cl)
                        good = cl < l.line if (l.market == 'spread') else ((cl > l.line) == (l.side == 'Over'))
                        r['clv'] = 'beat' if good else 'lost'
                    else:
                        nv0 = l.pb if l.pb == l.pb else None
                        nv1 = nv_side(q if l.market == 'moneyline' else q[q.point.abs() == abs(l.line)] if l.market == 'spread' else q[q.point == l.line], l.side)
                        if nv0 is not None and nv1 is not None:
                            r['nv_move'] = round((nv1 - nv0) * 100, 1)
                            r['clv'] = 'beat' if nv1 - nv0 >= 0.005 else 'lost' if nv0 - nv1 >= 0.005 else 'flat'
        if r['result'] in ('win', 'loss', 'push'):
            r['profit'] = round(dec(l.price) - 1, 3) if r['result'] == 'win' else -1.0 if r['result'] == 'loss' else 0.0
        rows.append(r)

R = pd.DataFrame(rows)
os.makedirs(O.DIR, exist_ok=True)
R.to_csv(os.path.join(O.DIR, 'graded_legs.csv'), index=False)


def summ(d, name):
    g = d[d.result.isin(['win', 'loss', 'push'])]
    c = d[d.clv.isin(['beat', 'lost', 'flat'])]
    w, lo = int((g.result == 'win').sum()), int((g.result == 'loss').sum())
    return dict(group=name, bets=int(len(g)), won=w, lost=lo, hit=round(w / max(1, w + lo), 3), units=round(float(g.profit.sum()), 2),
                roi=round(float(g.profit.sum()) / max(1, len(g)), 3), exp_hit=round(float(g.p.mean()), 3) if len(g) else None,
                clv_n=int(len(c)), beat=round(float((c.clv == 'beat').mean()), 3) if len(c) else None,
                lost_clv=round(float((c.clv == 'lost').mean()), 3) if len(c) else None)


rep = {'days': sorted(logs), 'groups': []}
if len(R):
    clean = R[~R.flagged]
    rep['groups'] = [summ(R[R.cat == 'Value'], 'Value legs'), summ(R[R.suggested], 'Suggested-parlay legs'),
                     summ(clean[clean.edge >= 0], 'All +edge legs'), summ(R[R.edge < 0], 'Negative-edge legs (control)')]
    rep['by_kind'] = [summ(R[(R.cat == 'Value') & (R.kind == k)], k) for k in sorted(R.kind.unique()) if ((R.cat == 'Value') & (R.kind == k)).any()]
import parlays as PZ
rep['parlays'] = PZ.grade(O.DIR, {(r['day'], r['id']): r['result'] for r in rows if r['result']})
json.dump(rep, open(os.path.join(O.DIR, 'grade_report.json'), 'w'), indent=1)
md = [f"# NBA pick grading ({', '.join(rep['days'])})", '', '| Group | Bets | W-L | Hit | Expected | Units | ROI | CLV checked | Beat close | Lost to close |', '|---|---|---|---|---|---|---|---|---|---|']
for s in rep['groups'] + rep.get('by_kind', []):
    md.append(f"| {s['group']} | {s['bets']} | {s['won']}-{s['lost']} | {s['hit']:.1%} | {s['exp_hit'] if s['exp_hit'] is None else format(s['exp_hit'], '.1%')} | {s['units']:+.2f} | {s['roi']:+.1%} | {s['clv_n']} | "
              f"{'' if s['beat'] is None else format(s['beat'], '.0%')} | {'' if s['lost_clv'] is None else format(s['lost_clv'], '.0%')} |")
if rep['parlays']['groups']:
    md += ['', '## Suggested parlays', '', '| Group | Parlays | W-L | Hit | Expected | Units | ROI |', '|---|---|---|---|---|---|---|']
    md += [f"| {s['group']} | {s['bets']} | {s['won']}-{s['lost']} | {s['hit']:.1%} | {s['exp_hit']:.1%} | {s['units']:+.2f} | {s['roi']:+.1%} |" for s in rep['parlays']['groups']]
open(os.path.join(O.DIR, 'grade_report.md'), 'w').write('\n'.join(md) + '\n')
print('\n'.join(md))
