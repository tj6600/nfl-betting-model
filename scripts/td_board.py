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
B = os.path.join(ROOT, 'board')
data = json.dumps(D, separators=(',', ':')).replace('</', '<\\/')
html = (open(os.path.join(B, 'head.html')).read() + open(os.path.join(B, 'body.html')).read().replace('2026 · Week 10', f'{season} · Week {week}')
        + f'<script type="application/json" id="td-data">{data}</script>\n<script>\n' + open(os.path.join(B, 'app.js')).read() + '</script>\n')
open(os.path.join(B, 'touchdown-board.html'), 'w').write(html)
print('wrote board/touchdown-board.html', len(out), 'players')
