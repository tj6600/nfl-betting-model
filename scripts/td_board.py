"""Build the Touchdown Board page (board/touchdown-board.html) from this week's TD picks and props odds.

Run after scripts/td_picks.py. Publish the output as the Touchdown Board artifact.
"""
import sys, os, glob, json; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
ROOT = os.path.join(os.path.dirname(__file__), '..')
import numpy as np, pandas as pd
from nflmodel.model import G
from nflmodel.odds import TEAMS
from nflmodel import touchdowns as T

f = sorted(glob.glob(os.path.join(ROOT, 'odds_log', 'picks', '*_td.csv')))[-1]
season, wk = os.path.basename(f).split('_')[:2]; season, week = int(season), int(wk[2:])
A = pd.read_csv(f)
C = pd.read_csv(f.replace('_td.csv', '_td_picks.csv'))[['pid', 'category', 'why']]
A = A.merge(C, on='pid', how='left')
GW = G[(G.season == season) & (G.week == week)]
props = sorted(glob.glob(os.path.join(ROOT, 'odds_log', 'props', 'anytime_td_*.json')))[-1]
rows = []
for e in json.load(open(props)):
    for bk in e.get('bookmakers', []):
        for m in bk['markets']:
            for o in m['outcomes']:
                if o.get('name', 'Yes') == 'Yes' and o.get('description'):
                    rows.append((TEAMS.get(e['home_team']), TEAMS.get(e['away_team']), o['description'], bk['title'], o['price']))
O = pd.DataFrame(rows, columns=['home', 'away', 'player', 'book', 'price']); O['k'] = T._key(O.player)
POSN = {'RB': 'running backs', 'WR': 'receivers', 'TE': 'tight ends', 'QB': 'quarterbacks'}
num = lambda x, f=lambda v: v: None if x != x else f(x)
out = []
for r in A.itertuples():
    away, home = r.game.split(' @ ')
    g = GW[(GW.home_team == home) & (GW.away_team == away)].iloc[0]
    k = T._key(pd.Series([r.full_name])).iloc[0]
    bks = O[(O.home == home) & (O.away == away) & (O.k == k)].sort_values('price', ascending=False)
    why = r.why if isinstance(r.why, str) else None
    if why is None:
        bits = [f"{r.h_carries:.1f} carries and {r.h_targets:.1f} targets a game", f"{r.h_gl_share * 100:.0f}% of the team's goal-line chances",
                f"team expected to score {r.imp_pts:.1f}"]
        if abs(r.def_td) >= 0.15:
            bits.append(f"{r.defteam} allows {'more' if r.def_td > 0 else 'fewer'} TDs than average to {POSN[r.position]}")
        if r.dc_rank == r.dc_rank:
            dc = f"depth chart {r.position}{int(r.dc_rank)}"
            if r.dc_prev == r.dc_prev and int(r.dc_prev) != int(r.dc_rank): dc += f" (was {r.position}{int(r.dc_prev)} at his last game)"
            bits.append(dc)
        why = ', '.join(bits)
        if r.missed_n >= 1:
            why = f"Missed the last {int(r.missed_n)} game{'s' if r.missed_n > 1 else ''}, so his usage is from before that. " + why
    out.append(dict(id=r.pid, name=r.full_name, team=r.posteam, opp=r.defteam, home=home, away=away, game=r.game,
                    day=str(g.gameday.date()), time=str(g.gametime), weekday=str(g.weekday), pos=r.position,
                    model=round(r.model_prob * 100, 1), book=num(r.book_prob, lambda v: round(v * 100, 1)),
                    best=num(r.best_price, int), bestBook=r.best_book if isinstance(r.best_book, str) else None,
                    median=num(r.median_price, round), ev=num(r.ev, lambda v: round(v * 100, 1)),
                    cat=r.category if isinstance(r.category, str) else '',
                    carries=round(r.h_carries, 1), targets=round(r.h_targets, 1), gl=round(r.h_gl_share * 100), rz=round(r.h_rz_share * 100),
                    tdpg=round(r.h_tds, 2), room=round(r.room_share * 100), last=round(r.last_share * 100), missed=int(r.missed_n),
                    imp=round(r.imp_pts, 1), deftd=round(r.def_td, 2), why=why,
                    depth=num(r.dc_rank, int), depthPrev=num(r.dc_prev, int),
                    books=[dict(b=b.book, p=int(b.price)) for b in bks.itertuples()]))
taken = pd.Timestamp(os.path.basename(props)[11:26].replace('T', ' ')[:-1] if False else os.path.basename(props)[11:].split('.')[0].replace('Z', ''))
D = dict(season=season, week=week, taken=taken.tz_localize('UTC').tz_convert('America/New_York').strftime('%A, %B %-d at %-I:%M %p ET'), players=out)
# rushing / receiving yards
yf = os.path.join(ROOT, 'odds_log', 'picks', f'{season}_wk{week:02d}_yards.csv')
yprops = sorted(glob.glob(os.path.join(ROOT, 'odds_log', 'props', 'yards_*.json')))
yards = []
if os.path.exists(yf) and yprops:
    Yd = pd.read_csv(yf)
    yrows = []
    for e in json.load(open(yprops[-1])):
        for bk in e.get('bookmakers', []):
            for m in bk['markets']:
                for o in m['outcomes']:
                    if o.get('description') and o.get('point') is not None:
                        yrows.append((TEAMS.get(e['home_team']), TEAMS.get(e['away_team']), 'rush' if m['key'] == 'player_rush_yds' else 'rec',
                                      o['description'], bk['title'], o['name'], o['point'], o['price']))
    YO = pd.DataFrame(yrows, columns=['home', 'away', 'kind', 'player', 'book', 'side', 'pt', 'pr']); YO['k'] = T._key(YO.player)
    gl = {r.game: r for r in GW.assign(game=GW.away_team + ' @ ' + GW.home_team).itertuples()}
    for (pid, market), grp in Yd.groupby(['pid', 'market']):
        kind = 'rush' if market.startswith('Rush') else 'rec'
        r = grp.iloc[0]; away, home = r.game.split(' @ '); g = gl[r.game]
        sides = {x.side: dict(line=float(x.best_line), price=int(x.best_price), book=x.best_book, p=round(float(x.model_prob), 4),
                              model=round(float(x.model_only), 4), mkt=round(float(x.market_prob), 4), ev=round(float(x.ev), 4)) for x in grp.itertuples()}
        lean = grp.sort_values('ev', ascending=False).iloc[0]
        cat = grp.category.dropna(); cat = cat.iloc[0] if len(cat) else ''
        note = grp.note.dropna(); note = note.iloc[0] if len(note) else ''
        k = T._key(pd.Series([r.player])).iloc[0]
        bl = YO[(YO.home == home) & (YO.away == away) & (YO.kind == kind) & (YO.k == k)]
        books = []
        for b, bg in bl.groupby('book'):
            o = bg[bg.side == 'Over']; u = bg[bg.side == 'Under']
            books.append(dict(b=b, o=dict(pt=float(o.pt.iloc[0]), pr=int(o.pr.iloc[0])) if len(o) else None,
                              u=dict(pt=float(u.pt.iloc[0]), pr=int(u.pr.iloc[0])) if len(u) else None))
        yards.append(dict(id=f'{pid}-{kind}', pid=pid, name=r.player, team=r.team, opp=r.opp, game=r.game, home=home, away=away,
                          day=str(g.gameday.date()), time=str(g.gametime), weekday=str(g.weekday), pos=r.position, market=kind,
                          line=float(r.line), lean=lean.side, sides=sides, projection=float(r.projection), median=float(r['median']),
                          q25=float(r.q25), q75=float(r.q75), recent=float(r.recent_yds), carries=float(r.carries), targets=float(r.targets),
                          imp=float(r.imp_pts), margin=float(r.exp_margin), defyds=float(r.def_yds) if r.def_yds == r.def_yds else 0.0,
                          missed=int(r.missed_n), depth=num(r.dc_rank, int), depthPrev=num(r.dc_prev, int), regular=bool(r.regular),
                          gap=float(r.gap), ev=float(lean.ev), p=float(lean.model_prob), cat=cat, note=note,
                          books=sorted(books, key=lambda x: x['b'])))
    yt = pd.Timestamp(os.path.basename(yprops[-1])[6:].split('.')[0].replace('Z', ''))
    D['yards'] = yards
    D['yardsTaken'] = yt.tz_localize('UTC').tz_convert('America/New_York').strftime('%A, %B %-d at %-I:%M %p ET')

# latest blind test (scripts/props_blind_test.py), shown on its own tab
bl = sorted(glob.glob(os.path.join(ROOT, 'odds_log', 'blind', '*_summary.csv')))
if bl:
    tag = os.path.basename(bl[-1]).replace('_summary.csv', '')
    bs, bw = tag.split('_'); bweek = int(bw[2:])
    Sm = pd.read_csv(bl[-1])
    tdb = pd.read_csv(bl[-1].replace('_summary', '_td')); tdb = tdb[tdb.played & (tdb.p_td >= 0.35)]
    ydb = pd.read_csv(bl[-1].replace('_summary', '_yards')); ydb = ydb[ydb.p_lean >= 0.57]
    D['blind'] = dict(season=int(bs), week=bweek, summary=Sm.to_dict('records'),
                      td=[dict(name=r.full_name, team=r.posteam, pos=r.position, p=round(r.p_td, 3), right=bool(r.scored)) for r in tdb.itertuples()],
                      yards=[dict(market=r.market, name=r.full_name, team=r.posteam, pos=r.position, line=r.line, proj=round(r.projection, 1),
                                  lean=r.lean, p=round(r.p_lean, 3), actual=r.actual, right=bool(r.right)) for r in ydb.sort_values('p_lean', ascending=False).itertuples()])

B = os.path.join(ROOT, 'board')
data = json.dumps(D, separators=(',', ':')).replace('</', '<\\/')
html = (open(os.path.join(B, 'head.html')).read() + open(os.path.join(B, 'body.html')).read().replace('2026 · Week 10', f'{season} · Week {week}')
        + f'<script type="application/json" id="td-data">{data}</script>\n<script>\n' + open(os.path.join(B, 'app.js')).read() + '</script>\n')
open(os.path.join(B, 'touchdown-board.html'), 'w').write(html)
print('wrote board/touchdown-board.html', len(out), 'TD players,', len(yards), 'yards props')
