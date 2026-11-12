"""NHL odds from The Odds API (sport key icehockey_nhl), DraftKings only. Needs ODDS_API_KEY.

  python -m nhlmodel.odds games                  # moneyline, puck line, totals for upcoming games: 3 credits
  python -m nhlmodel.odds props [YYYY-MM-DD]     # shots on goal + goalie saves for one slate: 2 credits per game
  python -m nhlmodel.odds history-games 2025-10-21 2026-04-16   # one 5 PM ET snapshot per day: 20 credits/day
  python -m nhlmodel.odds history-props 2026-01-14 [...]        # per game, 90 min before puck drop: 20 credits/game

Snapshots go to odds_log/nhl/. Historical pulls skip files that already exist, so they can be resumed.
"""
import os, sys, json, glob, datetime as dt, urllib.request, urllib.parse
import pandas as pd

BASE = 'https://api.the-odds-api.com/v4'
SPORT = 'icehockey_nhl'
ROOT = os.path.join(os.path.dirname(__file__), '..')
DIR = os.path.join(ROOT, 'odds_log', 'nhl')
HIST = os.path.join(DIR, 'history')
ET = dt.timezone(dt.timedelta(hours=-5))
PROP_MARKETS = {'player_shots_on_goal': 'sog', 'player_total_saves': 'saves'}

NAMES = {
    'Anaheim Ducks': 'ANA', 'Arizona Coyotes': 'ARI', 'Boston Bruins': 'BOS', 'Buffalo Sabres': 'BUF',
    'Calgary Flames': 'CGY', 'Carolina Hurricanes': 'CAR', 'Chicago Blackhawks': 'CHI', 'Colorado Avalanche': 'COL',
    'Columbus Blue Jackets': 'CBJ', 'Dallas Stars': 'DAL', 'Detroit Red Wings': 'DET', 'Edmonton Oilers': 'EDM',
    'Florida Panthers': 'FLA', 'Los Angeles Kings': 'LAK', 'Minnesota Wild': 'MIN', 'Montréal Canadiens': 'MTL',
    'Montreal Canadiens': 'MTL', 'Nashville Predators': 'NSH', 'New Jersey Devils': 'NJD', 'New York Islanders': 'NYI',
    'New York Rangers': 'NYR', 'Ottawa Senators': 'OTT', 'Philadelphia Flyers': 'PHI', 'Pittsburgh Penguins': 'PIT',
    'San Jose Sharks': 'SJS', 'Seattle Kraken': 'SEA', 'St Louis Blues': 'STL', 'St. Louis Blues': 'STL',
    'Tampa Bay Lightning': 'TBL', 'Toronto Maple Leafs': 'TOR', 'Utah Hockey Club': 'UTA', 'Utah Mammoth': 'UTA',
    'Vancouver Canucks': 'VAN', 'Vegas Golden Knights': 'VGK', 'Washington Capitals': 'WSH', 'Winnipeg Jets': 'WPG',
}


def _call(path, **q):
    key = os.environ.get('ODDS_API_KEY')
    if not key:
        raise SystemExit('ODDS_API_KEY is not set.')
    q = urllib.parse.urlencode({'apiKey': key, 'regions': 'us', 'bookmakers': 'draftkings', 'oddsFormat': 'american',
                                'dateFormat': 'iso', **q})
    with urllib.request.urlopen(f'{BASE}/{path}?{q}', timeout=60) as r:
        return json.loads(r.read()), r.headers.get('x-requests-remaining')


def _stamp():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H%MZ')


def _save(obj, f):
    os.makedirs(os.path.dirname(f), exist_ok=True)
    json.dump(obj, open(f, 'w'))


# ---------- live ----------
def games():
    ev, left = _call(f'sports/{SPORT}/odds', markets='h2h,spreads,totals')
    f = os.path.join(DIR, f'games_{_stamp()}.json'); _save(ev, f)
    print(f'{len(ev)} games saved to {f}; {left} credits left')
    return ev


def slate_events(day):
    ev, _ = _call(f'sports/{SPORT}/events')   # free
    return [e for e in ev if pd.Timestamp(e['commence_time']).tz_convert('America/New_York').date() == day]


def props(day=None):
    day = day or dt.datetime.now(ET).date()
    out, left = [], None
    for e in slate_events(day):
        d, left = _call(f"sports/{SPORT}/events/{e['id']}/odds", markets=','.join(PROP_MARKETS))
        out.append(d)
    f = os.path.join(DIR, f'props_{day}_{_stamp()}.json'); _save(out, f)
    print(f'{len(out)} games of props saved to {f}; {left} credits left')
    return out


def latest(kind, day=None):
    pat = 'games_*.json' if kind == 'games' else f'props_{day}_*.json' if day else 'props_*.json'
    fs = sorted(glob.glob(os.path.join(DIR, pat)))
    return fs[-1] if fs else None


# ---------- historical ----------
def history_games(start, end):
    """One snapshot per day at 22:00 UTC (5 PM ET): moneyline + puck line at DraftKings."""
    d, left = start, None
    while d <= end:
        f = os.path.join(HIST, 'games', f'{d}.json')
        if not os.path.exists(f):
            try:
                r, left = _call(f'historical/sports/{SPORT}/odds', markets='h2h,spreads', date=f'{d}T22:00:00Z')
                _save(r, f)
            except Exception as e:
                print(d, 'failed', e)
        d += dt.timedelta(days=1)
    print('games history done;', left, 'credits left')


def history_props(days, markets=None, budget=None):
    """For each game on each day: shots on goal + saves at DraftKings, 90 minutes before puck drop.
    markets: comma list (default both). budget: stop before spending more than this many credits."""
    left, start = None, None
    mk = markets or ','.join(PROP_MARKETS)
    per_game = 10 * len(mk.split(','))
    for d in days:
        evf = os.path.join(HIST, 'events', f'{d}.json')
        if os.path.exists(evf):
            evs = json.load(open(evf))
        else:
            r, left = _call(f'historical/sports/{SPORT}/events', date=f'{d}T16:00:00Z')
            start = start if start is not None else int(left) + 1
            evs = [e for e in r['data'] if pd.Timestamp(e['commence_time']).tz_convert('America/New_York').date() == d]
            _save(evs, evf)
        for e in evs:
            f = os.path.join(HIST, 'props', f"{d}_{e['id']}.json")
            if os.path.exists(f):
                continue
            if budget is not None and left is not None and start is not None and (start - int(left)) + per_game > budget:
                print('budget reached; stopping'); return
            t = (pd.Timestamp(e['commence_time']) - pd.Timedelta(minutes=90)).strftime('%Y-%m-%dT%H:%M:%SZ')
            try:
                r, left = _call(f"historical/sports/{SPORT}/events/{e['id']}/odds", markets=mk, date=t)
                _save(r, f)
            except Exception as ex:
                print(d, e['id'], 'failed', ex)
        print(d, len(evs), 'games;', left, 'credits left', flush=True)


# ---------- parsing ----------
def game_rows(events):
    rows = []
    for e in events:
        h, a = NAMES.get(e['home_team']), NAMES.get(e['away_team'])
        for b in e.get('bookmakers', []):
            for m in b['markets']:
                for o in m['outcomes']:
                    rows.append(dict(event=e['id'], start=e['commence_time'], home=h, away=a, book=b['key'],
                                     market=m['key'], side=NAMES.get(o['name'], o['name']), point=o.get('point'), price=o['price']))
    return pd.DataFrame(rows)


def prop_rows(events):
    rows = []
    for e in events:
        h, a = NAMES.get(e['home_team']), NAMES.get(e['away_team'])
        for b in e.get('bookmakers', []):
            for m in b['markets']:
                if m['key'] not in PROP_MARKETS:
                    continue
                for o in m['outcomes']:
                    if o.get('description') and o.get('point') is not None:
                        rows.append(dict(event=e['id'], start=e['commence_time'], home=h, away=a, book=b['key'],
                                         stat=PROP_MARKETS[m['key']], player=o['description'], side=o['name'],
                                         point=o['point'], price=o['price']))
    return pd.DataFrame(rows)


def history_game_rows():
    out = []
    for f in sorted(glob.glob(os.path.join(HIST, 'games', '*.json'))):
        r = json.load(open(f))
        snap = pd.Timestamp(r['timestamp'])
        ev = [e for e in r['data'] if pd.Timestamp(e['commence_time']) > snap]
        df = game_rows(ev)
        if len(df):
            df['snap'] = r['timestamp']; out.append(df)
    if not out:
        return pd.DataFrame()
    # each snapshot also lists the next day's games; keep the snapshot closest to puck drop
    df = pd.concat(out, ignore_index=True).sort_values('snap')
    return df.drop_duplicates(['event', 'market', 'side'], keep='last').reset_index(drop=True)


def history_prop_rows():
    out = []
    for f in sorted(glob.glob(os.path.join(HIST, 'props', '*.json'))):
        r = json.load(open(f))
        df = prop_rows([r['data']])
        if len(df):
            df['snap'] = r['timestamp']; out.append(df)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'games'
    D = dt.date.fromisoformat
    if cmd == 'games':
        games()
    elif cmd == 'props':
        props(D(sys.argv[2]) if len(sys.argv) > 2 else None)
    elif cmd == 'history-games':
        history_games(D(sys.argv[2]), D(sys.argv[3]))
    elif cmd == 'history-props':
        # optional flags: --markets=player_shots_on_goal --budget=500
        fl = dict(a[2:].split('=', 1) for a in sys.argv[2:] if a.startswith('--'))
        history_props([D(x) for x in sys.argv[2:] if not x.startswith('--')], fl.get('markets'),
                      int(fl['budget']) if 'budget' in fl else None)
