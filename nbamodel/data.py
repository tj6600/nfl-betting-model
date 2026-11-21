"""NBA data: ESPN box scores and DraftKings/consensus lines via sportsdataverse (hoopR) on GitHub.

Sources (both on raw.githubusercontent.com, updated daily by hoopR's own GitHub Actions):
  * hoopR-nba-data  parquet per season: player_box, team_box, schedules, play_by_play (spread columns).
    Reading parquet needs pyarrow, so it is only used to (re)build the history and the schedule.
  * hoopR-nba-raw   one JSON per finished game (nba/json/final/<game_id>.json) with the box score and
    ESPN's pick center (DraftKings closing spread, total and moneylines this season). This is what the
    daily update uses, so scheduled runs need nothing beyond numpy and pandas.

Cached in nba_data/:
  games.csv        one row per game: date, teams, score, market spread (home), total, moneylines, provider
  players.csv.gz   one row per player-game: minutes, points, rebounds, assists, threes, ... and DNP reason
  schedule.csv     the current season's regular-season schedule (game ids, tip times, teams)
"""
import os, io, json, gzip, datetime as dt, urllib.request, concurrent.futures as cf
import numpy as np, pandas as pd

ROOT = os.path.join(os.path.dirname(__file__), '..')
DIR = os.path.join(ROOT, 'nba_data')
RAW = 'https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-raw/main/nba/json/final/{}.json'
DATA = 'https://raw.githubusercontent.com/sportsdataverse/hoopR-nba-data/main/nba/{0}/parquet/{1}_{2}.parquet'
SEASON = 2027  # ESPN season label: 2027 = the 2026-27 season
NAMES = {'Atlanta Hawks': 'ATL', 'Brooklyn Nets': 'BKN', 'Boston Celtics': 'BOS', 'Charlotte Hornets': 'CHA',
         'Chicago Bulls': 'CHI', 'Cleveland Cavaliers': 'CLE', 'Dallas Mavericks': 'DAL', 'Denver Nuggets': 'DEN',
         'Detroit Pistons': 'DET', 'Golden State Warriors': 'GS', 'Houston Rockets': 'HOU', 'Indiana Pacers': 'IND',
         'LA Clippers': 'LAC', 'Los Angeles Clippers': 'LAC', 'Los Angeles Lakers': 'LAL', 'Memphis Grizzlies': 'MEM',
         'Miami Heat': 'MIA', 'Milwaukee Bucks': 'MIL', 'Minnesota Timberwolves': 'MIN', 'New Orleans Pelicans': 'NO',
         'New York Knicks': 'NY', 'Oklahoma City Thunder': 'OKC', 'Orlando Magic': 'ORL', 'Philadelphia 76ers': 'PHI',
         'Phoenix Suns': 'PHX', 'Portland Trail Blazers': 'POR', 'San Antonio Spurs': 'SA', 'Sacramento Kings': 'SAC',
         'Toronto Raptors': 'TOR', 'Utah Jazz': 'UTAH', 'Washington Wizards': 'WSH'}
PCOLS = ['game_id', 'season', 'date', 'team', 'opp', 'home', 'pid', 'name', 'pos', 'starter', 'dnp', 'reason',
         'min', 'pts', 'reb', 'ast', 'fg3m', 'fg3a', 'fgm', 'fga', 'ftm', 'fta', 'oreb', 'tov', 'stl', 'blk', 'pm']
GCOLS = ['game_id', 'season', 'stype', 'date', 'tip', 'home', 'away', 'hs', 'as_', 'spread', 'total', 'ml_home', 'ml_away',
         'provider']


def _get(url, timeout=60):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def _pick(pc, home_id):
    """Spread from the home side (negative = home favoured), total and moneylines from ESPN's pick center."""
    if not pc:
        return {}
    p = sorted(pc, key=lambda x: (x['provider']['name'] != 'DraftKings', x['provider'].get('priority', 9)))[0]
    h, a = p.get('homeTeamOdds', {}), p.get('awayTeamOdds', {})
    sp = p.get('spread')
    if sp is not None:   # ESPN's 'spread' is the favourite's number; the sign comes from who is favoured
        sp = -abs(sp) if h.get('favorite') else abs(sp)
    return dict(spread=sp, total=p.get('overUnder'), ml_home=h.get('moneyLine'), ml_away=a.get('moneyLine'),
                provider=p['provider']['name'])


def parse_game(g):
    """Turn one hoopR-nba-raw final JSON into (game row, player rows)."""
    comp = g['header']['competitions'][0]
    cs = {c['homeAway']: c for c in comp['competitors']}
    home, away = cs['home']['team']['abbreviation'], cs['away']['team']['abbreviation']
    tip = pd.Timestamp(comp['date']).tz_convert('America/New_York')
    gid = int(g['header']['id'])
    row = dict(game_id=gid, season=g['header']['season']['year'], stype=g['header']['season']['type'],
               date=str(tip.date()), tip=tip.strftime('%Y-%m-%d %H:%M'), home=home, away=away,
               hs=int(cs['home'].get('score') or 0), as_=int(cs['away'].get('score') or 0))
    row.update(_pick(g.get('pickcenter'), cs['home']['team']['id']))
    out = []
    for t in g.get('boxscore', {}).get('players', []):
        team = t['team']['abbreviation']; opp = away if team == home else home
        st = t['statistics'][0]; keys = st['keys']
        for a in st['athletes']:
            r = dict(game_id=gid, season=row['season'], date=row['date'], team=team, opp=opp, home=team == home,
                     pid=int(a['athlete']['id']), name=a['athlete']['displayName'],
                     pos=(a['athlete'].get('position') or {}).get('abbreviation'), starter=bool(a.get('starter')),
                     dnp=bool(a.get('didNotPlay')) or not a.get('stats'), reason=a.get('reason'))
            v = dict(zip(keys, a.get('stats') or []))
            def num(k):
                x = v.get(k)
                try: return float(str(x).replace('+', ''))
                except (TypeError, ValueError): return np.nan
            def pair(k, i):
                x = v.get(k)
                try: return float(str(x).split('-')[i])
                except (TypeError, ValueError, IndexError): return np.nan
            r.update(min=num('minutes'), pts=num('points'), reb=num('rebounds'), ast=num('assists'),
                     fg3m=pair('threePointFieldGoalsMade-threePointFieldGoalsAttempted', 0),
                     fg3a=pair('threePointFieldGoalsMade-threePointFieldGoalsAttempted', 1),
                     fgm=pair('fieldGoalsMade-fieldGoalsAttempted', 0), fga=pair('fieldGoalsMade-fieldGoalsAttempted', 1),
                     ftm=pair('freeThrowsMade-freeThrowsAttempted', 0), fta=pair('freeThrowsMade-freeThrowsAttempted', 1),
                     oreb=num('offensiveRebounds'), tov=num('turnovers'), stl=num('steals'), blk=num('blocks'),
                     pm=num('plusMinus'))
            out.append(r)
    return row, out


def fetch_games(ids, workers=16):
    """Download and parse finished games; returns (games df, players df, ids that are not final yet)."""
    def one(i):
        try:
            return parse_game(json.loads(_get(RAW.format(i))))
        except Exception:
            return None
    G, P, miss = [], [], []
    with cf.ThreadPoolExecutor(workers) as ex:
        for i, res in zip(ids, ex.map(one, ids)):
            if res is None or not res[1]:
                miss.append(i); continue
            G.append(res[0]); P.extend(res[1])
    return pd.DataFrame(G, columns=GCOLS), pd.DataFrame(P, columns=PCOLS), miss


# ---------- one-off history build from parquet (needs pyarrow) ----------
def _parquet(kind, name, season):
    return pd.read_parquet(io.BytesIO(_get(DATA.format(kind, name, season), timeout=180)))


def schedule_from_parquet(season=SEASON):
    s = _parquet('schedules', 'nba_schedule', season)
    s = s[s.season_type.isin([2, 3])]
    tip = pd.to_datetime(s.game_date_time)
    return pd.DataFrame(dict(game_id=s.game_id.astype(int), season=season, stype=s.season_type.astype(int),
                             date=tip.dt.strftime('%Y-%m-%d'), tip=tip.dt.strftime('%Y-%m-%d %H:%M'),
                             home=s.home_abbreviation, away=s.away_abbreviation,
                             final=s.status_type_completed.astype(bool))).sort_values('tip')


def history_from_parquet(season):
    pb = _parquet('player_box', 'player_box', season)
    pb = pb[pb.season_type.isin([2, 3]) & pb.athlete_id.notna()]
    P = pd.DataFrame(dict(game_id=pb.game_id.astype(int), season=season, date=pb.game_date.astype(str),
                          team=pb.team_abbreviation, opp=pb.opponent_team_abbreviation, home=pb.home_away == 'home',
                          pid=pb.athlete_id.astype(int), name=pb.athlete_display_name, pos=pb.athlete_position_abbreviation,
                          starter=pb.starter.astype(bool), dnp=pb.did_not_play.fillna(False).astype(bool) | pb.minutes.isna(),
                          reason=pb.reason, min=pb.minutes, pts=pb.points, reb=pb.rebounds, ast=pb.assists,
                          fg3m=pb.three_point_field_goals_made, fg3a=pb.three_point_field_goals_attempted,
                          fgm=pb.field_goals_made, fga=pb.field_goals_attempted, ftm=pb.free_throws_made,
                          fta=pb.free_throws_attempted, oreb=pb.offensive_rebounds, tov=pb.turnovers, stl=pb.steals,
                          blk=pb.blocks, pm=pd.to_numeric(pb.plus_minus.astype(str).str.replace('+', ''), errors='coerce')))
    s = schedule_from_parquet(season); s = s[s.final]
    tb = _parquet('team_box', 'team_box', season)
    sc = tb.pivot_table(index='game_id', columns='team_home_away', values='team_score', aggfunc='first')
    s = s.merge(sc.rename(columns={'home': 'hs', 'away': 'as_'}), left_on='game_id', right_index=True)
    # spreads for every season from the play-by-play file (home_team_spread > 0 means home favoured)
    try:
        pbp = _parquet('pbp', 'play_by_play', season)[['game_id', 'home_team_spread', 'game_spread_available']]
        pbp = pbp[pbp.game_spread_available == True].groupby('game_id').home_team_spread.last()
        s['spread'] = -s.game_id.map(pbp)
    except Exception:
        s['spread'] = np.nan
    s['total'] = np.nan; s['ml_home'] = np.nan; s['ml_away'] = np.nan; s['provider'] = np.where(s.spread.notna(), 'espn-pbp', None)
    return s[GCOLS], P[PCOLS]


def load():
    G = pd.read_csv(os.path.join(DIR, 'games.csv'))
    P = pd.read_csv(os.path.join(DIR, 'players.csv.gz'))
    S = pd.read_csv(os.path.join(DIR, 'schedule.csv'))
    return G, P, S


def save(G, P, S=None):
    os.makedirs(DIR, exist_ok=True)
    G.sort_values(['date', 'game_id']).to_csv(os.path.join(DIR, 'games.csv'), index=False)
    P.sort_values(['date', 'game_id', 'team', 'pid']).to_csv(os.path.join(DIR, 'players.csv.gz'), index=False,
                                                             compression={'method': 'gzip', 'mtime': 0})
    if S is not None:
        S.to_csv(os.path.join(DIR, 'schedule.csv'), index=False)


def update(today=None):
    """Add finished games from the current season that are not cached yet. Refreshes the schedule when pyarrow exists."""
    G, P, S = load()
    try:
        S = schedule_from_parquet()
    except Exception as e:   # no pyarrow in a scheduled run: keep the committed schedule
        print('schedule refresh skipped:', type(e).__name__)
    today = today or dt.datetime.now(dt.timezone.utc).astimezone(dt.timezone(dt.timedelta(hours=-5))).date()
    want = S[(pd.to_datetime(S.date).dt.date < today) & ~S.game_id.isin(G.game_id)].game_id.tolist()
    g, p, miss = fetch_games(want)
    if len(g):
        G = pd.concat([G[~G.game_id.isin(g.game_id)], g], ignore_index=True)
        P = pd.concat([P[~P.game_id.isin(g.game_id)], p], ignore_index=True)
    save(G, P, S)
    print(f'added {len(g)} games, {len(miss)} not available yet; cache has {len(G)} games through {G.date.max()}')
    return G, P, S
