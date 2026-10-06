[← Findings](findings.md)

# Score v2: learned on 2014-2017, tested on 2018-2021

The pre-registered v1 score barely beat random. v2 asks which signals actually predict a self-administered PE/RE fund hiring an outside administrator within 3 years. To keep the test honest, it learns only from funds whose base year is 2014-2017 and is graded on funds from 2018-2021 that it never saw. v1 is graded on the same test set.

## Results on the held-out test set

|  | v1 (pre-registered) | v2 (learned) |
|---|---|---|
| AUC (0.5 = random, 1.0 = perfect) | 0.528 | 0.596 |

Train: 12,636 funds (8.3% switched). Test: 6,524 funds (12.6% switched). Train AUC is 0.664 against 0.596 on test: part of what the model learned from the earlier years did not carry over to the later ones. The test figure is the one to trust.

**v2 test-set switch rate by score quintile:**

| Quintile | Funds | Switched within 3 yrs | vs average |
|---|---|---|---|
| Q1 (highest) | 1,305 | 15.2% | 1.20x |
| Q2 | 1,305 | 16.6% | 1.31x |
| Q3 | 1,304 | 16.3% | 1.29x |
| Q4 | 1,305 | 9.3% | 0.74x |
| Q5 (lowest) | 1,305 | 5.8% | 0.46x |

**v2 works as an exclusion filter, not a winner-picker.** The bottom 40% of funds by score switched at 7.6%, against 16.0% for the top 60% (2.1x). Within the top 60% the score barely separates funds, so ranking inside it adds little; dropping the bottom 40% does.

## What predicts a switch

Standardized logistic-regression weights (positive = more likely to hire an administrator; magnitude = effect of a one-standard-deviation change, holding the others fixed):

| Signal | Weight | Direction |
|---|---|---|
| Qualified purchasers only (3(c)(7)) | +0.29 | more likely |
| Fund age (years, capped at 10) | -0.23 | less likely |
| Real estate (vs PE) | -0.23 | less likely |
| Adviser already uses an administrator elsewhere | +0.22 | more likely |
| Fund of funds | +0.19 | more likely |
| Audited | +0.16 | more likely |
| Adviser private fund assets (log) | -0.15 | less likely |
| % assets valued by third party | +0.14 | more likely |
| Master/feeder structure | +0.12 | more likely |
| % owned by non-US investors | -0.08 | less likely |
| Minimum investment (log) | +0.07 | more likely |
| SEC-registered adviser (vs exempt) | -0.06 | less likely |
| Asset growth YoY (clipped) | +0.06 | more likely |
| % owned by adviser/related | -0.05 | less likely |
| Uses placement agent | +0.05 | more likely |
| Number of investors (log) | +0.04 | more likely |
| Adviser fund count (log) | -0.03 | less likely |
| Fund assets (log) | +0.02 | more likely |
| Audited financials sent to investors | +0.02 | more likely |
| Financials prepared under GAAP | +0.01 | more likely |

## Applied to today's targets

Each Tier A/B adviser is scored by its highest-scoring self-administered fund (fund detail as of its latest bulk filing). Tier A's 278 advisers range from 0.5% to 21.5% predicted 3-year switch probability (median 4.6%). Applying the test-set exclusion cutoff (7.1%) keeps **81 of 278** Tier A advisers. The ranked list is written to `data/private/targets_v2.csv` (not committed).

Caveats: the outcome is *hiring an administrator*, which is evidence of willingness to pay for the close, but not of demand for any specific product. Funds that stopped reporting are excluded. Probabilities are calibrated to the training period's base rate, which is lower than the test period's.
