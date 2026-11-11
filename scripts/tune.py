import sys; from model import *
import itertools
res=[]
for hl,al in itertools.product([90,150,250],[4,8,16]):
    rows=[]
    for s in [2023,2024,2025]:
        for wk in range(5,19):
            p=week_preds(s,wk,half_life=hl,alpha=al); rows.append(p)
    d=pd.concat(rows)
    res.append((hl,al,(d.pred_margin-d.result).abs().mean(),(d.spread_line-d.result).abs().mean(),(d.pred_total-d.total).abs().mean(),(d.total_line-d.total).abs().mean()))
for r in res: print('hl=%d a=%d  model MAE %.2f  line MAE %.2f | tot model %.2f line %.2f'%r)
