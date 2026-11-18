"""Bank Builder: small parlays of heavy favorites from the boards (NFL, college football, NHL; NBA removed), priced at DraftKings.

Thomas, 2026-11-16: "takes a $10 bet and makes it into a $15 or $20 total win ... two or three -400 legs ... any of the
three sports". Two -400 legs pay about 1.56x, three about 1.95x.

The legs come from the built board pages (board/site/index.html, nba.html, nhl.html), so this costs no Odds API
credits: whatever the scheduled runs last pulled is what it uses.
  * a leg: DraftKings price from PRICE_LO to PRICE_HI (about -400), no flags, model chance P_MIN+, at most JUICE pts
    below DraftKings' implied chance (implied includes the vig; "beats DK" = model chance above it), game starts in the
    next WINDOW_H hours and hasn't started.
  * a slip: 2 or 3 legs, one per game, whose total return on $10 is in RET: about $15 for 2 legs, about $20 for 3. Slips are
    ranked by combined model hit chance (Thomas values hitting over edge), then by expected value. A leg appears in at
    most 2 suggestions so the list varies; up to N_SLIPS per size.
Logging and grading (like parlays.py): each logged build writes odds_log/bank/<ET day>_<stamp>.json. NBA and NHL legs are
logged only if they're in that sport's first pick log of the day (the one its grader grades); NFL ids carry their line,
so nflmodel/record.py grades them directly. Graders write leg results to odds_log/{nba,nhl}/leg_results.json and
odds_log/bank/nfl_results.json. A slip loses if any leg loses; otherwise it pays the product of its winning legs'
DraftKings prices (push and void legs drop out). Each distinct slip counts once, from the first build that suggested it.

  python scripts/bank_board.py [--no-log]      # also run at the end of every board build
"""
import os, re, json, glob, math, itertools
import datetime as dt

ROOT = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(ROOT, 'board', 'site')
LOG = os.path.join(ROOT, 'odds_log', 'bank')

PRICE_LO, PRICE_HI = -700, -250      # about -400: -250 pays 1.40x, -700 pays 1.14x
P_MIN, JUICE = 0.70, 3.0             # model chance floor; at most 3 pts under DK's implied chance (same juice as PR 40)
RET = {2: (1.50, 1.75), 3: (1.80, 2.10)}   # $10 returns $15 to $17.50 (2 legs) or $18 to $21 (3 legs)
WINDOW_H, N_SLIPS, MAX_USE, TOP = 30, 5, 2, 45
SIZES = (2, 3)
# backup legs (page filters only): DK -150 to -1200, model 55%+, games in the next 7 days (a leg that meets the bar but starts after WINDOW_H isn't marked backup), top BACKUP_N per league
BACKUP_LO, BACKUP_HI, BACKUP_P, BACKUP_H, BACKUP_N = -1200, -150, 0.55, 168, 40
STAKE = 10


def dec(a): return 1 + a / 100 if a > 0 else 1 + 100 / -a
def imp(a): return 1 / dec(a)


def _data(page, tag):
    f = os.path.join(SITE, page)
    if not os.path.exists(f): return None
    m = re.search(r'<script type="application/json" id="%s">(.*?)</script>' % tag, open(f).read(), re.S)
    return json.loads(m.group(1).replace('<\\/', '</')) if m else None


def _t(s): return dt.datetime.fromisoformat(s.replace('Z', '+00:00')) if s else None


def legs(now=None, backup=False):
    """Every eligible leg from the three boards, normalized: sport, day (the grader's key), id, label, game, start, price, p, dk, edge, sid."""
    now = now or dt.datetime.now(dt.timezone.utc)
    out = []
    D = _data('index.html', 'td-data')
    if D:
        import parlays as PZ
        day = f"{D['season']}_wk{int(D['week']):02d}"
        for L in D['legs']:
            pr = (L.get('offers') or {}).get('DraftKings')
            if pr is None or L.get('flag'): continue
            out.append(dict(sport='NFL', day=day, id=L['id'], label=PZ._name(L), kind=L['kind'], game=L['game'],
                            start=(D.get('starts') or {}).get(L['game']), price=int(pr), p=L['p'], sid=L.get('sid')))
    D = _data('cfb.html', 'cfb-data')   # college football (added 2026-11-18): one board per football week, game lines only
    if D:
        for L in D['legs']:
            if L.get('flags') or L.get('price') is None: continue
            out.append(dict(sport='CFB', day=D['week'], id=L['id'], label=L['label'], kind=L['kind'], game=L['game'],
                            start=L.get('start'), price=int(L['price']), p=L['p'], sid=L.get('sid')))
    for sport, page, tag in [('NHL', 'nhl.html', 'nhl-data')]:   # NBA removed 2026-11-18
        D = _data(page, tag)
        if not D: continue
        st = {g['game']: g.get('start') for g in D.get('games', [])}
        for L in D['legs']:
            if L.get('flags') or L.get('price') is None: continue
            out.append(dict(sport=sport, day=D['day'], id=L['id'], label=L['label'], kind=L['kind'], game=L['game'],
                            start=st.get(L['game']), price=int(L['price']), p=L['p'], sid=L.get('sid')))
    pool, extra, seen = [], [], set()
    for L in out:
        s = _t(L['start'])
        if not s or s <= now or s > now + dt.timedelta(hours=BACKUP_H): continue
        L['key'] = L['sport'] + '|' + L['id']; L['dk'] = round(imp(L['price']), 4); L['edge'] = round((L['p'] - L['dk']) * 100, 1)
        k = (L['sport'], L['label'], L['price'])            # the NBA board can list one alt rung twice
        if k in seen: continue
        seen.add(k)
        good = PRICE_LO <= L['price'] <= PRICE_HI and L['p'] >= P_MIN and L['edge'] >= -JUICE
        if good and s <= now + dt.timedelta(hours=WINDOW_H): pool.append(L)
        elif good or (BACKUP_LO <= L['price'] <= BACKUP_HI and L['p'] >= BACKUP_P): extra.append(dict(L, backup=not good))
    pool.sort(key=lambda L: (-L['p'], -L['edge']))
    if not backup: return pool
    # next-best legs for a league the user picks on the page when it has too few Bank Builder legs (Thomas, 2026-11-16):
    # likeliest first, BACKUP_N per league, shown with a lower-hit-chance warning; never suggested or logged by default
    extra.sort(key=lambda L: (-L['p'], -L['edge']))
    keep, per = [], {}
    for L in extra:
        if per.get(L['sport'], 0) < BACKUP_N: keep.append(L); per[L['sport']] = per.get(L['sport'], 0) + 1
    return pool, keep


def _who(L):   # one leg per player: the label up to its number ("Kevin Durant 18+ points" -> "Kevin Durant")
    m = re.match(r'^(.*?)\s(?:Over|Under|[\d.]+\+)', L['label'])
    return (L['sport'], m.group(1)) if m and L['kind'] not in ('Game', 'Moneyline', 'Spread', 'Total', 'Puck line') else None


def slips(pool):
    """{size: [slip, ...]}, each slip a list of legs; best first."""
    top = pool[:TOP]
    out = {}
    for k in SIZES:
        cands = []
        for c in itertools.combinations(top, k):
            if len({L['game'] for L in c}) < k: continue
            w = [_who(L) for L in c if _who(L)]
            if len(set(w)) < len(w): continue
            r = math.prod(dec(L['price']) for L in c)
            if not RET[k][0] <= r <= RET[k][1]: continue
            p = math.prod(L['p'] for L in c)
            cands.append((-p, -(p * r - 1), c))
        cands.sort(key=lambda x: (x[0], x[1]))
        uses, picked = {}, []
        for _, _, c in cands:
            if any(uses.get(L['id'], 0) >= MAX_USE for L in c): continue
            picked.append(list(c))
            for L in c: uses[L['id']] = uses.get(L['id'], 0) + 1
            if len(picked) >= N_SLIPS: break
        out[k] = picked
    return out


def summary(s):
    p = math.prod(L['p'] for L in s); dk = math.prod(L['dk'] for L in s); r = math.prod(dec(L['price']) for L in s)
    return dict(p=round(p, 4), dk=round(dk, 4), ret=round(r, 4), ev=round(p * r - 1, 4))


# ---------- logging ----------
def _first_log_ids(sport, day):
    fs = sorted(glob.glob(os.path.join(ROOT, 'odds_log', sport.lower(), 'picks', f'{day}_*.csv')))
    if not fs: return set()
    import csv
    return {(r['id'], r['label']) for r in csv.DictReader(open(fs[0]))}


def _week_log_ids(sport, week):
    """CFB: every leg in any pick log of that week (scripts/cfb_grade.py grades each leg at its first logged price)."""
    import csv
    return {(r['id'], r['label']) for f in glob.glob(os.path.join(ROOT, 'odds_log', sport.lower(), 'picks', f'{week}_*.csv')) for r in csv.DictReader(open(f))}


def gradable(pool):
    """Legs the graders will see: NBA/NHL legs in that sport's first pick log of the day; NFL legs with a line in the id."""
    from nflmodel import record as REC
    cache, ok = {}, []
    for L in pool:
        if L['sport'] == 'NFL':
            if REC.RX_G.match(L['id']) or REC.RX_Y.match(L['id']) or REC.RX_M.match(L['id']) or L['id'].startswith('t-'): ok.append(L)
        else:
            k = (L['sport'], L['day'])
            if k not in cache: cache[k] = _week_log_ids(*k) if L['sport'] == 'CFB' else _first_log_ids(*k)
            if (L['id'], L['label']) in cache[k]: ok.append(L)
    return ok


def _slim(s):
    return dict(**summary(s), legs=[{k: L[k] for k in ('sport', 'day', 'id', 'label', 'game', 'start', 'price', 'p')} for L in s])


def log(S, stamp, day):
    os.makedirs(LOG, exist_ok=True)
    f = os.path.join(LOG, f'{day}_{stamp}.json')
    if not os.path.exists(f) and any(S.values()):
        json.dump({str(k): [_slim(s) for s in v] for k, v in S.items()}, open(f, 'w'))
    return f


# ---------- grading ----------
def results():
    """{(sport, day, id): 'win'|'loss'|'push'|'void'} from the three graders."""
    out = {}
    for sport, f in [('NBA', os.path.join(ROOT, 'odds_log', 'nba', 'leg_results.json')),
                     ('NHL', os.path.join(ROOT, 'odds_log', 'nhl', 'leg_results.json')),
                     ('CFB', os.path.join(ROOT, 'odds_log', 'cfb', 'leg_results.json')),
                     ('NFL', os.path.join(LOG, 'nfl_results.json'))]:
        if os.path.exists(f):
            for day, m in json.load(open(f)).items():
                for i, r in m.items():
                    if r: out[(sport, day, i)] = r
    return out


def nfl_wanted():
    """{(season, week): {leg_id: game}} for NFL legs in bank logs (nflmodel/record.py grades them)."""
    want = {}
    for f in glob.glob(os.path.join(LOG, '*_*T*.json')):
        for v in json.load(open(f)).values():
            for s in v:
                for L in s['legs']:
                    if L['sport'] == 'NFL':
                        se, w = L['day'].split('_wk'); want.setdefault((int(se), int(w[:2])), {})[L['id']] = L['game']
    return want


def grade():
    res = results()
    rows, seen = [], set()
    for f in sorted(glob.glob(os.path.join(LOG, '*_*T*.json'))):
        day = os.path.basename(f)[:10]
        for k, v in json.load(open(f)).items():
            for i, s in enumerate(v):
                key = frozenset((L['sport'], L['day'], L['id']) for L in s['legs'])
                if key in seen: continue
                seen.add(key)
                rs = [res.get((L['sport'], L['day'], L['id'])) for L in s['legs']]
                if 'loss' in rs: out, units = 'lost', -1.0
                elif any(r is None for r in rs): out, units = 'open', None
                else:
                    live = [L for L, r in zip(s['legs'], rs) if r == 'win']
                    out, units = ('push', 0.0) if not live else ('won', math.prod(dec(L['price']) for L in live) - 1)
                rows.append(dict(day=day, gday=max(str(L['day'])[:10] for L in s['legs']), size=int(k), top=i == 0, result=out, units=units, p=s['p'], ret=s['ret'],
                                 sports=sorted({L['sport'] for L in s['legs']}),
                                 legs=[dict(sport=L['sport'], label=L['label'], price=L['price'], result=r) for L, r in zip(s['legs'], rs)], _legs=s['legs']))
    out = report(rows)
    # day / week / month menus like the sport pages' Model record (Thomas, 2026-11-18): a slip counts on the day of its last game
    import calib as CAL
    out['by_period'] = CAL.by_period([r['gday'] for r in rows if r['result'] in ('won', 'lost', 'push')],
                                     lambda ds: report([r for r in rows if r['gday'] in ds]))
    out['pending'] = pending(rows)
    return out


def report(rows):
    """Slip groups, leg record and latest graded slips for these rows (all of them, or one day / week / month)."""
    groups = []

    def grp(name, x):
        x = [r for r in x if r['result'] in ('won', 'lost')]
        if not x: return
        w = sum(r['result'] == 'won' for r in x); u = sum(r['units'] for r in x)
        groups.append(dict(group=name, bets=len(x), won=w, lost=len(x) - w, hit=w / len(x), exp_hit=sum(r['p'] for r in x) / len(x),
                           units=round(u, 2), roi=u / len(x), dollars=round(u * STAKE, 2)))
    grp('All Bank Builder slips', rows)
    grp('Top slip of each build', [r for r in rows if r['top']])
    for k in SIZES: grp(f'{k}-leg slips', [r for r in rows if r['size'] == k])
    grp('Mixed-sport slips', [r for r in rows if len(r['sports']) > 1])
    # leg record: every distinct leg that went into a slip, as a straight bet
    lw = {}
    for r in rows:
        for L in r['legs']:
            if L['result'] in ('win', 'loss'): lw[(L['label'], L['price'])] = L['result'] == 'win'
    legrec = dict(n=len(lw), won=sum(lw.values()))
    done = [{k: v for k, v in r.items() if k != '_legs'} for r in rows if r['result'] in ('won', 'lost', 'push')]
    return dict(groups=groups, legs=legrec, recent=done[-12:][::-1], open=sum(r['result'] == 'open' for r in rows))


def pending(rows):
    """Slips still open, with what the page's Refresh results button needs to grade their legs from ESPN (Thomas,
    2026-11-18): legs [key, ET date, ESPN lookup, price, p, [], []] and slips [size, top, sports, p, ret, [[key, result, price, label]], day, last game day]."""
    import calib as CAL, csv
    from nflmodel import record as REC
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=4)).strftime('%Y-%m-%d')
    known = {}   # the sport pages' own waiting legs already carry the lookup (NHL ones with the skater's position)
    for sp in ('nba', 'nhl', 'cfb'):
        f = os.path.join(ROOT, 'odds_log', sp, 'grade_report.json')
        if os.path.exists(f):
            for L in (json.load(open(f)).get('pending') or {}).get('legs', []): known[(sp.upper(), L[0])] = L[2]
    csvs, legs, slips_ = {}, {}, []

    def x_of(L):
        if L['sport'] == 'NFL':
            x = REC.grade_x(L['day'], L['id'], L['game'], L['label']); return CAL.compact_x(x) if x else None
        k = (L['sport'], f"{L['day']}|{L['id']}")
        if k in known: return known[k]
        ck = (L['sport'], L['day'])
        if ck not in csvs:
            fs = sorted(glob.glob(os.path.join(ROOT, 'odds_log', L['sport'].lower(), 'picks', f"{L['day']}_*.csv")))
            csvs[ck] = {}
            for f in (fs if L['sport'] == 'CFB' else fs[:1]):   # CFB: a leg's first log of the week
                for r in csv.DictReader(open(f)): csvs[ck].setdefault(r['id'], r)
        r = csvs[ck].get(L['id'])
        return CAL.compact_x(CAL.csv_x(L['sport'], r)) if r else None
    from zoneinfo import ZoneInfo
    for r in rows:
        if r['result'] != 'open' or r['day'] < since: continue
        ls = []
        for L, lr in zip(r['_legs'], [x['result'] for x in r['legs']]):
            key = f"{L['sport']}|{L['day']}|{L['id']}"
            if lr is None and key not in legs:
                x = x_of(L)
                d = _t(L['start']).astimezone(ZoneInfo('America/New_York')).strftime('%Y-%m-%d') if L.get('start') else None
                if x: legs[key] = [key, d, x, int(L['price']), round(float(L['p']), 4), [], [], L['sport']]
            ls.append([key, lr, int(L['price']), L['label']])
        slips_.append([r['size'], r['top'], r['sports'], r['p'], r['ret'], ls, r['day'], r['gday']])
    return dict(legs=list(legs.values()), slips=slips_)


# ---------- page ----------
def build(log_it=True, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    pool, extra = legs(now, backup=True)
    S = slips(pool)
    stamp = now.strftime('%Y-%m-%dT%H%MZ')
    from zoneinfo import ZoneInfo
    et = now.astimezone(ZoneInfo('America/New_York'))
    if log_it:
        g = gradable(pool)
        log(slips(g), stamp, et.strftime('%Y-%m-%d'))
    rec = grade()
    taken = {}
    for sport, page, tag, k in [('NFL', 'index.html', 'td-data', 'taken'), ('CFB', 'cfb.html', 'cfb-data', 'weekLabel'), ('NHL', 'nhl.html', 'nhl-data', 'dayLabel')]:
        D = _data(page, tag)
        if D: taken[sport] = D.get(k)
    D = dict(built=stamp, stake=STAKE, rules=dict(lo=PRICE_LO, hi=PRICE_HI, pmin=P_MIN, juice=JUICE, ret={str(k): v for k, v in RET.items()}, window=WINDOW_H),
             taken=taken, pool=pool, backup=extra, n_slips=N_SLIPS, max_use=MAX_USE, top=TOP, slips={str(k): [[L['key'] for L in s] for s in v] for k, v in S.items()}, record=rec)
    B = os.path.join(ROOT, 'board')
    head = open(os.path.join(B, 'head.html')).read().replace('<title>Player Props Board</title>', '<title>Bank Builder</title>')
    data = json.dumps(D, separators=(',', ':')).replace('</', '<\\/')
    html = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<meta name="robots" content="noindex, nofollow">\n' + APP_HEAD + head + SPORT_CSS + '\n<style>\n' + open(os.path.join(B, 'bank.css')).read() + '</style>\n</head>\n<body>\n'
            + nav('bank') + open(os.path.join(B, 'bank_body.html')).read()
            + f'<script type="application/json" id="bank-data">{data}</script>\n<script>\n' + open(os.path.join(B, 'bank_app.js')).read() + '</script>\n</body>\n</html>\n')
    os.makedirs(SITE, exist_ok=True)
    open(os.path.join(SITE, 'bank.html'), 'w').write(html)
    print(f"Bank Builder: {len(pool)} legs, " + ', '.join(f'{len(v)} {k}-leg slips' for k, v in S.items())
          + f"; record {sum(g['bets'] for g in rec['groups'][:1])} graded, {rec['open']} open -> board/site/bank.html")
    return D


# the sport switch on every page (td_board.py, nba_board.py and nhl_board.py use nav() too)
# Installable app tags for every hosted page (board/site/manifest.webmanifest, sw.js): Add to Home Screen on
# Android/iPhone and the Play Store wrapper (android/README.md). The service worker is network-first, so boards stay fresh.
APP_HEAD = ('<link rel="manifest" href="manifest.webmanifest">\n'
            '<meta name="theme-color" content="#1f6b3a">\n'
            '<link rel="icon" href="icons/favicon-32.png" sizes="32x32">\n'
            '<link rel="apple-touch-icon" href="icons/apple-touch-icon.png">\n'
            '<meta name="mobile-web-app-capable" content="yes">\n'
            '<meta name="apple-mobile-web-app-capable" content="yes">\n'
            '<meta name="apple-mobile-web-app-title" content="GoonerGamble">\n'
            "<script>if ('serviceWorker' in navigator) addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));</script>\n")
SPORT_CSS = """<style>
.sportnav { display: flex; gap: 6px; max-width: 1080px; margin: 0 auto; padding: 14px max(16px, env(safe-area-inset-left, 0px)) 0; flex-wrap: wrap; }
.sportnav a { font: 700 15px var(--display, sans-serif); letter-spacing: .08em; text-transform: uppercase; text-decoration: none; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; padding: 6px 16px; background: var(--panel); }
.sportnav a[aria-current="page"] { background: var(--ink); color: var(--bg); border-color: var(--ink); }
.sportnav a.bell { margin-left: auto; padding: 6px 12px; }
</style>"""
# NBA was removed on 2026-11-18 (no edge over DraftKings in 7 days of graded lines); nba.html is now a notice page
PAGES = [('nfl', 'NFL', 'index.html'), ('cfb', 'College', 'cfb.html'), ('nhl', 'NHL', 'nhl.html'), ('tennis', 'Tennis', 'tennis.html'), ('bank', 'Bank Builder', 'bank.html')]


# alerts setup page (board/site/alerts.html): push notifications when new boards post (scripts/push_alert.py)
BELL = '<a class="bell" href="alerts.html" aria-label="Alerts" title="Alerts">&#128276;</a>'


def nav(cur):
    return ('<nav class="sportnav" aria-label="Sport">' + ''.join(
        f'<a href="{h}"{" aria-current=\"page\"" if k == cur else ""}>{t}</a>' for k, t, h in PAGES) + BELL + '</nav>\n')


def safe_build(log_it=True):
    """For the board scripts: a Bank Builder failure never stops a board run."""
    try:
        return build(log_it)
    except Exception as e:
        import traceback; traceback.print_exc(); print('Bank Builder skipped:', e)
