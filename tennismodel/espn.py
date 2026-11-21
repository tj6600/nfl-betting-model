"""ESPN's public tennis feeds (site.api.espn.com, no key, no Odds API credits): ATP and WTA singles results and schedules.

ESPN's tennis scoreboard (…/tennis/{atp,wta}/scoreboard?dates=YYYYMMDD) returns every tournament running that day with all
of its matches (main draw and qualifying). It has no odds; live DraftKings prices come from the Odds API (tennismodel/odds.py).

- history(tours, start, end): every singles match from start to end -> tennis_data/matches_<tour>.csv.gz (cached, incremental)
- schedule(tour, day): matches still to play (both players known) for the tournaments running on that day

  python -m tennismodel.espn update            # refresh both tours' results through today (free)
"""
import os, sys, json, time, urllib.request, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
BASE = 'https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard?dates={d}'
DATA = os.path.join(ROOT, 'tennis_data')
TOURS = ('atp', 'wta')
FIRST = dt.date(2021, 1, 1)
COLS = ['tour', 'mid', 'event_id', 'event', 'major', 'round', 'start', 'status', 'p1', 'p1_name', 'p2', 'p2_name', 'winner',
        'sets1', 'sets2', 'games1', 'games2', 'court']

# ESPN gives no surface, so it comes from the tournament name (anything not listed is hard court; the indoor/outdoor split is ignored)
CLAY = ['roland garros', 'french open', 'monte', 'madrid', 'rome', 'internazionali', 'italian', 'barcelona', 'hamburg', 'estoril',
        'munich', 'bmw open', 'geneva', 'lyon', 'houston', 'clay', 'marrakech', 'hassan', 'grand prix son altesse', 'lalla meryem',
        'bastad', 'nordea', 'gstaad', 'swiss open', 'kitzbuhel', 'kitzbühel', 'umag', 'croatia', 'bucharest', 'tiriac', 'buenos aires',
        'argentina open', 'rio open', 'chile', 'santiago', 'cordoba', 'córdoba', 'charleston', 'credit one', 'bogota', 'bogotá',
        'rabat', 'strasbourg', 'parma', 'palermo', 'prague', 'livesport', 'budapest', 'hungarian', 'iasi', 'iași',
        'lausanne', 'warsaw', 'polish open', 'portoroz', 'båstad', 'oeiras', 'saint-malo', 'rouen',
        'catalonia', 'catalunya', 'gonet', 'banja luka', 'srpska', 'cagliari', 'sardegna',
        'grand prix hassan']
# Stuttgart/Berlin/Bad Homburg/Mallorca/Belgrade/Antalya change surface by tour or month: handled in surface()
GRASS = ['wimbledon', 'queen', 'halle', 'terra wortmann', 'hertogenbosch', 'libema', 'eastbourne', 'rothesay', 'mallorca',
         'birmingham', 'nottingham', 'berlin', 'bad homburg', 'newport', 'hall of fame', 'infosys', 'stuttgart', 'boss open']


def surface(event, tour, start):
    """'Clay', 'Grass' or 'Hard' for a tournament name (+ month for the names that change surface)."""
    n = (event or '').lower()
    m = pd.Timestamp(start).month if start else 0
    if 'stuttgart' in n or 'porsche' in n or 'boss open' in n:
        return 'Clay' if (tour == 'wta' or m in (4, 5)) else 'Grass'
    if 'bad homburg' in n or 'berlin' in n or 'mallorca' in n:
        return 'Grass'
    if 'belgrade' in n or 'antalya' in n:
        return 'Clay' if m in (4, 5) else 'Hard'
    if any(k in n for k in GRASS) and m in (6, 7):
        return 'Grass'
    if any(k in n for k in CLAY):
        return 'Clay'
    return 'Hard'


def _get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            if i == tries - 1: raise
            time.sleep(1 + i)


def _ath(c):
    a = c.get('athlete') or {}
    return str(c.get('id') or a.get('id') or ''), a.get('displayName') or ''


def parse(js, tour):
    """Singles matches (rows of COLS) from one scoreboard response; doubles and TBD slots are skipped."""
    out = []
    for e in js.get('events') or []:
        for g in e.get('groupings') or []:
            gname = (g.get('grouping') or {}).get('displayName') or ''
            if 'Singles' not in gname: continue
            t = 'wta' if 'Women' in gname else 'atp' if 'Men' in gname else tour   # the majors list both draws under each tour
            if t != tour: continue
            for c in g.get('competitions') or []:
                cs = c.get('competitors') or []
                if len(cs) != 2 or any(x.get('type') != 'athlete' for x in cs): continue
                cs = sorted(cs, key=lambda x: x.get('order', 0))
                (i1, n1), (i2, n2) = _ath(cs[0]), _ath(cs[1])
                if not i1 or not i2 or not n1 or not n2 or 'TBD' in (n1, n2): continue
                st = (c.get('status') or {}).get('type') or {}
                l1 = [x.get('value') for x in cs[0].get('linescores') or []]
                l2 = [x.get('value') for x in cs[1].get('linescores') or []]
                w1 = [bool(x.get('winner')) for x in cs[0].get('linescores') or []]
                w2 = [bool(x.get('winner')) for x in cs[1].get('linescores') or []]
                win = 1 if cs[0].get('winner') else 2 if cs[1].get('winner') else 0
                out.append(dict(tour=tour, mid=str(c['id']), event_id=str(e.get('id')), event=e.get('name') or e.get('shortName') or '',
                                major=bool(e.get('major')), round=(c.get('round') or {}).get('displayName') or '',
                                start=c.get('date') or c.get('startDate'), status=st.get('name') or '',
                                p1=i1, p1_name=n1, p2=i2, p2_name=n2, winner=win, sets1=sum(w1), sets2=sum(w2),
                                games1=int(sum(v or 0 for v in l1)), games2=int(sum(v or 0 for v in l2)),
                                court=(c.get('venue') or {}).get('court') or ''))
    return out


def day(tour, d):
    return parse(_get(BASE.format(tour=tour, d=d.strftime('%Y%m%d'))), tour)


def _path(tour): return os.path.join(DATA, f'matches_{tour}.csv.gz')


def load(tour=None):
    fs = [_path(t) for t in ([tour] if tour else TOURS)]
    df = pd.concat([pd.read_csv(f, dtype={'mid': str, 'event_id': str, 'p1': str, 'p2': str}) for f in fs if os.path.exists(f)], ignore_index=True)
    df['ts'] = pd.to_datetime(df.start, utc=True)
    df['surface'] = [surface(e, t, s) for e, t, s in zip(df.event, df.tour, df.start)]
    return df.sort_values('ts').reset_index(drop=True)


def history(tours=TOURS, start=None, end=None, step=3):
    """Fetch every `step` days from start (default: 10 days before the last saved match, or FIRST) to end (default today).
    Tournaments run 6+ days and each response holds whole tournaments, so a 3-day step catches every match."""
    os.makedirs(DATA, exist_ok=True)
    end = end or dt.date.today()
    for tour in tours:
        old = pd.read_csv(_path(tour), dtype={'mid': str, 'event_id': str, 'p1': str, 'p2': str}) if os.path.exists(_path(tour)) else pd.DataFrame(columns=COLS)
        s = start or (pd.to_datetime(old.start, utc=True).max().date() - dt.timedelta(days=10) if len(old) else FIRST)
        days = [s + dt.timedelta(days=i) for i in range(0, (end - s).days + 1, step)] + [end]
        rows = []
        with ThreadPoolExecutor(8) as ex:
            for r in ex.map(lambda d: _safe(tour, d), days): rows += r
        new = pd.DataFrame(rows, columns=COLS)
        df = pd.concat([old[[c for c in COLS if c in old.columns]], new], ignore_index=True).drop_duplicates('mid', keep='last')
        df = df[df.status.isin(['STATUS_FINAL', 'STATUS_RETIRED', 'STATUS_WALKOVER', 'STATUS_FORFEIT']) | df.status.str.contains('FINAL|RETIRED|WALKOVER', na=False)]
        df.sort_values(['start', 'mid']).to_csv(_path(tour), index=False)
        print(f'{tour}: {len(df)} finished singles matches ({len(new)} fetched rows from {len(days)} days)')


def _safe(tour, d):
    try: return day(tour, d)
    except Exception as e:
        print('ESPN', tour, d, 'failed:', e); return []


def schedule(tour, d=None):
    """Matches not yet started with both players known, from the tournaments running on day d (default today)."""
    d = d or dt.date.today()
    rows = day(tour, d) + day(tour, d + dt.timedelta(days=1))
    df = pd.DataFrame(rows, columns=COLS).drop_duplicates('mid')
    return df[df.status == 'STATUS_SCHEDULED'].reset_index(drop=True)


if __name__ == '__main__':
    if sys.argv[1:2] == ['update']:
        history()
    elif sys.argv[1:2] == ['statuses']:
        print(load().status.value_counts())
