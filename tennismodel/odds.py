"""Tennis DraftKings match-winner prices from The Odds API. Needs ODDS_API_KEY. ESPN has no tennis odds, so this is the only
part of the tennis board that costs credits.

  python -m tennismodel.odds active                  # tennis tournaments with odds right now: FREE (/sports)
  python -m tennismodel.odds pull --budget 6         # h2h (winner) for each active tournament: 1 credit per tournament

The Odds API covers only the bigger events (the four majors, Masters 1000s / WTA 1000s and some 500s; about 50 sport keys
per year), not ATP/WTA 250s. One pull = 1 credit per active tournament (region us, market h2h, DraftKings only).
--budget is a hard cap: the pull stops before it would spend more. Thomas approves credit use (see the README of
odds_log/tennis or ask first); nothing here is scheduled until he does.

Snapshots: odds_log/tennis/snapshots/<stamp>.csv (one row per player per match with DraftKings' American price and betslip id).
"""
import os, sys, json, glob, argparse, datetime as dt, urllib.request, urllib.parse
import pandas as pd

BASE = 'https://api.the-odds-api.com/v4'
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DIR = os.path.join(ROOT, 'odds_log', 'tennis')
SNAP = os.path.join(DIR, 'snapshots')


def _call(path, credits=True, **q):
    key = os.environ.get('ODDS_API_KEY')
    if not key:
        raise SystemExit('ODDS_API_KEY is not set.')
    base = {'apiKey': key}
    if credits:
        base.update(regions='us', bookmakers='draftkings', oddsFormat='american', dateFormat='iso', includeLinks='true', includeSids='true')
    with urllib.request.urlopen(f'{BASE}/{path}?{urllib.parse.urlencode({**base, **q})}', timeout=60) as r:
        return json.loads(r.read()), r.headers.get('x-requests-remaining')


def active():
    """Active tennis sport keys (free endpoint)."""
    sp, _ = _call('sports', credits=False)
    return [s for s in sp if s.get('group') == 'Tennis' and s.get('active')]


def tour_of(key):
    return 'wta' if key.startswith('tennis_wta') else 'atp'


def pull(budget):
    keys = active()
    print(f'{len(keys)} active tennis tournaments:', ', '.join(s['title'] for s in keys))
    if len(keys) > budget:
        print(f'budget {budget} < {len(keys)} tournaments: pulling the first {budget} only')
    rows, left = [], None
    now = dt.datetime.now(dt.timezone.utc)
    for s in keys[:budget]:
        ev, left = _call(f"sports/{s['key']}/odds", markets='h2h')
        for e in ev:
            for b in e.get('bookmakers', []):
                for m in b['markets']:
                    if m['key'] != 'h2h': continue
                    for o in m['outcomes']:
                        rows.append(dict(sport=s['key'], tournament=s['title'], tour=tour_of(s['key']), event=e['id'], start=e['commence_time'],
                                         p1=e['home_team'], p2=e['away_team'], player=o['name'], price=o['price'], sid=o.get('sid'),
                                         book=b['key'], pulled=now.strftime('%Y-%m-%dT%H:%M:%SZ')))
    os.makedirs(SNAP, exist_ok=True)
    f = os.path.join(SNAP, f"{now.strftime('%Y-%m-%dT%H%MZ')}.csv")
    pd.DataFrame(rows).to_csv(f, index=False)
    print(f'{len(rows)} prices saved to {f}; {left} credits left')
    return f


def latest(max_age_h=30):
    """Newest snapshot (DataFrame) if pulled within max_age_h hours, else None."""
    fs = sorted(glob.glob(os.path.join(SNAP, '*.csv')))
    if not fs: return None
    df = pd.read_csv(fs[-1])
    if not len(df): return None
    age = pd.Timestamp.now(tz='UTC') - pd.to_datetime(df.pulled, utc=True).max()
    return df if age <= pd.Timedelta(hours=max_age_h) else None


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('cmd', choices=['active', 'pull']); ap.add_argument('--budget', type=int)
    a = ap.parse_args()
    if a.cmd == 'active':
        for s in active(): print(s['key'], '-', s['title'])
    else:
        if not a.budget: raise SystemExit('pull needs --budget N (credits): ask Thomas first')
        pull(a.budget)
