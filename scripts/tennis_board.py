"""Build the tennis board (board/site/tennis.html): ATP and WTA singles match picks, DraftKings winner prices, parlays, record.

  python scripts/tennis_board.py [--update] [--no-log] [--day YYYY-MM-DD]

--update refreshes ESPN results first (python -m tennismodel.espn update; free).
The slate is every singles match ESPN lists for today and tomorrow with both players known (main draw and qualifying).
Prices: the newest DraftKings snapshot from `python -m tennismodel.odds pull` (Odds API, 1 credit per active tournament,
only with Thomas's OK). Without a fresh snapshot the board still shows the model's pick for every match, and logs it,
so its hit rate is tracked for free; legs (and parlays) need DraftKings prices.
--day builds the board for a past day as if its matches had not started (for checking the page; nothing is logged).

Model: surface Elo per tour (tennismodel/model.py). Backtest (scripts/tennis_backtest.py, main draw 2024 onward, out of
sample): picks right 64.4% of the time and well calibrated (picks the model gave 80-90% won 82-85%).
"""
import sys, os, json, re, argparse, subprocess, unicodedata, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
from tennismodel import espn as E, model as M, odds as O
import parlays as PZ

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
ET = 'America/New_York'
BOOK = 'DraftKings'
DIR = os.path.join(ROOT, 'odds_log', 'tennis')
# weight on the Elo model vs DraftKings' no-vig chance. Betting markets are usually much sharper than Elo in tennis, so the
# board leans on DraftKings until the closing-odds test (tennis_backtest.py with tennis-data.co.uk files) says otherwise
W_MODEL = 0.25
VALUE_EV = 3.0     # Value: blended chance x DraftKings price is 3%+ better than even, priced -200 or longer

ap = argparse.ArgumentParser(); ap.add_argument('--update', action='store_true')
ap.add_argument('--no-log', action='store_true', help='rebuild the page only; save no pick or parlay log')
ap.add_argument('--day', help='build for a past day (YYYY-MM-DD) as if its matches were still to play; logs nothing')
args = ap.parse_args()
if args.update:
    E.history()

DEMO = args.day is not None
now = pd.Timestamp(args.day + 'T05:00Z') if DEMO else pd.Timestamp.now(tz='UTC')
today = now.tz_convert(ET).date()
H = E.load()
H = H[H.ts < now]
ELO = {t: M.Elo().fit(H[H.tour == t]) for t in E.TOURS}

# ---------- slate ----------
rows = []
for tour in E.TOURS:
    for d in (today, today + dt.timedelta(days=1)):
        try: rows += E.day(tour, d)
        except Exception as e: print('ESPN', tour, d, 'failed:', e)
S = pd.DataFrame(rows, columns=E.COLS).drop_duplicates('mid')
if len(S):
    S['ts'] = pd.to_datetime(S.start, utc=True)
    S = S[(S.status == 'STATUS_SCHEDULED') if not DEMO else (S.ts >= now) & (S.ts < now + pd.Timedelta(days=1))]
    S = S[(S.ts > now - pd.Timedelta(hours=1)) & (S.ts < now + pd.Timedelta(hours=48))].sort_values('ts').reset_index(drop=True)
    S['surface'] = [E.surface(e, t, s) for e, t, s in zip(S.event, S.tour, S.start)]


def ascii_(s): return unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower()
def full(n): return re.sub(r'[^a-z]', '', ascii_(n))
def short(n):
    w = re.sub(r'[^a-z ]', ' ', ascii_(n)).split()
    return (w[-1], w[0][:1]) if len(w) > 1 else (''.join(w), '')


# ---------- DraftKings prices (newest snapshot, if fresh) ----------
SNAP = None if DEMO else O.latest()
PRICE = {}      # (tour, name key) -> list of (event, start, player, price, sid, opponent)
if SNAP is not None:
    for ev, g in SNAP.groupby('event'):
        if len(g) != 2: continue
        a, b = g.iloc[0], g.iloc[1]
        for x, y in ((a, b), (b, a)):
            PRICE.setdefault((x.tour, full(x.player)), []).append(dict(event=ev, start=x.start, price=int(x.price), sid=x.sid if isinstance(x.sid, str) else None,
                                                                         opp=full(y.player), opp_short=short(y.player), tournament=x.tournament))
            PRICE.setdefault((x.tour, short(x.player)), []).append(dict(event=ev, start=x.start, price=int(x.price), sid=x.sid if isinstance(x.sid, str) else None,
                                                                          opp=full(y.player), opp_short=short(y.player), tournament=x.tournament))


def dk_for(tour, name, opp, start):
    """DraftKings (price, sid, event) for `name` against `opp` in a match starting near `start`, else None."""
    for key in ((tour, full(name)), (tour, short(name))):
        for c in PRICE.get(key, []):
            if (c['opp'] == full(opp) or c['opp_short'] == short(opp)) and abs((pd.Timestamp(c['start']) - start).total_seconds()) < 36 * 3600:
                return c
    return None


def dec(a): return 1 + a / 100 if a > 0 else 1 + 100 / -a
def imp(a): return 1 / dec(a)
def nv(a, b): return imp(a) / (imp(a) + imp(b))


def rnd_short(r):
    r = str(r)
    return {'Quarterfinal': 'QF', 'Semifinal': 'SF', 'Final': 'Final', 'Qualifying Final': 'Q-Final', 'Group Stage': 'Group'}.get(r, r.replace('Qualifying ', 'Q ').replace('Round ', 'R'))


legs, LEG, MATCHES = [], {}, []
for x in S.itertuples() if len(S) else []:
    el = ELO[x.tour]
    bo5 = M.is_bo5(x)
    pm = float(el.p(x.p1, x.p2, x.surface, bo5))
    n1, n2 = el.n.get(x.p1, 0), el.n.get(x.p2, 0)
    flags = [f'{nm} has {n} rated match{"es" if n != 1 else ""}' for nm, n in ((x.p1_name, n1), (x.p2_name, n2)) if n < 10]
    gm = f'{x.p1_name} vs {x.p2_name}'
    row = dict(id=x.mid, game=gm, tour=x.tour, event=x.event, round=x.round, rnd=rnd_short(x.round), qual=str(x.round).startswith('Qual'),
               surface=x.surface, bo5=bo5, start=x.ts.strftime('%Y-%m-%dT%H:%M:%SZ'), time=(x.ts.tz_convert(ET).strftime('%a, time TBA') if x.ts.tz_convert(ET).strftime('%H%M') == '0000' else x.ts.tz_convert(ET).strftime('%a %-I:%M %p')),
               court=x.court, p1=x.p1_name, p2=x.p2_name, elo1=round(el.rating(x.p1, x.surface)), elo2=round(el.rating(x.p2, x.surface)),
               pm1=round(pm, 3), n1=int(n1), n2=int(n2), legs=[])
    c1, c2 = dk_for(x.tour, x.p1_name, x.p2_name, x.ts), dk_for(x.tour, x.p2_name, x.p1_name, x.ts)
    if DEMO and not str(x.round).startswith('Qual'):
        # page check only: stand-in prices (the model's chance, nudged, with ~4.5% vig); never logged or published
        q = min(0.97, max(0.03, pm + np.random.default_rng(int(x.mid)).normal(0, 0.06)))
        am = lambda pr: int(round(-100 * pr / (1 - pr))) if pr >= 0.5 else int(round(100 * (1 - pr) / pr))
        c1, c2 = dict(price=am(min(0.985, q * 1.045)), sid=None), dict(price=am(min(0.985, (1 - q) * 1.045)), sid=None)
    if c1 and c2:
        pb = nv(c1['price'], c2['price'])
        p = W_MODEL * pm + (1 - W_MODEL) * pb
        row.update(dk1=c1['price'], dk2=c2['price'], pb1=round(pb, 3), p1p=round(p, 3))
        for side, nm, pid, c, pmx, pbx in (('p1', x.p1_name, x.p1, c1, pm, pb), ('p2', x.p2_name, x.p2, c2, 1 - pm, 1 - pb)):
            pp = W_MODEL * pmx + (1 - W_MODEL) * pbx
            L = dict(id=f'{x.mid}-{side}', gid=x.mid, game=gm, kind='Winner', market='moneyline', side=side, line=None, label=f'{nm} to win',
                     who=nm, pid=f'{x.tour}{pid}', tour=x.tour, event=x.event, price=int(c['price']), p=round(pp, 4), pm=round(pmx, 4), pb=round(pbx, 4),
                     edge=round((pp - imp(c['price'])) * 100, 1), ev=round((pp * dec(c['price']) - 1) * 100, 1), flags=list(flags),
                     sid=c['sid'], start=row['start'])
            legs.append(L); LEG[L['id']] = L; row['legs'].append(L['id'])
    else:
        p = pm
    row['pick'] = 'p1' if p >= 0.5 else 'p2'
    row['pick_p'] = round(max(p, 1 - p), 3)
    row['pick_name'] = x.p1_name if p >= 0.5 else x.p2_name
    MATCHES.append(row)

for L in legs:
    g = next(m for m in MATCHES if m['id'] == L['gid'])
    L['pick'] = bool(g['pick'] == L['side']); L['bpick'] = L['pick']
    L['cat'] = 'Value' if (L['ev'] >= VALUE_EV and L['price'] >= PZ.MAX_JUICE and not L['flags']) else ''
pool = sorted([l for l in legs if l['cat'] == 'Value'], key=lambda l: -l['ev'])
likely = lambda L: PZ.likely(L) or (L.get('pick') and L['p'] >= 0.55 and L['price'] >= PZ.MAX_JUICE and not L['flags'])

# ---------- logs for grading (scripts/tennis_grade.py) ----------
stamp = now.strftime('%Y-%m-%dT%H%MZ')
DAY = f'{today:%Y-%m-%d}'
if MATCHES and not args.no_log and not DEMO:
    os.makedirs(os.path.join(DIR, 'picks'), exist_ok=True)
    # every match's pick, priced or not (free hit-rate tracking), plus every priced leg
    pk = [dict(id=f"{m['id']}-{m['pick']}", gid=m['id'], game=m['game'], start=m['start'], tour=m['tour'], event=m['event'], round=m['round'],
               market='pick', side=m['pick'], label=f"{m['pick_name']} to win", p=m['pick_p'], pm=m['pm1'] if m['pick'] == 'p1' else 1 - m['pm1'],
               price=(m.get('dk1') if m['pick'] == 'p1' else m.get('dk2')), cat='', pick=True, bpick=True, flagged=False) for m in MATCHES]
    lg = [{k: l.get(k) for k in ['id', 'gid', 'game', 'start', 'tour', 'event', 'market', 'side', 'label', 'p', 'pm', 'pb', 'price', 'edge', 'ev', 'cat', 'pick', 'bpick']}
          | {'flagged': bool(l['flags'])} for l in legs]
    pd.DataFrame(pk + lg).to_csv(os.path.join(DIR, 'picks', f'{DAY}_{stamp}.csv'), index=False)
    if legs:
        PZ.log(DIR, DAY, stamp, legs, [l['id'] for l in pool], likely)
    subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'tennis_grade.py'), '--no-fetch'], check=False, stdout=subprocess.DEVNULL)
gr = os.path.join(DIR, 'grade_report.json')
LIVE = json.load(open(gr)) if os.path.exists(gr) else None
bf = os.path.join(ROOT, 'output', 'tennis_backtest.json')
BT = json.load(open(bf)) if os.path.exists(bf) else None

# ---------- ratings tab: top 30 per tour, active in the last 120 days ----------
RAT = {}
recent = now - pd.Timedelta(days=120)
names = {}
for x in H[H.ts >= now - pd.Timedelta(days=400)].itertuples():
    names[(x.tour, x.p1)] = x.p1_name; names[(x.tour, x.p2)] = x.p2_name
for t, el in ELO.items():
    act = [p for p, ts in el.last.items() if ts >= recent and el.n.get(p, 0) >= 20 and (t, p) in names]
    top = sorted(act, key=lambda p: -el.rating(p))[:30]
    RAT[t] = [dict(rank=i + 1, name=names[(t, p)], elo=round(el.rating(p)), hard=round(el.rating(p, 'Hard')), clay=round(el.rating(p, 'Clay')),
                   grass=round(el.rating(p, 'Grass')), matches=int(el.n.get(p, 0))) for i, p in enumerate(top)]

events = sorted({(m['tour'], m['event']) for m in MATCHES})
DATA = dict(day=DAY, dayLabel=f'{today:%A, %B %-d}', book=BOOK, built=stamp, demo=DEMO,
            through=str(H.ts.max().tz_convert(ET).date()) if len(H) else None,
            priced=SNAP is not None, snap=(str(pd.to_datetime(SNAP.pulled, utc=True).max().tz_convert(ET).strftime('%a %-I:%M %p')) if SNAP is not None else None),
            matches=MATCHES, legs=legs, pool=[l['id'] for l in pool], events=[dict(tour=t, name=n) for t, n in events],
            live=LIVE, backtest=BT, w_model=W_MODEL, value_ev=VALUE_EV, ratings=RAT)


def clean(o):
    if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, (float, np.floating)): return None if o != o else float(o)
    if isinstance(o, np.bool_): return bool(o)
    return o


B = os.path.join(ROOT, 'board')
import bank as BANK
head = open(os.path.join(B, 'head.html')).read().replace('<title>Player Props Board</title>', '<title>Tennis Board</title>')
data = json.dumps(clean(DATA), separators=(',', ':')).replace('</', '<\\/')
html = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n' + BANK.APP_HEAD + head + BANK.SPORT_CSS + '\n<style>\n' + open(os.path.join(B, 'nhl.css')).read() + open(os.path.join(B, 'cfb.css')).read()
        + open(os.path.join(B, 'tennis.css')).read() + '</style>\n</head>\n<body>\n' + BANK.nav('tennis') + open(os.path.join(B, 'tennis_body.html')).read()
        + f'<script type="application/json" id="tennis-data">{data}</script>\n<script>\n' + open(os.path.join(B, 'tennis_app.js')).read() + '</script>\n</body>\n</html>\n')
# a --day page check goes to output/ (stand-in prices; never published)
out = os.path.join(ROOT, 'output', 'tennis_demo.html') if DEMO else os.path.join(B, 'site', 'tennis.html')
open(out, 'w').write(html)
print(f'Tennis board {DAY}: {len(MATCHES)} matches, {len(legs)} priced legs, {len(pool)} value -> {os.path.relpath(out, ROOT)}')
