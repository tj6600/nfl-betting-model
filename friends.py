"""Friends page (board/site/friends.html): Google sign-in, friend groups and the weekly group parlay (Thomas, 2026-11-18).

Each week every member of a group picks one leg from that week's NFL board; the legs together are the group's parlay,
and a leaderboard tracks whose legs hit. Sign-in, groups and picks live in Firebase (Auth + Firestore, set up by Thomas;
board/site/firebase-config.js holds the project's public web config, and firestore.rules is what keeps the data private).
Nothing here holds a secret.

This module does the parts that need no sign-in, from the built NFL page only (no Odds API key, no credits):
  * snapshot(): every leg on the week's board that hasn't kicked off is saved to odds_log/friends/<season>_wk<NN>.json,
    with its kickoff and how the page's Refresh button finds its result on ESPN. A leg stays in the file once seen, so a
    pick made Monday still counts if the leg leaves the board later.
  * grade(): final results from the free nflverse data (nflmodel.record.results, the Model record's grader).
  * build(): board/site/group/<season>_wk<NN>.json for the page (legs, kickoffs, results) and board/site/friends.html.
The page trusts only these files for kickoffs and results, so a pick saved after its leg kicked off is shown as late and
never counts, whatever a phone sends.

  python scripts/friends_board.py [--no-grade]
"""
import os, re, json, glob
import datetime as dt

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, 'board', 'site')
LOG = os.path.join(ROOT, 'odds_log', 'friends')
OUT = os.path.join(SITE, 'group')
GRADE_AFTER_H = 4      # a leg is graded once its game kicked off this long ago (and nflverse has the final)


def _now(): return dt.datetime.now(dt.timezone.utc)
def _t(s): return dt.datetime.fromisoformat(str(s).replace('Z', '+00:00'))


def _board():
    import bank
    return bank._data('index.html', 'td-data')


def _file(season, week): return os.path.join(LOG, f'{season}_wk{int(week):02d}.json')


def _load(f):
    return json.load(open(f)) if os.path.exists(f) else None


def _x(season, week, L):
    """[event, market, stat, side, line, player, [season, week, away, home]] as head.html's liveCheck reads it."""
    import calib as CAL
    from nflmodel import record as REC
    x = REC.grade_x(f'{season}_wk{int(week):02d}', L['id'], L['game'], L.get('gt') or L.get('label'))
    if x and x.get('m') == 'stat' and L.get('who'): x['nm'] = L['who']
    return CAL.compact_x(x) if x else None


def snapshot(D=None, now=None):
    """Add the board's not-yet-started legs to this week's file; returns the week's data."""
    D = D or _board()
    if not D or not D.get('legs'): return None
    now = now or _now()
    season, week = int(D['season']), int(D['week'])
    f = _file(season, week)
    W = _load(f) or dict(season=season, week=week, legs={})
    starts = D.get('starts') or {}
    added = 0
    for L in D['legs']:
        price = (L.get('offers') or {}).get('DraftKings', L.get('price'))
        kick = starts.get(L.get('game'))
        if price is None or not kick or _t(kick) <= now: continue
        old = W['legs'].get(L['id'])
        if old:   # keep the leg; refresh its price and kickoff while it's still open
            old.update(price=int(price), kick=kick); continue
        x = _x(season, week, L)
        if not x: continue
        W['legs'][L['id']] = dict(kind=L['kind'], who=L.get('who'), label=L.get('label'), game=L['game'], team=L.get('team'),
                                  price=int(price), p=round(float(L.get('p') or 0), 4), kick=kick, x=x)
        added += 1
    W['updated'] = now.strftime('%Y-%m-%dT%H:%MZ')
    os.makedirs(LOG, exist_ok=True)
    json.dump(W, open(f, 'w'), separators=(',', ':'))
    print(f'Friends: {season} week {week}: {len(W["legs"])} legs ({added} new)')
    return W


def grade(now=None):
    """Final results for every leg whose game should be over; a failed download just waits for the next run."""
    from nflmodel import record as REC
    now = now or _now()
    files = sorted(glob.glob(os.path.join(LOG, '*.json')))
    want, by = {}, {}
    for f in files:
        W = json.load(open(f)); by[f] = W
        ids = {i: L['game'] for i, L in W['legs'].items()
               if not L.get('r') and (now - _t(L['kick'])).total_seconds() > GRADE_AFTER_H * 3600}
        if ids: want[(W['season'], W['week'])] = ids
    if not want: print('Friends: nothing to grade'); return 0
    try:
        res = REC.results(want)
    except Exception as e:
        print('Friends: grading skipped,', e); return 0
    n = 0
    for f, W in by.items():
        day = f'{W["season"]}_wk{W["week"]:02d}'
        hit = False
        for i, L in W['legs'].items():
            r = res.get((day, i))
            if r and not L.get('r'): L['r'] = r; n += 1; hit = True
        if hit: json.dump(W, open(f, 'w'), separators=(',', ':'))
    print(f'Friends: graded {n} legs')
    return n


def build():
    """The page's week files plus friends.html."""
    os.makedirs(OUT, exist_ok=True)
    weeks = []
    for f in sorted(glob.glob(os.path.join(LOG, '*.json'))):
        W = json.load(open(f)); key = f'{W["season"]}_wk{W["week"]:02d}'
        weeks.append(dict(key=key, season=W['season'], week=W['week'], n=len(W['legs']),
                          first=min((L['kick'] for L in W['legs'].values()), default=None),
                          last=max((L['kick'] for L in W['legs'].values()), default=None)))
        json.dump(dict(key=key, season=W['season'], week=W['week'], updated=W.get('updated'), legs=W['legs']),
                  open(os.path.join(OUT, key + '.json'), 'w'), separators=(',', ':'))
    D = _board() or {}
    cur = f'{int(D["season"])}_wk{int(D["week"]):02d}' if D.get('season') else (weeks[-1]['key'] if weeks else None)
    json.dump(dict(current=cur, weeks=weeks, built=_now().strftime('%Y-%m-%dT%H:%MZ')),
              open(os.path.join(OUT, 'index.json'), 'w'), separators=(',', ':'))
    page()
    print(f'Friends: {len(weeks)} week files, current {cur} -> board/site/friends.html')


def page():
    import bank
    B = os.path.join(ROOT, 'board')
    head = open(os.path.join(B, 'head.html')).read().replace('<title>Player Props Board</title>', '<title>Friends parlay</title>')
    html = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<meta name="robots" content="noindex, nofollow">\n' + bank.APP_HEAD + head + bank.SPORT_CSS
            + '\n<style>\n' + open(os.path.join(B, 'friends.css')).read() + '</style>\n</head>\n<body>\n'
            + bank.nav('friends') + open(os.path.join(B, 'friends_body.html')).read()
            + '<script src="firebase-config.js"></script>\n<script type="module">\n' + open(os.path.join(B, 'friends_app.js')).read()
            + '</script>\n</body>\n</html>\n')
    open(os.path.join(SITE, 'friends.html'), 'w').write(html)


def run(grade_it=True):
    snapshot()
    if grade_it: grade()
    build()


def safe_run(grade_it=False):
    """For the board scripts: a Friends failure never stops a board run."""
    try:
        run(grade_it)
    except Exception as e:
        import traceback; traceback.print_exc(); print('Friends skipped:', e)
