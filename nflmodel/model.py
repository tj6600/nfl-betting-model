import numpy as np, pandas as pd
from scipy.stats import norm
import os
GAMES_URL = 'https://github.com/nflverse/nfldata/raw/master/data/games.csv'
G = pd.read_csv(os.environ.get('NFL_GAMES_CSV', GAMES_URL), parse_dates=['gameday'])
G = G[G.season>=2018].copy()
TEAMS = sorted(set(G.home_team)|set(G.away_team)); TI={t:i for i,t in enumerate(TEAMS)}; N=len(TEAMS)

def fit(train, asof, half_life=120, alpha=8.0):
    tr = train.dropna(subset=['home_score'])
    age = (asof - tr.gameday).dt.days.values
    w = 0.5**(age/half_life)
    # offseason regression: games from earlier seasons count extra-discounted
    w = w * np.where(tr.season.values < asof.year if asof.month>=9 else tr.season.values < asof.year-1, 0.5, 1.0)
    n=len(tr); home=(tr.location=='Home').astype(float).values
    # rows: home points then away points. cols: off(N), def(N), home adv, intercept
    X=np.zeros((2*n,2*N+2)); y=np.zeros(2*n)
    hi=tr.home_team.map(TI).values; ai=tr.away_team.map(TI).values
    r=np.arange(n)
    X[r,hi]=1; X[r,N+ai]=-1; X[r,2*N]=home/2; X[r,2*N+1]=1; y[:n]=tr.home_score
    X[n+r,ai]=1; X[n+r,N+hi]=-1; X[n+r,2*N]=-home/2; X[n+r,2*N+1]=1; y[n:]=tr.away_score
    W=np.concatenate([w,w]); P=np.eye(2*N+2)*alpha; P[2*N,2*N]=P[2*N+1,2*N+1]=1e-6
    A=X.T@(X*W[:,None])+P; b=X.T@(W*y)
    return np.linalg.solve(A,b)

def predict(beta, games):
    hi=games.home_team.map(TI).values; ai=games.away_team.map(TI).values
    home=(games.location=='Home').astype(float).values
    ph=beta[2*N+1]+beta[hi]-beta[N+ai]+beta[2*N]*home/2
    pa=beta[2*N+1]+beta[ai]-beta[N+hi]-beta[2*N]*home/2
    out=games.copy(); out['pred_home']=ph; out['pred_away']=pa
    out['pred_margin']=ph-pa; out['pred_total']=ph+pa
    return out

def week_preds(season, week, **kw):
    tgt=G[(G.season==season)&(G.week==week)&(G.game_type=='REG')]
    asof=tgt.gameday.min()
    beta=fit(G[G.gameday<asof], asof, **kw)
    return predict(beta,tgt)

SD_M, SD_T = 13.5, 13.0
def novig(a,b):
    def ip(o): return np.where(o<0,-o/(-o+100),100/(o+100))
    x,y=ip(a),ip(b); return x/(x+y)

def annotate(p):
    p=p.copy()
    # spread_line = expected home margin per market (positive = home favored)
    p['p_home_cover']=1-norm.cdf(p.spread_line, p.pred_margin, SD_M)
    p['p_over']=1-norm.cdf(p.total_line, p.pred_total, SD_T)
    p['p_home_win']=1-norm.cdf(0, p.pred_margin, SD_M)
    p['mkt_home_win']=novig(p.home_moneyline,p.away_moneyline)
    return p
