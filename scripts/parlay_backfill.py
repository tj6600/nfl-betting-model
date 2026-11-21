"""Rebuild suggested-parlay logs for days logged before parlays were saved, from each day's earliest pick log.

Uses the same pool rules as the boards (scripts/nba_board.py, scripts/nhl_board.py) and parlays.suggest().
python scripts/parlay_backfill.py      # writes odds_log/{nba,nhl}/parlays/<day>_<stamp>.json where missing
"""
import os, sys, glob, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import pandas as pd
import parlays as PZ

ROOT = os.path.join(os.path.dirname(__file__), '..')
RULES = {
    'nba': (lambda L: L['edge'] >= 1 and L['p'] >= 0.55 and not L['flags'], ()),
    'nhl': (lambda L: (L['edge'] >= 1 or L.get('pick')) and L['p'] >= 0.55 and L['price'] >= -200 and not L['flags'], {'Saves'}),
}
for sport, (likely, no_sgp) in RULES.items():
    d = os.path.join(ROOT, 'odds_log', sport)
    first = {}
    for f in sorted(glob.glob(os.path.join(d, 'picks', '*.csv'))):
        first.setdefault(os.path.basename(f)[:10], f)
    for day, f in first.items():
        if glob.glob(os.path.join(d, 'parlays', f'{day}_*.json')):
            continue
        L = pd.read_csv(f)
        legs = []
        for r in L.to_dict('records'):
            pid = r.get('pid')
            legs.append(dict(id=r['id'], game=r['game'], kind=r['kind'], label=r['label'], price=int(r['price']), p=float(r['p']), edge=float(r['edge']),
                             pid=None if pid != pid else pid, flags=['flagged'] if r.get('flagged') else [], pick=bool(r.get('pick', False)),
                             cat=r['cat'] if isinstance(r.get('cat'), str) else ''))
        pool = sorted([l for l in legs if l['cat'] == 'Value'], key=lambda l: -l['edge'])
        pool += sorted([l for l in legs if l['cat'] != 'Value' and not l['flags'] and l['edge'] >= 1.5 and l['p'] >= 0.52], key=lambda l: -l['edge'])
        stamp = os.path.basename(f)[11:-4]
        print(sport, day, PZ.log(d, day, stamp, legs, [l['id'] for l in pool], likely, no_sgp))
