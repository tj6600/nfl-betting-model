"""Download nflverse play-by-play and aggregate it to one row per team per game."""
import os, numpy as np, pandas as pd

PBP_URL = 'https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{y}.csv.gz'
CACHE = os.path.join(os.path.dirname(__file__), '..', 'data')
COLS = ['game_id', 'season', 'week', 'posteam', 'defteam', 'play_type', 'epa', 'success',
        'pass', 'rush', 'qb_dropback', 'wp', 'id', 'qb_epa']


def load_season(y):
    local = os.path.join(os.environ.get('NFL_PBP_DIR', CACHE), f'pbp_{y}.csv.gz')
    src = local if os.path.exists(local) else PBP_URL.format(y=y)
    return pd.read_csv(src, usecols=lambda c: c in COLS, low_memory=False)


def team_games(seasons):
    """Per team-game offensive efficiency, excluding garbage time (win prob outside 5-95%)."""
    out_tg, out_qb = [], []
    for y in seasons:
        d = load_season(y)
        d = d[d.play_type.isin(['pass', 'run']) & d.epa.notna() & d.posteam.notna()]
        live = d[(d.wp > 0.05) & (d.wp < 0.95)]
        g = live.groupby(['game_id', 'posteam', 'defteam'])
        tg = pd.DataFrame({
            'pass_epa': g.apply(lambda x: x.loc[x['pass'] == 1, 'epa'].mean(), include_groups=False),
            'rush_epa': g.apply(lambda x: x.loc[x['rush'] == 1, 'epa'].mean(), include_groups=False),
            'succ': g.success.mean(),
            'plays': g.size(),
        }).reset_index()
        tg['season'] = y
        out_tg.append(tg)
        # QB efficiency per game (all dropbacks, not only live plays)
        qb = d[(d.qb_dropback == 1) & d.id.notna()]
        q = qb.groupby(['game_id', 'posteam', 'id']).agg(qb_epa=('qb_epa', 'mean'), n=('qb_epa', 'size')).reset_index()
        q['season'] = y
        out_qb.append(q)
    return pd.concat(out_tg, ignore_index=True), pd.concat(out_qb, ignore_index=True)


def cached(seasons=range(2018, 2027)):
    os.makedirs(CACHE, exist_ok=True)
    f1, f2 = os.path.join(CACHE, 'team_games.csv'), os.path.join(CACHE, 'qb_games.csv')
    if not (os.path.exists(f1) and os.path.exists(f2)):
        tg, qb = team_games(seasons)
        tg.to_csv(f1, index=False); qb.to_csv(f2, index=False)
    return pd.read_csv(f1), pd.read_csv(f2)
