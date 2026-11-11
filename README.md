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

## EPA model (v2)

- `nflmodel/pbp.py` downloads nflverse play-by-play and aggregates it per team-game: pass EPA/play, rush EPA/play and success rate, with garbage time removed (win probability outside 5–95%).
- `nflmodel/features.py` builds pre-game features from games before the target week only:
  - opponent-adjusted offense and defense ratings for pass EPA, rush EPA and success rate;
  - a **QB adjustment**: the listed starter's shrunk EPA per dropback minus that of the QBs the team used in its last 4 games, which captures injuries and benchings at QB;
  - rest difference, home field, dome and wind;
  - the v1 points model's margin and total.
- `nflmodel/predict.py` fits a ridge regression on past games only, giving margin, total, cover and win probabilities, and expected value for every spread, total and moneyline leg.
  - `market_anchor=True` fits the model *on top of* the market line, which tests whether the features add anything the line doesn't already have.

```
python scripts/build_features.py   # downloads ~150 MB of play-by-play on first run
python scripts/evaluate.py         # v2 and v3, plain and market-anchored
```

### Results

| Test | v1 points | v2 EPA | v2 anchored to line |
|---|---|---|---|
| 2023–25 ATS, all games | 48.0% | 51.1% | 51.1% |
| 2023–25 ATS, edge ≥ 3 pts | 47.3% | 42.6% | 35.7% (n=28) |
| 2023–25 O/U, all games | 51.2% | 49.1% | 50.9% |
| 2023–25 secure moneyline (p ≥ 75%) ROI | n/a | −5.7% | −3.1% |
| 2026 wk 9 margin MAE (line 8.80) | n/a | 8.48 | 8.47 |
| 2026 wk 9 ATS | 5/15 | 8/15, top 5 edges 5/5 | 9/15 |
| 2026 wk 9 O/U | 8/15 | 7/15 | 7/15 |

The 2023–25 backtest covers weeks 3–18. Break-even at -110 is 52.4%.

**Takeaway:** EPA and QB features beat the line in week 9, but over three seasons they don't, and the anchored fit shows they add almost nothing the market hasn't already priced. One week of 15 games is noise. Don't bet real money on this yet.

## Injuries, roster moves and coaching (v3)

`nflmodel/roster.py` uses nflverse injury reports, snap counts and weekly rosters, and head coaches from `games.csv`. It works per position group (OL, WR/TE/RB, DL/LB, DB), counting players in "full-time starters", where 1.0 is a player on every snap:

- **Missing:** recent regulars (≥50% of snaps over the team's last 3 games) who are out this week. That means ruled Out (100%), Doubtful (90%) or Questionable (20%), off the active roster (IR, cut), or traded away.
- **Returning:** established regulars who missed recent games and are active again.
- **Arrivals:** regulars from another team who are now on this team's active roster (trades and signings), counted at half weight.
- **Coaching:** a first-season head coach, and a mid-season (interim) coaching change.

Points per unit learned from 2019–2026 week 8, home minus away:

| Feature | Points |
|---|---|
| Net WR/TE/RB starters | +1.03 |
| Net DL/LB starters | +0.64 |
| Net OL starters | +0.48 |
| Net DB starters | +0.48 |
| First-year head coach | −1.10 |
| Interim head coach | −0.50 |

### v3 results

| Test | v2 EPA+QB | v3 + roster |
|---|---|---|
| 2023–25 ATS, all games | 51.1% | 49.5% |
| 2023–25 ATS, edge ≥ 3 | 42.6% | 47.1% |
| 2023–25 margin MAE (line 9.94) | 10.43 | 10.46 |
| 2026 wk 9 ATS | 8/15 | 8/15 |
| 2026 wk 9 optimal picks | 7–5, +1.46 u | 5–7, −2.38 u |
| 2026 wk 9 secure picks | 5–0, +1.42 u | 5–0, +1.43 u |

The roster features move predictions in the right direction (losing starters costs points), but they don't improve accuracy against the line. The market already prices injury news, and by kickoff it does so faster and better than a snap-share proxy can. Snap share also measures playing time, not how good the player is.

## Next steps

1. Player quality, not just playing time (e.g. EPA per target or PFF-style grades), so losing a star counts more than losing an average starter
2. Opening lines (`initial_lines.csv`), to bet early numbers and measure closing line value
3. Key-number-aware margin distribution (3, 7, 10) in place of the normal approximation
4. "Optimal" and "secure" leg ranking with expected value and fractional Kelly staking
5. Measure closing line value using opening lines
