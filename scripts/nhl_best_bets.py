"""Print today's NHL best bets from the built board (board/site/nhl.html): straight bets and 2-4 leg parlays.

Uses the board's own rules. Straight bets: Value legs (edge 3+ pts, chance 55%+, no flag), then the most likely
legs that still have an edge of 1+ pt. Parlays: the parlay builder's "Most likely to hit" pool (chance 55%+, edge 1+
or a winner pick, priced -200 or longer, no flag), one leg per game, highest chance first. Parlay chances assume
the legs are independent (they're in different games). Free: reads the page, no API calls.

  python scripts/nhl_best_bets.py
"""
import os, re, json, itertools

ROOT = os.path.join(os.path.dirname(__file__), '..')


def dec(a): return 1 + a / 100 if a > 0 else 1 + 100 / -a
def am(d): return f'+{round((d - 1) * 100)}' if d >= 2 else f'{round(-100 / (d - 1))}'


def main():
    h = open(os.path.join(ROOT, 'board', 'site', 'nhl.html')).read()
    D = json.loads(re.search(r'id="nhl-data"[^>]*>(.*?)</script>', h, re.S).group(1))
    legs = D['legs']
    fmt = lambda l: f"{l['label']} ({l['game']}, {l['kind']}) {l['price']:+d}: chance {l['p']:.0%}, edge {l['edge']:+.1f} pts"
    props = sum(l['kind'] in ('Shots on goal', 'Saves') for l in legs)
    print(f"NHL best bets for {D.get('dayLabel', D['day'])} (DraftKings prices; {props} prop legs priced)\n")
    clean = [l for l in legs if not l['flags'] and l['price'] >= -200]
    value = sorted([l for l in clean if l.get('cat') == 'Value'], key=lambda l: -l['edge'])
    likely = sorted([l for l in clean if l['p'] >= 0.55 and l['edge'] >= 1 and l not in value], key=lambda l: -l['p'])
    print('STRAIGHT BETS')
    straights = (value + likely)[:8]
    for l in straights:
        print(f"  {'[Value] ' if l in value else ''}{fmt(l)}")
    if not straights:
        print('  none meet the rules today')
    pool = sorted([l for l in clean if l['p'] >= 0.55 and (l['edge'] >= 1 or l.get('pick'))], key=lambda l: (-l['p'], -l['edge']))
    for size in (2, 3, 4):
        print(f'\n{size}-LEG PARLAYS')
        used, n = set(), 0
        for _ in range(2):
            slip, games = [], set()
            for l in pool:
                if l['id'] in used or l['game'] in games:
                    continue
                slip.append(l); games.add(l['game'])
                if len(slip) == size:
                    break
            if len(slip) < size:
                break
            used.update(l['id'] for l in slip); n += 1
            p = 1.0; d = 1.0
            for l in slip:
                p *= l['p']; d *= dec(l['price'])
            print(f"  Slip {n}: DK about {am(d)}, chance {p:.0%}, expected return {p * d - 1:+.0%}")
            for l in slip:
                print(f'    - {fmt(l)}')
        if not n:
            print('  not enough qualifying legs in different games')


if __name__ == '__main__':
    main()
