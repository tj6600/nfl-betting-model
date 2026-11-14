"""Grade logged picks: closing line value (did the line move our way by kickoff?) and results.

Closing line = the consensus line in the last snapshot taken before each game's kickoff.
Writes odds_log/clv_report.md and odds_log/graded_picks.csv.
"""
import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
from nflmodel.model import G
from nflmodel.odds import all_snapshots
from nflmodel.predict import american_to_decimal
ROOT = os.path.join(os.path.dirname(__file__), '..')
PDIR = os.path.join(ROOT, 'odds_log', 'picks')

files = sorted(f for f in os.listdir(PDIR) if f.endswith('.csv')) if os.path.isdir(PDIR) else []
if not files:
    raise SystemExit('No logged picks yet.')
L = pd.concat([pd.read_csv(os.path.join(PDIR, f)) for f in files], ignore_index=True)
L = L[L.category.fillna('') != ''].copy()
snaps = all_snapshots()
snaps['t'] = pd.to_datetime(snaps.taken_at, format='%Y-%m-%dT%H%MZ', utc=True)
snaps['ko'] = pd.to_datetime(snaps.kickoff, utc=True)
cons = snaps[(snaps.book == 'consensus') & (snaps.t < snaps.ko)]
last = cons[cons.t == cons.groupby('event_id').t.transform('max')]
g = G.set_index('game_id')

rows = []
for r in L.itertuples():
    home, away = g.loc[r.game_id, 'home_team'], g.loc[r.game_id, 'away_team']
    c = last[(last.home_team == home) & (last.away_team == away) & (last.market == r.market) & (last.side == r.side)]
    close_line = c.point.iloc[0] if len(c) else np.nan
    close_price = c.price.iloc[0] if len(c) else np.nan
    res, tot = g.loc[r.game_id, 'result'], g.loc[r.game_id, 'total']
    bet_line = r.best_line if r.best_line == r.best_line else r.open_line
    if r.market == 'spread':
        margin = res if r.side == home else -res
        clv = close_line - bet_line if close_line == close_line else np.nan  # more points for us at the close = we beat it
        clv = -clv  # our number is better when the close gives fewer points than we got
        outcome = np.nan if res != res else (margin + bet_line)
    elif r.market == 'total':
        clv = (close_line - bet_line) if r.side == 'Over' else (bet_line - close_line)
        outcome = np.nan if tot != tot else ((tot - bet_line) if r.side == 'Over' else (bet_line - tot))
    else:
        clv = (american_to_decimal(r.best_price) - american_to_decimal(close_price)) if close_price == close_price else np.nan
        clv = float(clv) if clv == clv else np.nan
        outcome = np.nan if res != res else ((res if r.side == home else -res))
    won = np.nan if outcome != outcome else (1.0 if outcome > 0 else 0.5 if outcome == 0 else 0.0)
    units = np.nan if won != won else (float(american_to_decimal(r.best_price)) - 1 if won == 1 else 0.0 if won == 0.5 else -1.0)
    rows.append(dict(season=r.season, week=r.week, game=r.game, market=r.market, side=r.side, category=r.category,
                     bet_line=bet_line, bet_price=r.best_price, close_line=close_line, clv=clv, result=won, units=units))
D = pd.DataFrame(rows)
D.to_csv(os.path.join(ROOT, 'odds_log', 'graded_picks.csv'), index=False)

def summ(d):
    done = d[d.result.notna()]
    sp = d[d.market != 'moneyline']
    return {'picks': len(d), 'graded': len(done), 'won': int((done.result == 1).sum()), 'lost': int((done.result == 0).sum()),
            'units': round(done.units.sum(), 2),
            'avg_clv_pts': round(sp.clv.mean(), 2) if sp.clv.notna().any() else None,
            'beat_close_pct': round((sp.clv > 0).mean() * 100, 1) if sp.clv.notna().any() else None}

lines = ['# Opening-line tracking', '', 'Picks logged from the early-week opener, graded against the last line before kickoff and the final score.',
         'CLV (closing line value) is in points for spreads and totals: positive means the line moved toward our pick after we bet.', '',
         '| Week | Picks | Won–Lost | Units | Avg CLV (pts) | Beat the close |', '|---|---|---|---|---|---|']
for (s, w), d in D.groupby(['season', 'week']):
    x = summ(d); lines.append(f"| {s} wk {w} | {x['picks']} | {x['won']}–{x['lost']} | {x['units']:+.2f} | {x['avg_clv_pts']} | {x['beat_close_pct']}% |")
x = summ(D); lines.append(f"| **All** | {x['picks']} | {x['won']}–{x['lost']} | {x['units']:+.2f} | {x['avg_clv_pts']} | {x['beat_close_pct']}% |")
for cat in ['Optimal', 'Secure', 'Watch']:
    y = summ(D[D.category == cat]); lines.append(f"| {cat} | {y['picks']} | {y['won']}–{y['lost']} | {y['units']:+.2f} | {y['avg_clv_pts']} | {y['beat_close_pct']}% |")
open(os.path.join(ROOT, 'odds_log', 'clv_report.md'), 'w').write('\n'.join(lines) + '\n')
print('\n'.join(lines))
