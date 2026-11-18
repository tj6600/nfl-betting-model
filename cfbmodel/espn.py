"""ESPN's public college football feeds (site.api.espn.com, no key, no Odds API credits).

- season(year): every FBS game of a season (weeks 1-16 + bowls), with final scores -> cfb_data/games_<year>.csv
- lines(year): DraftKings opening and closing spread / total / moneyline for finished games, from each game's summary
  "pickcenter" (ESPN has them for 2026 games; 2025 games have none) -> odds_log/cfb/espn_lines.csv
- scoreboard(day or week): upcoming games with DraftKings lines and DraftKings betslip outcome ids.

  python -m cfbmodel.espn update [2025 2026]      # refresh games + lines (free)
"""
import os, re, sys, json, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
BASE = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football'
DATA = os.path.join(ROOT, 'cfb_data')
LINES = os.path.join(ROOT, 'odds_log', 'cfb', 'espn_lines.csv')
CURRENT = 2026
LINE_COLS = ['sp_home', 'sp_home_px', 'sp_away_px', 'total', 'over', 'under', 'ml_home', 'ml_away']


def _get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            if i == tries - 1: raise
            time.sleep(1 + i)


def _num(s):
    if s in (None, '', 'OFF'): return None
    if s == 'EVEN': return 100.0
    try: return float(str(s).lstrip('ou'))
    except ValueError: return None


def _sid(link):
    """DraftKings outcome id from ESPN's betslip deep link (…outcomes%3D0ML87191401_1)."""
    h = (link or {}).get('href') or ''
    m = re.search(r'outcomes(?:=|%3D)([^&%]+)', h)
    return urllib.parse.unquote(m.group(1)) if m else None


def odds_block(o, when='close'):
    """Flatten a DraftKings odds block (scoreboard odds or summary pickcenter) to one dict for one side of time."""
    if not o: return {}
    ml, ps, tt = o.get('moneyline') or {}, o.get('pointSpread') or {}, o.get('total') or {}
    g = lambda d, side, k: _num(((d.get(side) or {}).get(when) or {}).get(k))
    r = dict(sp_home=g(ps, 'home', 'line'), sp_home_px=g(ps, 'home', 'odds'), sp_away_px=g(ps, 'away', 'odds'),
             total=g(tt, 'over', 'line'), over=g(tt, 'over', 'odds'), under=g(tt, 'under', 'odds'),
             ml_home=g(ml, 'home', 'odds'), ml_away=g(ml, 'away', 'odds'))
    if when == 'close':
        if r['total'] is None: r['total'] = _num(o.get('overUnder'))
        if r['ml_home'] is None: r['ml_home'] = _num((o.get('homeTeamOdds') or {}).get('moneyLine'))
        if r['ml_away'] is None: r['ml_away'] = _num((o.get('awayTeamOdds') or {}).get('moneyLine'))
        sk = lambda d, side: _sid(((d.get(side) or {}).get('close') or {}).get('link'))
        r.update(sid_ml_home=sk(ml, 'home'), sid_ml_away=sk(ml, 'away'), sid_sp_home=sk(ps, 'home'), sid_sp_away=sk(ps, 'away'),
                 sid_over=sk(tt, 'over'), sid_under=sk(tt, 'under'))
    return r


def _event_row(e):
    c = e['competitions'][0]
    side = {t['homeAway']: t for t in c['competitors']}
    h, a = side['home'], side['away']
    rank = lambda t: (t.get('curatedRank') or {}).get('current') if (t.get('curatedRank') or {}).get('current', 99) <= 25 else None
    st = c['status']['type']
    sc = lambda t: float(t['score']) if st.get('completed') and t.get('score') not in (None, '') else None
    notes = '; '.join(n.get('headline', '') for n in c.get('notes') or [])
    return dict(espn_id=e['id'], season=(e.get('season') or {}).get('year'), season_type=(e.get('season') or {}).get('type'),
                week=(e.get('week') or {}).get('number'), start=e['date'], status=st['name'],
                home_id=h['team']['id'], away_id=a['team']['id'], home=h['team'].get('abbreviation'), away=a['team'].get('abbreviation'),
                home_name=h['team'].get('shortDisplayName') or h['team'].get('location'), away_name=a['team'].get('shortDisplayName') or a['team'].get('location'),
                home_conf=h['team'].get('conferenceId'), away_conf=a['team'].get('conferenceId'),
                home_rank=rank(h), away_rank=rank(a), neutral=bool(c.get('neutralSite')), conf_game=bool(c.get('conferenceCompetition')),
                home_pts=sc(h), away_pts=sc(a), note=notes)


def _board(year, stype, week=None):
    q = f'groups=80&seasontype={stype}&dates={year}&limit=400' + (f'&week={week}' if week else '')
    return _get(f'{BASE}/scoreboard?{q}').get('events', [])


def season(year):
    jobs = [(2, w) for w in range(1, 17)] + [(3, None)]
    with ThreadPoolExecutor(8) as ex:
        evs = [e for es in ex.map(lambda j: _board(year, *j), jobs) for e in es]
    g = pd.DataFrame([_event_row(e) for e in evs]).drop_duplicates('espn_id')
    os.makedirs(DATA, exist_ok=True)
    g.sort_values('start').to_csv(os.path.join(DATA, f'games_{year}.csv'), index=False)
    print(f'{year}: {len(g)} games, {g.home_pts.notna().sum()} final -> cfb_data/games_{year}.csv')
    return g


def _summary_lines(eid):
    try: d = _get(f'{BASE}/summary?event={eid}')
    except Exception: return None
    pc = next((p for p in d.get('pickcenter') or [] if (p.get('provider') or {}).get('name') == 'DraftKings'), None)
    if not pc: return None
    r = {k: v for k, v in odds_block(pc, 'close').items() if not k.startswith('sid')}
    r.update({f'open_{k}': v for k, v in odds_block(pc, 'open').items()})
    r['espn_id'] = str(eid)
    return r


def lines(year):
    """DK closing (and opening) lines for finished games of a season that aren't saved yet."""
    g = load([year])
    old = pd.read_csv(LINES, dtype={'espn_id': str}) if os.path.exists(LINES) else pd.DataFrame(columns=['espn_id'])
    todo = [e for e in g[g.home_pts.notna()].espn_id if e not in set(old.espn_id)]
    with ThreadPoolExecutor(8) as ex:
        new = [x for x in ex.map(_summary_lines, todo) if x]
    out = pd.concat([old, pd.DataFrame(new)]).drop_duplicates('espn_id', keep='last') if new else old
    os.makedirs(os.path.dirname(LINES), exist_ok=True)
    out.to_csv(LINES, index=False)
    print(f'{year}: {len(new)} new games with DraftKings lines ({len(todo)} checked) -> {LINES}')
    return out


def load(years=None):
    fs = sorted(f for f in os.listdir(DATA) if f.startswith('games_')) if os.path.isdir(DATA) else []
    g = pd.concat([pd.read_csv(os.path.join(DATA, f), dtype={'espn_id': str, 'home_id': str, 'away_id': str, 'home_conf': str, 'away_conf': str})
                   for f in fs if years is None or int(f[6:10]) in years])
    return g.reset_index(drop=True)


def load_lines():
    return pd.read_csv(LINES, dtype={'espn_id': str}) if os.path.exists(LINES) else pd.DataFrame(columns=['espn_id'] + LINE_COLS)


def scoreboard(year=CURRENT, week=None, stype=2):
    """Upcoming games with DraftKings lines (current prices) and betslip ids."""
    rows = []
    for e in _board(year, stype, week):
        r = _event_row(e)
        c = e['competitions'][0]
        o = next((x for x in (c.get('odds') or []) if (x.get('provider') or {}).get('name') == 'DraftKings'), None)
        r.update(odds_block(o, 'close'))
        r.update({f'open_{k}': v for k, v in odds_block(o, 'open').items()})
        r['tv'] = ', '.join(b for x in c.get('broadcasts') or [] for b in x.get('names', []))
        rows.append(r)
    return pd.DataFrame(rows)


def current_week():
    """ESPN's current week number and season type from the default scoreboard."""
    d = _get(f'{BASE}/scoreboard?groups=80')
    return (d.get('week') or {}).get('number'), (d.get('season') or {}).get('type'), (d.get('season') or {}).get('year')


if __name__ == '__main__':
    if sys.argv[1] == 'update':
        ys = [int(y) for y in sys.argv[2:]] or [CURRENT]
        for y in ys:
            season(y)
        lines(CURRENT)
