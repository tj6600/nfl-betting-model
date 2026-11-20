"""Build the college football board (board/site/cfb.html): game picks, spreads, totals and the parlay builder.

  python scripts/cfb_board.py [--update] [--no-log]

--update refreshes this season's scores and DraftKings lines from ESPN first (python -m cfbmodel.espn update; free).
Every line on the board is DraftKings' own number from ESPN's scoreboard, so the board costs no Odds API credits.
The slate is every FBS game from now through the Monday after the coming Saturday (one football week).

Backtest (scripts/cfb_backtest.py, 2026 weeks 4-11, ~490 games): the model's spread picks went 56% against DraftKings'
opening line when it disagreed by 3+ points (202 bets), and the line moved toward the model 64% of the time, but only
47% against the closing line. So spread value is real only while the line is fresh: the board shows the opener and how
far the line has moved, and Value legs need the model 3+ points off the line it is priced at now. Totals and moneylines:
DraftKings was better than the model, so the board leans on DraftKings there.
"""
import sys, os, json, argparse, subprocess, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
from cfbmodel import espn as E, model as M
import parlays as PZ

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
ET = 'America/New_York'
BOOK = 'DraftKings'
DIR = os.path.join(ROOT, 'odds_log', 'cfb')
# weight on the model vs DraftKings no-vig (output/cfb_backtest.json): the spread model beat the opener but not the close;
# moneyline log loss was best with DraftKings alone (25% model costs almost nothing and lets the pick differ on toss-ups);
# the totals model was worse than DraftKings, so totals are DraftKings' chances only
W = {'Spread': 0.5, 'Moneyline': 0.25, 'Total': 0.0}
VALUE_PTS = 3.0     # Value spread: the model's line is 3+ points off DraftKings' current line

ap = argparse.ArgumentParser(); ap.add_argument('--update', action='store_true')
ap.add_argument('--no-log', action='store_true', help='rebuild the page only; save no pick or parlay log')
args = ap.parse_args()
if args.update:
    E.season(E.CURRENT); E.lines(E.CURRENT)

now = pd.Timestamp.now(tz='UTC')
today = now.tz_convert(ET).date()
sat = today + dt.timedelta(days=(5 - today.weekday()) % 7)
end = pd.Timestamp(sat + dt.timedelta(days=3), tz=ET)          # through Monday night
wk, stype, year = E.current_week()
frames = []
for w, st in ([(wk, stype), (wk + 1, stype)] if stype == 2 else [(1, 3)]) + ([(1, 3)] if stype == 2 and wk >= 14 else []):
    try: frames.append(E.scoreboard(year, w, st))
    except Exception as e: print('scoreboard', w, st, 'failed:', e)
S = pd.concat(frames).drop_duplicates('espn_id') if frames else pd.DataFrame()
S['ts'] = pd.to_datetime(S.start, utc=True)
S = S[(S.status == 'STATUS_SCHEDULED') & (S.ts > now) & (S.ts < end)].sort_values('ts').reset_index(drop=True)
WEEK = f"{year}_wk{int(S.week.mode().iloc[0]):02d}" if len(S) and stype == 2 else f'{year}_post_{sat:%m%d}'
if len(S) and S.season_type.eq(3).all(): WEEK = f'{year}_post_{sat:%m%d}'

G = E.load([year - 1, year]); LN = E.load_lines()
R = M.Ratings(lines=LN).fit(G, now, year)
if len(S):
    S['m'], S['t'] = R.predict(S)


def dec(a): return 1 + a / 100 if a > 0 else 1 + 100 / -a
def imp(a): return 1 / dec(a)
def nv(a, b): return imp(a) / (imp(a) + imp(b))
def ok(x): return x is not None and x == x


legs, LEG = [], {}


def mk_leg(lid, game, kind, label, price, p_model, p_book, flags, extra):
    w = W[kind]
    p = w * p_model + (1 - w) * p_book
    leg = dict(id=lid, game=game, kind=kind, label=label, price=int(price), p=round(float(p), 4), pm=round(float(p_model), 4), pb=round(float(p_book), 4),
               edge=round((p - imp(price)) * 100, 1), ev=round((p * dec(price) - 1) * 100, 1), flags=list(flags))
    leg.update(extra); legs.append(leg); LEG[lid] = leg
    return leg


def name(r, side): return r.home_name if side == 'home' else r.away_name


GAMES = []
for r in S.itertuples():
    gm = f'{r.away} @ {r.home}'
    m, t = float(r.m), float(r.t)
    nh, na = R.n_games.get(r.home_id, 0), R.n_games.get(r.away_id, 0)
    flags = [f'{name(r, s)} has played {n} game{"s" if n != 1 else ""} this season' for s, n in (('away', na), ('home', nh)) if n < 3]
    fcs = [name(r, s) for s, i in (('away', r.away_id), ('home', r.home_id)) if i not in R.fbs]
    row = dict(id=r.espn_id, game=gm, home=r.home, away=r.away, home_name=r.home_name, away_name=r.away_name,
               home_rank=None if not ok(r.home_rank) else int(r.home_rank), away_rank=None if not ok(r.away_rank) else int(r.away_rank),
               kick=r.ts.tz_convert(ET).strftime('%a %-I:%M %p'), start=r.ts.strftime('%Y-%m-%dT%H:%M:%SZ'), tv=r.tv or '', neutral=bool(r.neutral), note=r.note if isinstance(r.note, str) else '',
               model_line=round(-m * 2) / 2, model_total=round(t * 2) / 2, p_home=round(float(M.p_win(m)), 3), fcs=fcs, legs=[])
    ex = lambda market, side, line, sid: dict(gid=r.espn_id, market=market, side=side, line=line, sid=sid if isinstance(sid, str) else None, start=row['start'])
    if ok(r.sp_home) and ok(r.sp_home_px) and ok(r.sp_away_px):
        b = nv(r.sp_home_px, r.sp_away_px); ph = float(M.p_cover(m, r.sp_home))
        diff = (m + r.sp_home)                                  # >0: the model likes the home side by this many points
        row.update(line=float(r.sp_home), open_line=float(r.open_sp_home) if ok(r.open_sp_home) else None, diff=round(diff, 1))
        if ok(r.open_sp_home):   # how far DraftKings has moved since it opened, and whether toward the model
            row['moved'] = float(r.sp_home - r.open_sp_home)
        for side, pt, px, pm, pb, sid in (('home', r.sp_home, r.sp_home_px, ph, b, r.sid_sp_home), ('away', -r.sp_home, r.sp_away_px, 1 - ph, 1 - b, r.sid_sp_away)):
            team = r.home if side == 'home' else r.away
            L = mk_leg(f'{r.espn_id}-sp-{side}', gm, 'Spread', f'{name(r, side)} {pt:+g}', px, pm, pb, flags, ex('spread', side, float(pt), sid))
            L['pts'] = round(diff if side == 'home' else -diff, 1); L['team'] = team
            row['legs'].append(L['id'])
    if ok(r.ml_home) and ok(r.ml_away):
        b = nv(r.ml_home, r.ml_away); pw = float(M.p_win(m))
        pb_ = W['Moneyline'] * pw + (1 - W['Moneyline']) * b
        row['pick'] = 'home' if pb_ >= 0.5 else 'away'; row['pick_p'] = round(max(pb_, 1 - pb_), 3)
        for side, px, pm, pb, sid in (('home', r.ml_home, pw, b, r.sid_ml_home), ('away', r.ml_away, 1 - pw, 1 - b, r.sid_ml_away)):
            L = mk_leg(f'{r.espn_id}-ml-{side}', gm, 'Moneyline', f'{name(r, side)} to win', px, pm, pb, flags, ex('moneyline', side, None, sid))
            L['team'] = r.home if side == 'home' else r.away
            row['legs'].append(L['id'])
    else:   # no DraftKings moneyline (usually a big mismatch): the model's own winner pick
        row['pick'] = 'home' if m >= 0 else 'away'; row['pick_p'] = round(float(max(M.p_win(m), 1 - M.p_win(m))), 3)
    if ok(r.total) and ok(r.over) and ok(r.under):
        b = nv(r.over, r.under); po = float(M.p_over(t, r.total))
        row.update(line_total=float(r.total), open_total=float(r.open_total) if ok(r.open_total) else None)
        for side, px, pm, pb, sid in (('Over', r.over, po, b, r.sid_over), ('Under', r.under, 1 - po, 1 - b, r.sid_under)):
            row['legs'].append(mk_leg(f'{r.espn_id}-to-{side}', gm, 'Total', f'{side} {r.total:g} ({r.away} @ {r.home})', px, pm, pb, flags, ex('total', side, float(r.total), sid))['id'])
    # the board's call on every market (Thomas, 2026-11-18: "just predict the correct winners, spreads and totals"):
    # spread = the side with the higher blended cover chance; total = the side of the model's projected total
    sp = [LEG[i] for i in row['legs'] if LEG[i]['market'] == 'spread']
    if sp:
        b = max(sp, key=lambda L: L['p']); b['bpick'] = True; row['sp_pick'] = b['id']
    to = [LEG[i] for i in row['legs'] if LEG[i]['market'] == 'total']
    if to:
        b = next(L for L in to if L['side'] == ('Over' if t > L['line'] else 'Under')); b['bpick'] = True; row['to_pick'] = b['id']
    GAMES.append(row)
gl = {g['id']: g for g in GAMES}


def is_value(L):
    """Value (backtest rule): a spread where the model's line is 3+ points better than DraftKings' line now, priced -200 or
    longer, no flags. Moneylines and totals never count (DraftKings beat the model there)."""
    return L['kind'] == 'Spread' and L['pts'] >= VALUE_PTS and L['price'] >= PZ.MAX_JUICE and not L['flags']


for L in legs:
    g = gl[L['gid']]
    L['pick'] = bool(L['market'] == 'moneyline' and g.get('pick') == L['side'])
    L['bpick'] = bool(L.get('bpick') or L['pick'])
    L['cat'] = 'Value' if is_value(L) else ''
pool = sorted([l for l in legs if l['cat'] == 'Value'], key=lambda l: -l['pts'])
pool += sorted([l for l in legs if l['cat'] != 'Value' and l['kind'] == 'Spread' and not l['flags'] and 1.5 <= l['pts'] < VALUE_PTS and l['price'] >= PZ.MAX_JUICE], key=lambda l: -l['pts'])
likely = lambda L: PZ.likely(L) or (L.get('pick') and L['p'] >= 0.55 and L['price'] >= PZ.MAX_JUICE and not L['flags'])

# pick log for grading (scripts/cfb_grade.py): every priced leg; each leg is graded at the first price the board showed
stamp = now.strftime('%Y-%m-%dT%H%MZ')
if legs and not args.no_log:
    os.makedirs(os.path.join(DIR, 'picks'), exist_ok=True)
    pd.DataFrame([{k: l.get(k) for k in ['id', 'gid', 'game', 'start', 'kind', 'market', 'side', 'team', 'line', 'label', 'price', 'p', 'pm', 'pb', 'edge', 'ev', 'pts', 'cat']}
                  | {'flagged': bool(l['flags']), 'pick': l['pick'], 'bpick': l['bpick']} for l in legs]).to_csv(os.path.join(DIR, 'picks', f'{WEEK}_{stamp}.csv'), index=False)
    PZ.log(DIR, WEEK, stamp, legs, [l['id'] for l in pool], likely)
    subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'cfb_grade.py')], check=False, stdout=subprocess.DEVNULL)
gr = os.path.join(DIR, 'grade_report.json')
LIVE = json.load(open(gr)) if os.path.exists(gr) else None
bf = os.path.join(ROOT, 'output', 'cfb_backtest.json')
BT = json.load(open(bf)) if os.path.exists(bf) else None

# top 25 ratings, for the Ratings tab
fb = [t for t in R.fbs if t in R.off]
names = {}
for x in G.itertuples():
    names[x.home_id] = (x.home, x.home_name); names[x.away_id] = (x.away, x.away_name)
top = sorted(fb, key=lambda t: -R.rating(t))
RAT = [dict(rank=i + 1, team=names.get(t, (t, t))[1], abbr=names.get(t, (t, t))[0], rating=round(R.rating(t), 1), off=round(R._o(t), 1), dfn=round(R._d(t), 1),
            games=int(R.n_games.get(t, 0))) for i, t in enumerate(top)]

DATA = dict(week=WEEK, weekLabel=(f'Week {int(S.week.mode().iloc[0])}' if stype == 2 and len(S) else 'Bowl season') + f' · {today:%B %-d}', book=BOOK,
            through=str(pd.to_datetime(G[G.home_pts.notna()].start, utc=True).max().tz_convert(ET).date()), built=stamp,
            sd=dict(m=M.SD_MARGIN, t=M.SD_TOTAL),   # margin/total sd, for the page's line editor (board/site/lines.js)
            games=GAMES, legs=legs, pool=[l['id'] for l in pool], live=LIVE, backtest=BT, weights=W, value_pts=VALUE_PTS, hfa=round(float(R.home), 1),
            ratings=RAT)


def clean(o):
    if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, (float, np.floating)): return None if o != o else float(o)
    if isinstance(o, np.bool_): return bool(o)
    return o


B = os.path.join(ROOT, 'board')
import bank as BANK
head = open(os.path.join(B, 'head.html')).read().replace('<title>Player Props Board</title>', '<title>College Football Board</title>')
data = json.dumps(clean(DATA), separators=(',', ':')).replace('</', '<\\/')
html = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n' + BANK.APP_HEAD + head + BANK.SPORT_CSS + '\n<style>\n' + open(os.path.join(B, 'nhl.css')).read() + open(os.path.join(B, 'cfb.css')).read()
        + '</style>\n</head>\n<body>\n' + BANK.nav('cfb') + open(os.path.join(B, 'cfb_body.html')).read()
        + f'<script type="application/json" id="cfb-data">{data}</script>\n<script>\n' + open(os.path.join(B, 'cfb_app.js')).read() + '</script>\n</body>\n</html>\n')
os.makedirs(os.path.join(B, 'site'), exist_ok=True)
open(os.path.join(B, 'site', 'cfb.html'), 'w').write(html)
print(f'CFB board {WEEK}: {len(GAMES)} games, {len(legs)} priced legs, {sum(l["cat"] == "Value" for l in legs)} value -> board/site/cfb.html')

BANK.safe_build(log_it=not args.no_log)
