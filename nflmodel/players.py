"""Per-player game stats from play-by-play, used to rate player quality.

Skill players (WR/TE/RB): EPA on their targets and carries.
Defenders: impact plays (sack 1, half sack 0.5, QB hit 0.5, tackle for loss 0.5,
pass breakup 0.5, interception 1.5, forced fumble 1).
Offensive linemen have no individual play-by-play stats, so they are rated by playing time only.
"""
import os, numpy as np, pandas as pd
from .pbp import PBP_URL, CACHE

DEF_COLS = {'sack_player_id': 1.0, 'half_sack_1_player_id': 0.5, 'half_sack_2_player_id': 0.5,
            'qb_hit_1_player_id': 0.5, 'qb_hit_2_player_id': 0.5, 'tackle_for_loss_1_player_id': 0.5,
            'tackle_for_loss_2_player_id': 0.5, 'pass_defense_1_player_id': 0.5, 'pass_defense_2_player_id': 0.5,
            'interception_player_id': 1.5, 'forced_fumble_player_1_player_id': 1.0}
PLAY_COLS = ['game_id', 'play_id', 'posteam', 'defteam', 'play_type', 'epa', 'pass', 'rush', 'qb_dropback', 'wp',
             'receiver_player_id', 'rusher_player_id']


def _season(y):
    local = os.path.join(os.environ.get('NFL_PBP_DIR', CACHE), f'pbp_{y}.csv.gz')
    src = local if os.path.exists(local) else PBP_URL.format(y=y)
    return pd.read_csv(src, usecols=lambda c: c in PLAY_COLS + list(DEF_COLS), low_memory=False)


def build(seasons=range(2018, 2027)):
    games, plays = [], []
    for y in seasons:
        d = _season(y)
        d = d[d.play_type.isin(['pass', 'run']) & d.epa.notna() & d.posteam.notna()]
        tgt = d[d['pass'] == 1].dropna(subset=['receiver_player_id'])
        car = d[d['rush'] == 1].dropna(subset=['rusher_player_id'])
        off = pd.concat([tgt[['game_id', 'receiver_player_id', 'epa']].rename(columns={'receiver_player_id': 'gsis'}),
                         car[['game_id', 'rusher_player_id', 'epa']].rename(columns={'rusher_player_id': 'gsis'})])
        off = off.groupby(['game_id', 'gsis']).agg(opps=('epa', 'size'), epa=('epa', 'sum')).reset_index()
        de = pd.concat([d[['game_id', c]].dropna().rename(columns={c: 'gsis'}).assign(impact=w) for c, w in DEF_COLS.items()])
        de = de.groupby(['game_id', 'gsis']).impact.sum().reset_index()
        games.append(off.merge(de, on=['game_id', 'gsis'], how='outer').fillna({'opps': 0, 'epa': 0, 'impact': 0}))
        plays.append(d[['game_id', 'play_id', 'posteam', 'defteam', 'epa', 'pass', 'rush', 'qb_dropback', 'wp']])
    return pd.concat(games, ignore_index=True), pd.concat(plays, ignore_index=True)


def cached():
    f1, f2 = os.path.join(CACHE, 'player_games.csv'), os.path.join(CACHE, 'plays.csv')
    if not (os.path.exists(f1) and os.path.exists(f2)):
        pg, pl = build()
        pg.to_csv(f1, index=False); pl.to_csv(f2, index=False)
    return pd.read_csv(f1), pd.read_csv(f2)
