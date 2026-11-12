"""NBA player props: projected points, rebounds, assists, threes and P+R+A, with over/under chances.

Projection = expected minutes x per-minute rate x opponent factor x game-total factor, all from games
before the target game:
  * minutes: EWM of minutes in games played (half-life 4 games); players returning from a long absence
    are flagged.
  * rate: minutes-weighted EWM of the stat per minute (half-life 12 games), shrunk toward his position
    average with 60 pseudo-minutes.
  * opponent: what the opponent allowed per minute to that position (G/F/C) vs league, EWM over its
    games, shrunk and taken to the 0.5 power.
  * game total: the market total (else the teams' recent totals) vs league average, to the 0.5 power.
Over/under chances come from the empirical spread of actual / projected in past games, grouped by stat
and projection size, so they carry minutes risk, blowouts and foul trouble.
"""
import numpy as np, pandas as pd

STATS = ['pts', 'reb', 'ast', 'fg3m', 'pra']
LABEL = {'pts': 'Points', 'reb': 'Rebounds', 'ast': 'Assists', 'fg3m': 'Threes', 'pra': 'Pts+Reb+Ast'}
MARKET = {'player_points': 'pts', 'player_rebounds': 'reb', 'player_assists': 'ast', 'player_threes': 'fg3m',
          'player_points_rebounds_assists': 'pra'}
POSG = {'PG': 'G', 'SG': 'G', 'G': 'G', 'SF': 'F', 'PF': 'F', 'F': 'F', 'C': 'C'}


def _ewm(s, hl):
    return s.shift(1).ewm(halflife=hl, ignore_na=True).mean()


def features(P, G, totals=None):
    """Pre-game features for every player-game row in P (rows for upcoming games may have NaN stats)."""
    p = P.copy()
    p['pra'] = p.pts + p.reb + p.ast
    p['pg'] = p.pos.map(POSG).fillna('F')
    p['played'] = (~p.dnp.astype(bool)) & (p['min'] > 0)
    p = p.sort_values(['pid', 'date', 'game_id']).reset_index(drop=True)
    g = p.groupby('pid', sort=False)
    m = p['min'].where(p.played)
    p['m_ewm'] = g['min'].transform(lambda s: _ewm(s.where(p.loc[s.index, 'played']), 4))
    p['m_ewm10'] = g['min'].transform(lambda s: _ewm(s.where(p.loc[s.index, 'played']), 10))
    p['n_prev'] = g.played.transform(lambda s: s.shift(1).fillna(False).astype(int).cumsum())
    p['start_prev'] = g.starter.shift(1)
    # games since his last appearance (team games, roughly) and days since
    lastd = pd.to_datetime(p.date.where(p.played))
    p['last_played'] = lastd.groupby(p.pid).transform(lambda s: s.shift(1).ffill())
    p['days_off'] = (pd.to_datetime(p.date) - p.last_played).dt.days
    for k in STATS:
        num = g[k].transform(lambda s: _ewm(s.where(p.loc[s.index, 'played']), 12))
        p[f'{k}_pm_raw'] = num / p.m_ewm10.replace(0, np.nan)
    # league position averages per minute (by season, from played games)
    pl = p[p.played]
    for k in STATS:
        pos = (pl.groupby(['season', 'pg'])[k].sum() / pl.groupby(['season', 'pg'])['min'].sum()).rename(f'{k}_pos')
        p = p.merge(pos, left_on=['season', 'pg'], right_index=True, how='left')
        w = (p.n_prev.clip(upper=40) * p.m_ewm10.fillna(0)).fillna(0)
        p[f'{k}_pm'] = (p[f'{k}_pm_raw'].fillna(p[f'{k}_pos']) * w + p[f'{k}_pos'] * 60) / (w + 60)
    # opponent allowed per minute to position group
    tg = pl.groupby(['game_id', 'date', 'opp', 'pg'])[STATS + ['min']].sum().reset_index().sort_values('date')
    for k in STATS:
        tg[f'{k}_r'] = tg[k] / tg['min']
    og = tg.groupby(['opp', 'pg'])
    lg = {k: (pl[k].sum() / pl['min'].sum()) for k in STATS}
    opp = tg[['game_id', 'opp', 'pg']].copy()
    for k in STATS:
        opp[f'{k}_opp'] = og[f'{k}_r'].transform(lambda s: s.shift(1).ewm(halflife=15).mean())
        opp[f'{k}_oppn'] = og[f'{k}_r'].transform(lambda s: s.shift(1).notna().cumsum())
    # rows for upcoming games need the latest value: carry forward per (opp, pg)
    latest = tg.groupby(['opp', 'pg']).apply(lambda d: pd.Series({f'{k}_opp': d[f'{k}_r'].ewm(halflife=15).mean().iloc[-1] for k in STATS}))
    p = p.merge(opp, on=['game_id', 'opp', 'pg'], how='left')
    for k in STATS:
        miss = p[f'{k}_opp'].isna()
        if miss.any():
            fill = p.loc[miss, ['opp', 'pg']].merge(latest[[f'{k}_opp']], left_on=['opp', 'pg'], right_index=True, how='left')[f'{k}_opp']
            p.loc[miss, f'{k}_opp'] = fill.values
        f = (p[f'{k}_opp'] / p.season.map(lambda s: lg[k])).fillna(1.0)
        p[f'{k}_of'] = (1 + (f - 1) * 0.7) ** 0.5
    # game total factor
    gt = G.assign(tot=G.hs + G.as_)
    long = pd.concat([gt[['game_id', 'date', 'home', 'tot']].rename(columns={'home': 't'}), gt[['game_id', 'date', 'away', 'tot']].rename(columns={'away': 't'})]).sort_values('date')
    long['t_ewm'] = long.groupby('t').tot.transform(lambda s: s.shift(1).ewm(halflife=10).mean())
    te = long.set_index(['game_id', 't']).t_ewm
    p['team_tot'] = [te.get((a, b), np.nan) for a, b in zip(p.game_id, p.team)]
    p['opp_tot'] = [te.get((a, b), np.nan) for a, b in zip(p.game_id, p.opp)]
    lt = G.set_index('game_id').total
    p['mkt_total'] = p.game_id.map(lt)
    if totals:
        p['mkt_total'] = p.mkt_total.fillna(p.game_id.map(totals))
    lg_tot = (gt.tot).groupby(gt.season).mean()
    exp_tot = p.mkt_total.fillna((p.team_tot + p.opp_tot) / 2)
    p['tf'] = (exp_tot / p.season.map(lg_tot)).fillna(1.0) ** 0.5
    for k in STATS:
        p[f'{k}_proj'] = p.m_ewm * p[f'{k}_pm'] * p[f'{k}_of'] * p.tf
    return p


def eligible(f):
    """Rows we project: regular role, has played recently."""
    return (f.n_prev >= 3) & (f.m_ewm >= 12) & (f.days_off <= 21)


BUCKETS = {'pts': [0, 8, 12, 16, 20, 25, 99], 'reb': [0, 3, 5, 7, 9, 99], 'ast': [0, 2, 3.5, 5, 7, 99],
           'fg3m': [0, 1, 1.75, 2.5, 3.25, 99], 'pra': [0, 14, 20, 26, 32, 40, 99]}


class Spread:
    """Empirical distribution of actual / projected, per stat and projection bucket (from played games;
    a DNP after being projected is rare and is voided by books)."""
    def fit(self, f):
        self.r = {}
        for k in STATS:
            d = f[eligible(f) & f.played & f[f'{k}_proj'].notna() & (f[f'{k}_proj'] > 0)]
            b = pd.cut(d[f'{k}_proj'], BUCKETS[k], labels=False)
            self.r[k] = {i: np.sort((d[k] / d[f'{k}_proj'])[b == i].values) for i in range(len(BUCKETS[k]) - 1)}
        return self

    def p_over(self, k, proj, line):
        proj = np.atleast_1d(np.asarray(proj, float)); line = np.atleast_1d(np.asarray(line, float))
        b = np.clip(np.digitize(proj, BUCKETS[k]) - 1, 0, len(BUCKETS[k]) - 2)
        out = np.empty(len(proj))
        for j, (pj, ln, bi) in enumerate(zip(proj, line, b)):
            r = self.r[k][bi]
            out[j] = 1 - np.searchsorted(r, ln / pj, side='right') / len(r) if len(r) else np.nan
        return out

    def quantiles(self, k, proj, qs=(0.1, 0.5, 0.9)):
        b = int(np.clip(np.digitize(proj, BUCKETS[k]) - 1, 0, len(BUCKETS[k]) - 2))
        r = self.r[k][b]
        return [float(np.quantile(r, q) * proj) for q in qs]
