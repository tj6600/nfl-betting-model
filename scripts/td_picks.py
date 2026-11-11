"""Anytime-touchdown picks for the coming week: model chance vs sportsbook odds.

1. Fits the touchdown model (nflmodel/touchdowns.py) on every finished 2021+ game.
2. Prices this week's players using implied team points from the latest consensus line.
3. Reads the newest odds_log/props/anytime_td_*.json (The Odds API, market player_anytime_td).
4. Writes odds_log/picks/<season>_wk<NN>_td.csv with model %, book-implied %, best price and EV.
"""
import sys, os, glob, json; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
ROOT = os.path.join(os.path.dirname(__file__), '..')
_c = os.path.join(ROOT, 'data', 'td_player_games.csv')
if os.path.exists(_c): os.remove(_c)          # rebuild player history with the latest games
import numpy as np, pandas as pd
from nflmodel.model import G
from nflmodel import touchdowns as T
from nflmodel.odds import all_snapshots, TEAMS

today = pd.Timestamp.now(tz='UTC').tz_localize(None).normalize()
up = G[(G.game_type == 'REG') & G.result.isna() & (pd.to_datetime(G.gameday) >= today - pd.Timedelta(days=1))]
season = int(up.season.min()); week = int(up[up.season == season].week.min())
target = G[(G.season == season) & (G.week == week)]

df = T.training_frame()
b = T.fit(T.design(df), df.scored.values)

# implied points from the latest consensus snapshot (fall back to games.csv lines)
s = all_snapshots(); s = s[s.book == 'consensus']
s = s[s.taken_at == s.taken_at.max()]
lines = []
for g in target.itertuples():
    sp = s[(s.home_team == g.home_team) & (s.away_team == g.away_team) & (s.market == 'spread') & (s.side == g.home_team)].point
    tt = s[(s.home_team == g.home_team) & (s.away_team == g.away_team) & (s.market == 'total') & (s.side == 'Over')].point
    lines.append({'game_id': g.game_id, 'home_team': g.home_team, 'away_team': g.away_team,
                  'spread_line': -sp.iloc[0] if len(sp) else g.spread_line, 'total_line': tt.iloc[0] if len(tt) else g.total_line})
lines = pd.DataFrame(lines)
ov_path = os.path.join(ROOT, 'odds_log', 'injury_overrides.csv')
ov = pd.read_csv(ov_path) if os.path.exists(ov_path) else None
P = T.upcoming(season, week, T.implied_points(lines), ov)
P['model_prob'] = T.predict(b, T.design(P))
# depth chart (shown and used as a flag, not in the model: on 2026 games it did not improve the predictions
# because recent usage already carries the same information)
try:
    snaps = T.depth_snapshots([season])
    P = T.add_depth(P, snaps, now=snaps.dt.max() + pd.Timedelta(minutes=1))
except Exception as e:
    print('depth charts unavailable:', e); P['dc_rank'] = P['dc_prev'] = np.nan; P['dc_tier'] = 0; P['dc_demoted'] = P['dc_promoted'] = 0.0
P = P.merge(lines[['game_id', 'home_team', 'away_team']], on='game_id')

# sportsbook anytime TD prices
f = sorted(glob.glob(os.path.join(ROOT, 'odds_log', 'props', 'anytime_td_*.json')))[-1]
rows = []
for e in json.load(open(f)):
    for bk in e.get('bookmakers', []):
        for m in bk['markets']:
            for o in m['outcomes']:
                if o.get('name', 'Yes') == 'Yes' and o.get('description'):
                    rows.append({'home_team': TEAMS.get(e['home_team']), 'away_team': TEAMS.get(e['away_team']),
                                 'player': o['description'], 'book': bk['key'], 'price': o['price']})
O = pd.DataFrame(rows)
O['k'] = T._key(O.player)
imp = lambda o: np.where(o < 0, -o / (-o + 100), 100 / (o + 100))
O['book_prob'] = imp(O.price)
agg = O.groupby(['home_team', 'away_team', 'k']).agg(player=('player', 'first'), books=('book', 'nunique'),
                                                    median_price=('price', 'median'), book_prob=('book_prob', 'median')).reset_index()
best = O.sort_values('price', ascending=False).drop_duplicates(['home_team', 'away_team', 'k'])[['home_team', 'away_team', 'k', 'price', 'book']]
agg = agg.merge(best.rename(columns={'price': 'best_price', 'book': 'best_book'}), on=['home_team', 'away_team', 'k'])
P['k'] = T._key(P.full_name)
M = P.merge(agg, on=['home_team', 'away_team', 'k'], how='left')
dec = lambda o: np.where(o < 0, 1 + 100 / -o, 1 + o / 100)
M['ev'] = M.model_prob * dec(M.best_price.fillna(-1e9)) - 1
M.loc[M.best_price.isna(), 'ev'] = np.nan
M['edge_pct'] = (M.model_prob - M.book_prob) * 100
M['game'] = M.away_team + ' @ ' + M.home_team
keep = ['game', 'pid', 'posteam', 'full_name', 'position', 'model_prob', 'book_prob', 'edge_pct', 'median_price', 'best_price', 'best_book',
        'books', 'ev', 'imp_pts', 'h_rz_share', 'h_gl_share', 'h_carries', 'h_targets', 'h_tds',
        'room_share', 'last_share', 'missed_n', 'def_td', 'defteam', 'dc_rank', 'dc_prev', 'dc_tier', 'dc_demoted']
M = M[keep].sort_values('ev', ascending=False)
os.makedirs(os.path.join(ROOT, 'odds_log', 'picks'), exist_ok=True)
out = os.path.join(ROOT, 'odds_log', 'picks', f'{season}_wk{week:02d}_td.csv')
M.round(4).to_csv(out, index=False)
pd.set_option('display.width', 250)
print(f'{len(P)} players priced, {M.best_price.notna().sum()} matched to odds ({len(agg)} players offered)')
print(M.head(25).round(3).to_string(index=False))
print('unmatched offered:', sorted(set(agg.player) - set(M.dropna(subset=["best_price"]).full_name))[:40])

# categories shown on the page
M = M[M.best_price.notna() & (M.books >= 3)].copy()
M['opps'] = M.h_carries + M.h_targets
ratio = M.model_prob / M.book_prob
value = (M.opps >= 5) & (M.model_prob >= 0.15) & (M.ev >= 0.05) & (ratio <= 1.6)
check = (M.opps >= 5) & (ratio > 1.6) & (M.model_prob >= 0.12)   # model far above books: recent role may not carry over
check |= (M.model_prob >= 0.15) & (ratio > 1.3) & ((M.dc_demoted == 1) | (M.dc_tier == 3))   # depth chart says he's moved down
top = M.model_prob.rank(ascending=False) <= 12
M['category'] = np.select([value, check, top], ['TD value', 'Check role', 'Most likely'], '')

POSN = {'RB': 'running backs', 'WR': 'receivers', 'TE': 'tight ends', 'QB': 'quarterbacks'}
def why(r):
    bits = [f"{r.h_carries:.1f} carries and {r.h_targets:.1f} targets a game", f"{r.h_gl_share * 100:.0f}% of the team's goal-line chances",
            f"team expected to score {r.imp_pts:.1f}"]
    if abs(r.def_td) >= 0.15:
        bits.append(f"{r.defteam} allows {'more' if r.def_td > 0 else 'fewer'} TDs than average to {POSN[r.position]}")
    if r.dc_rank == r.dc_rank:
        dc = f"depth chart {r.position}{int(r.dc_rank)}"
        if r.dc_prev == r.dc_prev and int(r.dc_prev) != int(r.dc_rank):
            dc += f" (was {r.position}{int(r.dc_prev)} at his last game)"
        bits.append(dc)
    s = ', '.join(bits)
    if r.missed_n >= 1:
        s = f"Missed the last {int(r.missed_n)} game{'s' if r.missed_n > 1 else ''}, so his usage is from before that. " + s
    if r.category == 'Check role':
        if r.dc_demoted == 1:
            lead = "The depth chart has moved him down, so his recent usage may not carry over. "
        elif r.dc_tier == 3:
            lead = f"He is a backup on the depth chart ({r.position}{int(r.dc_rank)}), and the books price him well below the model. "
        else:
            lead = "The books are far lower than the model, so his role has probably changed or he may not be healthy. "
        s = lead + s
    return s
M['why'] = M.apply(why, axis=1)
C = M[M.category != ''].copy()
C.round(4).to_csv(out.replace('_td.csv', '_td_picks.csv'), index=False)
page = pd.DataFrame({'pick_id': (C.full_name + '-' + C.posteam).str.replace(' ', '_'), 'game': C.game, 'team': C.posteam,
                     'player': C.full_name, 'position': C.position, 'model_pct': (C.model_prob * 100).round(1),
                     'book_pct': (C.book_prob * 100).round(1), 'edge_pct': C.edge_pct.round(1), 'best_price': C.best_price.astype(int),
                     'best_book': C.best_book, 'ev_pct': (C.ev * 100).round(1), 'category': C.category, 'why': C.why})
page.to_csv(out.replace('_td.csv', '_td_page.csv'), index=False)
print(M[M.category != ''][['game', 'full_name', 'model_prob', 'book_prob', 'best_price', 'ev', 'category']].round(3).to_string(index=False))
