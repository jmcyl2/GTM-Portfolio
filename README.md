# GTM Portfolio

Joseph Leung's go-to-market engineering projects. Each one runs on real data and is checked against real outcomes, not demo data.

Every folder is a standalone project with its own README, code, setup and results.

## Projects

| Project | What it does | Stack | Status |
|---|---|---|---|
| [**Fund Signal Engine**](fund-signal-engine/) | Finds small PE/RE fund managers that still run their own quarterly close, using SEC filings, then backtests the targeting against what those funds did next. 2M fund records → 280 Tier A targets → a 63-adviser shortlist (filter confirmed on a 2025–26 forward test) → 41 QA-checked contact emails (14 at finance-titled contacts) for 54 Clay credits. | Python · DuckDB · SQL · scikit-learn · Clay · SEC EDGAR | Targeting, backtest, forward test and enrichment shipped; personalized openers next |

## How each project is laid out

```
<project>/
├── README.md          problem, approach, results, how to run
├── outputs/           committed results (aggregates only)
├── src/               code
└── data/              local only, gitignored (raw pulls + contact-level output)
```

No personal or contact-level data is committed. Anything identifying stays in each project's gitignored `data/` folder.
