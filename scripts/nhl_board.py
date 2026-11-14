"""Build the NHL board (board/site/nhl.html): game picks, shots on goal, goalie saves, parlay builder.

  python scripts/nhl_board.py [--update] [--date YYYY-MM-DD] [--no-log]

--update refreshes the current season from the GitHub mirror first (python -m nhlmodel.data).
Game lines and probable goalies come from ESPN's scoreboard (DraftKings prices, free). Shots-on-goal and saves lines
come from the latest odds_log/nhl/props_<day>_*.json (python -m nhlmodel.odds props: about 2 Odds API credits per game).
Without that file the props tabs show projections only.
"""
import sys, os, json, glob, argparse, datetime as dt
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
from nhlmodel import data as D, espn as E, odds as O, live as LV
from nhlmodel.features import skater_features, goalie_features
from nhlmodel.props import SogModel, SavesModel, norm_name
from nhlmodel.games import GameModel
from nhlmodel.stats import p_over, nb_cdf

ROOT = os.path.join(os.path.dirname(__file__), '..')
ET = 'America/New_York'
BOOK = 'DraftKings'
# weights on the model vs DraftKings no-vig, from the 2025-26 and 2026-27 backtests (output/nhl_*_backtest*.json)
W = {'Moneyline': 0.5,   # blend had the best log loss; model alone ~ DK
     'Puck line': 0.25,  # DK clearly better than the model
     'Total': 0.25,      # DK better than the model at the close
     'Shots on goal': 0.5,  # blend beat DK in both seasons
     'Saves': 0.5}       # blend slightly better than DK, small sample

ap = argparse.ArgumentParser(); ap.add_argument('--update', action='store_true'); ap.add_argument('--date')
ap.add_argument('--no-log', action='store_true', help='rebuild the page only; save no pick or parlay log (the 9 AM grading run)')
args = ap.parse_args()
if args.update:
    D.fetch(D.CURRENT); D.build()
day = dt.date.fromisoformat(args.date) if args.date else pd.Timestamp.now(tz=ET).date()

games, sk, go, tg = D.load()
slate = E.scoreboard(day)
# a past --date rebuilds that slate (for testing grading); today keeps only games not yet started
if len(slate) and day >= pd.Timestamp.now(tz=ET).date():
    slate = slate[slate.status == 'STATUS_SCHEDULED'].reset_index(drop=True)
elif len(slate):   # past slate: the scoreboard drops odds after the game, so use the saved closing lines
    ef = os.path.join(ROOT, 'odds_log', 'nhl', 'espn_lines.csv')
    if os.path.exists(ef):
        cl = pd.read_csv(ef, dtype={'espn_id': str})
        cols = ['ml_home', 'ml_away', 'pl_home_pt', 'pl_home', 'pl_away', 'total', 'over', 'under']
        slate = slate.drop(columns=[c for c in cols if c in slate]).merge(cl[['espn_id'] + cols], on='espn_id', how='left')
INJ = LV.injuries()
games2, sk2, go2, tg2, GID, NOTES = LV.augment(games, sk, go, tg, slate, day, INJ)
seasons = sorted(games.season.unique())

# ---------- models (fit on every finished game) ----------
skf, lm = skater_features(sk2, tg2)
sm = SogModel().fit(skf, lm, skf.season.isin(seasons) & skf.sog.notna())
skf['mu'] = sm.mu(skf)
st, lm2 = goalie_features(go2, tg2)
vm = SavesModel().fit(st, lm2, st.season.isin(seasons))
st['mu'] = vm.mu(st)
gm = GameModel().fit(games2, go2, tg2, seasons)
d = gm.d
d['lam'] = gm.lam(d)


def dec(a): return 1 + a / 100 if a > 0 else 1 + 100 / -a
def imp(a): return 1 / dec(a)


legs = []


def mk_leg(lid, game, kind, label, sub, price, p_model, p_book, flags=(), extra=None):
    w = W[kind]
    p = p_model if p_book is None else w * p_model + (1 - w) * p_book
    leg = dict(id=lid, game=game, kind=kind, label=label, sub=sub, price=int(price), p=round(float(p), 4),
               pm=round(float(p_model), 4), pb=None if p_book is None else round(float(p_book), 4),
               edge=round((p - imp(price)) * 100, 1), ev=round((p * dec(price) - 1) * 100, 1), flags=list(flags))
    if extra: leg.update(extra)
    legs.append(leg)
    return leg


def nv(a, b): return imp(a) / (imp(a) + imp(b))


# ---------- games ----------
G = []
for r in slate.itertuples():
    g = GID[r.espn_id]
    gm_ = f'{r.away} @ {r.home}'
    h = d[(d.game_id == g) & (d.is_home == 1)]; a = d[(d.game_id == g) & (d.is_home == 0)]
    if not len(h) or not len(a):
        continue
    lh, la = float(h.lam.iloc[0]), float(a.lam.iloc[0])
    pr = gm.probs(lh, la)
    tp = gm.total_pmf(lh, la)
    nh, na = NOTES.get((g, r.home), {}), NOTES.get((g, r.away), {})
    row = dict(id=g, game=gm_, home=r.home, away=r.away, tip=pd.Timestamp(r.start).tz_convert(ET).strftime('%-I:%M %p'),
               xg_home=round(lh, 2), xg_away=round(la, 2), total=round(sum(t * p for t, p in tp.items()), 2),
               p_home=round(pr['home_win'], 3), gk_home=nh.get('goalie'), gk_away=na.get('goalie'),
               gk_home_ok=nh.get('confirmed', False), gk_away_ok=na.get('confirmed', False),
               out_home=nh.get('outs', []), out_away=na.get('outs', []), legs=[])
    ex = lambda market, side, line: dict(gid=g, market=market, side=side, line=line)
    if r.ml_home == r.ml_home and r.ml_away == r.ml_away and r.ml_home and r.ml_away:
        b = nv(r.ml_home, r.ml_away)
        pm_blend = W['Moneyline'] * pr['home_win'] + (1 - W['Moneyline']) * b
        row['pick'] = r.home if pm_blend >= 0.5 else r.away
        row['pick_p'] = round(max(pm_blend, 1 - pm_blend), 3)
        for side, price, pm, pb in [(r.home, r.ml_home, pr['home_win'], b), (r.away, r.ml_away, 1 - pr['home_win'], 1 - b)]:
            row['legs'].append(mk_leg(f'{g}-ml-{side}', gm_, 'Moneyline', f'{side} to win', gm_, price, pm, pb, extra=ex('moneyline', side, None))['id'])
    if r.pl_home == r.pl_home and r.pl_away == r.pl_away and r.pl_home_pt in (1.5, -1.5):
        b = nv(r.pl_home, r.pl_away)
        ph = pr['home_-1.5'] if r.pl_home_pt < 0 else pr['home_+1.5']
        row['pl'] = float(r.pl_home_pt)
        for side, pt, price, pm, pb in [(r.home, r.pl_home_pt, r.pl_home, ph, b), (r.away, -r.pl_home_pt, r.pl_away, 1 - ph, 1 - b)]:
            row['legs'].append(mk_leg(f'{g}-pl-{side}', gm_, 'Puck line', f'{side} {pt:+g}', gm_, price, pm, pb, extra=ex('puckline', side, float(pt)))['id'])
    if r.total == r.total and r.over == r.over and r.under == r.under:
        b = nv(r.over, r.under)
        po = sum(p for t, p in tp.items() if t > r.total)
        row['line_total'] = float(r.total)
        for side, price, pm, pb in [('Over', r.over, po, b), ('Under', r.under, 1 - po, 1 - b)]:
            row['legs'].append(mk_leg(f'{g}-to-{side}', gm_, 'Total', f'{side} {r.total:g} goals', gm_, price, pm, pb, extra=ex('total', side, float(r.total)))['id'])
    G.append(row)
gl = {g['id']: g for g in G}

# ---------- props ----------
pfile = O.latest('props', day)
PRW = O.prop_rows(json.load(open(pfile))) if pfile else pd.DataFrame(columns=['player', 'stat', 'side', 'point', 'price', 'book'])
if len(PRW):
    PRW = PRW[PRW.book == 'draftkings'].copy(); PRW['k'] = PRW.player.map(norm_name)


def prop_line(name, stat):
    if not len(PRW): return None
    q = PRW[(PRW.k == norm_name(name)) & (PRW.stat == stat)]
    if not len(q): return None
    ln = q.point.mode().iloc[0]; q = q[q.point == ln]
    o, u = q[q.side == 'Over'], q[q.side == 'Under']
    return (float(ln), int(o.price.iloc[0]), int(u.price.iloc[0])) if len(o) and len(u) else None


def chances(mu, r, lines):
    return {f'{int(k)}+': round(float(1 - nb_cdf(k - 1, mu, r)[0]), 3) for k in lines}


hist_sk = skf[skf.sog.notna()]
players = []
up = skf[skf.game_id.isin(gl) & (skf.n_prior >= 5)]
for x in up.itertuples():
    g = gl[x.game_id]
    flags = []
    if isinstance(x.inj, str): flags.append(f'Injury report: {x.inj}')
    if x.days_off == x.days_off and x.days_off > 10: flags.append(f'Returning: last played {int(x.days_off)} days ago')
    lg = hist_sk[hist_sk.player_id == x.player_id].tail(12)
    log = [dict(d=r.game_date[5:], o=('vs ' if r.is_home else '@ ') + r.opp, toi=round(r.toi, 1), sog=int(r.sog), g=int(r.goals), a=int(r.assists),
                blk=int(r.blocked_shots)) for r in lg.iloc[::-1].itertuples()]
    cur = hist_sk[(hist_sk.player_id == x.player_id) & (hist_sk.season == LV.SEASON_CODE)]
    mu = float(x.mu)
    cdf = np.array([float(nb_cdf(k, mu, sm.r)[0]) for k in range(15)])
    lo, hi = int(np.searchsorted(cdf, 0.1)), int(np.searchsorted(cdf, 0.9))
    e = dict(proj=round(mu, 2), lo=lo, hi=hi, ch=chances(mu, sm.r, [2, 3, 4]))
    pl = prop_line(x.full_name, 'sog')
    if pl:
        ln, po, pu = pl
        pm = float(p_over(ln, mu, sm.r)[0]); b = nv(po, pu)
        e['line'] = ln
        for side, price, pmm, pb in [('Over', po, pm, b), ('Under', pu, 1 - pm, 1 - b)]:
            L = mk_leg(f'{x.player_id}-sog-{side}', g['game'], 'Shots on goal', f'{x.full_name} {side} {ln:g} shots', f'{x.team} vs {x.opp} · proj {mu:.1f}',
                       price, pmm, pb, flags, dict(pid=int(x.player_id), team=x.team, gid=int(x.game_id), market='sog', side=side, line=ln))
            e[side.lower()] = dict(id=L['id'], price=price, p=L['p'], edge=L['edge'], ev=L['ev'])
    players.append(dict(id=int(x.player_id), name=x.full_name, team=x.team, opp=x.opp, game=g['game'], pos='D' if x.position == 'D' else 'F',
                        toi=round(float(x.s_toi), 1), pp=round(float(x.l_pp_cf), 2), flags=flags, log=log, gp=int(len(cur)),
                        avg=round(float(cur.sog.mean()), 2) if len(cur) else None, sog=e))

goalies = []
hist_g = go2[go2.saves.notna() & (go2.starter == True)]
for x in st[st.game_id.isin(gl)].itertuples():
    g = gl[x.game_id]
    conf = NOTES.get((x.game_id, x.team), {}).get('confirmed', False)
    flags = [] if conf else ['Starter not confirmed: projected from recent starts']
    mu = float(x.mu)
    lg = hist_g[hist_g.player_id == x.player_id].tail(10)
    log = [dict(d=r.game_date[5:], o=('vs ' if r.is_home else '@ ') + r.opp, sa=int(r.shots_against), sv=int(r.saves),
                pct=round(r.saves / r.shots_against, 3) if r.shots_against else None) for r in lg.iloc[::-1].itertuples()]
    e = dict(proj=round(mu, 1), lo=round(mu - 1.28 * np.sqrt(mu + mu * mu / vm.r), 1), hi=round(mu + 1.28 * np.sqrt(mu + mu * mu / vm.r), 1),
             sv=round(float(x.sv_hat), 3))
    pl = prop_line(x.full_name, 'saves')
    if pl:
        ln, po, pu = pl
        pm = float(p_over(ln, mu, vm.r)[0]); b = nv(po, pu)
        e['line'] = ln
        for side, price, pmm, pb in [('Over', po, pm, b), ('Under', pu, 1 - pm, 1 - b)]:
            L = mk_leg(f'{x.player_id}-sv-{side}', g['game'], 'Saves', f'{x.full_name} {side} {ln:g} saves', f'{x.team} vs {x.opp} · proj {mu:.1f}',
                       price, pmm, pb, flags, dict(pid=int(x.player_id), team=x.team, gid=int(x.game_id), market='saves', side=side, line=ln))
            e[side.lower()] = dict(id=L['id'], price=price, p=L['p'], edge=L['edge'], ev=L['ev'])
    goalies.append(dict(id=int(x.player_id), name=x.full_name, team=x.team, opp=x.opp, game=g['game'], confirmed=conf, flags=flags, log=log, saves=e))

# ---------- DraftKings betslip ids (The Odds API includeSids) so a slip can open in DraftKings ----------
SID = {}
gfile = O.latest('games')
if gfile:
    gr = O.game_rows(json.load(open(gfile)))
    if 'sid' in gr:
        mk = {'h2h': 'moneyline', 'spreads': 'puckline', 'totals': 'total'}
        for r in gr[gr.sid.notna()].itertuples():
            pt = None if r.market == 'h2h' or r.point != r.point else float(r.point)
            SID[('g', f'{r.away} @ {r.home}', mk.get(r.market), r.side, pt)] = r.sid
if pfile:
    pr_ = O.prop_rows(json.load(open(pfile)))
    if 'sid' in pr_:
        for r in pr_[pr_.sid.notna()].itertuples():
            SID[('p', norm_name(r.player), r.stat, r.side, float(r.point))] = r.sid
NAME = {**{x['id']: x['name'] for x in players}, **{x['id']: x['name'] for x in goalies}}
for L in legs:
    if L.get('pid') is not None:
        L['sid'] = SID.get(('p', norm_name(NAME.get(L['pid'], '')), L['market'], L['side'], float(L['line'])))
    else:
        L['sid'] = SID.get(('g', L['game'], L['market'], L['side'], L.get('line')))

# ---------- picks and suggested pool (same rules as the NBA board) ----------
for L in legs:
    L['pick'] = bool(L.get('market') == 'moneyline' and gl[L['gid']].get('pick') == L['side'])
    L['cat'] = 'Value' if (L['edge'] >= 3 and L['p'] >= 0.55 and not L['flags']) else ''
ok = lambda l: not l['flags']
pool = sorted([l for l in legs if l['cat'] == 'Value'], key=lambda l: -l['edge'])
pool += sorted([l for l in legs if l['cat'] != 'Value' and ok(l) and l['edge'] >= 1.5 and l['p'] >= 0.52], key=lambda l: -l['edge'])

# pick log for grading (scripts/nhl_grade.py): every priced leg plus each game's winner pick
stamp = pd.Timestamp.now(tz='UTC').strftime('%Y-%m-%dT%H%MZ')
if legs and not args.no_log:
    os.makedirs(os.path.join(O.DIR, 'picks'), exist_ok=True)
    lf = os.path.join(O.DIR, 'picks', f'{day}_{stamp}.csv')
    pd.DataFrame([{k: l.get(k) for k in ['id', 'gid', 'game', 'kind', 'market', 'side', 'line', 'pid', 'team', 'label', 'price', 'p', 'pm', 'pb', 'edge', 'ev', 'cat']}
                  | {'flagged': bool(l['flags']), 'pick': l['pick']} for l in legs]).to_csv(lf, index=False)
    # suggested parlays as the page builds them (both modes, every leg count), graded by scripts/nhl_grade.py
    import parlays as PZ
    PZ.log(O.DIR, day, stamp, legs, [l['id'] for l in pool],
           lambda L: (L['edge'] >= 1 or L.get('pick')) and L['p'] >= 0.55 and L['price'] >= -200 and not L['flags'], no_sgp={'Saves'})

# ---------- backtest summary for the Model record tab ----------
bt = {}
for k, f in [('props', 'nhl_props_backtest.json'), ('props_now', 'nhl_props_backtest_2026-27.json'), ('games', 'nhl_game_backtest.json')]:
    fp = os.path.join(ROOT, 'output', f)
    if os.path.exists(fp): bt[k] = json.load(open(fp))
small = {}
if 'props' in bt:
    small['sog'] = {s: dict(lines=bt[k]['sog']['lines'], ll=bt[k]['sog']['logloss'], b3=bt[k]['sog']['betting']['blend_50']['ev>=0.03'],
                            b0=bt[k]['sog']['betting']['blend_50']['ev>=0.00']) for s, k in [('2025-26', 'props'), ('2026-27', 'props_now')] if k in bt}
    small['saves'] = dict(lines=bt['props']['saves']['lines'], ll=bt['props']['saves']['logloss'], b3=bt['props']['saves']['betting']['blend_50']['ev>=0.03'])
if 'games' in bt:
    gb = bt['games']
    small['ml'] = dict(n=gb['moneyline']['n'], ll=gb['moneyline']['logloss'], b0=gb['moneyline']['blend_50']['ev>=0.00'])
    small['pl'] = dict(n=gb['puck_line']['n'], ll=gb['puck_line']['logloss'], b0=gb['puck_line']['model']['ev>=0.00'])
    small['totals'] = {k: dict(n=v['n'], ll=v['logloss']) for k, v in gb.get('totals_close', {}).items()}
    small['winners'] = gb.get('winner_accuracy', {})
gr = os.path.join(O.DIR, 'grade_report.json')
LIVE = json.load(open(gr)) if os.path.exists(gr) else None

DATA = dict(day=str(day), dayLabel=pd.Timestamp(day).strftime('%A, %B %-d'), book=BOOK, through=games.game_date.max(),
            propsTaken=os.path.basename(pfile)[len(f'props_{day}_'):-5] if pfile else None, injuries=INJ is not None,
            games=G, players=players, goalies=goalies, legs=legs, pool=[l['id'] for l in pool], backtest=small, live=LIVE, weights=W)


def clean(o):
    if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(v) for v in o]
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, (float, np.floating)): return None if o != o else float(o)
    if isinstance(o, np.bool_): return bool(o)
    return o


B = os.path.join(ROOT, 'board')
head = open(os.path.join(B, 'head.html')).read().replace('<title>Player Props Board</title>', '<title>NHL Board</title>')
nav = '<nav class="sportnav" aria-label="Sport"><a href="index.html">NFL</a><a href="nba.html">NBA</a><a href="nhl.html" aria-current="page">NHL</a></nav>\n'
SPORT_CSS = """<style>
.sportnav { display: flex; gap: 6px; max-width: 1080px; margin: 0 auto; padding: 14px max(16px, env(safe-area-inset-left, 0px)) 0; }
.sportnav a { font: 700 15px var(--display, sans-serif); letter-spacing: .08em; text-transform: uppercase; text-decoration: none; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: 6px 16px; background: var(--panel); }
.sportnav a[aria-current="page"] { background: var(--ink); color: var(--bg); border-color: var(--ink); }
</style>"""
data = json.dumps(clean(DATA), separators=(',', ':')).replace('</', '<\\/')
html = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="robots" content="noindex, nofollow">\n' + head + SPORT_CSS + '\n<style>\n' + open(os.path.join(B, 'nhl.css')).read() + '</style>\n</head>\n<body>\n' + nav
        + open(os.path.join(B, 'nhl_body.html')).read()
        + f'<script type="application/json" id="nhl-data">{data}</script>\n<script>\n' + open(os.path.join(B, 'nhl_app.js')).read() + '</script>\n</body>\n</html>\n')
os.makedirs(os.path.join(B, 'site'), exist_ok=True)
open(os.path.join(B, 'site', 'nhl.html'), 'w').write(html)
print(f'NHL board for {day}: {len(G)} games, {len(players)} skaters, {len(goalies)} goalies, {len(legs)} priced legs -> board/site/nhl.html')
