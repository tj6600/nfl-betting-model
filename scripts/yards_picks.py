"""Rushing and receiving yards over/under picks: model vs sportsbook lines.

1. Fits the yards model (nflmodel/yards.py) on every finished 2021+ game.
2. Prices this week's players (same player pool as the TD picks: active, not ruled out).
3. Reads the newest odds_log/props/yards_*.json (The Odds API: player_rush_yds, player_reception_yds).
4. Writes odds_log/picks/<season>_wk<NN>_yards.csv with the model's projection, chance of each side, best line and EV.
"""
import sys, os, glob, json; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
ROOT = os.path.join(os.path.dirname(__file__), '..')
import numpy as np, pandas as pd
from nflmodel.model import G
from nflmodel.odds import all_snapshots, TEAMS
from nflmodel import touchdowns as T, yards as Y

VALUE_EV, VALUE_P, MIN_BOOKS = 0.05, 0.57, 3
W_MODEL = 0.5           # untested against real prop lines, so the model's chance is blended 50/50 with the books' no-vig chance
MAX_GAP = 0.25          # model projection more than 25% away from the line: the books likely know something (role, injury)
MIN_VOL = {'rush': 8.0, 'rec': 3.0}   # carries or targets a game for a regular role
today = pd.Timestamp.now(tz='UTC').tz_localize(None).normalize()
up = G[(G.game_type == 'REG') & G.result.isna() & (pd.to_datetime(G.gameday) >= today - pd.Timedelta(days=1))]
season = int(up.season.min()); week = int(up[up.season == season].week.min())
target = G[(G.season == season) & (G.week == week)]

# this week's lines from the latest consensus snapshot
s = all_snapshots(); s = s[s.book == 'consensus']; s = s[s.taken_at == s.taken_at.max()]
lines = []
for g in target.itertuples():
    sp = s[(s.home_team == g.home_team) & (s.away_team == g.away_team) & (s.market == 'spread') & (s.side == g.home_team)].point
    tt = s[(s.home_team == g.home_team) & (s.away_team == g.away_team) & (s.market == 'total') & (s.side == 'Over')].point
    lines.append({'game_id': g.game_id, 'home_team': g.home_team, 'away_team': g.away_team,
                  'spread_line': -sp.iloc[0] if len(sp) else g.spread_line, 'total_line': tt.iloc[0] if len(tt) else g.total_line})
lines = pd.DataFrame(lines)
ov_path = os.path.join(ROOT, 'odds_log', 'injury_overrides.csv')
P = T.upcoming(season, week, T.implied_points(lines), pd.read_csv(ov_path) if os.path.exists(ov_path) else None)
P = P.merge(Y.team_margin(lines), on='posteam', how='left', suffixes=('', '_m'))
P = P.merge(lines[['game_id', 'home_team', 'away_team']], on='game_id')
try:
    snaps = T.depth_snapshots([season]); P = T.add_depth(P, snaps, now=snaps.dt.max() + pd.Timedelta(minutes=1))
except Exception as e:
    print('depth charts unavailable:', e); P['dc_rank'] = P['dc_prev'] = np.nan; P['dc_tier'] = 0; P['dc_demoted'] = 0.0

base = T.training_frame()
hist = T.history()
models = {}
for kind in Y.STATS:
    tr = Y.frame(kind, base)
    models[kind] = Y.fit(kind, tr)
    d = Y.defense_yards(hist, Y.STATS[kind]['y'])
    dn = d.sort_values('gameday').groupby(['defteam', 'position']).now.last().rename(f'def_{kind}').reset_index()
    P = P.merge(dn, on=['defteam', 'position'], how='left')

# odds: one row per player, market, side and book
f = sorted(glob.glob(os.path.join(ROOT, 'odds_log', 'props', 'yards_*.json')))[-1]
rows = []
for e in json.load(open(f)):
    for bk in e.get('bookmakers', []):
        for m in bk['markets']:
            kind = 'rush' if m['key'] == 'player_rush_yds' else 'rec'
            for o in m['outcomes']:
                if o.get('description') and o.get('point') is not None:
                    rows.append({'home_team': TEAMS.get(e['home_team']), 'away_team': TEAMS.get(e['away_team']), 'kind': kind,
                                 'player': o['description'], 'side': o['name'], 'point': o['point'], 'price': o['price'], 'book': bk['title']})
O = pd.DataFrame(rows); O['k'] = T._key(O.player)
P['k'] = T._key(P.full_name)
dec = lambda o: np.where(o < 0, 1 + 100 / -o, 1 + o / 100)
out = []
for (home, away, k, kind), grp in O.groupby(['home_team', 'away_team', 'k', 'kind']):
    pl = P[(P.home_team == home) & (P.away_team == away) & (P.k == k)]
    if pl.empty or pl.iloc[0].position not in Y.STATS[kind]['pos']:
        continue
    r = pl.iloc[0].copy()
    r['def_yds'] = r[f'def_{kind}']
    b, spread = models[kind]
    mu = float(Y.apply(b, Y.design(pd.DataFrame([r]), kind))[0])
    cons = grp.point.median()
    # books' no-vig chance of the Over at the consensus number (median prices of each side)
    imp = lambda o: np.where(o < 0, -o / (-o + 100.0), 100.0 / (o + 100.0))
    po = float(imp(grp[grp.side == 'Over'].price.median())) if (grp.side == 'Over').any() else np.nan
    pu = float(imp(grp[grp.side == 'Under'].price.median())) if (grp.side == 'Under').any() else np.nan
    mkt_over = po / (po + pu) if po == po and pu == pu else np.nan
    for side in ['Over', 'Under']:
        g2 = grp[grp.side == side]
        if g2.empty: continue
        # best number for this side, then best price at that number
        g2 = g2.sort_values(['point', 'price'], ascending=[side == 'Over', False])
        x = g2.iloc[0]
        p_over = float(spread.p_over([mu], [x.point])[0])
        model_p = p_over if side == 'Over' else 1 - p_over
        mkt = (mkt_over if side == 'Over' else 1 - mkt_over) if mkt_over == mkt_over else model_p
        p = W_MODEL * model_p + (1 - W_MODEL) * mkt
        out.append(dict(game=f'{away} @ {home}', pid=r.pid, team=r.posteam, opp=r.defteam, player=r.full_name, position=r.position,
                        market='Rushing yards' if kind == 'rush' else 'Receiving yards', side=side, line=cons, best_line=x.point,
                        best_price=int(x.price), best_book=x.book, books=g2.book.nunique(), projection=round(mu, 1),
                        median=round(float(spread.quantile([mu], .5)[0]), 1),
                        q25=round(float(spread.quantile([mu], .25)[0]), 1), q75=round(float(spread.quantile([mu], .75)[0]), 1), model_only=model_p, market_prob=mkt, model_prob=p,
                        ev=p * float(dec(x.price)) - 1, carries=r.h_carries, targets=r.h_targets,
                        recent_yds=r['h_' + Y.STATS[kind]['y']], imp_pts=r.imp_pts, exp_margin=r.exp_margin, def_yds=r.def_yds,
                        missed_n=r.missed_n, dc_rank=r.dc_rank, dc_prev=r.dc_prev, dc_demoted=r.dc_demoted,
                        volume=r[Y.STATS[kind]['vol']], regular=bool(r[Y.STATS[kind]['vol']] >= MIN_VOL[kind])))
M = pd.DataFrame(out)
M['gap'] = (M.projection - M.line) / M.line
risky = (M.missed_n >= 1) | (M.dc_demoted == 1) | (M.gap.abs() > MAX_GAP)
good = (M.ev >= VALUE_EV) & (M.model_prob >= VALUE_P) & (M.books >= MIN_BOOKS) & M.regular
M['category'] = np.where(good & ~risky, 'Value', np.where(good & risky, 'Check role', ''))
M['note'] = np.select([M.missed_n >= 1, M.dc_demoted == 1, M.gap.abs() > MAX_GAP], [
    'Missed his last game; his usage is from before that.', 'The depth chart has moved him down.',
    'The model and the line are far apart, so the books probably know about a role change or injury.'], '')
M = M.sort_values('ev', ascending=False)
path = os.path.join(ROOT, 'odds_log', 'picks', f'{season}_wk{week:02d}_yards.csv')
M.round(4).to_csv(path, index=False)
pd.set_option('display.width', 250)
print(f'{M.player.nunique()} players, {len(M)} sides priced; {(M.category == "Value").sum()} value picks')
print(M[M.category != ''][['game', 'player', 'market', 'side', 'line', 'best_line', 'best_price', 'best_book', 'projection', 'median', 'model_prob', 'ev', 'category']].round(3).to_string(index=False))

# ---- milestones (alternate lines: "40+ receiving yards" = Over 39.5) ----
ALT_MARGIN = 1.06    # alternate lines have no Under side; book chances are divided by an estimated 6% margin
af = sorted(glob.glob(os.path.join(ROOT, 'odds_log', 'props', 'altyards_*.json')))
if af:
    rows = []
    for e in json.load(open(af[-1])):
        for bk in e.get('bookmakers', []):
            for m in bk['markets']:
                kind = 'rush' if m['key'].startswith('player_rush') else 'rec'
                for o in m['outcomes']:
                    pt = o.get('point')
                    if o.get('name') == 'Over' and o.get('description') and pt is not None and (pt + 0.5) % 5 == 0 and 9.5 <= pt <= 199.5:
                        rows.append({'home_team': TEAMS.get(e['home_team']), 'away_team': TEAMS.get(e['away_team']), 'kind': kind,
                                     'player': o['description'], 'point': pt, 'price': o['price'], 'book': bk['title']})
    A = pd.DataFrame(rows); A['k'] = T._key(A.player)
    base_rows = M.drop_duplicates(['pid', 'market']).copy()
    base_rows['kind'] = np.where(base_rows.market.str.startswith('Rush'), 'rush', 'rec')
    base_rows['k'] = T._key(base_rows.player)
    imp = lambda o: np.where(o < 0, -o / (-o + 100.0), 100.0 / (o + 100.0))
    out = []
    for (home, away, k, kind, pt), g in A.groupby(['home_team', 'away_team', 'k', 'kind', 'point']):
        br = base_rows[(base_rows.game == f'{away} @ {home}') & (base_rows.k == k) & (base_rows.kind == kind)]
        if br.empty:
            continue
        r = br.iloc[0]; spread = models[kind][1]
        model_p = float(spread.p_over([r.projection], [pt])[0])
        book_p = float(np.median(imp(g.price.values))) / ALT_MARGIN
        p = W_MODEL * model_p + (1 - W_MODEL) * min(book_p, 0.995)
        best = g.sort_values('price', ascending=False).iloc[0]
        out.append(dict(game=r.game, pid=r.pid, team=r.team, opp=r.opp, player=r.player, position=r.position, market=r.market,
                        milestone=int(pt + 0.5), point=pt, model_only=model_p, book_prob=book_p, prob=p,
                        best_price=int(best.price), best_book=best.book, books=g.book.nunique(),
                        ev=p * float(dec(best.price)) - 1, projection=r.projection, median=r['median'], main_line=r.line,
                        regular=r.regular, risky=bool((r.missed_n >= 1) or (r.dc_demoted == 1) or (abs(r.gap) > MAX_GAP))))
    MS = pd.DataFrame(out)
    MS['category'] = np.select([(MS.prob >= 0.80) & ~MS.risky & MS.regular,
                                (MS.ev >= 0.05) & (MS.prob >= 0.25) & (MS.books >= 2) & ~MS.risky & MS.regular],
                               ['Likely hit', 'Value'], '')
    mpath = os.path.join(ROOT, 'odds_log', 'picks', f'{season}_wk{week:02d}_milestones.csv')
    MS.round(4).to_csv(mpath, index=False)
    print(f'\n{len(MS)} milestones priced; {(MS.category == "Likely hit").sum()} likely hits, {(MS.category == "Value").sum()} value')
    print(MS[MS.category != ''].sort_values(['category', 'ev'], ascending=[True, False]).head(40)[
        ['player', 'market', 'milestone', 'model_only', 'book_prob', 'prob', 'best_price', 'best_book', 'ev', 'category']].round(3).to_string(index=False))
