"""NFL model record: grade the board's logged picks and suggested parlays at DraftKings prices.

Free data only: final scores from the nflverse games file (nflmodel.model.G), rushing/receiving/TD stats from the
play-by-play (touchdowns._player_games), passing yards from nflverse weekly stats (passing.load).
  * picks: odds_log/nfl_legs/<season>_wk<NN>.json, the board's categorized legs, saved the first time a week's board builds.
  * parlays: odds_log/parlays/<season>_wk<NN>_<stamp>.json (parlays.log(..., nfl=True)), graded by parlays.grade.
A leg is graded only once its game is final. A player who didn't play voids his yards/receptions bet, as books do;
an anytime TD for a player with no touches counts as a loss, as in scripts/td_grade.py.
"""
import os, re, glob, json
import pandas as pd
import parlays as PZ

ROOT = os.path.join(os.path.dirname(__file__), '..')
LOG = os.path.join(ROOT, 'odds_log')
RX_G = re.compile(r'^g-(\d{4}_\d{2}_[A-Z]+_[A-Z]+)-(ml|sp|tot)-([A-Za-z]+)(?:-(-?[\d.]+))?$')
RX_Y = re.compile(r'^y-(.+)-(Rush|Rec|Recs|Pass)-(Over|Under)-(-?[\d.]+)$')
RX_M = re.compile(r'^m-(.+)-(Rush|Rec|Recs|Pass)-(\d+)$')
STAT = {'Rush': 'rush_yds', 'Rec': 'rec_yds', 'Recs': 'receptions', 'Pass': 'passing_yards'}


def started(season, week, now=None):
    """'AWAY @ HOME' for this week's games that have kicked off (nflverse gameday + gametime are US Eastern).
    A board built after kickoff knows how the game went (snaps, injuries), so those legs are never logged as picks."""
    from nflmodel.model import G
    now = pd.Timestamp.now(tz='UTC') if now is None else pd.Timestamp(now)
    g = G[(G.season == season) & (G.week == week)]
    ko = pd.to_datetime(g.gameday.astype(str) + ' ' + g.gametime.fillna('00:00')).dt.tz_localize('America/New_York')
    return set((g.away_team + ' @ ' + g.home_team)[ko.dt.tz_convert('UTC') <= now])


def log_legs(season, week, legs):
    """Save this week's categorized legs once (the earliest board of the week is the record)."""
    d = os.path.join(LOG, 'nfl_legs'); os.makedirs(d, exist_ok=True)
    f = os.path.join(d, f'{season}_wk{week:02d}.json')
    if not os.path.exists(f):
        keep = [dict(id=l['id'], kind=l['kind'], label=PZ._name(l), game=l['game'], cat=l['cat'], p=l['p'],
                     price=int(l['offers']['DraftKings'])) for l in legs if l.get('cat') and 'DraftKings' in l['offers']]
        json.dump(keep, open(f, 'w'))
    return f


def _week(day):   # '2026_wk10', or '2026_wk10thu' for a log of one week's Thursday game alone
    s, w = day.split('_wk'); return int(s), int(w[:2])


def results(want):
    """want: {(season, week): {leg_id: 'AWAY @ HOME'}} -> {(day, leg_id): 'win'|'loss'|'push'|'void'} for final games."""
    if not want: return {}
    from nflmodel.model import G
    from nflmodel import touchdowns as T
    seasons = sorted({s for s, _ in want})
    pg = T._player_games(seasons)
    pbp_games = set(pg.game_id)
    st = pg.groupby(['season', 'week', 'pid'])[['tds', 'rush_yds', 'rec_yds', 'receptions']].sum()
    qb, qweeks = None, set()
    if any('-Pass-' in i for ids in want.values() for i in ids):
        from nflmodel import passing as PY
        q = PY.load(seasons); qweeks = set(zip(q.season, q.week))
        qb = q.groupby(['season', 'week', 'pid']).passing_yards.sum()
    g = G.set_index('game_id')
    out = {}
    for (s, w), ids in want.items():
        day = f'{s}_wk{w:02d}'
        for i, game in ids.items():
            r = None
            m = RX_G.match(i)
            if m:
                gid, mk, side, pt = m.groups()
                if gid not in g.index or g.loc[gid, 'result'] != g.loc[gid, 'result']: continue
                res, tot, home = float(g.loc[gid, 'result']), float(g.loc[gid, 'total']), g.loc[gid, 'home_team']
                if mk == 'tot': x = (tot - float(pt)) * (1 if side == 'Over' else -1)
                else: x = (res if side == home else -res) + (float(pt) if mk == 'sp' else 0)
                r = 'win' if x > 0 else 'push' if x == 0 else 'loss'
            else:
                away, home = game.split(' @ '); gid = f'{s}_{w:02d}_{away}_{home}'
                if gid not in pbp_games: continue
                if i.startswith('t-'):
                    k = (s, w, i[2:]); r = 'win' if k in st.index and st.loc[k, 'tds'] > 0 else 'loss'
                else:
                    m = RX_Y.match(i) or RX_M.match(i)
                    if not m: continue
                    pid, kind = m.group(1), m.group(2); k = (s, w, pid)
                    if kind == 'Pass':
                        if (s, w) not in qweeks: continue          # weekly stats not posted yet
                        a = qb.loc[k] if k in qb.index else None
                    else:
                        a = st.loc[k, STAT[kind]] if k in st.index else None
                    if a is None or a != a: r = 'void'
                    elif RX_M.match(i): r = 'win' if a >= int(m.group(3)) else 'loss'
                    else:
                        line = float(m.group(4)); x = (a - line) * (1 if m.group(3) == 'Over' else -1)
                        r = 'win' if x > 0 else 'push' if x == 0 else 'loss'
            out[(day, i)] = r
    return out


MKT = {'Game': 'Game lines', 'TD': 'Anytime TDs', 'Rush': 'Yards and receptions', 'Rec': 'Yards and receptions',
       'Recs': 'Yards and receptions', 'Pass': 'Yards and receptions'}


def moneylines():
    """Every game's moneyline pick, rebuilt from logged data only (no hindsight, no odds credits):
    the model's win chance from the week's picks file (odds_log/picks/<season>_wk<NN>.csv) blended 50/50 with the
    DraftKings/FanDuel no-vig chance as the board does, at the first saved odds snapshot taken after the picks were
    logged and before kickoff. The pick is the side given 50%+, graded at that snapshot's DraftKings price."""
    import calib as CAL
    from nflmodel.model import G
    snaps = sorted(glob.glob(os.path.join(LOG, 'snapshots', '*.csv')))
    if not snaps: return []
    SN = pd.concat([pd.read_csv(f) for f in snaps], ignore_index=True)
    SN = SN[(SN.market == 'moneyline') & SN.book.isin(['draftkings', 'fanduel'])]
    SN = SN[pd.to_datetime(SN.taken_at, format='%Y-%m-%dT%H%MZ', utc=True) < pd.to_datetime(SN.kickoff, utc=True)]
    g = G.set_index('game_id'); rows = []
    for f in sorted(glob.glob(os.path.join(LOG, 'picks', '*_wk[0-9][0-9].csv'))):
        P = pd.read_csv(f); P = P[P.market == 'moneyline']
        for gid, pg in P.groupby('game_id'):
            if gid not in g.index or g.loc[gid, 'result'] != g.loc[gid, 'result']: continue
            home, away = g.loc[gid, 'home_team'], g.loc[gid, 'away_team']
            q = SN[(SN.home_team == home) & (SN.away_team == away) & (SN.taken_at >= pg.logged_at.iloc[0])]
            dk = q[q.book == 'draftkings']
            if dk.empty: continue
            first = dk.taken_at.min(); q = q[q.taken_at == q[q.taken_at >= first].groupby('book').taken_at.transform('min')]
            best = None
            for x in pg.itertuples():
                nv = []
                for b, bq in q.groupby('book'):
                    a, o = bq[bq.side == x.side], bq[bq.side != x.side]
                    if len(a) and len(o): ia, io = 1 / PZ.dec(a.price.iloc[0]), 1 / PZ.dec(o.price.iloc[0]); nv.append(ia / (ia + io))
                pr = dk[(dk.taken_at == first) & (dk.side == x.side)]
                if not nv or pr.empty: continue
                bk = min(0.99, max(0.005, sum(nv) / len(nv))); w = 0.5 * min(1.0, max(0.4, (bk - 0.03) / 0.22))
                pp = w * float(x.model_prob) + (1 - w) * bk
                if best is None or pp > best['p']: best = dict(p=pp, side=x.side, price=int(pr.price.iloc[0]))
            if best is None: continue
            res = float(g.loc[gid, 'result']); m = res if best['side'] == home else -res
            if m == 0: continue   # a tie pushes
            rows.append(dict(p=best['p'], won=m > 0, units=PZ.dec(best['price']) - 1 if m > 0 else -1.0))
    return rows


def record():
    """Report for the NFL Model record tab: graded picks by category and market, plus suggested parlays."""
    want, picks = {}, {}
    for f in sorted(glob.glob(os.path.join(LOG, 'nfl_legs', '*.json'))):
        day = os.path.basename(f)[:-5]; picks[day] = json.load(open(f))
        want.setdefault(_week(day), {}).update({l['id']: l['game'] for l in picks[day]})
    plogs = {}
    for f in sorted(glob.glob(os.path.join(LOG, 'parlays', '*.json'))):
        plogs.setdefault(os.path.basename(f).rsplit('_', 1)[0], f)
    for day, f in plogs.items():
        for m in json.load(open(f)).values():
            for slips in m['slips'].values():
                for s in slips: want.setdefault(_week(day), {}).update({L['id']: L['game'] for L in s})
    import bank as BANK   # Bank Builder slips' NFL legs (bank.py) are graded here too
    bw = BANK.nfl_wanted()
    for k, ids in bw.items(): want.setdefault(k, {}).update(ids)
    try:
        res = results(want)
    except Exception as e:   # data download failed: show what's logged, grade next run
        print('NFL record: grading skipped,', e); res = {}
    bf = os.path.join(BANK.LOG, 'nfl_results.json')   # kept across runs, so a failed download loses nothing
    bres = json.load(open(bf)) if os.path.exists(bf) else {}
    for (se, wk), ids in bw.items():
        for i in ids:
            v = res.get(('%d_wk%02d' % (se, wk), i))
            if v: bres.setdefault('%d_wk%02d' % (se, wk), {})[i] = v
    if bw: os.makedirs(BANK.LOG, exist_ok=True); json.dump(bres, open(bf, 'w'))
    # a parlay log like 2026_wk10thu_* grades with its week's results
    res.update({(d, i): v for d in plogs if d not in picks for (d0, i), v in list(res.items()) if d0 == '%d_wk%02d' % _week(d)})
    rows = []
    for day, ls in picks.items():
        for l in ls:
            r = res.get((day, l['id']))
            if l['cat'] == 'Check role': continue   # a warning, not a pick
            if l['kind'] == 'Milestone': continue   # alt lines aren't counted; the main over/under covers the player (Thomas, 2026-11-14)
            if r in ('win', 'loss'):
                rows.append(dict(cat=l['cat'], mkt=MKT.get(l['kind'], l['kind']), won=r == 'win', p=l['p'],
                                 units=PZ.dec(l['price']) - 1 if r == 'win' else -1.0))
    groups = []

    def grp(name, x):
        if not x: return
        w = sum(r['won'] for r in x); u = sum(r['units'] for r in x)
        groups.append(dict(group=name, bets=len(x), won=w, lost=len(x) - w, hit=w / len(x), exp_hit=sum(r['p'] for r in x) / len(x),
                           units=round(u, 2), roi=u / len(x)))
    grp('All picks', rows)
    for mk in dict.fromkeys(MKT.values()): grp(mk, [r for r in rows if r['mkt'] == mk])
    for c in sorted({r['cat'] for r in rows}): grp(f'{c} picks', [r for r in rows if r['cat'] == c])
    pick_groups, groups = groups, []
    # the legs the parlay suggestions chose, each as a 1-unit straight bet at its DK price (alt lines included)
    for mode, name in [('value', 'Best value'), ('likely', 'Most likely to hit')]:
        star, every = {}, {}
        for day, f in plogs.items():
            m = json.load(open(f)).get(mode)
            if not m: continue
            for k, slips in m['slips'].items():
                for i, sl in enumerate(slips):
                    for L in sl:
                        r = res.get((day, L['id']))
                        if r not in ('win', 'loss'): continue
                        row = dict(won=r == 'win', p=L['p'], alt=L['id'].startswith('m-'),
                                   units=PZ.dec(L['price']) - 1 if r == 'win' else -1.0)
                        every[(day, L['id'])] = row
                        if str(m['best']) == k and i == 0: star[(day, L['id'])] = row
        grp(f'{name}: ★ suggestion legs', list(star.values()))
        grp(f'{name}: every suggested leg', list(every.values()))
        grp(f'{name}: alt-line legs', [r for r in every.values() if r['alt']])
        grp(f'{name}: main-line legs', [r for r in every.values() if not r['alt']])
    # calibration by leg type (calib.py): the moneyline pick in every game, then the board's logged picks by market
    import calib as CAL
    try: ml = moneylines()
    except Exception as e: print('NFL record: moneylines skipped,', e); ml = []
    cr = []
    for day, ls in picks.items():
        for l in ls:
            r = res.get((day, l['id']))
            if l['cat'] == 'Check role' or r not in ('win', 'loss'): continue
            cr.append(dict(kind=l['kind'], id=l['id'], p=l['p'], won=r == 'win', units=PZ.dec(l['price']) - 1 if r == 'win' else -1.0))
    lg = {}
    for day, f in plogs.items():
        for m in json.load(open(f)).values():
            for slips in m['slips'].values():
                for sl in slips:
                    for L in sl:
                        r = res.get((day, L['id']))
                        if r in ('win', 'loss'): lg[(day, L['id'])] = dict(p=L['p'], won=r == 'win', units=PZ.dec(L['price']) - 1 if r == 'win' else -1.0)
    cal = CAL.sections(
        ('Moneyline picks', ml, 'The team the board gave the better chance to win, every game, at the first DraftKings price saved before kickoff.', True),
        ('Spreads and totals', [r for r in cr if r['kind'] == 'Game' and '-ml-' not in r['id']], "The board's categorized spread and total picks.", True),
        ('Yards and receptions', [r for r in cr if r['kind'] in ('Rush', 'Rec', 'Recs', 'Pass')], "The board's categorized over/under picks on main lines.", True),
        ('Anytime TDs', [r for r in cr if r['kind'] == 'TD'], "The board's TD picks; a TD is one-sided, so chances run the full range.", False),
        ('Alt lines', [r for r in cr if r['kind'] == 'Milestone'], "The board's alt-line picks (Likely hit, Value).", False),
        ('Legs in suggested parlays', list(lg.values()), 'Every leg the Parlay builder suggested, alt lines included, as its own straight bet.', False))
    return dict(cal=cal, weeks=sorted(picks), graded=sorted({'%d_wk%02d' % _week(d) for (d, _), v in res.items() if v}), picks=pick_groups, legs=groups,
                parlays=PZ.grade(LOG, {k: v for k, v in res.items() if v}))
