"""Backtest NHL shots-on-goal and goalie-saves projections against real DraftKings lines.

Lines come from odds_log/nhl/history (python -m nhlmodel.odds history-props ...), taken 90 minutes before
puck drop. Models are fit on 2024-25 only and tested on 2025-26 lines, so nothing leaks.

  python scripts/nhl_props_backtest.py            # writes output/nhl_props_backtest.json
  python scripts/nhl_props_backtest.py --season 2026-27   # fit on 2024-26, test on this season's lines only
"""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import numpy as np
import pandas as pd
from nhlmodel.data import load
from nhlmodel.features import skater_features, goalie_features
from nhlmodel.props import SogModel, SavesModel, norm_name
from nhlmodel.odds import history_prop_rows
from nhlmodel.stats import p_over, am_to_prob, am_to_dec, novig

OUT = os.path.join(os.path.dirname(__file__), '..', 'output', 'nhl_props_backtest.json')
TRAIN = 20242025


def pair_lines(pr):
    """One row per (event, player, stat, point) with the Over and Under prices side by side."""
    pr = pr.sort_values('snap').drop_duplicates(['event', 'player', 'stat', 'point', 'side'], keep='last')
    w = pr.pivot_table(index=['event', 'start', 'home', 'away', 'stat', 'player', 'point'], columns='side',
                       values='price', aggfunc='first').reset_index()
    return w.dropna(subset=['Over', 'Under'])


def attach_games(lines, games):
    lines = lines.copy()
    lines['game_date'] = pd.to_datetime(lines.start).dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d')
    return lines.merge(games[['game_id', 'game_date', 'home', 'away']], on=['game_date', 'home', 'away'], how='inner')


def evaluate(df, label):
    """df has columns p_model, p_mkt, y (1 if over hit), Over, Under."""
    res = {'lines': int(len(df))}
    eps = 1e-6
    ll = lambda p: float(-np.mean(df.y * np.log(np.clip(p, eps, 1)) + (1 - df.y) * np.log(np.clip(1 - p, eps, 1))))
    res['logloss'] = {'model': ll(df.p_model), 'market': ll(df.p_mkt), 'blend_50': ll(0.5 * df.p_model + 0.5 * df.p_mkt)}
    res['over_rate'] = float(df.y.mean())
    res['brier'] = {'model': float(np.mean((df.p_model - df.y) ** 2)), 'market': float(np.mean((df.p_mkt - df.y) ** 2))}
    out = {}
    for name, p in [('model', df.p_model), ('blend_50', 0.5 * df.p_model + 0.5 * df.p_mkt)]:
        dO, dU = am_to_dec(df.Over), am_to_dec(df.Under)
        evO, evU = p * dO - 1, (1 - p) * dU - 1
        side_over = evO >= evU
        ev = np.where(side_over, evO, evU)
        win = np.where(side_over, df.y == 1, df.y == 0)
        price = np.where(side_over, df.Over, df.Under)
        dec = np.where(side_over, dO, dU)
        prob = np.where(side_over, p, 1 - p)
        rows = {}
        for th in [0.0, 0.03, 0.05, 0.08, 0.12]:
            m = ev >= th
            # "no heavy juice" version: only prices of -150 or longer
            mj = m & (price >= -150)
            rows[f'ev>={th:.2f}'] = {
                'bets': int(m.sum()), 'hit': float(win[m].mean()) if m.any() else None,
                'roi': float((np.where(win, dec - 1, -1)[m]).mean()) if m.any() else None,
                'avg_model_prob': float(prob[m].mean()) if m.any() else None,
                'overs': int((m & side_over).sum()),
                'no_heavy_juice': {'bets': int(mj.sum()), 'hit': float(win[mj].mean()) if mj.any() else None,
                                   'roi': float((np.where(win, dec - 1, -1)[mj]).mean()) if mj.any() else None},
            }
        out[name] = rows
    res['betting'] = out
    # calibration of the model's over chance
    q = pd.cut(df.p_model, [0, .2, .3, .4, .5, .6, .7, .8, 1])
    res['calibration'] = [{'bucket': str(k), 'n': int(len(v)), 'model': float(v.p_model.mean()), 'market': float(v.p_mkt.mean()),
                           'actual': float(v.y.mean())} for k, v in df.groupby(q, observed=True)]
    print(f'\n== {label}: {len(df)} lines, over rate {df.y.mean():.3f}')
    print('  log loss  model %.4f  market %.4f  blend %.4f' % tuple(res['logloss'].values()))
    for name, rows in out.items():
        for k, v in rows.items():
            if v['bets']:
                nj = v['no_heavy_juice']
                print(f"  {name:9s} {k}: {v['bets']:4d} bets hit {v['hit']:.3f} roi {v['roi']:+.3f} (overs {v['overs']})"
                      f" | -150 or better: {nj['bets']} hit {nj['hit'] if nj['hit'] is None else round(nj['hit'],3)} roi {nj['roi'] if nj['roi'] is None else round(nj['roi'],3)}")
    return res


def main():
    global OUT
    games, sk, go, tg = load()
    pr = history_prop_rows()
    lines = attach_games(pair_lines(pr), games)
    train, test = [TRAIN], 20252026
    if '--season' in sys.argv and sys.argv[sys.argv.index('--season') + 1] == '2026-27':
        train, test = [20242025, 20252026], 20262027
        OUT = OUT.replace('.json', '_2026-27.json')
    lines = lines.merge(games[['game_id', 'season']], on='game_id')
    lines = lines[lines.season == test].drop(columns='season')
    lines['key'] = lines.player.map(norm_name)
    lines['p_mkt'] = novig(am_to_prob(lines.Over), am_to_prob(lines.Under))[0]
    report = {}

    # shots on goal
    skf, lm = skater_features(sk, tg)
    m = SogModel().fit(skf, lm, skf.season.isin(train))
    skf['mu'] = m.mu(skf)
    skf['key'] = skf.full_name.map(norm_name)
    s = lines[lines.stat == 'sog'].merge(skf[['game_id', 'key', 'mu', 'sog', 'n_prior', 'team']], on=['game_id', 'key'], how='inner')
    s = s[s.n_prior >= 5]
    s['p_model'] = np.array([p_over(pt, mu, m.r)[0] for pt, mu in zip(s.point, s.mu)])
    s['y'] = (s.sog > s.point).astype(int)
    print('SOG lines matched', len(s), 'of', int((lines.stat == 'sog').sum()), '| NB size', round(m.r, 1))
    report['sog'] = evaluate(s, 'Shots on goal')
    report['sog']['by_line'] = {str(k): {'n': int(len(v)), 'over_rate': float(v.y.mean()), 'model': float(v.p_model.mean()),
                                         'market': float(v.p_mkt.mean())} for k, v in s.groupby('point')}

    # goalie saves
    st, lm2 = goalie_features(go, tg)
    gm = SavesModel().fit(st, lm2, st.season.isin(train))
    st['mu'] = gm.mu(st)
    st['key'] = st.full_name.map(norm_name)
    if not (lines.stat == 'saves').any():
        json.dump(report, open(OUT, 'w'), indent=1); s.to_csv(OUT.replace('.json', '_sog.csv'), index=False); return
    v = lines[lines.stat == 'saves'].merge(st[['game_id', 'key', 'mu', 'saves', 'n_starts']], on=['game_id', 'key'], how='inner')
    v['p_model'] = np.array([p_over(pt, mu, gm.r)[0] for pt, mu in zip(v.point, v.mu)])
    v['y'] = (v.saves > v.point).astype(int)
    print('Saves lines matched (starters only)', len(v), 'of', int((lines.stat == 'saves').sum()), '| NB size', round(gm.r, 1))
    report['saves'] = evaluate(v, 'Goalie saves')

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(report, open(OUT, 'w'), indent=1)
    s.to_csv(OUT.replace('.json', '_sog.csv'), index=False)
    v.to_csv(OUT.replace('.json', '_saves.csv'), index=False)


if __name__ == '__main__':
    main()
