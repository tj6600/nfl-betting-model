import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from nflmodel.model import *
rows=[]
for s in [2023,2024,2025]:
    for wk in range(5,19): rows.append(annotate(week_preds(s,wk,half_life=150,alpha=8)))
d=pd.concat(rows).dropna(subset=['result'])
d=d[d.result!=d.spread_line]
edge=d.pred_margin-d.spread_line
for th in [0,2,3,4,6]:
    m=edge.abs()>=th; win=(np.sign(edge[m])==np.sign((d.result-d.spread_line)[m]))
    print(f'spread |edge|>={th}: n={m.sum()} hit={win.mean():.3f}')
d2=d[d.total!=d.total_line]; e=d2.pred_total-d2.total_line
for th in [0,2,3,4,6]:
    m=e.abs()>=th; win=(np.sign(e[m])==np.sign((d2.total-d2.total_line)[m]))
    print(f'total |edge|>={th}: n={m.sum()} hit={win.mean():.3f}')
# favourites moneyline 'secure' : model win prob >=0.75
p=np.maximum(d.p_home_win,1-d.p_home_win); m=p>=0.75
fav_home=d.p_home_win>=0.5; won=np.where(fav_home,d.result>0,d.result<0)
print('model p>=.75 picks: n',m.sum(),'won',won[m].mean())
