import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from nflmodel.features import all_features
f = all_features(range(2019, 2027))
f.to_csv(os.path.join(os.path.dirname(__file__), '..', 'data', 'features.csv'), index=False)
print(f.shape); print(f.describe().T.round(3))
