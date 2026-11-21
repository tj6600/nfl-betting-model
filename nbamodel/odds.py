"""NBA odds from The Odds API (sport key basketball_nba). Needs ODDS_API_KEY.

  python -m nbamodel.odds games            # spreads, totals, moneylines for upcoming games: 3 credits
  python -m nbamodel.odds props [YYYY-MM-DD]  # player points/rebounds/assists/threes/P+R+A for one slate:
                                              # 5 credits per game (US books), so ~40-75 per slate
  python -m nbamodel.odds alt [YYYY-MM-DD]    # DraftKings alternate points/rebounds/assists/threes ("25+ points")
                                              # for the parlays: about 4 credits per game (fewer if DK posts fewer)

Snapshots go to odds_log/nba/games_<UTC>.json, odds_log/nba/props_<date>_<UTC>.json and odds_log/nba/alt_<date>_<UTC>.json.
"""
import os, sys, json, datetime as dt, urllib.request, urllib.parse
import pandas as pd
from nbamodel.data import NAMES
from nbamodel.props import MARKET

ALT_MARKET = {'player_points_alternate': 'pts', 'player_rebounds_alternate': 'reb', 'player_assists_alternate': 'ast',
              'player_threes_alternate': 'fg3m'}

BASE = 'https://api.the-odds-api.com/v4/sports/basketball_nba'
ROOT = os.path.join(os.path.dirname(__file__), '..')
DIR = os.path.join(ROOT, 'odds_log', 'nba')
ET = dt.timezone(dt.timedelta(hours=-5))


def _call(path, **q):
    key = os.environ.get('ODDS_API_KEY')
    if not key:
        raise SystemExit('ODDS_API_KEY is not set.')
    q = urllib.parse.urlencode({'apiKey': key, 'regions': 'us', 'oddsFormat': 'american', 'dateFormat': 'iso', 'includeLinks': 'true', 'includeSids': 'true', **q})
    with urllib.request.urlopen(f'{BASE}/{path}?{q}', timeout=60) as r:
        return json.loads(r.read()), r.headers.get('x-requests-remaining')


def _stamp():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H%MZ')


def games():
    ev, left = _call('odds', markets='h2h,spreads,totals')
    os.makedirs(DIR, exist_ok=True)
    f = os.path.join(DIR, f'games_{_stamp()}.json'); json.dump(ev, open(f, 'w'))
    print(f'{len(ev)} games saved to {f}; {left} credits left')
    return ev


def slate_events(day):
    ev, _ = _call('events')   # free
    return [e for e in ev if pd.Timestamp(e['commence_time']).tz_convert('America/New_York').date() == day]


def props(day=None, markets=None):
    day = day or dt.datetime.now(ET).date()
    mk = markets or ','.join(MARKET)
    out, left = [], None
    for e in slate_events(day):
        d, left = _call(f"events/{e['id']}/odds", markets=mk)
        out.append(d)
    os.makedirs(DIR, exist_ok=True)
    f = os.path.join(DIR, f'props_{day}_{_stamp()}.json'); json.dump(out, open(f, 'w'))
    print(f'{len(out)} games of props saved to {f}; {left} credits left')
    return out


def alt(day=None):
    """Alternate lines (Over only, "X+"), DraftKings only. Costs 1 credit per market DK posts, per game."""
    day = day or dt.datetime.now(ET).date()
    out, left = [], None
    for e in slate_events(day):
        d, left = _call(f"events/{e['id']}/odds", markets=','.join(ALT_MARKET), bookmakers='draftkings')
        out.append(d)
    os.makedirs(DIR, exist_ok=True)
    f = os.path.join(DIR, f'alt_{day}_{_stamp()}.json'); json.dump(out, open(f, 'w'))
    print(f'{len(out)} games of alternate lines saved to {f}; {left} credits left')
    return out


def latest(kind, day=None):
    import glob
    if kind == 'alt':
        fs = sorted(glob.glob(os.path.join(DIR, f'alt_{day}_*.json' if day else 'alt_*.json'))); return fs[-1] if fs else None
    pat = f'games_*.json' if kind == 'games' else f'props_{day}_*.json' if day else 'props_*.json'
    fs = sorted(glob.glob(os.path.join(DIR, pat)))
    return fs[-1] if fs else None


def game_rows(events):
    rows = []
    for e in events:
        h, a = NAMES.get(e['home_team']), NAMES.get(e['away_team'])
        for b in e.get('bookmakers', []):
            for m in b['markets']:
                for o in m['outcomes']:
                    rows.append(dict(event=e['id'], tip=e['commence_time'], home=h, away=a, book=b['title'], bkey=b['key'],
                                     market=m['key'], side=NAMES.get(o['name'], o['name']), point=o.get('point'), price=o['price'], link=o.get('link'), sid=o.get('sid')))
    return pd.DataFrame(rows)


def alt_rows(events):
    """DraftKings alternate lines: one row per player, stat and rung (Over only; "25+ points" = Over 24.5)."""
    rows = []
    for e in events:
        h, a = NAMES.get(e['home_team']), NAMES.get(e['away_team'])
        for b in e.get('bookmakers', []):
            if b['key'] != 'draftkings': continue
            for m in b['markets']:
                st = ALT_MARKET.get(m['key'])
                for o in m['outcomes'] if st else []:
                    if o.get('description') and o.get('point') is not None and o.get('name', 'Over') == 'Over':
                        rows.append(dict(event=e['id'], home=h, away=a, stat=st, player=o['description'], point=float(o['point']),
                                         price=o['price'], sid=o.get('sid')))
    return pd.DataFrame(rows, columns=['event', 'home', 'away', 'stat', 'player', 'point', 'price', 'sid'])


def prop_rows(events):
    rows = []
    for e in events:
        h, a = NAMES.get(e['home_team']), NAMES.get(e['away_team'])
        for b in e.get('bookmakers', []):
            for m in b['markets']:
                if m['key'] not in MARKET:
                    continue
                for o in m['outcomes']:
                    if o.get('description') and o.get('point') is not None:
                        rows.append(dict(event=e['id'], home=h, away=a, book=b['title'], bkey=b['key'], stat=MARKET[m['key']],
                                         player=o['description'], side=o['name'], point=o['point'], price=o['price'], link=o.get('link'), sid=o.get('sid')))
    return pd.DataFrame(rows)


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'games'
    if cmd == 'games':
        games()
    elif cmd == 'props':
        props(dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else None)
    elif cmd == 'alt':
        alt(dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else None)
