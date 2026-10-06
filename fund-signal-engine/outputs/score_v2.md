[← Findings](findings.md)

# Score v2: learned from 2014-2017 funds, tested on 2018-2021

The v1 score, written down before looking at any results, barely beat random. v2 lets a model work out which signals predict that a PE/RE fund doing its own books will hire an outside administrator within 3 years. To keep the test honest, it learns only from funds whose starting year is 2014-2017, and is graded on 2018-2021 funds it never saw. v1 is graded on the same funds.

## Results on funds the model never saw

|  | v1 (written in advance) | v2 (learned) |
|---|---|---|
| AUC (0.5 = coin flip, 1.0 = perfect) | 0.528 | 0.597 |

AUC measures how well a score ranks funds that hired an administrator above funds that didn't.

Training set: 12,636 funds (8.3% hired an administrator). Test set: 6,524 funds (12.6%). The model scores 0.664 on the funds it learned from but 0.597 on the test funds, so some of what it picked up from the earlier years didn't hold in the later ones. The test figure is the honest one.

**v2 on the test set, with funds split into five equal groups by score:**

| Group | Funds | Hired admin within 3 yrs | vs average |
|---|---|---|---|
| 1 (highest scores) | 1,305 | 15.4% | 1.22x |
| 2 | 1,305 | 16.6% | 1.32x |
| 3 | 1,304 | 15.9% | 1.26x |
| 4 | 1,305 | 9.4% | 0.75x |
| 5 (lowest scores) | 1,305 | 5.8% | 0.46x |

**v2 is good at ruling funds out, not at picking the best ones.** The lowest-scoring 40% of funds hired an administrator 7.6% of the time, against 16.0% for the rest (2.1x). Within the top 60% the score barely separates funds, so its value is in dropping the bottom 40%, not in ranking the rest.

## What predicts hiring an administrator

Logistic regression weights, standardized so they can be compared with each other. Positive means more likely to hire an administrator, negative means less likely. A bigger number means a bigger effect from a typical-sized change in that signal (one standard deviation), with the others held fixed. "(log)" means the value was log-scaled before fitting.

| Signal | Weight | Direction |
|---|---|---|
| Only takes qualified purchasers (large or very wealthy investors) | +0.28 | more likely |
| Fund age (years, capped at 10) | -0.23 | less likely |
| Real estate fund (vs PE) | -0.23 | less likely |
| Adviser already uses an administrator for another fund | +0.22 | more likely |
| Fund of funds | +0.19 | more likely |
| Audited | +0.16 | more likely |
| Adviser private fund assets (log) | -0.15 | less likely |
| % assets valued by third party | +0.14 | more likely |
| Master/feeder structure | +0.12 | more likely |
| % owned by non-US investors | -0.08 | less likely |
| Minimum investment (log) | +0.07 | more likely |
| Fund asset growth over the year (capped) | +0.06 | more likely |
| % owned by adviser/related | -0.05 | less likely |
| Uses a placement agent to raise money | +0.05 | more likely |
| Adviser fully SEC-registered (vs exempt reporting) | -0.05 | less likely |
| Number of investors (log) | +0.04 | more likely |
| Adviser fund count (log) | -0.03 | less likely |
| Fund assets (log) | +0.02 | more likely |
| Audited financials sent to investors | +0.02 | more likely |
| Financials prepared under GAAP | +0.00 | more likely |

## Applied to today's targets

Each Tier A/B adviser gets the score of its highest-scoring fund that does its own books (using fund details from its latest bulk filing). Tier A's 277 advisers range from a 0.5% to a 21.7% predicted chance of hiring an administrator within 3 years (median 4.6%). The cut-off that marks the bottom 40% on the test set is 7.1%, and **79 of 277** Tier A advisers are above it. The ranked list is written to `data/private/targets_v2.csv` (not committed).

Caveats: the outcome measured is *hiring an administrator*. That shows a fund will pay someone to do its accounting, not that it wants any particular product. Funds that stopped filing are left out. The predicted percentages are tuned to the training years, when fewer funds switched than in the test years, so they run low.
