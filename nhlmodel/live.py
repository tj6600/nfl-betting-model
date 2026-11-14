"""Add tonight's games to the history tables so the same rolling features describe them.

Each upcoming game gets a row with no results: one per team, one per expected skater (everyone who played
the team's last game, minus players ESPN lists as out), and one for each team's starting goalie (ESPN's
probable starter, or the team's most-used goalie in its last 10 games, flagged as unconfirmed).
"""
import json, urllib.request
import numpy as np
import pandas as pd
from nhlmodel.props import norm_name

SEASON_CODE = 20262027
INJ_URL = 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries'


def injuries():
    """{normalised name: (status, comment)} for players ESPN lists as Out, IR or day-to-day. None if unreachable."""
    try:
        with urllib.request.urlopen(INJ_URL, timeout=30) as r:
            d = json.loads(r.read())
    except Exception:
        return None
    out = {}
    for t in d.get('injuries', []):
        for i in t.get('injuries', []):
            nm = (i.get('athlete') or {}).get('displayName')
            if nm:
                out[norm_name(nm)] = (i.get('status') or '', i.get('shortComment') or '')
    return out


def is_out(status):
    s = status.lower()
    return 'injured reserve' in s or s in ('out', 'suspended') or 'ir' == s


def augment(games, sk, go, tg, slate, day, inj=None):
    """slate: rows from espn.scoreboard (home, away, gk_home, gk_away, espn_id). Returns augmented tables + notes."""
    inj = inj or {}
    day = str(day)
    gid = {r.espn_id: -int(r.espn_id) for r in slate.itertuples()}
    g_new, t_new, s_new, k_new = [], [], [], []
    notes = {}
    for r in slate.itertuples():
        g = gid[r.espn_id]
        g_new.append(dict(game_id=g, season=SEASON_CODE, game_date=day, home=r.home, away=r.away))
        for team, opp, home, gk_name in ((r.home, r.away, 1, r.gk_home), (r.away, r.home, 0, r.gk_away)):
            t_new.append(dict(game_id=g, season=SEASON_CODE, game_date=day, team=team, opp=opp, is_home=home))
            # skaters from the team's last game
            last = sk[sk.team == team].game_date.max()
            roster = sk[(sk.team == team) & (sk.game_date == last) & (sk.toi > 0)]
            outs = []
            for p in roster.itertuples():
                st = inj.get(norm_name(p.full_name))
                if st and is_out(st[0]):
                    outs.append(f'{p.full_name} ({st[0].lower()})'); continue
                s_new.append(dict(game_id=g, season=SEASON_CODE, game_date=day, player_id=p.player_id, player_name=p.player_name,
                                  full_name=p.full_name, team=team, opp=opp, is_home=home, position=p.position,
                                  inj=(st[0] if st else None)))
            # goalie
            gt = go[go.team == team].sort_values('game_date')
            starts = gt[gt.starter == True].tail(10)
            match = None
            if isinstance(gk_name, str):
                cand = gt[gt.full_name.map(norm_name) == norm_name(gk_name)]
                if len(cand):
                    match = cand.iloc[-1]
            confirmed = match is not None
            if match is None and len(starts):
                match = gt[gt.player_id == starts.player_id.mode().iloc[0]].iloc[-1]
            if match is not None:
                k_new.append(dict(game_id=g, season=SEASON_CODE, game_date=day, player_id=match.player_id, player_name=match.player_name,
                                  full_name=match.full_name, team=team, opp=opp, is_home=home, starter=True))
            notes[(g, team)] = dict(goalie=None if match is None else match.full_name, confirmed=confirmed,
                                    espn_goalie=gk_name if isinstance(gk_name, str) else None, outs=outs)
    games2 = pd.concat([games, pd.DataFrame(g_new)], ignore_index=True)
    tg2 = pd.concat([tg, pd.DataFrame(t_new)], ignore_index=True)
    sk2 = pd.concat([sk, pd.DataFrame(s_new)], ignore_index=True)
    go2 = pd.concat([go, pd.DataFrame(k_new)], ignore_index=True)
    return games2, sk2, go2, tg2, gid, notes
