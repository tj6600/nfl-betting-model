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

## Player quality and scheme matchups (v4)

**Player quality** (`nflmodel/players.py`): each missing, returning or arriving regular is weighted by a quality multiplier from their last 17 games. An average regular is 1.0, the range is 0.25 to 2.25, and small samples are shrunk toward average.
- Receivers, tight ends and backs: EPA on their targets and carries.
- Defenders: impact plays (sacks, QB hits, tackles for loss, pass breakups, interceptions, forced fumbles).
- Offensive linemen: no individual stats exist in play-by-play, so they all stay at 1.0.

**Scheme matchups** (`nflmodel/schemes.py`, in EPA per dropback):
- **Man vs zone:** how much better or worse the offense does against man than against zone, times how often the opposing defense plays man. This uses NGS participation data, which covers 2023–25 only. 2026 isn't published yet, so 2026 games use 2023–25 tendencies.
- **Blitz:** the offense's EPA against the blitz minus without it, times the defense's blitz rate. This uses FTN charting, 2022–26.
- **Play action:** the defense's EPA allowed on play action minus other dropbacks, times the offense's play-action rate. Also FTN, 2022–26.

### v4 results

| Test | v2 EPA+QB | v3 + roster (quality-weighted) | v4 + schemes |
|---|---|---|---|
| 2023–25 ATS, all games | 51.1% | 49.4% | 48.2% |
| 2023–25 ATS, edge ≥ 3 | 42.6% | 46.9% | 47.9% |
| 2023–25 margin MAE (line 9.94) | 10.43 | 10.46 | 10.47 |
| 2026 wk 9 ATS | 8/15 | 9/15 | 10/15 |
| 2026 wk 9 optimal picks | 7–5, +1.46 u | 5–7, −2.38 u | 6–7, −1.51 u |
| 2026 wk 9 secure picks | 5–0 | 5–0 | 5–0 |

Scheme matchups turn out tiny. A typical matchup is worth under 0.01 EPA per dropback, about 0.2 points a game, and the fitted weights are within noise. Teams adjust their game plans to the opponent, so a season-long tendency like "plays a lot of man" says little about one game.

## Betting opening lines

`scripts/opening_lines.py` tests v2 picks (EPA + QB) against nflverse's early lines (`sc_lines.csv`). These are spreads only, 2019–2020, and the source is undocumented. They sit about 1 point from the close on average and predict results a bit worse, as opening lines do. The weights are fit leave-one-season-out. Use `--no-qb` to drop the starting-QB feature, since a QB change is often only known after openers are posted.

| Opener bets, 2019–20 (n≈430) | with QB feature | without (`--no-qb`) |
|---|---|---|
| Hit rate, all games | 54.1% | 53.8% |
| Hit rate, edge ≥ 1.5 | 55.9% | 55.2% |
| Line moved toward our side by kickoff (edge ≥ 1.5) | 65% | 59% |
| Avg closing line value, edge ≥ 3 | +0.98 pts | +0.75 pts |

This is the first test where the model shows **positive closing line value**: the market tends to move toward the model's side after the open. That's the standard sign of a real edge. Two seasons is still a small sample, though, and later seasons need their own opening-line data to confirm it.

## Live opening-line tracking

These scripts need `ODDS_API_KEY` (free key from the-odds-api.com, 500 credits a month; each snapshot costs 3).

| Step | Command | When |
|---|---|---|
| Snapshot odds | `python -m nflmodel.odds` | Early in the week (opener), then just before kickoffs (close) |
| Price the week vs openers | `python scripts/weekly_picks.py` | After the opener snapshot |
| Grade picks (CLV and results) | `python scripts/clv_report.py` | Any time; writes `odds_log/clv_report.md` |

- Snapshots go to `odds_log/snapshots/` (every book plus a median "consensus" line).
- Picks go to `odds_log/picks/<season>_wk<NN>.csv`. **Optimal** means a spread with an edge of 1.5+ points over the opener and EV of 5%+ at the best available line. **Secure** means a moneyline with model win probability of 70%+. **Watch** means a total that would qualify, tracked separately because totals weren't backtested against openers.
- The closing line is the last consensus snapshot before each game's kickoff.

Set `NFL_GAMES_CSV` to a local copy of nflverse `games.csv` (clone `nflverse/nfldata`).

## Passing yards props (`nflmodel/passing.py`)

QB passing yards over/unders. The data is nflverse weekly player stats (`stats_player_week_<year>.csv`, downloaded from the github.com releases; set `NFL_STATS_DIR` to use a local copy). The model uses gross passing yards, which is what books use.
- **Projection:** a ridge regression on the QB's recency-weighted yards and attempts in his previous starts (15+ attempts), his team's implied points and expected margin, and the passing yards the defense has allowed lately. The chance of the Over comes from the empirical actual/expected spread.
- **Backtest** (`scripts/pass_backtest.py`, fit on earlier seasons and tested on the next). Average miss in yards per game:

| Season | Model | QB's season average |
|---|---|---|
| 2024 | 55.5 | 59.9 |
| 2025 | 52.8 | 56.3 |
| 2026 so far | 56.7 | 60.3 |

- **Pricing:** `python -m nflmodel.odds yards` now also pulls `player_pass_yds`. `scripts/yards_picks.py` prices each team's expected starter: whoever started the latest game and is on this week's active roster, unless he's listed Out in `odds_log/injury_overrides.csv`.
- **Board:** passing yards get their own tab, and the parlay builder has a "Pass yds" filter.

## Next steps

1. Opening lines (`initial_lines.csv`), to bet early numbers and measure closing line value
3. Key-number-aware margin distribution (3, 7, 10) in place of the normal approximation
4. "Optimal" and "secure" leg ranking with expected value and fractional Kelly staking
5. Measure closing line value using opening lines

## NBA board (`nbamodel/`, `board/site/nba.html`)

Data comes from [sportsdataverse hoopR](https://github.com/sportsdataverse/hoopR-nba-data) on raw.githubusercontent.com (stats.nba.com and ESPN are blocked from the cloud environment): ESPN box scores for every player-game since 2021-22, plus ESPN's listed lines (DraftKings from 2025-26, consensus before). It is cached in `nba_data/`; `--update` adds new games from hoopR's per-game JSON, so scheduled runs need only numpy and pandas.

| Step | Command |
|---|---|
| Rebuild history (one-off, needs pyarrow) | `python scripts/nba_build_history.py` |
| DraftKings game lines (3 credits) | `python -m nbamodel.odds games` |
| Player props for a slate (~5 credits a game) | `python -m nbamodel.odds props [YYYY-MM-DD]` |
| Build the page | `python scripts/nba_board.py --update` |
| Backtests | `python scripts/nba_backtest.py`, `python scripts/nba_props_backtest.py` |

- **Game model** (`nbamodel/games.py`): recency-weighted ridge ratings on points scored, with home court, back-to-backs and the value of regulars who sat the team's previous game. Walk-forward against the listed spread, 2023-24 to 2025-26: **50.1% ATS over 3,742 games** (break-even 52.4%), totals 49.0%. Margin error 11.3 vs the line's 10.8. A regression of results on line and model gives the model a weight of about 0.07, so the board shows game chances as 25% model, 75% DraftKings no-vig.
- **Props** (`nbamodel/props.py`): minutes x per-minute rate (shrunk to position) x opponent-by-position factor x game-total factor. Average miss beats season-to-date and last-10 averages (points 4.88 vs 5.02). Over/under chances come from the empirical spread of actual vs projected and are calibrated against a stand-in line (season average rounded to the half point). There are no historical prop lines, so the board blends 50/50 with DraftKings, as on the NFL board.
- **Drift correction:** every prop projection is scaled by how the league's actual stats compared with projections over the previous 21 days. Early in 2026-27, projections ran about 7% high because of deeper rotations and lower scoring, which pushed the board toward Overs.
- **Parlay builder modes:** *Best value* (biggest edge first) or *Most likely to hit*, which uses the highest-chance legs that are still +EV (edge 1+ pt, 55%+ chance, no flags).
- **Injuries** (`nbamodel/injuries.py`): ESPN's injury report (site.api.espn.com, allowed in the Default environment). Players listed Out are dropped. Teammates pick up part of their projected production in proportion to each teammate's own projection: 63% of points, 49% of rebounds, 59% of assists and 56% of threes (`props.SHARE`, fit on 2023-24 to 2025-26). Only regulars who played in the last 21 days count, so a long-term absence that teammates' recent form already reflects isn't counted twice. Their value also feeds the game model's missing-player term. If the report can't be reached, the board falls back to who sat each team's last game.
- **Live grading** (`scripts/nba_grade.py`): each board build logs every priced leg to `odds_log/nba/picks/`. The grader takes each day's first log and grades it at the logged DraftKings price against box scores, voiding players who sit. It also compares each leg with the day's last DraftKings snapshot before tip-off (closing line value). Results go to `odds_log/nba/grade_report.md` and the board's Model record tab.

## NHL model (`nhlmodel/`), backtests only so far

**Data.** The NHL API is blocked from the cloud env, so box scores and play-by-play (with xG) come from the
sportsdataverse mirror on raw.githubusercontent.com (`python -m nhlmodel.data` fetches the current season and
rebuilds `nhl_data/`, which is gitignored). DraftKings history comes from The Odds API historical endpoints
(`python -m nhlmodel.odds history-props ...` / `history-games ...`) and is saved in `odds_log/nhl/history/`.
The pull cost about 8,100 credits: 20 sample nights of 2025-26 props (228 games) and every 2025-26 day of
moneylines and puck lines.

**Models.** All are fit on 2024-25 and tested on 2025-26 DraftKings lines.
- Shots on goal: Poisson regression on recent shots, shot attempts, ice time, power-play attempts, opponent shots
  allowed, home and back-to-back, with a negative binomial for over/under chances.
- Goalie saves: opponent shot attempts x the goalie's shrunk save rate, with a haircut for the chance he's pulled.
- Games: each team's non-empty-net regulation goals (xG and goals for/against vs the current league rate, opposing
  goalie, rest), a shared-goal Skellam margin, an empirical empty-net table (a 1-goal lead became 2+ about 40% of
  the time), overtime, then a logistic recalibration of "wins by 2+".

**Results on 2025-26 DraftKings lines** (`scripts/nhl_props_backtest.py`, `scripts/nhl_game_backtest.py`):

| Market | Lines | Log loss model / DK / 50-50 blend | Best bet filter |
|---|---|---|---|
| Shots on goal | 3,344 | 0.6843 / 0.6840 / **0.6829** | blend, EV 3%+: 231 bets, 55.0% hit, +12.2% ROI (almost all unders) |
| Goalie saves | 375 | 0.6960 / 0.6936 / **0.6924** | blend, EV 3%+: 55 bets, 56.4% hit, +6.8% ROI (too few to trust) |
| Moneyline | 1,215 | 0.6841 / 0.6833 / **0.6825** | roughly break-even at every filter |
| Puck line | 1,215 | 0.6261 / **0.6236** / 0.6237 | loses 3% to 10% at every filter |

The shots-on-goal blend is the only lead, and it's concentrated in March and April (153 of the 231 bets).
November to January was flat or negative. Treat it as unproven until it's tested on another season.

**2026-27 retest (shots on goal only, 495 credits, 5 nights, 822 lines).** Fit on 2024-26 and run with
`python scripts/nhl_props_backtest.py --season 2026-27`. Log loss: model 0.6772, DK 0.6792, blend **0.6765**. Every
blend pick with positive EV: 139 bets, 59.0% hit, +9.3% ROI. At EV 3%+: 40 bets, 60.0% hit, +13.0% ROI, all but
one unders. Betting every under blindly lost 4.6%, so the gain comes from which unders the model picks. Three of
the five nights were profitable. That's encouraging, but the sample is still small.

### NHL board (`board/site/nhl.html`, `scripts/nhl_board.py`)

The board has these tabs: Games (a pick to win, model goals, goalies, and moneyline, puck line and total legs), Shots on goal,
Goalie saves, Parlay builder and Model record. Game lines and probable goalies come from ESPN's scoreboard, which
carries DraftKings prices and costs no Odds API credits. ESPN's summaries also give DraftKings closing lines from 2025-26
on (`python -m nhlmodel.espn history ...`, free). Those lines were used to test totals (DraftKings was better) and winner
picks (the model picked 54-61% correctly, DraftKings' favorite 56-62%). Shots-on-goal and saves lines need
`python -m nhlmodel.odds props` (about 2 credits per game). Without them, the prop tabs show projections only.

Model weights against the DraftKings no-vig price: moneyline 50%, shots on goal 50%, saves 50%, puck line 25%, total 25%.
Winner picks also join the "Most likely to hit" parlay pool, priced no shorter than -200.

A daily run would be: `pip install pyarrow` (to read the mirror's parquet files), `python -m nhlmodel.data` (rebuilds
the current season only, since past seasons are committed in `nhl_data/<year>/`), `python scripts/nhl_grade.py`,
optionally `python -m nhlmodel.odds props` (costs credits), then `python scripts/nhl_board.py`.
