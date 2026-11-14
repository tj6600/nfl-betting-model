"""NHL box scores and play-by-play from the sportsdataverse fastRhockey-nhl-data mirror on GitHub.

The NHL's own API (api-web.nhle.com) is blocked from the cloud env, but raw.githubusercontent.com is not.
The mirror rebuilds from the NHL API daily. Files are named by the season's end year (2026 = 2025-26).

  python -m nhlmodel.data            # refresh the current season's files and rebuild the caches
"""
import os, sys, urllib.request
import numpy as np
import pandas as pd

ROOT = os.path.join(os.path.dirname(__file__), '..')
RAW = os.path.join(ROOT, 'nhl_data', 'raw')
CACHE = os.path.join(ROOT, 'nhl_data')
MIRROR = 'https://raw.githubusercontent.com/sportsdataverse/fastRhockey-nhl-data/main/nhl'
FAMILIES = {'skater_box': 'skater_box', 'goalie_box': 'goalie_box', 'team_box': 'team_box',
            'game_info': 'game_info', 'scratches': 'scratches', 'pbp': 'play_by_play'}
SEASONS = [2025, 2026, 2027]
CURRENT = 2027


def fetch(season, families=FAMILIES):
    os.makedirs(RAW, exist_ok=True)
    for fam, stem in families.items():
        url = f'{MIRROR}/{fam}/parquet/{stem}_{season}.parquet'
        out = os.path.join(RAW, f'{fam}_{season}.parquet')
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                data = r.read()
            open(out, 'wb').write(data)
        except Exception as e:
            print('fetch failed', url, e)


def _read(fam, seasons):
    fs = [os.path.join(RAW, f'{fam}_{s}.parquet') for s in seasons]
    return pd.concat([pd.read_parquet(f) for f in fs if os.path.exists(f)], ignore_index=True)


def _mins(s):
    p = s.fillna('0:00').astype(str).str.split(':', expand=True)
    return p[0].astype(float) + p[1].astype(float) / 60


def build(seasons=SEASONS):
    frames = {f: _read(f, seasons) for f in ('game_info', 'pbp', 'skater_box', 'goalie_box')}
    games, sk, go, tg = assemble(frames['game_info'], frames['pbp'], frames['skater_box'], frames['goalie_box'])
    save(games, sk, go, tg, seasons)


def assemble(gi, pbp, sk, go):
    """Turn raw game info, play-by-play and box scores (any set of games) into the cached tables."""
    gi = gi[(gi.game_type == 'R') & (gi.game_state.isin(['OFF', 'FINAL']))].copy()
    games = gi.rename(columns={'home_team_abbr': 'home', 'away_team_abbr': 'away'})[
        ['game_id', 'season', 'game_date', 'home', 'away', 'home_score', 'away_score']].copy()

    # play-by-play aggregates
    pbp = pbp[pbp.game_id.isin(games.game_id)]
    per = pbp.groupby('game_id').period.max()
    so = pbp[pbp.event_type == 'SHOOTOUT_COMPLETE'].game_id.unique()
    games['ot'] = games.game_id.map(per).fillna(3).gt(3).astype(int)
    games['so'] = games.game_id.isin(so).astype(int)

    att = pbp[pbp.event_type.isin(['SHOT', 'MISSED_SHOT', 'BLOCKED_SHOT', 'GOAL']) & (pbp.period <= 4)].copy()
    # blocked shots are credited to the blocking team; the shooter is always event_player_1
    opp = np.where(att.event_team_abbr == att.home_abbr, att.away_abbr, att.home_abbr)
    att['shoot_team'] = np.where(att.event_type == 'BLOCKED_SHOT', opp, att.event_team_abbr)
    home_shoot = att.shoot_team == att.home_abbr
    own = np.where(home_shoot, att.home_skaters, att.away_skaters)
    oth = np.where(home_shoot, att.away_skaters, att.home_skaters)
    att['pp'] = (own > oth) & (oth >= 3)
    att['sog'] = att.event_type.isin(['SHOT', 'GOAL'])
    att['xg'] = att.xg.fillna(0)
    att['pp_s'] = att.pp & att.sog
    att['en'] = att.empty_net.fillna(False).astype(bool)
    att = att[~att.en]   # empty-net attempts distort shot rates

    pl = att.groupby(['game_id', 'event_player_1_id']).agg(
        icf=('sog', 'size'), ixg=('xg', 'sum'), pp_cf=('pp', 'sum'),
        pp_sog=('pp_s', 'sum')).reset_index().rename(columns={'event_player_1_id': 'player_id'})

    gl = pbp[pbp.event_type == 'GOAL'].copy()
    gl['en'] = gl.empty_net.fillna(False).astype(bool)
    gl['reg'] = (gl.period <= 3) & ~gl.en
    gl['en_g'] = gl.en & (gl.period <= 3)
    gt = gl.groupby(['game_id', 'event_team_abbr']).agg(gf_reg=('reg', 'sum'), en_gf=('en_g', 'sum')).reset_index() \
        .rename(columns={'event_team_abbr': 'team'})

    tm = att.groupby(['game_id', 'shoot_team']).agg(cf=('sog', 'size'), sf=('sog', 'sum'), xgf=('xg', 'sum'),
                                                    pp_cf=('pp', 'sum')).reset_index().rename(columns={'shoot_team': 'team'})

    # skaters
    sk = sk[sk.game_id.isin(games.game_id)].copy()
    sk['toi'] = _mins(sk.toi)
    sk = sk.merge(games[['game_id', 'game_date', 'home', 'away']], on=['game_id', 'game_date'], how='left')
    sk['is_home'] = (sk.home_away == 'home').astype(int)
    sk['team'] = sk.team_abbrev
    sk['opp'] = np.where(sk.is_home == 1, sk.away, sk.home)
    sk = sk.merge(pl, on=['game_id', 'player_id'], how='left')
    for c in ['icf', 'ixg', 'pp_cf', 'pp_sog']:
        sk[c] = sk[c].fillna(0)
    sk = sk[['game_id', 'season', 'game_date', 'player_id', 'player_name', 'team', 'opp', 'is_home', 'position',
             'toi', 'shifts', 'shots_on_goal', 'goals', 'assists', 'points', 'blocked_shots', 'hits',
             'icf', 'ixg', 'pp_cf', 'pp_sog']].rename(columns={'shots_on_goal': 'sog'})

    # full skater names from the play-by-play (box scores only have "B. Tkachuk")
    nm = pd.concat([pbp[[f'event_player_{i}_id', f'event_player_{i}_name']].set_axis(['player_id', 'name'], axis=1)
                    for i in (1, 2, 3)]).dropna().drop_duplicates('player_id', keep='last')
    sk['full_name'] = sk.player_id.map(nm.set_index('player_id').name).fillna(sk.player_name)

    # goalies
    go = go[go.game_id.isin(games.game_id)].copy()
    go['toi'] = _mins(go.toi)
    go = go.merge(games[['game_id', 'home', 'away']], on='game_id', how='left')
    go['is_home'] = (go.home_away == 'home').astype(int)
    go['team'] = go.team_abbrev
    go['opp'] = np.where(go.is_home == 1, go.away, go.home)
    gnm = pbp[['event_goalie_id', 'event_goalie_name']].dropna().drop_duplicates('event_goalie_id', keep='last')
    go['full_name'] = go.player_id.map(gnm.set_index('event_goalie_id').event_goalie_name).fillna(go.player_name)
    go = go[['game_id', 'season', 'game_date', 'player_id', 'player_name', 'full_name', 'team', 'opp', 'is_home',
             'starter', 'toi', 'shots_against', 'saves', 'goals_against']]

    # team games: one row per team per game
    rows = []
    for side, o in (('home', 'away'), ('away', 'home')):
        t = games[['game_id', 'season', 'game_date', side, o, f'{side}_score', f'{o}_score', 'ot', 'so']].copy()
        t.columns = ['game_id', 'season', 'game_date', 'team', 'opp', 'gf', 'ga', 'ot', 'so']
        t['is_home'] = int(side == 'home')
        rows.append(t)
    tg = pd.concat(rows, ignore_index=True)
    tg = tg.merge(tm, on=['game_id', 'team'], how='left').merge(gt, on=['game_id', 'team'], how='left')
    tg[['gf_reg', 'en_gf']] = tg[['gf_reg', 'en_gf']].fillna(0)
    tg = tg.merge(tm.rename(columns={'team': 'opp', 'cf': 'ca', 'sf': 'sa', 'xgf': 'xga', 'pp_cf': 'pk_ca'}),
                  on=['game_id', 'opp'], how='left')

    return games, sk, go, tg


def save(games, sk, go, tg, seasons):
    # one folder per season (nhl_data/<end year>/), so a daily run only rebuilds the current season
    for y in seasons:
        code = int(f'{y - 1}{y}')
        out = os.path.join(CACHE, str(y)); os.makedirs(out, exist_ok=True)
        for name, df in [('games', games), ('skaters', sk), ('goalies', go), ('team_games', tg)]:
            df[df.season == code].to_csv(os.path.join(out, f'{name}.csv.gz'), index=False)
    print(f'{len(games)} games, {len(sk)} skater rows, {len(go)} goalie rows through {games.game_date.max()}')


RAW_JSON = 'https://raw.githubusercontent.com/sportsdataverse/fastRhockey-nhl-raw/main/nhl/json/final'


def _game_json(gid):
    import json
    try:
        with urllib.request.urlopen(f'{RAW_JSON}/{gid}.json', timeout=120) as r:
            return json.loads(r.read())
    except Exception:
        return None


def update(season=CURRENT, lookahead=40):
    """Daily path with no pyarrow: add newly finished games from the mirror's per-game JSON files to nhl_data/<season>/."""
    out = os.path.join(CACHE, str(season))
    have = pd.read_csv(os.path.join(out, 'games.csv.gz')) if os.path.exists(os.path.join(out, 'games.csv.gz')) else pd.DataFrame(columns=['game_id'])
    done = set(have.game_id.astype(int))
    base = (season - 1) * 1000000 + 20000          # regular season ids: 2026020001, ...
    top = max(done) if done else base
    todo = [g for g in range(max(base + 1, top - 60), top + lookahead) if g not in done]
    gi, pbp, sk, go, misses = [], [], [], [], 0
    for gid in todo:
        d = _game_json(gid)
        if not d or not d.get('game_info'):
            if gid > top:
                misses += 1
                if misses >= 4: break
            continue
        info = pd.DataFrame(d['game_info'])
        if info.game_state.iloc[0] not in ('OFF', 'FINAL'):
            continue
        meta = dict(game_id=gid, season=int(info.season.iloc[0]), game_date=info.game_date.iloc[0])
        gi.append(info)
        pbp.append(pd.DataFrame(d['all_plays']).assign(**meta))
        sk.append(pd.DataFrame(d['skater_stats']).assign(**meta))
        go.append(pd.DataFrame(d['goalie_stats']).assign(**meta))
    if not gi:
        print('no new NHL games'); return 0
    g2, s2, k2, t2 = assemble(pd.concat(gi, ignore_index=True), pd.concat(pbp, ignore_index=True),
                              pd.concat(sk, ignore_index=True), pd.concat(go, ignore_index=True))
    for name, df in [('games', g2), ('skaters', s2), ('goalies', k2), ('team_games', t2)]:
        f = os.path.join(out, f'{name}.csv.gz')
        old = pd.read_csv(f) if os.path.exists(f) else pd.DataFrame()
        pd.concat([old, df], ignore_index=True).drop_duplicates([c for c in ('game_id', 'player_id', 'team') if c in df.columns], keep='last') \
            .to_csv(f, index=False)
    print(f'added {len(g2)} NHL games through {g2.game_date.max()}')
    return len(g2)


def load():
    import glob
    dirs = sorted(d for d in glob.glob(os.path.join(CACHE, '[0-9]' * 4)) if os.path.isdir(d))
    r = lambda f: pd.concat([pd.read_csv(os.path.join(d, f)) for d in dirs], ignore_index=True)
    return r('games.csv.gz'), r('skaters.csv.gz'), r('goalies.csv.gz'), r('team_games.csv.gz')


if __name__ == '__main__':
    # default (daily): add new games from per-game JSON, no pyarrow needed.
    # --parquet: re-download and rebuild the current season from parquet (needs pyarrow); --all: rebuild every season.
    if '--parquet' in sys.argv or '--all' in sys.argv:
        if '--no-fetch' not in sys.argv:
            fetch(CURRENT)
        build(SEASONS if '--all' in sys.argv else [CURRENT])
    else:
        update()
