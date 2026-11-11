"""Price the coming NFL week against the opening lines and log the picks.

Run after `python -m nflmodel.odds` has saved a snapshot early in the week (the "opener").
1. Rebuilds team ratings from the latest nflverse play-by-play (cached files are refreshed).
2. Fits the v2 model (EPA + QB) on every finished game. Injury and roster features are left out
   because injury reports come out after openers are posted.
3. Compares the model with the consensus opening spread and total, and with the best line on offer.
4. Writes odds_log/picks/<season>_wk<NN>.csv.

Usage: NFL_GAMES_CSV=<path to nflverse games.csv> python scripts/weekly_picks.py
"""
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
ROOT = os.path.join(os.path.dirname(__file__), '..')
DATA = os.path.join(ROOT, 'data')
for f in ['team_games.csv', 'qb_games.csv']:   # force fresh play-by-play aggregates
    if os.path.exists(os.path.join(DATA, f)): os.remove(os.path.join(DATA, f))

import numpy as np, pandas as pd
from scipy.stats import norm
from nflmodel.model import G, novig
from nflmodel.features import all_features, build
from nflmodel.predict import fit_predict, american_to_decimal, BASE_MARGIN_X, BASE_TOTAL_X
from nflmodel.odds import all_snapshots

OPTIMAL_EV, SECURE_P, MIN_EDGE = 0.05, 0.70, 1.5

today = pd.Timestamp.now(tz='UTC').tz_localize(None).normalize()
upcoming = G[(G.game_type == 'REG') & G.result.isna() & (G.gameday >= today - pd.Timedelta(days=1))]
if upcoming.empty:
    raise SystemExit('No upcoming regular-season games in games.csv.')
season, week = int(upcoming.season.min()), int(upcoming[upcoming.season == upcoming.season.min()].week.min())
target = G[(G.season == season) & (G.week == week)]
print(f'Pricing {season} week {week}: {len(target)} games')

# features: history (for fitting) + this week
hist = all_features(range(2019, season + 1), with_roster=False)
cols = ['game_id', 'season', 'week', 'gameday', 'away_team', 'home_team', 'away_score', 'home_score', 'result', 'total',
        'spread_line', 'total_line', 'home_moneyline', 'away_moneyline', 'home_spread_odds', 'away_spread_odds',
        'over_odds', 'under_odds', 'home_qb_name', 'away_qb_name']
df = hist.merge(G[cols], on='game_id')
df['gameday'] = pd.to_datetime(df.gameday)

# opening lines: the earliest snapshot that has each game
snaps = all_snapshots()
if snaps.empty:
    raise SystemExit('No odds snapshots yet. Run: python -m nflmodel.odds')
snaps = snaps[snaps.home_team.isin(target.home_team) & snaps.away_team.isin(target.away_team)]
first = snaps.groupby(['home_team', 'away_team']).taken_at.transform('min')
opener = snaps[snaps.taken_at == first]
cons = opener[opener.book == 'consensus']

def pick(home, away, market, side):
    r = cons[(cons.home_team == home) & (cons.away_team == away) & (cons.market == market) & (cons.side == side)]
    return (r.point.iloc[0], r.price.iloc[0]) if len(r) else (np.nan, np.nan)

def best(home, away, market, side):
    """Most favorable line for this side across books (higher spread/over-total for us), then best price."""
    r = opener[(opener.home_team == home) & (opener.away_team == away) & (opener.market == market)
               & (opener.side == side) & (opener.book != 'consensus')]
    if r.empty: return np.nan, np.nan, ''
    asc = side == 'Over'   # for Over a lower total is better; for spreads and Under a higher number is better
    r = r.sort_values(['point', 'price'], ascending=[asc, False]) if market != 'moneyline' else r.sort_values('price', ascending=False)
    x = r.iloc[0]; return x.point, x.price, x.book

open_rows = []
for g in target.itertuples():
    sp, _ = pick(g.home_team, g.away_team, 'spread', g.home_team)
    tot, _ = pick(g.home_team, g.away_team, 'total', 'Over')
    hml, _ = pick(g.home_team, g.away_team, 'moneyline', g.home_team)
    hml = cons[(cons.home_team == g.home_team) & (cons.away_team == g.away_team) & (cons.market == 'moneyline') & (cons.side == g.home_team)].price
    aml = cons[(cons.home_team == g.home_team) & (cons.away_team == g.away_team) & (cons.market == 'moneyline') & (cons.side == g.away_team)].price
    open_rows.append({'game_id': g.game_id, 'open_spread': -sp if sp == sp else np.nan, 'open_total': tot,
                      'open_home_ml': hml.iloc[0] if len(hml) else np.nan, 'open_away_ml': aml.iloc[0] if len(aml) else np.nan})
op = pd.DataFrame(open_rows)

train = df.gameday < pd.to_datetime(target.gameday).min()
p = fit_predict(df, train & df.result.notna(), df.game_id.isin(target.game_id), False, BASE_MARGIN_X, BASE_TOTAL_X)
p = p.merge(op, on='game_id', how='left')

out = []
for g in p.itertuples():
    game = f'{g.away_team} @ {g.home_team}'
    if g.open_spread == g.open_spread:
        cover_home = 1 - norm.cdf(g.open_spread, g.pred_margin, g.sd_margin)
        for side, prob, sign in [(g.home_team, cover_home, 1), (g.away_team, 1 - cover_home, -1)]:
            bpt, bpr, bk = best(g.home_team, g.away_team, 'spread', side)
            # probability at the best number for this side
            if bpt == bpt:
                line_home = -bpt if side == g.home_team else bpt   # home-margin threshold
                prob_b = (1 - norm.cdf(line_home, g.pred_margin, g.sd_margin)) if side == g.home_team else norm.cdf(line_home, g.pred_margin, g.sd_margin)
            else:
                prob_b, bpr = prob, -110
            out.append(dict(game_id=g.game_id, game=game, kickoff=g.gameday, market='spread', side=side,
                            open_line=(-g.open_spread if side == g.home_team else g.open_spread),
                            model_line=(-g.pred_margin if side == g.home_team else g.pred_margin),
                            edge_pts=sign * (g.pred_margin - g.open_spread), model_prob=prob,
                            best_line=bpt, best_price=bpr, best_book=bk,
                            ev=prob_b * float(american_to_decimal(bpr)) - 1))
    if g.open_total == g.open_total:
        p_over = 1 - norm.cdf(g.open_total, g.pred_total, g.sd_total)
        for side, prob, sign in [('Over', p_over, 1), ('Under', 1 - p_over, -1)]:
            bpt, bpr, bk = best(g.home_team, g.away_team, 'total', side)
            prob_b = ((1 - norm.cdf(bpt, g.pred_total, g.sd_total)) if side == 'Over' else norm.cdf(bpt, g.pred_total, g.sd_total)) if bpt == bpt else prob
            out.append(dict(game_id=g.game_id, game=game, kickoff=g.gameday, market='total', side=side,
                            open_line=g.open_total, model_line=g.pred_total, edge_pts=sign * (g.pred_total - g.open_total),
                            model_prob=prob, best_line=bpt, best_price=bpr if bpr == bpr else -110, best_book=bk,
                            ev=prob_b * float(american_to_decimal(bpr if bpr == bpr else -110)) - 1))
    for side, prob in [(g.home_team, g.p_home_win), (g.away_team, 1 - g.p_home_win)]:
        bpt, bpr, bk = best(g.home_team, g.away_team, 'moneyline', side)
        if bpr == bpr:
            out.append(dict(game_id=g.game_id, game=game, kickoff=g.gameday, market='moneyline', side=side,
                            open_line=np.nan, model_line=np.nan, edge_pts=np.nan, model_prob=prob,
                            best_line=np.nan, best_price=bpr, best_book=bk, ev=prob * float(american_to_decimal(bpr)) - 1))
L = pd.DataFrame(out)
# Only spreads were backtested against openers, so value totals are logged as "Watch" and graded separately.
value = (L.ev >= OPTIMAL_EV) & (L.edge_pts >= MIN_EDGE)
L['category'] = np.select([(L.market == 'moneyline') & (L.model_prob >= SECURE_P),
                           (L.market == 'spread') & value, (L.market == 'total') & value],
                          ['Secure', 'Optimal', 'Watch'], '')
L.insert(0, 'season', season); L.insert(1, 'week', week)
L['logged_at'] = cons.taken_at.min() if len(cons) else ''
os.makedirs(os.path.join(ROOT, 'odds_log', 'picks'), exist_ok=True)
path = os.path.join(ROOT, 'odds_log', 'picks', f'{season}_wk{week:02d}.csv')
L.round(4).to_csv(path, index=False)
picks = L[L.category != ''].sort_values('ev', ascending=False)
pd.set_option('display.width', 200)
print(picks[['game', 'market', 'side', 'open_line', 'model_line', 'edge_pts', 'model_prob', 'best_line', 'best_price', 'best_book', 'ev', 'category']].round(3).to_string(index=False))
print(f'\nsaved {len(L)} legs ({len(picks)} picks) to {path}')
