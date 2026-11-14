"""Build the Touchdown Board page (board/touchdown-board.html) from this week's TD picks and props odds.

Run after scripts/td_picks.py. Publish the output as the Touchdown Board artifact.
"""
import sys, os, glob, json, re; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
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
    no_role = r.h_carries + r.h_targets < 0.05
    if no_role:
        why = (f"No carries or targets yet this season{f' (depth chart {r.position}{int(r.dc_rank)})' if r.dc_rank == r.dc_rank else ''}, "
               f"so this is the model's baseline for a player without a role; team expected to score {r.imp_pts:.1f}.")
    out.append(dict(id=r.pid, name=r.full_name, team=r.posteam, opp=r.defteam, home=home, away=away, game=r.game,
                    day=str(g.gameday.date()), time=str(g.gametime), weekday=str(g.weekday), pos=r.position,
                    model=round(r.model_prob * 100, 1), book=num(r.book_prob, lambda v: round(v * 100, 1)),
                    best=num(r.best_price, int), bestBook=r.best_book if isinstance(r.best_book, str) else None,
                    median=num(r.median_price, round), ev=num(r.ev, lambda v: round(v * 100, 1)),
                    cat=r.category if isinstance(r.category, str) else '',
                    carries=round(r.h_carries, 1), targets=round(r.h_targets, 1), gl=round(r.h_gl_share * 100), rz=round(r.h_rz_share * 100),
                    tdpg=round(r.h_tds, 2), room=round(r.room_share * 100), last=round(r.last_share * 100), missed=0 if no_role else int(r.missed_n),
                    imp=round(r.imp_pts, 1), deftd=round(r.def_td, 2), why=why,
                    depth=num(r.dc_rank, int), depthPrev=num(r.dc_prev, int),
                    books=[dict(b=b.book, p=int(b.price)) for b in bks.itertuples()]))
taken = pd.Timestamp(os.path.basename(props)[11:26].replace('T', ' ')[:-1] if False else os.path.basename(props)[11:].split('.')[0].replace('Z', ''))
from nflmodel import weather as W
try:
    WXB = W.prop_weather(GW)
    weather = {f'{r.away_team} @ {r.home_team}': dict(desc=r.desc, note=r.note) for r in GW.merge(WXB[['game_id', 'desc', 'note']], on='game_id').itertuples()}
except Exception as e:
    print('weather unavailable:', e); weather = {}
D = dict(weather=weather, season=season, week=week, taken=taken.tz_localize('UTC').tz_convert('America/New_York').strftime('%A, %B %-d at %-I:%M %p ET'), players=out)
# rushing / receiving / passing yards
MK = {'Rushing yards': 'rush', 'Receiving yards': 'rec', 'Passing yards': 'pass', 'Receptions': 'recs'}
YKEYS = {'player_rush_yds': 'rush', 'player_reception_yds': 'rec', 'player_pass_yds': 'pass', 'player_receptions': 'recs'}
yf = os.path.join(ROOT, 'odds_log', 'picks', f'{season}_wk{week:02d}_yards.csv')
yprops = sorted(glob.glob(os.path.join(ROOT, 'odds_log', 'props', 'yards_*.json')))
yards = []
if os.path.exists(yf) and yprops:
    Yd = pd.read_csv(yf)
    yrows = []
    rprops = sorted(glob.glob(os.path.join(ROOT, 'odds_log', 'props', 'recs_*.json')))
    for e in json.load(open(yprops[-1])) + (json.load(open(rprops[-1])) if rprops else []):
        for bk in e.get('bookmakers', []):
            for m in bk['markets']:
                for o in m['outcomes']:
                    if o.get('description') and o.get('point') is not None:
                        yrows.append((TEAMS.get(e['home_team']), TEAMS.get(e['away_team']), YKEYS.get(m['key'], 'rec'),
                                      o['description'], bk['title'], o['name'], o['point'], o['price']))
    YO = pd.DataFrame(yrows, columns=['home', 'away', 'kind', 'player', 'book', 'side', 'pt', 'pr']); YO['k'] = T._key(YO.player)
    gl = {r.game: r for r in GW.assign(game=GW.away_team + ' @ ' + GW.home_team).itertuples()}
    for (pid, market), grp in Yd.groupby(['pid', 'market']):
        kind = MK[market]
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

# alternate-line milestones (scripts/yards_picks.py), one entry per player and market
mf = os.path.join(ROOT, 'odds_log', 'picks', f'{season}_wk{week:02d}_milestones.csv')
aprops = sorted(glob.glob(os.path.join(ROOT, 'odds_log', 'props', 'altyards_*.json')))
if os.path.exists(mf):
    M = pd.read_csv(mf); ms = []
    gl = {r.game: r for r in GW.assign(game=GW.away_team + ' @ ' + GW.home_team).itertuples()}
    for (pid, market), grp in M.groupby(['pid', 'market'], sort=False):
        r = grp.iloc[0]; kind = MK[market]; g = gl.get(r.game)
        if g is None: continue
        steps = [dict(m=int(x.milestone), p=round(float(x.prob), 4), model=round(float(x.model_only), 4), book=round(float(x.book_prob), 4),
                      price=int(x.best_price), bk=x.best_book, n=int(x.books), ev=round(float(x.ev), 4),
                      cat=x.category if isinstance(x.category, str) else '') for x in grp.sort_values('milestone').itertuples()]
        cats = set(s['cat'] for s in steps)
        cat = 'Value' if 'Value' in cats else 'Likely hit' if 'Likely hit' in cats else ''
        ms.append(dict(id=f'{pid}-{kind}-m', pid=pid, name=r.player, team=r.team, opp=r.opp, game=r.game, day=str(g.gameday.date()), time=str(g.gametime),
                       weekday=str(g.weekday), pos=r.position, market=kind, projection=float(r.projection), median=float(r['median']),
                       line=None if r.main_line != r.main_line else float(r.main_line), regular=bool(r.regular), risky=bool(r.risky),
                       cat=cat, steps=steps))
    D['milestones'] = ms
    if aprops:
        at = pd.Timestamp(os.path.basename(aprops[-1])[9:].split('.')[0].replace('Z', ''))
        D['altTaken'] = at.tz_localize('UTC').tz_convert('America/New_York').strftime('%A, %B %-d at %-I:%M %p ET')

# every priced leg for the parlay builder, at the book Thomas uses (DraftKings only since 2026-11-11).
# A leg is a market + side + number; it lists its price at each book that offers that exact number.
from nflmodel.stats import norm
BOOKS = {'draftkings': 'DraftKings', 'fanduel': 'FanDuel', 'DraftKings': 'DraftKings', 'FanDuel': 'FanDuel'}
def _dec(a): return 1 + a / 100 if a > 0 else 1 + 100 / -a
def _imp(a): return -a / (-a + 100.0) if a < 0 else 100.0 / (a + 100.0)
def _cat(x): return x if isinstance(x, str) else ''
def _inv(q):   # standard normal quantile by bisection
    lo, hi = -8.0, 8.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if norm.cdf(mid) < q: lo = mid
        else: hi = mid
    return (lo + hi) / 2
LEGS = {}
PARLAY_BOOKS = ['DraftKings']
# DraftKings outcome ids ("sid", pulled with includeSids, no extra credits) so a slip can open in the DraftKings betslip
# with its legs loaded: https://sportsbook.draftkings.com/?outcomes=<sid>+<sid> (same link as the NBA and NHL pages)
SID = {}
_PK = {'player_rush_yds': 'rush', 'player_reception_yds': 'rec', 'player_pass_yds': 'pass', 'player_receptions': 'recs'}
_AK = {'player_rush_yds_alternate': 'rush', 'player_reception_yds_alternate': 'rec', 'player_receptions_alternate': 'recs', 'player_pass_yds_alternate': 'pass'}
_pt = lambda v: None if v is None or v != v else round(float(v), 1)
for pre in ['anytime_td', 'yards', 'recs', 'altyards', 'altrecs', 'altpass']:
    fs = sorted(glob.glob(os.path.join(ROOT, 'odds_log', 'props', f'{pre}_*.json')))
    if not fs: continue
    for e in json.load(open(fs[-1])):
        h, a = TEAMS.get(e['home_team']), TEAMS.get(e['away_team'])
        for bk in e.get('bookmakers', []):
            if bk.get('key') != 'draftkings': continue
            for m in bk['markets']:
                for o in m['outcomes']:
                    if not o.get('sid') or not o.get('description'): continue
                    k = T._key(pd.Series([o['description']])).iloc[0]
                    if m['key'] == 'player_anytime_td' and o.get('name', 'Yes') == 'Yes': SID[('td', h, a, k)] = o['sid']
                    elif m['key'] in _PK: SID[('y', h, a, _PK[m['key']], k, o['name'], _pt(o.get('point')))] = o['sid']
                    elif m['key'] in _AK and o.get('name') == 'Over': SID[('m', h, a, _AK[m['key']], k, _pt(o.get('point')))] = o['sid']


def add_leg(lid, book, price, sk=None, **kw):
    if book not in PARLAY_BOOKS: return
    l = LEGS.setdefault(lid, dict(id=lid, offers={}, bps=[], **kw))
    if book in l['offers']: return
    l['offers'][book] = int(price)
    if book == 'DraftKings' and sk is not None and SID.get(sk): l['sid'] = SID[sk]
    if kw.get('bp') == kw.get('bp') and kw.get('bp') is not None: l['bps'].append(kw['bp'])

# game lines: rebuild the model's margin and total from the picks file, then price every DraftKings/FanDuel number
gp = pd.read_csv(os.path.join(ROOT, 'odds_log', 'picks', f'{season}_wk{week:02d}.csv'))
snapf = sorted(glob.glob(os.path.join(ROOT, 'odds_log', 'snapshots', '*.csv')))[-1]
SN = pd.read_csv(snapf); SN = SN[SN.book.isin(['draftkings', 'fanduel'])]
if 'sid' in SN:
    for x in SN[(SN.book == 'draftkings') & SN.sid.notna()].itertuples():
        SID[('g', x.home_team, x.away_team, x.market, x.side, None if x.market == 'moneyline' else _pt(x.point))] = x.sid
sdm, sdt, GM = [], [], {}
for game, gg in gp.groupby('game'):
    away, home = game.split(' @ ')
    hs = gg[(gg.market == 'spread') & (gg.side == home)]; ov = gg[(gg.market == 'total') & (gg.side == 'Over')]
    info = dict(game_id=gg.game_id.iloc[0])
    if len(hs):
        h = hs.iloc[0]; pred = -h.model_line; S = -h.open_line; info['pm'] = pred
        if abs(S - pred) > 1: sdm.append((S - pred) / _inv(1 - h.model_prob))
    if len(ov):
        o = ov.iloc[0]; info['pt'] = o.model_line
        if abs(o.open_line - o.model_line) > 1: sdt.append((o.open_line - o.model_line) / _inv(1 - o.model_prob))
    GM[game] = info
SDM, SDT = float(np.median(sdm)), float(np.median(sdt))
print(f'game model spread sd {SDM:.1f}, total sd {SDT:.1f}')
for (home, away, book, market), bg in SN.groupby(['home_team', 'away_team', 'book', 'market']):
    game = f'{away} @ {home}'
    if game not in GM: continue
    gi = GM[game]; bk = BOOKS[book]
    for x in bg.itertuples():
        other = bg[(bg.side != x.side)]
        if market == 'moneyline':
            row = gp[(gp.game == game) & (gp.market == 'moneyline') & (gp.side == x.side)]
            if row.empty: continue
            model = float(row.model_prob.iloc[0]); lab = f'{x.side} moneyline'; lid = f'g-{gi["game_id"]}-ml-{x.side}'
            grp, gt, sl = f'g-{gi["game_id"]}-ml', f'{game} moneyline', x.side
        elif market == 'spread':
            if 'pm' not in gi or x.point != x.point: continue
            model = 1 - norm.cdf(-x.point, gi['pm'], SDM) if x.side == home else norm.cdf(x.point, gi['pm'], SDM)
            other = other[other.point == -x.point]; lab = f'{x.side} {x.point:+g}'; lid = f'g-{gi["game_id"]}-sp-{x.side}-{x.point:g}'
            hp = x.point if x.side == home else -x.point
            grp, gt, sl = f'g-{gi["game_id"]}-sp-{hp:g}', f'{game} spread {abs(x.point):g}', f'{x.side} {x.point:+g}'
        else:
            if 'pt' not in gi or x.point != x.point: continue
            po = 1 - norm.cdf(x.point, gi['pt'], SDT); model = po if x.side == 'Over' else 1 - po
            other = other[other.point == x.point]; lab = f'{x.side} {x.point:g}'; lid = f'g-{gi["game_id"]}-tot-{x.side}-{x.point:g}'
            grp, gt, sl = f'g-{gi["game_id"]}-tot-{x.point:g}', f'{game} total {x.point:g}', x.side
        bp = _imp(x.price) / (_imp(x.price) + _imp(other.price.iloc[0])) if len(other) else np.nan
        cat = gp[(gp.game == game) & (gp.market == market) & (gp.side == x.side)].category
        add_leg(lid, bk, x.price, sk=('g', home, away, market, x.side, None if market == 'moneyline' else _pt(x.point)), game=game, kind='Game', who=game, label=lab, grp=grp, gt=gt, sl=sl, model=float(model), bp=bp,
                cat=_cat(cat.iloc[0]) if len(cat) else '', key=f'{game}-{market}', flag='')
# touchdowns: one number, so only the price differs by book
for r in A.itertuples():
    away, home = r.game.split(' @ ')
    k = T._key(pd.Series([r.full_name])).iloc[0]
    bks = O[(O.home == home) & (O.away == away) & (O.k == k) & O.book.isin(['DraftKings', 'FanDuel'])]
    flag = 'Check role' if r.category == 'Check role' else ('small role' if r.h_carries + r.h_targets < 3 else '')
    for b in bks.itertuples():
        add_leg(f't-{r.pid}', b.book, b.price, sk=('td', home, away, k), game=r.game, kind='TD', who=r.full_name, pid=r.pid, label='anytime TD', grp=f't-{r.pid}', gt=f'{r.full_name} anytime TD', sl='Yes', team=r.posteam, model=float(r.model_prob),
                bp=float(r.book_prob) if r.book_prob == r.book_prob else np.nan, cat=_cat(r.category), key=f'td-{r.pid}', flag=flag)
# yards over/unders: each book's own number, with the model's chance at that number (scripts/yards_picks.py)
yb = yf.replace('_yards.csv', '_yards_books.csv')
if os.path.exists(yb):
    Yd = pd.read_csv(yf)
    for r in pd.read_csv(yb).itertuples():
        base = Yd[(Yd.pid == r.pid) & (Yd.market.map(MK) == r.kind) & (Yd.side == r.side)]
        if base.empty: continue
        m = base.iloc[0]; kind = r.kind.title()   # Rush, Rec, Pass, Recs (receptions)
        unit = 'receptions' if r.kind == 'recs' else f'{kind.lower()} yds'
        flag = 'Check role' if m.category == 'Check role' else ('' if m.regular else 'small role')
        ya, yh = m.game.split(' @ ')
        add_leg(f'y-{r.pid}-{kind}-{r.side}-{r.point:g}', r.book, r.price, sk=('y', yh, ya, r.kind, T._key(pd.Series([m.player])).iloc[0], r.side, _pt(r.point)), game=m.game, kind=kind, who=m.player, team=m.team,
                label=f'{r.side} {r.point:g} {unit}', model=float(r.model_only),
                pid=r.pid, grp=f'y-{r.pid}-{kind}-{r.point:g}', gt=f'{m.player} {r.point:g} {unit}', sl=r.side,
                bp=float(r.book_p) if r.book_p == r.book_p else float(m.market_prob), cat=_cat(m.category) if m.best_line == r.point else '',
                key=f'{r.pid}-{kind}', flag=flag)
# milestones: one number, only the price differs by book
mb = mf.replace('_milestones.csv', '_milestones_books.csv')
if os.path.exists(mb):
    Ms = pd.read_csv(mf); Ms['kind'] = Ms.market.map(MK)
    Ms = Ms.set_index(['pid', 'kind', 'milestone'])
    for r in pd.read_csv(mb).itertuples():
        if (r.pid, r.kind, r.milestone) not in Ms.index: continue
        m = Ms.loc[(r.pid, r.kind, r.milestone)]
        if not 0.05 <= m.prob <= 0.97: continue
        kind = r.kind.title()   # Rush, Rec, Recs: the same key as the player's main line, so a slip holds one or the other
        unit = 'receptions' if r.kind == 'recs' else f'{kind.lower()} yds'
        flag = 'Check role' if m.risky else ('' if m.regular else 'small role')
        ma, mh = m.game.split(' @ ')
        add_leg(f'm-{r.pid}-{kind}-{r.milestone}', r.book, r.price, sk=('m', mh, ma, r.kind, T._key(pd.Series([m.player])).iloc[0], _pt(r.milestone - 0.5)), game=m.game, kind='Milestone', who=m.player, team=m.team,
                label=f'{r.milestone}+ {unit}', model=float(m.model_only), alt=True, main=float(m.main_line) if m.main_line == m.main_line else None,
                pid=r.pid, grp=f'm-{r.pid}-{kind}', gt=f'{m.player} alt {unit}', sl=f'{r.milestone}+', bp=float(m.book_prob), cat=_cat(m.category),
                key=f'{r.pid}-{kind}', flag=flag)
# chance = model blended with the books' no-vig chance: 50/50 normally, leaning on the books for long shots
# (model weight 0.5 at a 25%+ book chance, sliding to 0.2 below about 12%), since the model is least reliable in the tails.
# Each leg's headline price is the better of DraftKings and FanDuel, DraftKings on a tie.
legs = []
for l in LEGS.values():
    bps = l.pop('bps'); l.pop('bp', None)
    bk = float(np.mean(bps)) if bps else l['model']
    bk = min(0.99, max(0.005, bk))
    w = 0.5 * min(1.0, max(0.4, (bk - 0.03) / 0.22))
    pp = w * l['model'] + (1 - w) * bk
    book = max(l['offers'], key=lambda b: (_dec(l['offers'][b]), b == 'DraftKings'))
    d = _dec(l['offers'][book])
    l.update(model=round(l['model'], 4), book_p=round(bk, 4), p=round(pp, 4), price=l['offers'][book], book=book,
             ev=round(pp * d - 1, 4), edge=round(pp - 1 / d, 4))
    legs.append(l)
D['legs'] = legs
print(sum(1 for l in legs if l.get('sid')), 'of', len(legs), 'legs have a DraftKings betslip id')
# season game logs for every player on the board (play-by-play derived; weeks his team played without him show as DNP)
H = T.history(); H = H[H.season == season]
pids = {l['pid'] for l in legs if l.get('pid')} | {p['id'] for p in out} | {y['pid'] for y in D.get('yards', [])}
GS = G[(G.season == season) & (G.game_type == 'REG') & G.result.notna()]
logs = {}
for pid, hg in H[H.pid.isin(pids)].groupby('pid'):
    hg = hg.sort_values('week'); team = hg.posteam.iloc[-1]; byw = {r.week: r for r in hg.itertuples()}
    teamg = GS[(GS.home_team == team) | (GS.away_team == team)]
    weeks = sorted(set(teamg.week) | set(byw))
    rows = []
    for w in weeks:
        r = byw.get(w)
        if r is not None:
            home, away = r.game_id.split('_')[3], r.game_id.split('_')[2]
            opp = away if r.posteam == home else home; at = r.posteam != home
            rows.append([int(w), opp, at, int(r.carries), round(r.rush_yds), int(r.targets), int(r.receptions), round(r.rec_yds), int(r.tds)])
        else:
            g = teamg[teamg.week == w].iloc[0]; at = g.away_team == team
            rows.append([int(w), g.home_team if at else g.away_team, bool(at), None, None, None, None, None, None])
    logs[pid] = dict(name=hg.full_name.iloc[-1], pos=hg.position.iloc[-1], team=team, g=rows)
# team changes: compare what the old and new offenses give his position (volume per game, recency-weighted),
# and his own production before and after. Display only: as a model input it did not improve 2024-25 backtests.
HA = T.history().sort_values(['pid', 'gameday'])
CTX = T.team_context(HA).set_index(['game_id', 'posteam', 'position'])
CNOW = T.team_context_now(HA)
MAIN = {'WR': ['targets', 'rec_yds'], 'TE': ['targets', 'rec_yds'], 'RB': ['carries', 'targets', 'rush_yds', 'rec_yds'], 'QB': ['carries', 'rush_yds']}
for pid, L in logs.items():
    x = HA[HA.pid == pid].tail(25); team = L['team']
    if (x.posteam == team).all() or x.posteam.iloc[-1] != team: continue
    old = x[x.posteam != team]; old_team = old.posteam.iloc[-1]; old = old[old.posteam == old_team].tail(17)
    new = x[(x.posteam == team) & (x.gameday > old.gameday.max())]
    if new.empty: continue
    pos = x.position.iloc[-1]; first = new.iloc[0]
    if pos == 'QB': continue
    try:
        co = CTX.loc[(old.game_id.iloc[-1], old_team, pos)]; cn = CNOW.loc[(team, pos)]
    except KeyError:
        continue
    stats_ = MAIN.get(pos, ['targets'])
    ctx = {c: [round(float(co[f'at_{c}']), 1), round(float(cn[f'at_{c}']), 1)] for c in ['targets', 'carries', 'rec_yds', 'rush_yds']}
    his = {c: [round(float(old[c].mean()), 1), round(float(new[c].mean()), 1)] for c in ['targets', 'carries', 'rec_yds', 'rush_yds']}
    k = stats_[0] if pos != 'RB' else None
    vo = sum(ctx[c][0] for c in (['carries', 'targets'] if pos == 'RB' else [stats_[0]])); vn = sum(ctx[c][1] for c in (['carries', 'targets'] if pos == 'RB' else [stats_[0]]))
    chg = (vn - vo) / vo if vo else 0.0
    L['move'] = dict(frm=old_team, to=team, season=int(first.season), week=int(first.week), pos=pos, ctx=ctx, his=his,
                     n_old=len(old), n_new=len(new), chg=round(chg, 3),
                     verdict='benefits' if chg >= 0.10 else 'falls' if chg <= -0.10 else 'similar')
D['logs'] = logs
print(sum('move' in v for v in logs.values()), 'players on new teams')
print(len(logs), 'game logs')

# season check: flag a likely-looking yards side that has lost most of the time this season (4+ games played).
# The recency weights reach back into earlier seasons and old teams, so a player in a new role can be
# projected off his old usage (e.g. a backup turned starter); his own season is the warning sign.
for l in legs:
    if l['kind'] not in ('Rush', 'Rec', 'Recs', 'Milestone') or l.get('pid') not in logs or 'pass' in l['label']: continue
    rows = [r for r in logs[l['pid']]['g'] if r[3] is not None]
    num = float(re.search(r'[\d.]+', l['label']).group())
    line = num - 0.5 if l['kind'] == 'Milestone' else num
    i = 4 if 'rush' in l['label'] else 6 if 'receptions' in l['label'] else 7
    over = l['kind'] == 'Milestone' or l['sl'] == 'Over'
    hits = sum((r[i] > line) if over else (r[i] < line) for r in rows)
    l['season'] = f'{hits}/{len(rows)}'
    if len(rows) >= 4 and l['p'] >= 0.55 and hits / len(rows) < 0.4 and not l['flag']:
        l['flag'] = 'season disagrees'

# suggested parlay: at each book, the best-edge qualifying leg from each of the four strongest games; keep the book with the higher EV
LG = pd.DataFrame(legs)
ALL = LG.copy()
LG = LG[(LG.cat.isin(['Value', 'Optimal', 'Secure', 'TD value', 'Likely hit'])) & (LG.flag == '') & (LG.p >= 0.55)]
# an Over on a yards/receptions line under 60% ("not secure") is swapped for the same player's likeliest alternate line
# that is 60%+ and fairly priced (edge 0+) at DraftKings; alt lines are overs only, so Unders stay (same rule as board/app.js)
ALTS = ALL[(ALL.alt == True) & (ALL.flag == '') & (ALL.p >= 0.6) & (ALL.edge >= 0) & ALL.offers.map(lambda o: 'DraftKings' in o)] if 'alt' in ALL else ALL.iloc[:0]
def _safer(r):
    if r.get('alt') == True or r.kind not in ('Rush', 'Rec', 'Recs', 'Pass') or r.sl != 'Over' or r.p >= 0.6: return r
    c = ALTS[(ALTS.key == r.key) & (ALTS.p > r.p)].sort_values('p', ascending=False)
    if c.empty: return r
    a = c.iloc[0].copy(); a['swapped'] = True; print(f'  safer alt: {r.who} {r.label} ({r.p:.0%}) -> {a.label} ({a.p:.0%})'); return a
if len(LG):
    LG = pd.DataFrame([_safer(r) for _, r in LG.iterrows()]).drop_duplicates('id')
    LG['swapped'] = LG.get('swapped', False).fillna(False).astype(bool) if 'swapped' in LG else False
sug = []
for b in PARLAY_BOOKS:
    X = LG[LG.offers.map(lambda o: b in o)].copy()
    X['d'] = X.offers.map(lambda o: _dec(o[b])); X['evb'] = X.p * X.d - 1; X['edgeb'] = X.p - 1 / X.d
    X = X[(X.evb > 0.03) | X.swapped].sort_values('edgeb', ascending=False).groupby('game').head(1).head(4)
    sug.append((X.p.prod() * X.d.prod() - 1, b == 'DraftKings', b, list(X.id), X.p.prod(), X.d.prod()))
    print(f'suggested at {b}: EV {sug[-1][0]:+.1%}, hit {sug[-1][4]:.1%}, decimal {sug[-1][5]:.2f}:', list(X.label + ' ' + X.who.where(X.kind != 'Game', '')))
best = max(sug)
D['suggested'] = dict(book=best[2], ids=best[3])

# save this week's picks and suggested parlays (same rules as the Parlay builder), then grade every finished week for the
# Model record tab (nflmodel/record.py: free nflverse scores and stats, DraftKings prices)
import parlays as PZ
from nflmodel import record as REC
_gone = REC.started(season, week)   # only games not yet kicked off count as picks (no hindsight in the record)
_pre = [l for l in legs if l['game'] not in _gone]
REC.log_legs(season, week, _pre)
PZ.log(os.path.join(ROOT, 'odds_log'), f'{season}_wk{week:02d}', taken.strftime('%Y-%m-%dT%H%MZ'), _pre, nfl=True)
D['record'] = REC.record()
print('model record:', len(D['record']['picks']), 'pick groups,', len(D['record']['parlays']['groups']), 'parlay groups; graded weeks', D['record']['graded'])

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
# sport switch shown on the hosted site (each sport is its own page: index.html = NFL, nba.html = NBA)
SPORT_CSS = """<style>
.sportnav { display: flex; gap: 6px; max-width: 1080px; margin: 0 auto; padding: 14px max(16px, env(safe-area-inset-left, 0px)) 0; }
.sportnav a { font: 700 15px var(--display, sans-serif); letter-spacing: .08em; text-transform: uppercase; text-decoration: none; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: 6px 16px; background: var(--panel); }
.sportnav a[aria-current="page"] { background: var(--ink); color: var(--bg); border-color: var(--ink); }
</style>"""
def sport_nav(cur):
    return ('<nav class="sportnav" aria-label="Sport">' + ''.join(
        f'<a href="{href}"{" aria-current=\"page\"" if k == cur else ""}>{k.upper()}</a>' for k, href in [('nfl', 'index.html'), ('nba', 'nba.html'), ('nhl', 'nhl.html')]) + '</nav>\n')
# standalone copy for a static host (render.yaml publishes board/site): a full document, kept out of search engines
head = open(os.path.join(B, 'head.html')).read()
body = html[len(head):]
head = head.replace('<title>Player Props Board</title>', '<title>NFL Props Board</title>')
os.makedirs(os.path.join(B, 'site'), exist_ok=True)
open(os.path.join(B, 'site', 'index.html'), 'w').write(
    '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    '<meta name="robots" content="noindex, nofollow">\n' + head + SPORT_CSS + '\n</head>\n<body>\n' + sport_nav('nfl') + body + '</body>\n</html>\n')
print('wrote board/touchdown-board.html', len(out), 'TD players,', len(yards), 'yards props,', len(D.get('milestones', [])), 'milestone ladders,', len(legs), 'parlay legs')

# NBA page placeholder until the NBA pipeline writes board/site/nba.html (never overwrites a real NBA page)
nba = os.path.join(B, 'site', 'nba.html')
if not os.path.exists(nba) or 'nba-placeholder' in open(nba).read():
    open(nba, 'w').write(
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n' + head.replace('<title>NFL Props Board</title>', '<title>NBA Props Board</title>') + SPORT_CSS
        + '\n</head>\n<body>\n' + sport_nav('nba')
        + '<div class="wrap nba-placeholder"><header><span class="eyebrow">NBA</span><h1>NBA Props Board</h1>'
        + '<p class="lede">The NBA model is being built: game picks, player points, rebounds and assists, and the same parlay builder as the NFL board, priced at DraftKings. This page fills in once it is ready.</p></header></div>\n</body>\n</html>\n')
