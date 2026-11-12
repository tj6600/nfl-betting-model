"""Log NFL odds snapshots from The Odds API (https://the-odds-api.com).

Needs the environment variable ODDS_API_KEY. One snapshot of US books for moneylines, spreads and
totals costs 3 credits; the free plan has 500 a month.

Each snapshot is saved to odds_log/snapshots/<UTC time>.csv with one row per book, game, market and side,
plus a consensus row (book = "consensus": the median line across books).
"""
import os, json, datetime as dt, urllib.request, urllib.parse
import numpy as np, pandas as pd

API = 'https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds'
ROOT = os.path.join(os.path.dirname(__file__), '..')
SNAP_DIR = os.path.join(ROOT, 'odds_log', 'snapshots')
TEAMS = {'Arizona Cardinals': 'ARI', 'Atlanta Falcons': 'ATL', 'Baltimore Ravens': 'BAL', 'Buffalo Bills': 'BUF',
         'Carolina Panthers': 'CAR', 'Chicago Bears': 'CHI', 'Cincinnati Bengals': 'CIN', 'Cleveland Browns': 'CLE',
         'Dallas Cowboys': 'DAL', 'Denver Broncos': 'DEN', 'Detroit Lions': 'DET', 'Green Bay Packers': 'GB',
         'Houston Texans': 'HOU', 'Indianapolis Colts': 'IND', 'Jacksonville Jaguars': 'JAX', 'Kansas City Chiefs': 'KC',
         'Las Vegas Raiders': 'LV', 'Los Angeles Chargers': 'LAC', 'Los Angeles Rams': 'LA', 'Miami Dolphins': 'MIA',
         'Minnesota Vikings': 'MIN', 'New England Patriots': 'NE', 'New Orleans Saints': 'NO', 'New York Giants': 'NYG',
         'New York Jets': 'NYJ', 'Philadelphia Eagles': 'PHI', 'Pittsburgh Steelers': 'PIT', 'San Francisco 49ers': 'SF',
         'Seattle Seahawks': 'SEA', 'Tampa Bay Buccaneers': 'TB', 'Tennessee Titans': 'TEN', 'Washington Commanders': 'WAS'}


def fetch(api_key=None):
    key = api_key or os.environ.get('ODDS_API_KEY')
    if not key:
        raise SystemExit('ODDS_API_KEY is not set. Add it to the cloud environment as an environment variable.')
    q = urllib.parse.urlencode({'apiKey': key, 'regions': 'us', 'markets': 'h2h,spreads,totals',
                                'oddsFormat': 'american', 'dateFormat': 'iso'})
    with urllib.request.urlopen(f'{API}?{q}', timeout=60) as r:
        remaining = r.headers.get('x-requests-remaining')
        events = json.loads(r.read())
    return events, remaining


def to_rows(events, taken_at):
    rows = []
    for ev in events:
        home, away = TEAMS.get(ev['home_team']), TEAMS.get(ev['away_team'])
        if not home or not away:
            continue
        for bk in ev.get('bookmakers', []):
            for mk in bk.get('markets', []):
                for oc in mk.get('outcomes', []):
                    side = TEAMS.get(oc['name'], oc['name'])  # team abbreviation, or Over/Under
                    rows.append({'taken_at': taken_at, 'event_id': ev['id'], 'kickoff': ev['commence_time'],
                                 'home_team': home, 'away_team': away, 'book': bk['key'],
                                 'market': {'h2h': 'moneyline', 'spreads': 'spread', 'totals': 'total'}[mk['key']],
                                 'side': side, 'point': oc.get('point'), 'price': oc.get('price')})
    df = pd.DataFrame(rows)
    if len(df):
        cons = (df.groupby(['taken_at', 'event_id', 'kickoff', 'home_team', 'away_team', 'market', 'side'], dropna=False)
                  .agg(point=('point', 'median'), price=('price', 'median')).reset_index().assign(book='consensus'))
        df = pd.concat([df, cons], ignore_index=True)
    return df


def snapshot():
    taken_at = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H%MZ')
    events, remaining = fetch()
    df = to_rows(events, taken_at)
    os.makedirs(SNAP_DIR, exist_ok=True)
    path = os.path.join(SNAP_DIR, f'{taken_at}.csv')
    df.to_csv(path, index=False)
    print(f'saved {len(df)} rows for {df.event_id.nunique() if len(df) else 0} games to {path}; credits left: {remaining}')
    return path


def all_snapshots():
    files = sorted(f for f in os.listdir(SNAP_DIR) if f.endswith('.csv')) if os.path.isdir(SNAP_DIR) else []
    return pd.concat([pd.read_csv(os.path.join(SNAP_DIR, f)) for f in files], ignore_index=True) if files else pd.DataFrame()


def consensus_spread(snaps):
    """Home spread in nflverse convention (positive = home favored) per game and snapshot."""
    s = snaps[(snaps.book == 'consensus') & (snaps.market == 'spread') & (snaps.side == snaps.home_team)]
    return s.assign(spread_line=-s.point)[['taken_at', 'kickoff', 'home_team', 'away_team', 'spread_line']]


def props_snapshot(days=8, markets='player_anytime_td', prefix='anytime_td'):
    """Player prop odds for every game in the next `days` days (1 credit per market per game) -> odds_log/props/."""
    key = os.environ.get('ODDS_API_KEY')
    if not key:
        raise SystemExit('ODDS_API_KEY is not set.')
    base = API.rsplit('/odds', 1)[0]
    with urllib.request.urlopen(f'{base}/events?apiKey={key}', timeout=60) as r:
        events = json.loads(r.read())
    now = dt.datetime.now(dt.timezone.utc)
    soon = [e for e in events if dt.datetime.fromisoformat(e['commence_time'].replace('Z', '+00:00')) < now + dt.timedelta(days=days)]
    out, remaining = [], None
    for e in soon:
        q = urllib.parse.urlencode({'apiKey': key, 'regions': 'us', 'markets': markets, 'oddsFormat': 'american'})
        with urllib.request.urlopen(f"{base}/events/{e['id']}/odds?{q}", timeout=60) as r:
            remaining = r.headers.get('x-requests-remaining'); out.append(json.loads(r.read()))
    d = os.path.join(os.path.dirname(SNAP_DIR), 'props'); os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{prefix}_{now.strftime('%Y-%m-%dT%H%MZ')}.json")
    json.dump(out, open(path, 'w'))
    print(f'saved {markets} odds for {len(out)} games to {path}; API credits left: {remaining}')
    return path


if __name__ == '__main__':
    import sys
    if 'props' in sys.argv[1:]:
        props_snapshot()
    elif 'alt' in sys.argv[1:]:
        props_snapshot(markets='player_rush_yds_alternate,player_reception_yds_alternate', prefix='altyards')
    elif 'yards' in sys.argv[1:]:
        props_snapshot(markets='player_rush_yds,player_reception_yds,player_pass_yds', prefix='yards')
    else:
        snapshot()
