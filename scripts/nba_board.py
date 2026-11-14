"""Build the NBA board (board/site/nba.html): game picks, player props, parlay builder, game logs.

  python scripts/nba_board.py [--update] [--date YYYY-MM-DD] [--no-log]

--update first adds newly finished games to nba_data/ (hoopR raw JSON; no pyarrow needed).
Prices come from the latest odds_log/nba snapshots (python -m nbamodel.odds games / props).
"""
import sys, os, json, glob, argparse, datetime as dt; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
from nbamodel import data as D, games as M, props as PR, odds as O, injuries as INJ

ROOT = os.path.join(os.path.dirname(__file__), '..')
ap = argparse.ArgumentParser(); ap.add_argument('--update', action='store_true'); ap.add_argument('--date')
ap.add_argument('--no-log', action='store_true', help='rebuild the page only; save no pick or parlay log (the 9 AM grading run)')
args = ap.parse_args()
if args.update:
    D.update()
G, P, S = D.load()
G = G[G.home.isin(M.TEAMS) & G.away.isin(M.TEAMS)].sort_values('date').reset_index(drop=True)
P = P[P.team.isin(M.TEAMS)]
ET = 'America/New_York'
MODEL_W_GAME = 0.25   # backtest: the game model adds nothing beyond the line (50.1% ATS), so it gets a small weight
MODEL_W_PROP = 0.5    # props: no historical prop lines to test against, so half model, half book (as for the NFL board)
BOOK = 'DraftKings'


def dec(a): return 1 + a / 100 if a > 0 else 1 + 100 / -a
def imp(a): return 1 / dec(a)


# ---------- slate ----------
gf = O.latest('games')
ev = json.load(open(gf)) if gf else []
taken = pd.Timestamp(os.path.basename(gf)[6:-5].replace('Z', '')).tz_localize('UTC').tz_convert(ET) if gf else None
GR = O.game_rows(ev) if ev else pd.DataFrame(columns=['event', 'tip', 'home', 'away', 'book', 'bkey', 'market', 'side', 'point', 'price'])
if len(GR):
    GR['day'] = pd.to_datetime(GR.tip).dt.tz_convert(ET).dt.date.astype(str)
day = args.date or (GR.day.min() if len(GR) else str(pd.Timestamp.now(tz=ET).date()))
slate = S[S.date == day][['game_id', 'date', 'tip', 'home', 'away']].copy()
slate['season'] = D.SEASON
GR = GR[GR.day == day] if len(GR) else GR

# ---------- game model ----------
MS = M.team_missing(P)
rest_src = pd.concat([G[['game_id', 'date', 'home', 'away']], slate[['game_id', 'date', 'home', 'away']]])
r = M.Ratings().fit(G, MS, day, rest=M.rest_days(rest_src))
# who sat each team's last game (the only availability signal we have)
last_gid = P.sort_values('date').groupby('team').game_id.last()
miss = {t: MS['val'].get((g, t), 0.0) for t, g in last_gid.items()}
pf = M.player_form(P)
INJURY = INJ.latest()   # ESPN injury report; None if unreachable (then the last-game proxy is used)
if INJURY is not None:
    form = pf[~pf.dnp & (pf['min'] > 0)].sort_values('date').groupby('pid').tail(1).set_index('pid')
    form = form[form.date >= str(pd.Timestamp(day) - pd.Timedelta(days=60))[:10]]
    miss = {t: 0.0 for t in M.TEAMS}
    for pid, v in INJURY.items():
        if v['status'] == 'Out' and pid in form.index and v['team']:
            f = form.loc[pid]
            if f.mpg >= 15: miss[v['team']] += float(f.mpg * (f.gsm - M.REP))
pred = r.predict(slate, miss=miss)
outs = {}
for t, g in last_gid.items():
    q = pf[(pf.game_id == g) & (pf.team == t) & pf.dnp & ~pf.reason.fillna('').str.contains('COACH', case=False) & (pf.mpg >= 15)]
    outs[t] = [dict(name=x.name, reason=str(x.reason).title(), mpg=round(x.mpg, 1)) for x in q.itertuples()]
if INJURY is not None:   # replace the proxy with today's report: regulars listed Out
    recent_m = pf[~pf.dnp & (pf['min'] > 0)].sort_values('date').groupby('pid').tail(1).set_index('pid')
    outs = {t: [] for t in M.TEAMS}
    for pid, v in INJURY.items():
        if v['status'] == 'Out' and v['team'] and pid in recent_m.index and recent_m.loc[pid].mpg >= 15:
            outs[v['team']].append(dict(name=v['name'], reason=v['comment'], mpg=round(float(recent_m.loc[pid].mpg), 1)))

teams = r.team_table()
games, legs = [], []


def mk_leg(lid, game, kind, label, sub, price, p_model, p_book, w, flags=(), extra=None):
    p = p_model if p_book is None else w * p_model + (1 - w) * p_book
    be = imp(price)
    leg = dict(id=lid, game=game, kind=kind, label=label, sub=sub, price=int(price), p=round(float(p), 4),
               pm=round(float(p_model), 4), pb=None if p_book is None else round(float(p_book), 4),
               edge=round((p - be) * 100, 1), ev=round((p * dec(price) - 1) * 100, 1), flags=list(flags))
    if extra: leg.update(extra)
    legs.append(leg)
    return leg


for g in pred.merge(slate[['game_id', 'tip']], on='game_id').itertuples():
    gm = f'{g.away} @ {g.home}'
    q = GR[(GR.home == g.home) & (GR.away == g.away)] if len(GR) else GR
    dk = q[q.book == BOOK]
    row = dict(id=int(g.game_id), game=gm, home=g.home, away=g.away, tip=pd.Timestamp(g.tip).strftime('%-I:%M %p'),
               margin=round(g.margin, 1), total=round(g.total, 1), p_home=round(g.p_home, 1), p_away=round(g.p_away, 1),
               rank_home=int(teams.reset_index(drop=True).index[teams.team.values == g.home][0]) + 1,
               rank_away=int(teams.reset_index(drop=True).index[teams.team.values == g.away][0]) + 1,
               out_home=outs.get(g.home, []), out_away=outs.get(g.away, []), legs=[])
    def pair(mkt):
        x = dk[dk.market == mkt]
        return {s.side: s for s in x.itertuples()}
    sp, to, ml = pair('spreads'), pair('totals'), pair('h2h')
    if g.home in sp and g.away in sp:
        hs, as_ = sp[g.home], sp[g.away]
        nv = imp(hs.price) / (imp(hs.price) + imp(as_.price))
        ch, _, _ = M.probs(g.margin, g.total, hs.point, 0)
        row['spread'] = float(hs.point)
        for side, s, pm, pb in [(g.home, hs, float(ch), nv), (g.away, as_, 1 - float(ch), 1 - nv)]:
            row['legs'].append(mk_leg(f'{g.game_id}-sp-{side}', gm, 'Spread', f'{side} {s.point:+g}', gm, s.price, pm, pb, MODEL_W_GAME, extra=dict(gid=int(g.game_id), market='spread', side=side, line=float(s.point), sid=getattr(s, 'sid', None)))['id'])
    if 'Over' in to and 'Under' in to:
        o, u = to['Over'], to['Under']
        nv = imp(o.price) / (imp(o.price) + imp(u.price))
        _, po, _ = M.probs(g.margin, g.total, 0, o.point)
        row['line_total'] = float(o.point)
        for side, s, pm, pb in [('Over', o, float(po), nv), ('Under', u, 1 - float(po), 1 - nv)]:
            row['legs'].append(mk_leg(f'{g.game_id}-to-{side}', gm, 'Total', f'{side} {s.point:g}', gm, s.price, pm, pb, MODEL_W_GAME, extra=dict(gid=int(g.game_id), market='total', side=side, line=float(s.point), sid=getattr(s, 'sid', None)))['id'])
    if g.home in ml and g.away in ml:
        h, a = ml[g.home], ml[g.away]
        nv = imp(h.price) / (imp(h.price) + imp(a.price))
        _, _, pw = M.probs(g.margin, g.total, 0, 0)
        for side, s, pm, pb in [(g.home, h, float(pw), nv), (g.away, a, 1 - float(pw), 1 - nv)]:
            row['legs'].append(mk_leg(f'{g.game_id}-ml-{side}', gm, 'Moneyline', f'{side} to win', gm, s.price, pm, pb, MODEL_W_GAME, extra=dict(gid=int(g.game_id), market='moneyline', side=side, line=None, sid=getattr(s, 'sid', None)))['id'])
    games.append(row)

# ---------- props ----------
pfile = O.latest('props', day)
PRW = O.prop_rows(json.load(open(pfile))) if pfile else pd.DataFrame(columns=['event', 'home', 'away', 'book', 'bkey', 'stat', 'player', 'side', 'point', 'price'])
# upcoming rows: everyone who played in either of the team's last two games
recent = P.sort_values('date')
tg = recent[['team', 'game_id', 'date']].drop_duplicates().sort_values('date').groupby('team').tail(2)
cand = recent.merge(tg, on=['team', 'game_id', 'date'])
cand = cand[~cand.dnp | ~cand.reason.fillna('').str.contains('COACH', case=False)].sort_values('date').groupby('pid').tail(1)
up = []
for s in slate.itertuples():
    for t, o, h in [(s.home, s.away, True), (s.away, s.home, False)]:
        c = cand[cand.team == t]
        for x in c.itertuples():
            up.append(dict(game_id=s.game_id, season=D.SEASON, date=day, team=t, opp=o, home=h, pid=x.pid, name=x.name, pos=x.pos,
                           starter=x.starter, dnp=False, reason=None))
U = pd.DataFrame(up)
tot = {g['id']: g.get('line_total', g['total']) for g in games}
# injuries: players listed Out sit; the props model hands their production to teammates (props.SHARE, backtested)
OUT = set()
if INJURY is not None and len(U):
    OUT = {(g, i) for g, i in zip(U.game_id, U.pid) if (INJURY.get(int(i)) or {}).get('status') == 'Out'}
F = PR.features(pd.concat([P, U], ignore_index=True), G, totals=tot, out=OUT)
hist = F[F.date < day]
SP = PR.Spread().fit(hist[hist.season >= D.SEASON - 2])
FU = F[(F.date == day) & F.game_id.isin(slate.game_id)]
gone = FU[FU.absent]
FU = FU[(FU.n_prev >= 3) & (FU.m_ewm >= 10) & ~FU.apply(lambda r: (r.game_id, r.pid) in OUT, axis=1)].copy()
bn = gone.groupby(['game_id', 'team']).name.apply(lambda s: ', '.join(s)).to_dict()
FU['boost'] = [bn.get((g, t)) if v > 0 else None for g, t, v in zip(FU.game_id, FU.team, FU.vacated)]
key = lambda s: s.str.lower().str.replace(r'[^a-z]', '', regex=True).str.replace(r'(jr|sr|ii|iii|iv)$', '', regex=True)
if len(PRW):
    PRW['k'] = key(PRW.player)
# alternate lines ("25+ points", Over only) for the parlays: python -m nbamodel.odds alt
afile = O.latest('alt', day)
ALT = O.alt_rows(json.load(open(afile))) if afile else O.alt_rows([])
ALT['k'] = key(ALT.player) if len(ALT) else ''
ALT_MARGIN = 1.06    # alt lines have no Under to remove the vig; book chances are divided by an estimated 6% margin (as for NFL)
FU = FU.assign(k=key(FU.name))
gl = {g['id']: g for g in games}
players = []
for x in FU.itertuples():
    sat = [o['name'] for o in outs.get(x.team, [])]
    flags = []
    if x.days_off > 7: flags.append(f'Returning: last played {int(x.days_off)} days ago')
    inj = (INJURY or {}).get(int(x.pid))
    if inj: flags.append(f"{inj['status']}: {inj['comment']}")
    elif x.name in sat and INJURY is None: flags.append('Sat out the last game')
    lg = hist[(hist.pid == x.pid) & hist.played].sort_values('date').tail(12)
    log = [dict(d=r.date[5:], o=('vs ' if r.home else '@ ') + r.opp, m=int(getattr(r, 'min')), pts=int(r.pts), reb=int(r.reb), ast=int(r.ast),
                fg3m=int(r.fg3m), pra=int(r.pra)) for r in lg.iloc[::-1].itertuples()]
    season_rows = hist[(hist.pid == x.pid) & hist.played & (hist.season == D.SEASON)]
    p = dict(id=int(x.pid), name=x.name, team=x.team, opp=x.opp, game=gl[x.game_id]['game'], pos=x.pg, mpg=round(x.m_ewm, 1),
             start=bool(x.start_prev) if x.start_prev == x.start_prev else False, flags=flags, log=log,
             avg={k: round(float(season_rows[k].mean()), 1) if len(season_rows) else None for k in PR.STATS}, gp=int(len(season_rows)),
             props={}, boost=getattr(x, 'boost', None) if isinstance(getattr(x, 'boost', None), str) else None)
    for k in PR.STATS:
        proj = getattr(x, f'{k}_proj')
        if not proj == proj or proj <= 0: continue
        lo, md, hi = SP.quantiles(k, proj)
        e = dict(proj=round(proj, 1), lo=round(lo, 1), hi=round(hi, 1), opp=round(getattr(x, f'{k}_of'), 3))
        if len(PRW):
            q = PRW[(PRW.k == x.k) & (PRW.stat == k)]
            dkq = q[q.book == BOOK]
            if len(dkq):
                ln = dkq.point.mode().iloc[0]
                dd = dkq[dkq.point == ln]; so = dd[dd.side == 'Over']; su = dd[dd.side == 'Under']
                if len(so) and len(su):
                    po_m = 0.5 + 0.85 * (float(SP.p_over(k, proj, ln)[0]) - 0.5)
                    nv = imp(so.price.iloc[0]) / (imp(so.price.iloc[0]) + imp(su.price.iloc[0]))
                    e.update(line=float(ln), books=q[q.point == ln].pivot_table(index='book', columns='side', values='price', aggfunc='first').reset_index().rename(columns=str.lower).to_dict('records'))
                    for side, pr_, pm, pb in [('Over', int(so.price.iloc[0]), po_m, nv), ('Under', int(su.price.iloc[0]), 1 - po_m, 1 - nv)]:
                        L = mk_leg(f'{x.pid}-{k}-{side}', p['game'], PR.LABEL[k], f'{x.name} {side} {ln:g} {PR.LABEL[k].lower()}',
                                   f'{x.team} vs {x.opp} · proj {proj:.1f}', pr_, pm, pb, MODEL_W_PROP, flags=flags,
                                   extra=dict(pid=int(x.pid), stat=k, team=x.team, gid=int(x.game_id), market=k, side=side, line=float(ln),
                                              sid=(so if side == 'Over' else su).get('sid', pd.Series([None])).iloc[0]))
                        e[side.lower()] = dict(id=L['id'], price=pr_, p=L['p'], pm=L['pm'], pb=L['pb'], edge=L['edge'], ev=L['ev'])
        for a in (ALT[(ALT.k == x.k) & (ALT.stat == k)].itertuples() if len(ALT) else []):
            n = int(a.point + 0.5)
            pm_ = 0.5 + 0.85 * (float(SP.p_over(k, proj, a.point)[0]) - 0.5)
            L = mk_leg(f'{x.pid}-{k}-alt{n}', p['game'], 'Alt ' + PR.LABEL[k].lower(), f'{x.name} {n}+ {PR.LABEL[k].lower()}',
                       f'{x.team} vs {x.opp} · proj {proj:.1f}', int(a.price), pm_, min(0.995, imp(a.price) / ALT_MARGIN), MODEL_W_PROP, flags=flags,
                       extra=dict(pid=int(x.pid), stat=k, team=x.team, gid=int(x.game_id), market=k, side='Over', line=float(a.point), alt=True,
                                  sid=a.sid if isinstance(a.sid, str) else None))
            if not 0.5 <= L['p'] <= 0.97: legs.remove(L)   # keep the rungs worth a parlay leg
        p['props'][k] = e
    players.append(p)

# picks: value = edge >= 3 pts and chance >= 55%, no flag
for L in legs:
    L['cat'] = 'Value' if (L['edge'] >= 3 and L['p'] >= 0.55 and not L['flags'] and not L.get('alt')) else ''
# suggested slips: up to 6 different parlays, each the best remaining legs (1 per game, 1 per player, 2-4 legs);
# a leg is used in at most one slip so each suggestion is different. Value legs first, then near-value (edge 1.5+, 52%+).
def build_slips(pool, n=6, size=4):
    slips, used = [], set()
    for _ in range(n):
        slip, g_used, p_used = [], set(), set()
        for L in pool:
            if L['id'] in used or L['game'] in g_used or (L.get('pid') and L['pid'] in p_used): continue
            slip.append(L['id']); g_used.add(L['game'])
            if L.get('pid'): p_used.add(L['pid'])
            if len(slip) >= size: break
        if len(slip) < 2: break
        used.update(slip); slips.append(slip)
    return slips
ok = lambda l: not l['flags']
pool = sorted([l for l in legs if l['cat'] == 'Value'], key=lambda l: -l['edge'])
pool += sorted([l for l in legs if l['cat'] != 'Value' and ok(l) and not l.get('alt') and l['edge'] >= 1.5 and l['p'] >= 0.52], key=lambda l: -l['edge'])
slips = build_slips(pool)
sug = slips[0] if slips else []

# pick log: every priced leg as offered when this board was built, keyed to the odds snapshot it used.
# scripts/nba_grade.py grades the earliest log of each day against results and closing lines.
if legs and not args.no_log:
    stamp = os.path.basename(pfile)[17:-5] if pfile else os.path.basename(gf)[6:-5]
    os.makedirs(os.path.join(O.DIR, 'picks'), exist_ok=True)
    lf = os.path.join(O.DIR, 'picks', f'{day}_{stamp}.csv')
    if not os.path.exists(lf):
        pl = pd.DataFrame([{k: l.get(k) for k in ['id', 'gid', 'game', 'kind', 'market', 'side', 'line', 'pid', 'team', 'label', 'price', 'p', 'pm', 'pb', 'edge', 'ev', 'cat']}
                           | {'alt': bool(l.get('alt')), 'flagged': bool(l['flags']), 'suggested': l['id'] in sug} for l in legs])
        pl.to_csv(lf, index=False)
    # suggested parlays as the page builds them (both modes, every leg count), graded by scripts/nba_grade.py
    import parlays as PZ
    PZ.log(O.DIR, day, stamp, legs, [l['id'] for l in pool], lambda L: L['edge'] >= 1 and L['p'] >= 0.55 and not L['flags'])
# backtest summary for the page
bt = {}
bf = os.path.join(D.DIR, 'backtest_games.csv')
if os.path.exists(bf):
    b = pd.read_csv(bf)
    rows = []
    for th in [0, 2, 4, 6]:
        a = b[b.edge.abs() >= th].ats_win.dropna(); t = b[b.tedge.abs() >= th].tot_win.dropna()
        rows.append(dict(edge=th, ats_n=int(len(a)), ats=round(float(a.mean()), 3), tot_n=int(len(t)), tot=round(float(t.mean()), 3)))
    bt = dict(games=int(len(b)), seasons='2023-24 to 2025-26', rows=rows,
              mae_model=round(float((b.res - b.margin).abs().mean()), 2), mae_line=round(float((b.res + b.spread).abs().mean()), 2))
pb = os.path.join(D.DIR, 'backtest_props.json')
if os.path.exists(pb):
    bt['props'] = json.load(open(pb))

gr = os.path.join(O.DIR, 'grade_report.json')
LIVE = json.load(open(gr)) if os.path.exists(gr) else None
DATA = dict(live=LIVE, injuries=INJURY is not None, day=day, dayLabel=pd.Timestamp(day).strftime('%A, %B %-d'), taken=taken.strftime('%A %-I:%M %p ET') if taken is not None else None,
            propsTaken=os.path.basename(pfile)[17:-5] if pfile else None, through=G.date.max(), book=BOOK,
            games=games, players=players, legs=legs, suggested=sug, slips=slips, pool=[l['id'] for l in pool], backtest=bt,
            teams=[dict(team=t.team, off=round(t.off, 1), deff=round(t.deff, 1), net=round(t.net, 1)) for t in teams.itertuples()])
B = os.path.join(ROOT, 'board')
head = open(os.path.join(B, 'head.html')).read().replace('<title>Player Props Board</title>', '<title>NBA Props Board</title>')
nav = ('<nav class="sportnav" aria-label="Sport"><a href="index.html">NFL</a><a href="nba.html" aria-current="page">NBA</a><a href="nhl.html">NHL</a></nav>\n')
SPORT_CSS = """<style>
.sportnav { display: flex; gap: 6px; max-width: 1080px; margin: 0 auto; padding: 14px max(16px, env(safe-area-inset-left, 0px)) 0; }
.sportnav a { font: 700 15px var(--display, sans-serif); letter-spacing: .08em; text-transform: uppercase; text-decoration: none; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: 6px 16px; background: var(--panel); }
.sportnav a[aria-current="page"] { background: var(--ink); color: var(--bg); border-color: var(--ink); }
</style>"""
def clean(o):
    if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (float, np.floating)): return None if o != o else float(o)
    if isinstance(o, np.bool_): return bool(o)
    return o
data = json.dumps(clean(DATA), separators=(',', ':')).replace('</', '<\\/')
html = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n' + head + SPORT_CSS + '\n<style>\n' + open(os.path.join(B, 'nba.css')).read() + '</style>\n</head>\n<body>\n' + nav
        + open(os.path.join(B, 'nba_body.html')).read()
        + f'<script type="application/json" id="nba-data">{data}</script>\n<script>\n' + open(os.path.join(B, 'nba_app.js')).read() + '</script>\n</body>\n</html>\n')
os.makedirs(os.path.join(B, 'site'), exist_ok=True)
open(os.path.join(B, 'site', 'nba.html'), 'w').write(html)
print(f'NBA board for {day}: {len(games)} games, {len(players)} players, {len(legs)} priced legs, {len(sug)} suggested -> board/site/nba.html')
