"""Roster availability and coaching features from injury reports, snap counts, weekly rosters and coaches.

For each team and game, using only information available before kickoff:

* missing_<grp>  - recent regulars (snap share over the team's last 3 games) who are out this week:
                   ruled Out/Doubtful, partly for Questionable, no longer on the active roster (IR, cut),
                   or traded/signed away.
* return_<grp>   - established regulars who missed recent games and are active again.
* arrive_<grp>   - regulars from another team who are now on this team's active roster (trades, signings),
                   counted at half weight since they may not start straight away.
* net_<grp>      - return + arrive - missing, in "full-time starters" (1.0 = one player on every snap),
                   each player weighted by quality (players.py): about 0.25 for a weak starter up to 2.25 for a star.
                   Linemen have no individual stats, so they all count as 1.0.

Groups: OL, SKILL (WR/TE/RB), FRONT (DL/LB), DB. QBs are handled separately in features.py.

* new_hc     - head coach in his first season with the team.
* interim_hc - head coach changed during this season.
"""
import os, numpy as np, pandas as pd
from .model import G
from .players import cached as player_games

REL = 'https://github.com/nflverse/nflverse-data/releases/download'
URLS = {'inj': REL + '/injuries/injuries_{y}.csv', 'snaps': REL + '/snap_counts/snap_counts_{y}.csv',
        'roster': REL + '/weekly_rosters/roster_weekly_{y}.csv'}
CACHE = os.path.join(os.path.dirname(__file__), '..', 'data')
GROUPS = ['OL', 'SKILL', 'FRONT', 'DB']
SNAP_POS = {'T': 'OL', 'G': 'OL', 'C': 'OL', 'OL': 'OL', 'WR': 'SKILL', 'TE': 'SKILL', 'RB': 'SKILL', 'FB': 'SKILL',
            'DE': 'FRONT', 'DT': 'FRONT', 'NT': 'FRONT', 'DL': 'FRONT', 'LB': 'FRONT', 'OLB': 'FRONT', 'ILB': 'FRONT',
            'MLB': 'FRONT', 'CB': 'DB', 'S': 'DB', 'FS': 'DB', 'SS': 'DB', 'DB': 'DB'}
INJ_AVAIL = {'Out': 0.0, 'Doubtful': 0.1, 'Questionable': 0.8}
REGULAR, ESTABLISHED = 0.5, 0.6


def _load(kind, y):
    local = os.path.join(os.environ.get('NFL_EXTRA_DIR', CACHE), f'{kind}_{y}.csv')
    return pd.read_csv(local if os.path.exists(local) else URLS[kind].format(y=y), low_memory=False)


def _key(name):
    return name.str.lower().str.replace(r'[^a-z]', '', regex=True)


def build(seasons=range(2018, 2027)):
    snaps = pd.concat([_load('snaps', y) for y in seasons], ignore_index=True)
    snaps = snaps[snaps.game_type == 'REG'] if 'game_type' in snaps else snaps
    snaps['grp'] = snaps.position.map(SNAP_POS)
    snaps = snaps[snaps.grp.notna()].copy()
    snaps['share'] = snaps[['offense_pct', 'defense_pct']].max(axis=1).clip(0, 1)
    snaps['key'] = _key(snaps.player) + '|' + snaps.grp
    snaps = snaps.merge(G[['game_id', 'gameday']], on='game_id')
    snaps = _add_quality_stats(snaps, seasons)

    inj = pd.concat([_load('inj', y) for y in seasons], ignore_index=True)
    inj = inj[inj.report_status.isin(INJ_AVAIL)]
    inj['name'] = _key(inj.full_name)
    inj_avail = {(r.season, r.week, r.team, r.name): INJ_AVAIL[r.report_status] for r in inj.itertuples()}

    ros = pd.concat([_load('roster', y)[['season', 'week', 'team', 'status', 'full_name', 'position']] for y in seasons])
    ros['name'] = _key(ros.full_name)
    active = ros[ros.status == 'ACT'].groupby(['season', 'week', 'team']).name.apply(set).to_dict()

    # per-player game log, sorted by date
    by_team = {t: d.sort_values('gameday') for t, d in snaps.groupby('team')}
    by_player = {k: d.sort_values('gameday') for k, d in snaps.groupby('key')}

    rows = []
    reg = G[G.game_type == 'REG']
    for g in reg.itertuples():
        for team in (g.home_team, g.away_team):
            rows.append(_team_game(g, team, by_team.get(team), by_player, active, inj_avail))
    out = pd.DataFrame(rows)
    return out.merge(_coaching(), on=['game_id', 'team'], how='left')


ROSTER_GRP = {'OL': 'OL', 'WR': 'SKILL', 'TE': 'SKILL', 'RB': 'SKILL', 'FB': 'SKILL', 'DL': 'FRONT', 'LB': 'FRONT', 'DB': 'DB'}
Q_SCALE = {}


def _add_quality_stats(snaps, seasons):
    """Attach each player's per-game quality stat: EPA for skill players, impact plays for defenders."""
    ros = pd.concat([_load('roster', y)[['gsis_id', 'full_name', 'position']] for y in seasons]).dropna()
    ros = ros.drop_duplicates('gsis_id', keep='last')
    ros['key'] = _key(ros.full_name) + '|' + ros.position.map(ROSTER_GRP)
    pg, _ = player_games()
    pg = pg.merge(ros[['gsis_id', 'key']], left_on='gsis', right_on='gsis_id')
    snaps = snaps.merge(pg[['game_id', 'key', 'epa', 'impact']], on=['game_id', 'key'], how='left').fillna({'epa': 0.0, 'impact': 0.0})
    snaps['qstat'] = np.where(snaps.grp == 'SKILL', snaps.epa, np.where(snaps.grp.isin(['FRONT', 'DB']), snaps.impact, 0.0))
    # league scale of a regular's per-game rate, for z-scores
    reg = snaps[snaps.share >= REGULAR].groupby(['season', 'key', 'grp']).qstat.mean().reset_index()
    for grp, d in reg.groupby('grp'):
        Q_SCALE[grp] = (d.qstat.mean(), d.qstat.std() or 1.0)
    return snaps


def _quality(log, grp):
    """Quality multiplier from a player's last 17 games: 1.0 = average regular, shrunk toward average."""
    if grp == 'OL' or grp not in Q_SCALE or not len(log):
        return 1.0
    mu, sd = Q_SCALE[grp]
    rate = (log.qstat.tail(17).sum() + 4 * mu) / (min(len(log), 17) + 4)
    return float(np.clip(1 + 0.5 * (rate - mu) / sd, 0.25, 2.25))


def _team_game(g, team, tlog, by_player, active, inj_avail):
    f = {'game_id': g.game_id, 'team': team}
    for grp in GROUPS:
        f[f'missing_{grp}'] = f[f'return_{grp}'] = f[f'arrive_{grp}'] = 0.0
    if tlog is None:
        return f
    before = tlog[tlog.gameday < g.gameday]
    last_games = before.drop_duplicates('game_id').tail(3).game_id
    recent = before[before.game_id.isin(last_games)]
    n = max(len(last_games), 1)
    recent_share = recent.groupby('key').share.sum() / n
    act = active.get((g.season, g.week, team))

    def avail(key):
        name = key.split('|')[0]
        if act is not None and name not in act:
            return 0.0
        return inj_avail.get((g.season, g.week, team, name), 1.0)

    # regulars over the last 3 games who are out now
    def q(key):
        log = by_player[key]
        return _quality(log[log.gameday < g.gameday], key.split('|')[1])

    for key, s in recent_share[recent_share >= REGULAR].items():
        a = avail(key)
        if a < 1:
            f['missing_' + key.split('|')[1]] += s * (1 - a) * q(key)
    if act is None:
        return _net(f)
    # established players who were absent recently (returning) or played elsewhere (arrivals)
    seen = set(recent_share[recent_share >= 0.3].index)
    cand = before.key.unique().tolist()
    for key in cand:
        if key in seen or key.split('|')[0] not in act:
            continue
        log = by_player[key]
        log = log[(log.gameday < g.gameday) & (log.gameday > g.gameday - pd.Timedelta(days=400))].tail(6)
        if len(log) < 3 or log.share.mean() < ESTABLISHED or log.team.iloc[-1] != team:
            continue
        f['return_' + key.split('|')[1]] += log.share.mean() * (1 - recent_share.get(key, 0)) * avail(key) * _quality(log, key.split('|')[1])
    # arrivals: on this week's active roster, last game played for another team
    names_here = {k for k in act}
    for key, log in _recent_elsewhere(team, g.gameday, names_here, by_player):
        f['arrive_' + key.split('|')[1]] += 0.5 * log.share.mean() * avail(key) * _quality(log, key.split('|')[1])
    return _net(f)


_ELSEWHERE_CACHE = {}


def _recent_elsewhere(team, day, names_here, by_player):
    # players whose most recent game (within 400 days) was for another team and who were regulars there
    if not _ELSEWHERE_CACHE:
        for key, log in by_player.items():
            _ELSEWHERE_CACHE.setdefault(key.split('|')[0], []).append(key)
    out = []
    for name in names_here:
        for key in _ELSEWHERE_CACHE.get(name, []):
            log = by_player[key]
            log = log[(log.gameday < day) & (log.gameday > day - pd.Timedelta(days=400))].tail(6)
            if len(log) >= 3 and log.team.iloc[-1] != team and log.share.mean() >= ESTABLISHED:
                out.append((key, log))
    return out


def _net(f):
    for grp in GROUPS:
        f[f'net_{grp}'] = f[f'return_{grp}'] + f[f'arrive_{grp}'] - f[f'missing_{grp}']
    return f


def _coaching():
    rows = []
    g = G[G.game_type == 'REG'].sort_values('gameday')
    long = pd.concat([
        g[['game_id', 'season', 'gameday', 'home_team', 'home_coach']].rename(columns={'home_team': 'team', 'home_coach': 'coach'}),
        g[['game_id', 'season', 'gameday', 'away_team', 'away_coach']].rename(columns={'away_team': 'team', 'away_coach': 'coach'}),
    ]).sort_values('gameday')
    for team, d in long.groupby('team'):
        prev_season_coach, first_coach_this_season, season = None, None, None
        last_by_season = d.groupby('season').coach.last().to_dict()
        for r in d.itertuples():
            if r.season != season:
                season, first_coach_this_season = r.season, r.coach
                prev_season_coach = last_by_season.get(r.season - 1)
            rows.append({'game_id': r.game_id, 'team': team,
                         'new_hc': float(prev_season_coach is not None and r.coach != prev_season_coach
                                         and r.coach == first_coach_this_season),
                         'interim_hc': float(r.coach != first_coach_this_season)})
    return pd.DataFrame(rows)


def cached():
    f = os.path.join(CACHE, 'roster_features.csv')
    if not os.path.exists(f):
        build().to_csv(f, index=False)
    return pd.read_csv(f)
