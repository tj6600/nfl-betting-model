"""Calibration sections for the Model record tabs (NFL, NBA, NHL), one section per leg type (Thomas, 2026-11-17).

Each section answers: when the board gave a side a chance of 50-60%, 60-70%, ... how often did that side win?
The page draws one bar per chance bucket (the actual hit rate) with a dashed line at the chance the board gave.

rows: dicts with p (the chance the board gave the side it chose), won (True/False; pushes and voids are left out)
and units (profit for 1 unit at the logged DraftKings price).
"""

# a chosen side is the one the board gave 50%+, so its buckets start at 50%; one-sided bets (anytime TDs, alt rungs)
# can be any chance, so they use the full range
BINS_PICK = [(0, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01)]
BINS_ALL = [(0, .1), (.1, .2), (.2, .3), (.3, .4), (.4, .5), (.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.01)]


def section(name, rows, note=None, picked=True):
    """One section: totals plus a bucket per 10 points of chance. picked=True: every row is the side the board favored."""
    rows = [r for r in rows if r.get('won') is not None and r.get('p') == r.get('p') and r.get('p') is not None]
    if not rows: return None
    bins = BINS_PICK if picked else BINS_ALL
    buckets = []
    for lo, hi in bins:
        x = [r for r in rows if lo <= r['p'] < hi]
        if not x: continue
        w = sum(bool(r['won']) for r in x)
        buckets.append(dict(label=f'{50 if picked and lo == 0 else round(lo * 100)}–{min(100, round(hi * 100))}%', n=len(x), won=w, lost=len(x) - w,
                            said=round(float(sum(r['p'] for r in x)) / len(x), 4), hit=round(w / len(x), 4), units=round(float(sum(r['units'] for r in x)), 2)))
    w = sum(bool(r['won']) for r in rows); u = float(sum(r['units'] for r in rows))
    return dict(name=name, note=note, n=len(rows), won=w, lost=len(rows) - w, said=round(float(sum(r['p'] for r in rows)) / len(rows), 4),
                hit=round(w / len(rows), 4), units=round(u, 2), roi=round(u / len(rows), 4), buckets=buckets)


def favored(rows, key):
    """Keep the side the board gave the bigger chance in each group of rows sharing key(row) (both sides of a line are logged)."""
    best = {}
    for r in rows:
        k = key(r)
        if k not in best or r['p'] > best[k]['p']: best[k] = r
    return list(best.values())


def sections(*specs):
    """specs: (name, rows, note, picked) tuples -> the non-empty sections, in order."""
    return [s for s in (section(*sp) for sp in specs) if s]


def dec(a): return 1 + a / 100 if a > 0 else 1 + 100 / -a


# ---------- day / week / month menus on the Model record tabs (Thomas, 2026-11-18) ----------
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
MAX_DAYS = 31    # the Day menu lists the latest 31 game days, so the page stays small


def _d(s):
    import datetime as dt
    return dt.date.fromisoformat(str(s)[:10])


def _short(d): return f'{MONTHS[d.month - 1]} {d.day}'


def monday_week(day):
    """(key, label) of the Monday-to-Sunday week holding day ('YYYY-MM-DD')."""
    import datetime as dt
    d = _d(day); a = d - dt.timedelta(days=d.weekday()); b = a + dt.timedelta(days=6)
    return a.isoformat(), f'{_short(a)} – {b.day}' if a.month == b.month else f'{_short(a)} – {_short(b)}'


def periods(dates, week_of=monday_week):
    """dates: the game days (YYYY-MM-DD) with graded bets. Returns (menu, groups):
    menu = {'day': [{key, label}], 'week': [...], 'month': [...]}, newest first;
    groups = {key: set of dates in that period}. Keys look like d:2026-11-17, w:<week key>, m:2026-11."""
    ds = sorted({str(x)[:10] for x in dates if x})
    menu, groups = {'day': [], 'week': [], 'month': []}, {}
    for s in ds[::-1][:MAX_DAYS]:
        d = _d(s); k = 'd:' + s
        menu['day'].append(dict(key=k, label=f'{WEEKDAYS[d.weekday()]} {_short(d)}')); groups[k] = {s}
    wk = {}
    for s in ds:
        k, lab = week_of(s); wk.setdefault('w:' + k, [lab, set()])[1].add(s)
    for k in sorted(wk, reverse=True):
        menu['week'].append(dict(key=k, label=wk[k][0])); groups[k] = wk[k][1]
    mo = {}
    for s in ds: mo.setdefault('m:' + s[:7], set()).add(s)
    for k in sorted(mo, reverse=True):
        y, m = int(k[2:6]), int(k[7:9])
        menu['month'].append(dict(key=k, label=f'{MONTHS_LONG[m - 1]} {y}')); groups[k] = mo[k]
    return menu, groups


def by_period(dates, build, week_of=monday_week):
    """build(set_of_dates) -> the report for those days. Returns {'menu': ..., 'reports': {key: report}} for the page."""
    menu, groups = periods(dates, week_of)
    return dict(menu=menu, reports={k: build(v) for k, v in groups.items()})


# ---------- bets still waiting on a result, for the Refresh results button (Thomas, 2026-11-18) ----------
# The page grades these itself from ESPN's free scoreboard and box scores, then adds each result to the record groups,
# chance-check sections and day/week/month reports listed here. The next grading run makes them official.
import re as _re
NAME_RX = _re.compile(r'^(.*?) (?:(?:Over|Under) [\d.]+ |\d+\+ |anytime TD)')


def player_name(label):
    m = NAME_RX.match(str(label)); return m.group(1) if m else None


def period_keys(day, week_of=monday_week):
    """[[key, label], ...] of the day, week and month menus a game day belongs to."""
    d = _d(day); wk, wl = week_of(str(day)[:10])
    return [['d:' + str(day)[:10], f'{WEEKDAYS[d.weekday()]} {_short(d)}'], ['w:' + wk, wl], ['m:' + str(day)[:7], f'{MONTHS_LONG[d.month - 1]} {d.year}']]


class Pending:
    """Collects waiting legs and parlays in a compact form for the page (calib.Pending().add_leg(...); .out())."""
    def __init__(self, push_counts=False):
        self.g, self.c, self.per, self.legs, self.parlays, self.push = [], [], {}, {}, [], push_counts

    def _gi(self, path, name):
        x = [path, name]
        if x not in self.g: self.g.append(x)
        return self.g.index(x)

    def _ci(self, path, name, picked, note):
        for i, c in enumerate(self.c):
            if c[:2] == [path, name]: return i
        self.c.append([path, name, bool(picked), note]); return len(self.c) - 1

    def _pk(self, day, week_of):
        ks = []
        for k, lab in period_keys(day, week_of): self.per[k] = lab; ks.append(k)
        return ks

    def add_leg(self, key, day, grade, price, p, groups=(), cal=None, week_of=monday_week):
        """grade: how the page finds the result (ev/wk/t/m/st/sd/ln/pid/nm); groups: [(path, name)];
        cal: (path, section, picked, note) or None."""
        L = self.legs.get(key)
        if L is None:
            L = self.legs[key] = dict(k=key, d=str(day)[:10] if day else None, x=grade, pr=int(price), p=round(float(p), 4), g=[], c=[],
                                      per=self._pk(day, week_of) if day else [])
        for path, name in groups:
            i = self._gi(path, name)
            if i not in L['g']: L['g'].append(i)
        if cal and self._ci(*cal) not in L['c']: L['c'].append(self._ci(*cal))
        return L

    def add_parlay(self, day, legs, groups, p, week_of=monday_week):
        """legs: [(leg key, known result or None, DK price)]; a parlay waits while no leg lost and some leg has no result."""
        self.parlays.append(dict(d=str(day)[:10] if day else None, l=[[k, r, int(pr)] for k, r, pr in legs], g=sorted({self._gi(*x) for x in groups}),
                                 p=round(float(p), 5), per=self._pk(day, week_of) if day else []))

    def out(self):
        """Compact for the page: legs are [key, day, x, price, p, [group idx], [cal idx]]; x is [ev, m, st, side, line, who, week];
        parlays are [day, [[leg key, result, price]], [group idx], p]; days maps each day to its menu keys."""
        need = {k for pz in self.parlays for k, r, _ in pz['l'] if r is None}
        legs = [L for L in self.legs.values() if L['g'] or L['c'] or L['k'] in need]
        X = compact_x
        days = {}
        for L in legs: days[L['d']] = L['per']
        for pz in self.parlays: days[pz['d']] = pz['per']
        return dict(push=self.push, g=self.g, c=self.c, per=self.per, days={d: v for d, v in days.items() if d},
                    legs=[[L['k'], L['d'], X(L['x']), L['pr'], L['p'], L['g'], L['c']] for L in legs],
                    parlays=[[pz['d'], pz['l'], pz['g'], pz['p']] for pz in self.parlays])


def compact_x(x):
    """A leg's ESPN lookup as the page reads it: [event id, market, stat, side, line, player id or name, NFL week / NHL position]."""
    return [x.get('ev'), x.get('m'), x.get('st'), x.get('sd'), x.get('ln'), x.get('pid') or x.get('nm'), x.get('wk')]


def csv_x(sport, r):
    """ESPN lookup for a row of an NBA or NHL pick log (odds_log/<sport>/picks/*.csv), as the graders build it."""
    away, home = str(r['game']).split(' @ ')
    ev = str(abs(int(float(r['gid']))))
    line = None if r.get('line') in (None, '') or r['line'] != r['line'] else float(r['line'])
    mk = {'moneyline': 'ml', 'spread': 'sp', 'puckline': 'sp', 'total': 'tot'}.get(r['market'])
    if mk: return dict(ev=ev, m=mk, sd=r['side'] if mk == 'tot' else ('home' if r['side'] == home else 'away'), ln=line)
    if sport == 'NBA': return dict(ev=ev, m='stat', st=r['market'], sd=r['side'], ln=line, pid=str(int(float(r['pid']))))
    return dict(ev=ev, m='stat', st=r['market'], sd=r['side'], ln=line, nm=player_name(r['label']), wk='G' if r['market'] == 'saves' else None)
