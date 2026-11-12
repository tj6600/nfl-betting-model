"""One-off: build nba_data/ from hoopR parquet (needs pyarrow) plus ESPN pick-center lines.

python scripts/nba_build_history.py [first_season]   # ESPN season labels, default 2022 (= 2021-22)
"""
import sys, os, json, concurrent.futures as cf; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np, pandas as pd
from nbamodel import data as D

first = int(sys.argv[1]) if len(sys.argv) > 1 else 2022
Gs, Ps = [], []
for s in range(first, D.SEASON + 1):
    g, p = D.history_from_parquet(s); Gs.append(g); Ps.append(p); print(s, len(g), 'games', len(p), 'player rows')
G, P = pd.concat(Gs, ignore_index=True), pd.concat(Ps, ignore_index=True)

# pick-center lines (totals and moneylines; DraftKings in 2025-26 on, ESPN consensus before)
cache = os.environ.get('NBA_PICK_CACHE')   # optional folder of <game_id>.json pick-center dumps
def pick(i):
    try:
        if cache and os.path.exists(os.path.join(cache, f'{i}.json')):
            pc = json.load(open(os.path.join(cache, f'{i}.json')))
        else:
            pc = json.loads(D._get(D.RAW.format(i))).get('pickcenter')
        return D._pick(pc, None)
    except Exception:
        return {}
with cf.ThreadPoolExecutor(16) as ex:
    picks = list(ex.map(pick, G.game_id))
pk = pd.DataFrame(picks, index=G.index)
for c in ['spread', 'total', 'ml_home', 'ml_away', 'provider']:
    if c in pk:
        G[c] = pk[c].where(pk[c].notna(), G[c])
print('lines:', G.groupby('season')[['spread', 'total', 'ml_home']].apply(lambda x: x.notna().mean()).round(2))
D.save(G, P, D.schedule_from_parquet())
