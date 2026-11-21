"""NBA injury report from ESPN (site.api.espn.com; must be on the cloud environment's allowed hosts).

latest() returns {espn athlete id: dict(name, team, status, comment, date)}; status is Out, Doubtful,
Questionable, Day-To-Day, ... Each pull is saved to odds_log/nba/injuries_<UTC>.json.
"""
import os, re, json, datetime as dt, urllib.request
from nbamodel.data import NAMES

URL = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries'
DIR = os.path.join(os.path.dirname(__file__), '..', 'odds_log', 'nba')


def fetch(save=True):
    with urllib.request.urlopen(URL, timeout=30) as r:
        d = json.loads(r.read())
    if save:
        os.makedirs(DIR, exist_ok=True)
        json.dump(d, open(os.path.join(DIR, f"injuries_{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H%MZ')}.json"), 'w'))
    return parse(d)


def parse(d):
    out = {}
    for t in d.get('injuries', []):
        team = NAMES.get(t.get('displayName'))
        for i in t.get('injuries', []):
            a = i.get('athlete', {})
            pid = None
            for l in a.get('links', []):
                m = re.search(r'/id/(\d+)', l.get('href', ''))
                if m: pid = int(m.group(1)); break
            if pid is None: continue
            out[pid] = dict(name=a.get('displayName'), team=team, status=i.get('status'), comment=i.get('shortComment', ''), date=i.get('date'))
    return out


def latest():
    try:
        return fetch()
    except Exception as e:
        print('injury report unavailable:', type(e).__name__, e)
        return None
