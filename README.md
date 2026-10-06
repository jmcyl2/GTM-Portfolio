# GTM Portfolio

Joseph Leung's go-to-market engineering projects. Each one uses real data, and each is checked against what actually happened.

Each folder is a separate project with its own README, code, setup and results.

## Projects

| Project | What it does | Stack | Status |
|---|---|---|---|
| [**Fund Signal Engine**](fund-signal-engine/)<br>[case study](fund-signal-engine/CASE_STUDY.md) | **Which small investment funds should a fund-accounting business contact first?** Goes through 2M public SEC fund records to find small PE and real estate funds that still do their own books, and scores which are likely to pay for help. Tested on what those firms did next: firms that passed the score's filter hired outside help at twice the rate of those that failed (20% vs 9%, p = 0.011). Then finds each firm's finance contact: 41 verified emails from 50 firms for 54 Clay credits, plus a drafted opener for each, built from its own filing. | Python · DuckDB · SQL · scikit-learn · Clay · SEC EDGAR | Targeting, scoring, forward test, contact finding and opening lines done; packaging next |

## How each project is laid out

```
<project>/
├── README.md          the problem, the approach, results, how to run
├── outputs/           committed results (summary stats only)
├── src/               code
└── data/              local only, not committed (raw downloads + contact data)
```

No personal or contact data is committed. Anything that identifies a person or firm stays in each project's `data/` folder, which git ignores.
