"""Re-run this week's picks under 8 model settings; a pick whose edge shrinks or flips is fragile."""
import sys, os, runpy, io, contextlib
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..')); os.chdir(os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
with contextlib.redirect_stdout(io.StringIO()):
    g = runpy.run_path('scripts/weekly_picks.py')
import nflmodel.predict as P
df, train, target, op, L = g['df'], g['train'], g['target'], g['op'], g['L']
picks = L[L.category.isin(['Optimal', 'Watch'])]
base_r = P._ridge
def run(mask, alpha=1.0, mx=P.BASE_MARGIN_X, tx=P.BASE_TOTAL_X):
    P._ridge = lambda X, y, a=1.0: base_r(X, y, alpha if a == 1.0 else a)
    p = P.fit_predict(df, mask & df.result.notna(), df.game_id.isin(target.game_id), False, mx, tx)
    P._ridge = base_r
    return p.merge(op, on='game_id')
variants = {
    'base (2019+)': run(train),
    'train 2022+': run(train & (df.season >= 2022)),
    'train 2024+': run(train & (df.season >= 2024)),
    'ridge 0.2': run(train, 0.2),
    'ridge 10': run(train, 10.0),
    'no QB': run(train, mx=[c for c in P.BASE_MARGIN_X if c != 'd_qb'], tx=[c for c in P.BASE_TOTAL_X if c != 's_qb']),
    'no points rating': run(train, mx=[c for c in P.BASE_MARGIN_X if c != 'pts_margin'], tx=[c for c in P.BASE_TOTAL_X if c != 'pts_total']),
    'drop 2020 (covid)': run(train & (df.season != 2020)),
}
out = []
for r in picks.itertuples():
    row = {'game': r.game, 'pick': f'{r.side} {r.open_line:+g}' if r.market == 'spread' else f'{r.side} {r.open_line:g}', 'category': r.category}
    edges = []
    for name, p in variants.items():
        x = p[p.game_id == r.game_id].iloc[0]
        if r.market == 'spread':
            sign = 1 if r.side == x.home_team else -1
            e = sign * (x.pred_margin - x.open_spread)
        else:
            sign = 1 if r.side == 'Over' else -1
            e = sign * (x.pred_total - x.open_total)
        row[name] = round(e, 1); edges.append(e)
    row['same side'] = f'{sum(e > 0 for e in edges)}/{len(edges)}'
    row['edge 2+'] = f'{sum(e >= 2 for e in edges)}/{len(edges)}'
    row['min edge'] = round(min(edges), 1)
    out.append(row)
S = pd.DataFrame(out); pd.set_option('display.width', 300)
print(S.to_string(index=False))
S.to_csv('odds_log/stability.csv', index=False)
