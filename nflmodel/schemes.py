"""Scheme matchup features: how each offense does against the defensive looks its opponent uses most.

Data: nflverse FTN charting (2022+: blitzes, play action) and NGS participation
(2023-2025: man vs zone coverage; 2026 is not published yet, so 2026 games use 2023-25 tendencies).

For offense O facing defense D, each matchup is in EPA per dropback:

* man:   (O's EPA vs man - O's EPA vs zone)       x (D's man rate - league man rate)
* blitz: (O's EPA vs blitz - O's EPA vs no blitz) x (D's blitz rate - league blitz rate)
* pa:    (D's EPA allowed on play action - on other dropbacks) x (O's play-action rate - league rate)

Everything is computed from plays before the game, weighted toward recent seasons and shrunk toward
league average for small samples.
"""
import os, numpy as np, pandas as pd
from .model import G
from .players import cached as player_games

REL = 'https://github.com/nflverse/nflverse-data/releases/download'
CACHE = os.path.join(os.path.dirname(__file__), '..', 'data')
K = 120.0          # shrinkage, in dropbacks
HALF_LIFE = 365


def _read(kind, y, cols):
    name = {'ftn': f'ftn_{y}.csv', 'part': f'part_{y}.csv'}[kind]
    url = {'ftn': f'{REL}/ftn_charting/ftn_charting_{y}.csv', 'part': f'{REL}/pbp_participation/pbp_participation_{y}.csv'}[kind]
    local = os.path.join(os.environ.get('NFL_EXTRA_DIR', CACHE), name)
    try:
        return pd.read_csv(local if os.path.exists(local) else url, usecols=cols, low_memory=False)
    except Exception:
        return pd.DataFrame(columns=cols)


def dropbacks():
    _, plays = player_games()
    db = plays[(plays.qb_dropback == 1) & (plays.wp > 0.05) & (plays.wp < 0.95)].copy()
    ftn = pd.concat([_read('ftn', y, ['nflverse_game_id', 'nflverse_play_id', 'is_play_action', 'n_blitzers'])
                     for y in range(2022, 2027)])
    ftn = ftn.rename(columns={'nflverse_game_id': 'game_id', 'nflverse_play_id': 'play_id'})
    part = pd.concat([_read('part', y, ['nflverse_game_id', 'play_id', 'defense_man_zone_type']) for y in range(2023, 2027)])
    part = part.rename(columns={'nflverse_game_id': 'game_id'})
    db = db.merge(ftn, on=['game_id', 'play_id'], how='left').merge(part, on=['game_id', 'play_id'], how='left')
    db['pa'] = db.is_play_action.map({True: 1.0, False: 0.0, 'TRUE': 1.0, 'FALSE': 0.0})
    db['blitz'] = np.where(db.n_blitzers.notna(), (db.n_blitzers > 0).astype(float), np.nan)
    db['man'] = db.defense_man_zone_type.map({'MAN_COVERAGE': 1.0, 'ZONE_COVERAGE': 0.0})
    db = db.merge(G[['game_id', 'gameday']], on='game_id')
    return db[['game_id', 'gameday', 'posteam', 'defteam', 'epa', 'pa', 'blitz', 'man']]


def _split(d, side, flag, w):
    """Shrunk EPA when flag==1 minus when flag==0, per team on `side`."""
    x = d[d[flag].notna()]
    ww = w[x.index]
    lg = np.average(x.epa, weights=ww) if len(x) else 0.0
    out = {}
    for t, g in x.groupby(side):
        gw = ww[g.index]
        on, off = g[flag] == 1, g[flag] == 0
        e1 = (np.sum(gw[on] * g.epa[on]) + K * lg) / (gw[on].sum() + K)
        e0 = (np.sum(gw[off] * g.epa[off]) + K * lg) / (gw[off].sum() + K)
        out[t] = e1 - e0
    return out


def _rate(d, side, flag, w):
    x = d[d[flag].notna()]
    ww = w[x.index]
    if not len(x):
        return {}, 0.0
    lg = np.average(x[flag], weights=ww)
    return {t: (np.sum(ww[g.index] * g[flag]) + K * lg) / (ww[g.index].sum() + K) for t, g in x.groupby(side)}, lg


def matchups_asof(db, asof):
    d = db[db.gameday < asof]
    w = pd.Series(0.5 ** ((asof - d.gameday).dt.days.values / HALF_LIFE), index=d.index)
    off_man, off_blitz = _split(d, 'posteam', 'man', w), _split(d, 'posteam', 'blitz', w)
    def_pa = _split(d, 'defteam', 'pa', w)
    man_rate, lg_man = _rate(d, 'defteam', 'man', w)
    blitz_rate, lg_blitz = _rate(d, 'defteam', 'blitz', w)
    pa_rate, lg_pa = _rate(d, 'posteam', 'pa', w)

    def side(off, de):
        return {'m_man': off_man.get(off, 0) * (man_rate.get(de, lg_man) - lg_man),
                'm_blitz': off_blitz.get(off, 0) * (blitz_rate.get(de, lg_blitz) - lg_blitz),
                'm_pa': def_pa.get(de, 0) * (pa_rate.get(off, lg_pa) - lg_pa)}
    return side, {'man_rate': man_rate, 'blitz_rate': blitz_rate, 'pa_rate': pa_rate,
                  'off_man': off_man, 'off_blitz': off_blitz, 'def_pa': def_pa,
                  'lg': {'man': lg_man, 'blitz': lg_blitz, 'pa': lg_pa}}


def build(seasons=range(2019, 2027)):
    db = dropbacks()
    rows = []
    reg = G[(G.game_type == 'REG') & G.season.isin(list(seasons))]
    for (s, wk), t in reg.groupby(['season', 'week']):
        side, _ = matchups_asof(db, t.gameday.min())
        for g in t.itertuples():
            h, a = side(g.home_team, g.away_team), side(g.away_team, g.home_team)
            r = {'game_id': g.game_id}
            for k in h:
                r[f'd_{k}'] = h[k] - a[k]; r[f's_{k}'] = h[k] + a[k]
            rows.append(r)
    return pd.DataFrame(rows)


def cached():
    f = os.path.join(CACHE, 'scheme_features.csv')
    if not os.path.exists(f):
        build().to_csv(f, index=False)
    return pd.read_csv(f)
