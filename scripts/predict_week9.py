import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from nflmodel.model import *
p=annotate(week_preds(2026,9,half_life=150,alpha=8))
p['edge_spread']=p.pred_margin-p.spread_line; p['edge_total']=p.pred_total-p.total_line
c=['away_team','home_team','away_score','home_score','spread_line','pred_margin','edge_spread','result','total_line','pred_total','edge_total','total','p_home_win','mkt_home_win','home_moneyline','away_moneyline']
pd.set_option('display.width',250); print(p[c].round(2).to_string(index=False))
p.to_csv('output/2026_week9_predictions.csv',index=False)
