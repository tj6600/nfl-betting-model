"""Grade logged anytime-TD picks once the games are in the play-by-play.

Reads odds_log/picks/*_td_picks.csv, checks whether each player scored a rushing or receiving TD,
and stakes 1 unit at the best price logged. Writes odds_log/td_graded.csv and odds_log/td_report.md.
"""
import sys, os, glob; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
ROOT = os.path.join(os.path.dirname(__file__), '..')
import numpy as np, pandas as pd
from nflmodel import touchdowns as T

files = sorted(glob.glob(os.path.join(ROOT, 'odds_log', 'picks', '*_td_picks.csv')))
if not files:
    raise SystemExit('no TD picks logged yet')
picks = []
for f in files:
    season, wk = os.path.basename(f).split('_')[:2]
    picks.append(pd.read_csv(f).assign(season=int(season), week=int(wk[2:])))
P = pd.concat(picks, ignore_index=True)
scored = T._player_games(sorted(P.season.unique()))
sc = scored.groupby(['season', 'week', 'pid']).tds.sum().reset_index()
# grade game by game: a week is only partly played on Thursday, and Monday night's game comes after the Monday run
gids = scored.game_id.drop_duplicates()
played = pd.DataFrame({'season': gids.str[:4].astype(int), 'week': gids.str[5:7].astype(int),
                       'game': gids.str.split('_').str[2] + ' @ ' + gids.str.split('_').str[3]})
P = P.merge(played.assign(done=True), on=['season', 'week', 'game'], how='left')
P = P[P.done.fillna(False).astype(bool)].drop(columns='done')
if P.empty:
    print('no graded TD weeks yet (games not in the play-by-play)'); open(os.path.join(ROOT, 'odds_log', 'td_report.md'), 'w').write('')
else:
    P = P.merge(sc, on=['season', 'week', 'pid'], how='left')
    P['result'] = np.where(P.tds.fillna(0) > 0, 'Won', 'Lost')   # a player who did not touch the ball counts as a loss
    dec = np.where(P.best_price < 0, 1 + 100 / -P.best_price, 1 + P.best_price / 100)
    P['profit'] = np.where(P.result == 'Won', dec - 1, -1.0)
    P.to_csv(os.path.join(ROOT, 'odds_log', 'td_graded.csv'), index=False)
    g = P.groupby('category').agg(bets=('result', 'size'), won=('result', lambda r: (r == 'Won').sum()),
                                  avg_model=('model_prob', 'mean'), units=('profit', 'sum'))
    g['hit'] = g.won / g.bets; g['roi'] = g.units / g.bets
    md = '# Anytime TD picks: graded\n\n```\n' + g.round(3).to_string() + '\n```\n'
    open(os.path.join(ROOT, 'odds_log', 'td_report.md'), 'w').write(md)
    print(md)

# ---- rushing / receiving yards over/unders (odds_log/picks/*_yards.csv, Value picks) ----
yf = sorted(glob.glob(os.path.join(ROOT, 'odds_log', 'picks', '*_yards.csv')))
Ys = []
for f in yf:
    season, wk = os.path.basename(f).split('_')[:2]
    y = pd.read_csv(f).assign(season=int(season), week=int(wk[2:]))
    y = y[y.category == 'Value'].copy()
    # grade at DraftKings' own line and price (Thomas bets DraftKings only); best_line/best_price can be another book's
    bf = f.replace('_yards.csv', '_yards_books.csv')
    y['kind'] = y.market.map({'Rushing yards': 'rush', 'Receiving yards': 'rec', 'Receptions': 'recs', 'Passing yards': 'pass'})
    if os.path.exists(bf):
        dk = pd.read_csv(bf); dk = dk[dk.book == 'DraftKings'][['pid', 'kind', 'side', 'point', 'price']]
        dk = dk.sort_values('point').drop_duplicates(['pid', 'kind', 'side'])   # one DK line per side
        y = y.merge(dk.rename(columns={'point': 'dk_line', 'price': 'dk_price'}), on=['pid', 'kind', 'side'], how='left')
    else:
        y['dk_line'] = np.nan; y['dk_price'] = np.nan
    Ys.append(y)
if Ys:
    Yp = pd.concat(Ys, ignore_index=True)
    st = T._player_games(sorted(Yp.season.unique()))[['season', 'week', 'pid', 'rush_yds', 'rec_yds', 'receptions']]
    Yp = Yp.merge(played.assign(done=True), on=['season', 'week', 'game'], how='left')
    Yp = Yp[Yp.done.fillna(False).astype(bool)].merge(st, on=['season', 'week', 'pid'], how='left')
    if (Yp.kind == 'pass').any():   # passing yards come from nflverse weekly stats
        from nflmodel import passing as PY
        q = PY.load(sorted(Yp.season.unique()))[['season', 'week', 'pid', 'passing_yards']]
        Yp = Yp.merge(q, on=['season', 'week', 'pid'], how='left')
    else:
        Yp['passing_yards'] = np.nan
    Yp['actual'] = np.select([Yp.kind == 'rush', Yp.kind == 'rec', Yp.kind == 'recs'], [Yp.rush_yds, Yp.rec_yds, Yp.receptions], Yp.passing_yards)
    Yp = Yp[Yp.actual.notna()].copy()   # did not play: books void
    if len(Yp):
        Yp['line'] = Yp.dk_line.fillna(Yp.best_line); Yp['price'] = Yp.dk_price.fillna(Yp.best_price)
        Yp['book'] = np.where(Yp.dk_line.notna(), 'DraftKings', Yp.best_book)
        Yp['result'] = np.select([Yp.actual == Yp.line, (Yp.side == 'Over') == (Yp.actual > Yp.line)], ['Push', 'Won'], 'Lost')
        d2 = np.where(Yp.price < 0, 1 + 100 / -Yp.price, 1 + Yp.price / 100)
        Yp['profit'] = np.select([Yp.result == 'Won', Yp.result == 'Lost'], [d2 - 1, -1.0], 0.0)
        Yp.to_csv(os.path.join(ROOT, 'odds_log', 'yards_graded.csv'), index=False)
        gy = Yp.groupby('market').agg(bets=('result', 'size'), won=('result', lambda r: (r == 'Won').sum()), units=('profit', 'sum'))
        gy['hit'] = gy.won / gy.bets
        md = '\n# Yards, receptions and passing picks: graded at DraftKings lines\n\n```\n' + gy.round(3).to_string() + '\n```\n'
        open(os.path.join(ROOT, 'odds_log', 'td_report.md'), 'a').write(md); print(md)
