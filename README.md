# GTM Portfolio

Joseph Leung's go-to-market engineering projects. Each one runs on real data and is checked against real outcomes, not demo data.

Every folder is a standalone project with its own README, code, setup and results.

## Projects

| Project | What it does | Stack | Status |
|---|---|---|---|
| [**Fund Signal Engine**](fund-signal-engine/) | **Who should a fund-accounting business sell to first?** Reads 2M public SEC fund records to find small PE/RE funds that still do their own books, ranks them on likelihood to pay for help, and proves the ranking on what happened next (top-ranked firms bought at 2x the rate, p = 0.011). Then finds each firm's finance contact: 41 verified emails from 50 firms for 54 Clay credits. | Python · DuckDB · SQL · scikit-learn · Clay · SEC EDGAR | Targeting, ranking, forward test and enrichment shipped; personalized openers next |

## How each project is laid out

```
<project>/
├── README.md          problem, approach, results, how to run
├── outputs/           committed results (aggregates only)
├── src/               code
└── data/              local only, gitignored (raw pulls + contact-level output)
```

No personal or contact-level data is committed. Anything identifying stays in each project's gitignored `data/` folder.
