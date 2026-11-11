"""Turn features into predicted margins/totals with a walk-forward linear model."""
import numpy as np, pandas as pd
from .stats import norm
from .model import G, novig

BASE_MARGIN_X = ['pts_margin', 'd_pass_epa', 'd_rush_epa', 'd_succ', 'd_qb', 'home', 'rest']
BASE_TOTAL_X = ['pts_total', 's_pass_epa', 's_rush_epa', 's_succ', 's_qb', 'dome', 'wind']
ROSTER_MARGIN_X = ['d_net_OL', 'd_net_SKILL', 'd_net_FRONT', 'd_net_DB', 'd_new_hc', 'd_interim_hc']
ROSTER_TOTAL_X = ['s_net_OL', 's_net_SKILL', 's_net_FRONT', 's_net_DB']
SCHEME_MARGIN_X = ['d_m_man', 'd_m_blitz', 'd_m_pa']
SCHEME_TOTAL_X = ['s_m_man', 's_m_blitz', 's_m_pa']
MARGIN_X = BASE_MARGIN_X + ROSTER_MARGIN_X + SCHEME_MARGIN_X
TOTAL_X = BASE_TOTAL_X + ROSTER_TOTAL_X + SCHEME_TOTAL_X


def load(feat_csv):
    f = pd.read_csv(feat_csv)
    cols = ['game_id', 'season', 'week', 'gameday', 'away_team', 'home_team', 'away_score', 'home_score',
            'result', 'total', 'spread_line', 'total_line', 'home_moneyline', 'away_moneyline',
            'home_spread_odds', 'away_spread_odds', 'over_odds', 'under_odds', 'home_qb_name', 'away_qb_name']
    return f.merge(G[cols], on='game_id')


def _ridge(X, y, alpha=1.0):
    X1 = np.column_stack([X, np.ones(len(X))])
    P = np.eye(X1.shape[1]) * alpha; P[-1, -1] = 0
    return np.linalg.solve(X1.T @ X1 + P, X1.T @ y)


def _apply(b, X):
    return np.column_stack([X, np.ones(len(X))]) @ b


def fit_predict(df, train_mask, test_mask, market_anchor=False, margin_x=None, total_x=None):
    MARGIN_X, TOTAL_X = margin_x or globals()['MARGIN_X'], total_x or globals()['TOTAL_X']
    tr, te = df[train_mask & df.result.notna()], df[test_mask].copy()
    sd = tr[MARGIN_X].std().replace(0, 1); st = tr[TOTAL_X].std().replace(0, 1)
    if market_anchor:
        # learn only how far to move off the market line
        bm = _ridge(np.column_stack([(tr[MARGIN_X] / sd).values, tr.spread_line]), tr.result.values, 5.0)
        bt = _ridge(np.column_stack([(tr[TOTAL_X] / st).values, tr.total_line]), tr.total.values, 5.0)
        te['pred_margin'] = _apply(bm, np.column_stack([(te[MARGIN_X] / sd).values, te.spread_line]))
        te['pred_total'] = _apply(bt, np.column_stack([(te[TOTAL_X] / st).values, te.total_line]))
        rm = tr.result - _apply(bm, np.column_stack([(tr[MARGIN_X] / sd).values, tr.spread_line]))
        rt = tr.total - _apply(bt, np.column_stack([(tr[TOTAL_X] / st).values, tr.total_line]))
    else:
        bm = _ridge((tr[MARGIN_X] / sd).values, tr.result.values)
        bt = _ridge((tr[TOTAL_X] / st).values, tr.total.values)
        te['pred_margin'] = _apply(bm, (te[MARGIN_X] / sd).values)
        te['pred_total'] = _apply(bt, (te[TOTAL_X] / st).values)
        rm = tr.result - _apply(bm, (tr[MARGIN_X] / sd).values)
        rt = tr.total - _apply(bt, (tr[TOTAL_X] / st).values)
    te['sd_margin'], te['sd_total'] = rm.std(), rt.std()
    return probabilities(te)


def american_to_decimal(o):
    o = np.asarray(o, float)
    return np.where(o < 0, 1 + 100 / -o, 1 + o / 100)


def probabilities(p):
    p = p.copy()
    # spread_line = market's expected home margin. Half-point lines have no push.
    p['p_home_cover'] = 1 - norm.cdf(p.spread_line, p.pred_margin, p.sd_margin)
    p['p_over'] = 1 - norm.cdf(p.total_line, p.pred_total, p.sd_total)
    p['p_home_win'] = 1 - norm.cdf(0, p.pred_margin, p.sd_margin)
    p['mkt_home_win'] = novig(p.home_moneyline, p.away_moneyline)
    return p


def legs(p):
    """Every main-market leg with model probability, market odds and expected value per $1."""
    rows = []
    for _, g in p.iterrows():
        def add(market, pick, prob, odds, won):
            dec = float(american_to_decimal(odds)) if pd.notna(odds) else np.nan
            rows.append(dict(game=f'{g.away_team} @ {g.home_team}', market=market, pick=pick, model_prob=prob,
                             odds=odds, implied=1 / dec if dec == dec else np.nan, ev=prob * dec - 1, won=won))
        res, tot = g.result, g.total
        sl = g.spread_line
        add('spread', f'{g.home_team} {-sl:+g}', g.p_home_cover, g.home_spread_odds, None if pd.isna(res) else res > sl)
        add('spread', f'{g.away_team} {sl:+g}', 1 - g.p_home_cover, g.away_spread_odds, None if pd.isna(res) else res < sl)
        add('total', f'Over {g.total_line:g}', g.p_over, g.over_odds, None if pd.isna(tot) else tot > g.total_line)
        add('total', f'Under {g.total_line:g}', 1 - g.p_over, g.under_odds, None if pd.isna(tot) else tot < g.total_line)
        add('moneyline', g.home_team, g.p_home_win, g.home_moneyline, None if pd.isna(res) else res > 0)
        add('moneyline', g.away_team, 1 - g.p_home_win, g.away_moneyline, None if pd.isna(res) else res < 0)
    return pd.DataFrame(rows)
