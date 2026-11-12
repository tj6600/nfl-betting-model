"""Refresh odds_log/injury_overrides.csv from ESPN's NFL injury report (free, site.api.espn.com).

Players listed Out, Doubtful or on Injured Reserve for the current week are written as overrides, which the
TD, yards and receptions picks drop (Out/Doubtful) and the injury-aware game model counts as unavailable.
Hand-entered rows (any note not starting with "ESPN") are kept; earlier ESPN rows for this week are replaced.
Questionable players are listed in the output for the run summary but not written, since most of them play.
"""
import sys, os, json, urllib.request; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
ROOT = os.path.join(os.path.dirname(__file__), '..')
import pandas as pd
from nflmodel.model import G

URL = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries'
TEAM = {'WSH': 'WAS', 'LAR': 'LA'}   # ESPN -> nflverse abbreviations
STATUS = {'Out': 'Out', 'Doubtful': 'Doubtful', 'Injured Reserve': 'Out'}

today = pd.Timestamp.now(tz='UTC').tz_localize(None).normalize()
up = G[(G.game_type == 'REG') & G.result.isna() & (pd.to_datetime(G.gameday) >= today - pd.Timedelta(days=1))]
season = int(up.season.min()); week = int(up[up.season == season].week.min())

d = json.load(urllib.request.urlopen(urllib.request.Request(URL, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30))
rows, questionable = [], []
for t in d.get('injuries', []):
    for i in t.get('injuries', []):
        a = i.get('athlete', {}); team = a.get('team', {}).get('abbreviation'); team = TEAM.get(team, team)
        pos = (a.get('position') or {}).get('abbreviation', '')
        st = i.get('status')
        if st in STATUS:
            rows.append(dict(season=season, week=week, team=team, player=a.get('displayName'), status=STATUS[st],
                             note=f'ESPN {st} ({pos}), {i.get("date", "")[:10]}'))
        elif st == 'Questionable' and pos in ('QB', 'RB', 'WR', 'TE'):
            questionable.append(f'{a.get("displayName")} ({team} {pos})')

path = os.path.join(ROOT, 'odds_log', 'injury_overrides.csv')
old = pd.read_csv(path) if os.path.exists(path) else pd.DataFrame(columns=['season', 'week', 'team', 'player', 'status', 'note'])
keep = old[~((old.season == season) & (old.week == week) & old.note.fillna('').str.startswith('ESPN'))]
new = pd.DataFrame(rows)
manual = set(keep[(keep.season == season) & (keep.week == week)].player)
new = new[~new.player.isin(manual)]
pd.concat([keep, new], ignore_index=True).to_csv(path, index=False)
print(f'{season} week {week}: {len(new)} ESPN Out/Doubtful/IR players written ({(new.status == "Doubtful").sum()} doubtful); '
      f'{len(manual)} hand-entered rows kept')
skill = new[new.note.str.contains(r'\((?:QB|RB|WR|TE)\)')]
print('Skill players out or doubtful:', ', '.join(f'{r.player} ({r.team}, {r.status})' for r in skill.itertuples()) or 'none')
print(f'Questionable skill players ({len(questionable)}):', ', '.join(questionable))
