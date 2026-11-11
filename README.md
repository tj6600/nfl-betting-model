# NFL betting model

A baseline model that predicts NFL game margins and totals, compares them with bookmaker lines, and backtests the picks.

**No model guarantees profit.** The bookmaker margin (about 4.5% on spreads at -110) has to be beaten first, and closing lines are very efficient.

## How it works

- **Data:** [nflverse/nfldata](https://github.com/nflverse/nfldata) `games.csv` (scores, spreads, totals, moneylines, 2018+). Set `NFL_GAMES_CSV` to use a local copy.
- **Model** (`nflmodel/model.py`): weighted ridge regression on points scored. Each team gets an offense and a defense rating, plus a shared home-field term. Older games are down-weighted (150-day half-life), and earlier seasons are discounted further.
- **Probabilities:** the predicted margin and total are treated as normal distributions (SD 13.5 and 13.0), which gives cover, over and win probabilities. Market win probabilities come from the moneylines with the margin removed.

## Scripts

| Script | What it does |
|---|---|
| `scripts/predict_week9.py` | Predicts 2026 week 9 using only games before it |
| `scripts/backtest_ats.py` | Walk-forward backtest, 2023–2025 weeks 5–18: spread and total hit rates by edge size |
| `scripts/tune.py` | Grid search over half-life and ridge strength (MAE against the line) |

```
pip install -r requirements.txt
python scripts/predict_week9.py
```

## Results so far (baseline)

| Test | Result |
|---|---|
| 2026 week 9, straight-up winners | 14/15 (market favorites also 14/15) |
| 2026 week 9, against the spread | 5/15 |
| 2026 week 9, over/under | 8/15 |
| 2023–25 spread picks | 48.0% (break-even is 52.4%) |
| 2023–25 totals picks | 51.2% |
| 2023–25 model win prob ≥ 75% | 82.5% won (33/40), but these are heavy favorites |

The scores-only model is less accurate than the market line (margin MAE 10.2 vs 9.6).

## Next steps

1. Play-by-play efficiency (EPA per play, success rate) from nflverse play-by-play data
2. Quarterback and injury adjustments
3. Key-number-aware margin distribution (3, 7, 10) in place of the normal approximation
4. "Optimal" and "secure" leg ranking with expected value and fractional Kelly staking
5. Measure closing line value using opening lines
