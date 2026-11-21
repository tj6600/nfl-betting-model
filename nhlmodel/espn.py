"""ESPN's public NHL feeds (site.api.espn.com, no key, no Odds API credits).

- scoreboard(day): schedule, probable starting goalies, and DraftKings moneyline / puck line / total (open and current).
- history(start, end): DraftKings closing lines for finished games, from each game's summary "pickcenter".

  python -m nhlmodel.espn history 2025-10-07 2026-04-16   # writes odds_log/nhl/espn_lines.csv (free)
"""
import os, sys, json, datetime as dt, urllib.request
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

ROOT = os.path.join(os.path.dirname(__file__), '..')
BASE = 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl'
FIX = {'NJ': 'NJD', 'TB': 'TBL', 'LA': 'LAK', 'SJ': 'SJS', 'UTAH': 'UTA', 'WAS': 'WSH', 'MON': 'MTL', 'LV': 'VGK'}
OUT = os.path.join(ROOT, 'odds_log', 'nhl', 'espn_lines.csv')


def _get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def ab(x):
    return FIX.get(x, x)


def _num(s):
    if s in (None, '', 'EVEN', 'OFF'):
        return 100 if s == 'EVEN' else None
    s = str(s).lstrip('ou')
    try:
        return float(s)
    except ValueError:
        return None


def _odds_block(o, when='close'):
    """Flatten an ESPN DraftKings odds block (scoreboard or pickcenter) to one dict."""
    if not o:
        return {}
    r = {'book': (o.get('provider') or {}).get('name')}
    ml, ps, tt = o.get('moneyline') or {}, o.get('pointSpread') or {}, o.get('total') or {}
    g = lambda d, side, k: _num(((d.get(side) or {}).get(when) or {}).get(k))
    r.update(ml_home=g(ml, 'home', 'odds'), ml_away=g(ml, 'away', 'odds'),
             pl_home_pt=g(ps, 'home', 'line'), pl_home=g(ps, 'home', 'odds'), pl_away=g(ps, 'away', 'odds'),
             total=g(tt, 'over', 'line'), over=g(tt, 'over', 'odds'), under=g(tt, 'under', 'odds'))
    if r['total'] is None:
        r['total'] = o.get('overUnder')
    return r


def scoreboard(day):
    d = _get(f"{BASE}/scoreboard?dates={day.strftime('%Y%m%d')}")
    rows = []
    for e in d.get('events', []):
        c = e['competitions'][0]
        side = {t['homeAway']: t for t in c['competitors']}
        h, a = side['home'], side['away']
        gk = lambda t: next((p['athlete']['displayName'] for p in t.get('probables', []) if p.get('name') == 'probableStartingGoalie'), None)
        row = dict(espn_id=e['id'], start=e['date'], home=ab(h['team']['abbreviation']), away=ab(a['team']['abbreviation']),
                   status=c['status']['type']['name'], gk_home=gk(h), gk_away=gk(a))
        o = next((x for x in (c.get('odds') or []) if (x.get('provider') or {}).get('name') == 'DraftKings'), None)
        row.update({k: v for k, v in _odds_block(o, 'close').items() if k != 'book'})
        op = _odds_block(o, 'open')
        row.update({f'open_{k}': v for k, v in op.items() if k != 'book'})
        rows.append(row)
    cols = ['ml_home', 'ml_away', 'pl_home_pt', 'pl_home', 'pl_away', 'total', 'over', 'under']
    return pd.DataFrame(rows).reindex(columns=list(pd.DataFrame(rows).columns) + [c for c in cols if c not in (rows[0] if rows else {})])


def _summary_lines(eid):
    try:
        d = _get(f'{BASE}/summary?event={eid}')
    except Exception:
        return None
    pc = next((p for p in d.get('pickcenter') or [] if (p.get('provider') or {}).get('name') == 'DraftKings'), None)
    if not pc:
        return None
    r = _odds_block(pc, 'close')
    r['espn_id'] = eid
    hto, ato = pc.get('homeTeamOdds') or {}, pc.get('awayTeamOdds') or {}
    r['ml_home'] = r['ml_home'] if r.get('ml_home') is not None else hto.get('moneyLine')
    r['ml_away'] = r['ml_away'] if r.get('ml_away') is not None else ato.get('moneyLine')
    return r


def history(start, end, workers=8):
    days, d = [], start
    while d <= end:
        days.append(d); d += dt.timedelta(days=1)
    with ThreadPoolExecutor(workers) as ex:
        boards = list(ex.map(lambda x: (x, _get(f"{BASE}/scoreboard?dates={x.strftime('%Y%m%d')}")), days))
    games = []
    for day, b in boards:
        for e in b.get('events', []):
            c = e['competitions'][0]
            if c['status']['type']['name'] != 'STATUS_FINAL' or (e.get('season') or {}).get('type') not in (2, None):
                continue
            side = {t['homeAway']: t for t in c['competitors']}
            games.append(dict(espn_id=e['id'], game_date=str(day), home=ab(side['home']['team']['abbreviation']),
                              away=ab(side['away']['team']['abbreviation'])))
    g = pd.DataFrame(games)
    with ThreadPoolExecutor(workers) as ex:
        lines = [x for x in ex.map(_summary_lines, g.espn_id) if x] if len(g) else []
    if not lines:
        print('no DraftKings lines found (ESPN has them from 2025-26 on)'); return pd.DataFrame()
    out = g.merge(pd.DataFrame(lines), on='espn_id', how='inner')
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    old = pd.read_csv(OUT, dtype={'espn_id': str}) if os.path.exists(OUT) else pd.DataFrame()
    out = pd.concat([old, out]).drop_duplicates('espn_id', keep='last')
    out.to_csv(OUT, index=False)
    print(f'{len(out)} games with DraftKings closing lines -> {OUT}')
    return out


if __name__ == '__main__':
    D = dt.date.fromisoformat
    if sys.argv[1] == 'history':
        history(D(sys.argv[2]), D(sys.argv[3]))
    elif sys.argv[1] == 'scoreboard':
        print(scoreboard(D(sys.argv[2]) if len(sys.argv) > 2 else dt.date.today()).to_string())
