"""Pre-game features built only from earlier games (every rolling value is shifted one game)."""
import numpy as np
import pandas as pd


def _ewm(df, key, cols, hl, prefix):
    g = df.groupby(key, sort=False)
    for c in cols:
        df[f'{prefix}{c}'] = g[c].transform(lambda s: s.ewm(halflife=hl, min_periods=1).mean().shift(1))
    return df


def team_form(tg, hl=15):
    """Rolling team shot/xG rates for and against, plus rest days."""
    tg = tg.sort_values(['game_date', 'game_id']).copy()
    tg['date'] = pd.to_datetime(tg.game_date)
    tg = _ewm(tg, 'team', ['sf', 'sa', 'cf', 'ca', 'xgf', 'xga', 'gf', 'ga', 'pp_cf', 'pk_ca'], hl, 't_')
    tg['rest'] = tg.groupby('team').date.diff().dt.days.fillna(5).clip(upper=5)
    tg['n_team'] = tg.groupby('team').cumcount()
    return tg


def league_means(tg):
    return {c: float(tg[c].mean()) for c in ['sf', 'cf', 'xgf', 'gf', 'pp_cf']}


def opp_view(tf):
    """Opponent's rolling numbers, keyed by (game_id, team) of the side facing them."""
    cols = [c for c in tf.columns if c.startswith('t_')] + ['rest']
    o = tf[['game_id', 'team'] + cols].rename(columns={'team': 'opp', **{c: 'o' + c for c in cols}})
    return o


def skater_features(sk, tg, hl_short=6, hl_long=25):
    sk = sk.sort_values(['game_date', 'game_id']).copy()
    sk['toi'] = sk.toi.clip(lower=0)
    sk = _ewm(sk, 'player_id', ['sog', 'icf', 'toi', 'pp_cf', 'ixg', 'blocked_shots'], hl_short, 's_')
    sk = _ewm(sk, 'player_id', ['sog', 'icf', 'toi', 'pp_cf', 'ixg', 'blocked_shots'], hl_long, 'l_')
    sk['n_prior'] = sk.groupby('player_id').cumcount()
    sk['last_toi'] = sk.groupby('player_id').toi.shift(1)
    sk['date'] = pd.to_datetime(sk.game_date)
    sk['days_off'] = sk.groupby('player_id').date.diff().dt.days
    tf = team_form(tg)
    lm = league_means(tg)
    sk = sk.merge(tf[['game_id', 'team', 't_sf', 't_cf', 't_pp_cf', 'rest', 'n_team']], on=['game_id', 'team'], how='left')
    o = opp_view(tf)
    sk = sk.merge(o[['game_id', 'opp', 'ot_sa', 'ot_ca', 'ot_pk_ca']], on=['game_id', 'opp'], how='left')
    sk['is_d'] = (sk.position == 'D').astype(int)
    sk['b2b'] = (sk.rest == 1).astype(int)
    return sk, lm


SOG_X = ['c', 'lg_s_sog', 'lg_l_sog', 'lg_l_icf', 'lg_s_toi', 'lg_l_pp', 'lg_opp_sa', 'lg_team_sf', 'is_home', 'is_d', 'b2b']


def sog_design(sk, lm):
    e = 0.05
    X = pd.DataFrame(index=sk.index)
    X['c'] = 1.0
    X['lg_s_sog'] = np.log(sk.s_sog + e)
    X['lg_l_sog'] = np.log(sk.l_sog + e)
    X['lg_l_icf'] = np.log(sk.l_icf + e)
    X['lg_s_toi'] = np.log(sk.s_toi.clip(lower=3) / 16)
    X['lg_l_pp'] = np.log(sk.l_pp_cf + 0.1)
    X['lg_opp_sa'] = np.log(sk.ot_sa.fillna(lm['sf']) / lm['sf'])
    X['lg_team_sf'] = np.log(sk.t_sf.fillna(lm['sf']) / lm['sf'])
    X['is_home'] = sk.is_home
    X['is_d'] = sk.is_d
    X['b2b'] = sk.b2b
    return X[SOG_X]


def goalie_features(go, tg):
    """One row per starting goalie: saves target plus the opponent's shot volume and the goalie's save rate."""
    go = go.sort_values(['game_date', 'game_id']).copy()
    st = go[go.starter == True].copy()
    st['sv_rate'] = np.where(st.shots_against > 0, st.saves / st.shots_against.clip(lower=1), np.nan)
    st['full_game'] = (st.toi >= 55).astype(int)
    g = st.groupby('player_id')
    # save percentage, shrunk toward league average with 600 shots of prior
    st['cum_sa'] = g.shots_against.transform(lambda s: s.shift(1).rolling(60, min_periods=1).sum())
    st['cum_sv'] = g.saves.transform(lambda s: s.shift(1).rolling(60, min_periods=1).sum())
    lg = st.saves.sum() / st.shots_against.sum()
    st['sv_hat'] = (st.cum_sv.fillna(0) + 600 * lg) / (st.cum_sa.fillna(0) + 600)
    st['g_pull'] = g.full_game.transform(lambda s: 1 - s.shift(1).rolling(40, min_periods=1).mean())
    st['n_starts'] = g.cumcount()
    tf = team_form(tg)
    lm = league_means(tg)
    st = st.merge(tf[['game_id', 'team', 't_sa', 't_ca', 't_xga', 'rest']], on=['game_id', 'team'], how='left')
    o = opp_view(tf)
    st = st.merge(o[['game_id', 'opp', 'ot_sf', 'ot_cf', 'ot_xgf']], on=['game_id', 'opp'], how='left')
    st['b2b'] = (st.rest == 1).astype(int)
    st['lg_sv'] = lg
    return st, lm


SAVE_X = ['c', 'lg_opp_cf', 'lg_team_ca', 'is_home', 'b2b']


def saves_design(st, lm):
    X = pd.DataFrame(index=st.index)
    X['c'] = 1.0
    # shot attempts are steadier than shots on goal, and backtested slightly better against DraftKings
    X['lg_opp_cf'] = np.log(st.ot_cf.fillna(lm['cf']) / lm['cf'])
    X['lg_team_ca'] = np.log(st.t_ca.fillna(lm['cf']) / lm['cf'])
    X['is_home'] = st.is_home
    X['b2b'] = st.b2b
    return X[SAVE_X]
