[← GTM Portfolio](../README.md)

# Fund Signal Engine

A go-to-market signal engine built entirely on public SEC data. It finds small private-equity and real-estate fund managers that still run their own quarterly close, without an outside fund administrator, and backtests the targeting against what those funds actually did next.

The buyer it targets is the controller or CFO at a sub-$500M PE/RE fund, plus the boutique fund administrators who serve them. The pipeline stops before outreach: nothing here sends email.

**Results: [`outputs/findings.md`](outputs/findings.md) · [`outputs/score_v2.md`](outputs/score_v2.md) · [`outputs/refresh.md`](outputs/refresh.md) · [`outputs/enrichment.md`](outputs/enrichment.md)**

## Why this data

Most outbound lists start from a scraped database. This one starts from a regulatory filing:

- **Form ADV, Schedule D 7.B.(1).** Every SEC-registered and exempt-reporting adviser lists each private fund it manages, with the fund type, gross assets, whether the fund is audited, and **whether it uses an outside administrator**. A fund answering "no" runs its own books, and that is the pain signal.
- **The monthly SEC adviser roster** says which firms are still active today, and gives their current size and website.
- **Form D** shows new private offerings. It's a weak targeting source (most fund filings list offering size as "indefinite", and few match ADV cleanly), so here it only serves as a "something just happened" trigger.

## The backtest (in place of closed-won data)

Without outreach there are no won deals to validate the scoring model against. The public record has a substitute: a self-administered fund that later reports an outside administrator has **bought** fund-administration services. ADV history runs from 2011 and fund IDs stay stable across filings, so the engine can check whether funds that scored high in a base year were the ones that bought within three years.

The score is **pre-registered** in [`sql/03_backtest.sql`](src/fund_signal_engine/sql/03_backtest.sql). Its signals were fixed before any outcome was looked at:

| Signal | Hypothesis |
|---|---|
| Fund is audited | Auditor pressure exposes the close |
| Adviser has $20M–$500M in private funds | Big enough to need help, too small to staff it |
| Adviser reports 1–5 funds | No dedicated back office |
| Fund assets up 25%+ on the prior year | The close is getting heavier |

### What it found

Full numbers are in [`outputs/findings.md`](outputs/findings.md).

- **Self-administration is concentrated where the thesis said it would be.** 54% of real-estate funds and 39% of PE funds report no outside administrator, against 12% of hedge funds.
- **The target list is small: 280 Tier A advisers.** These are US managers, active today, with $20M–$500M in private funds across 1–5 funds, where every PE/RE fund is self-administered. 197 of them have every one of those funds audited. A list that size calls for hand-personalized outreach, not volume.
- **Only one of the four pre-registered signals held up.** Audited funds switched to an outside administrator at 1.8x the rate of unaudited ones. Mid-size advisers and fast-growing funds switched *less* often than the rest. The composite score's lift was only 1.2x, and it wasn't monotonic. The score is left as registered: refitting it after seeing outcomes would make the backtest meaningless.

### Score v2: rebuilt without cheating

Full numbers are in [`outputs/score_v2.md`](outputs/score_v2.md).

v1 failed, so v2 learns which signals matter from **20 fund attributes** in the filings. It is trained only on funds from 2014–2017 and graded on 2018–2021 funds it never saw, with v1 graded on the same set.

- **v2 beats v1 out of sample: AUC 0.597 vs 0.528** (0.5 is random). That's a modest gain, reported as it is.
- **It's an exclusion filter, not a winner-picker.** The bottom 40% by score switched at 7.6%, the top 60% at 16.0% (2.1x). Within the top 60% the score barely separates funds.
- **The strongest signals:** the fund is limited to institutional "qualified purchasers" (+); the adviser already uses an administrator for other funds (+); the fund is a fund of funds (+). Older funds and real-estate funds are *less* likely to switch. The number of investors, my strongest prior, barely matters.
- **Applied to today's list, only 79 of the 277 scoreable Tier A advisers pass the filter.** Most managers that run their own close look like the funds that historically never outsourced it. In other words, the market that does its own close is largely the market least likely to pay someone else to do it. That's the most useful thing this project found, and it's a question to take into discovery calls rather than something to assume away.

### Forward test: what happened after 2024

Full numbers are in [`outputs/refresh.md`](outputs/refresh.md).

The bulk data stops at Dec 2024, so each Tier A adviser's **current** Form ADV (filed as late as Sep 2026) was pulled and parsed. That brings the list up to date, and it's also a real forward test: these outcomes happened after every year the model saw.

- **The v2 filter held up on new data.** 20% of advisers that passed it bought fund administration after 2024, against 9% of those that failed (one-sided Fisher's exact p = 0.011). That matches the ~2x lift from the backtest.
- **34 of 277 Tier A advisers bought since 2024.** 19 moved an existing fund to an administrator and 15 launched a new fund with one. They come off the list.
- **That leaves an outreach shortlist of 63 advisers** that pass the filter and are still fully self-administered. Those 63 go into enrichment.
- **The parser is checked against the filings themselves.** Every adviser's parsed fund count matches the "Total Funds" figure it reported.

### Enrichment: public data first, Clay for the last mile

Full numbers are in [`outputs/enrichment.md`](outputs/enrichment.md); the method is in [`docs/clay-enrichment.md`](docs/clay-enrichment.md).

The top 50 shortlisted advisers were enriched (the Clay trial caps a table at 50 rows).

- **Domains and contacts cost nothing.**
  - **Contacts:** the contact is picked from Form ADV Schedule A (executive officers, with their titles), preferring finance roles. 49 of 50 firms got a named person.
  - **Domains:** they come from the filing or from research checked against it, and every domain must have an MX record. That check caught four firms whose website domain doesn't receive email, plus one more research found but rejected. 45 of 50 have a usable mail domain.
  - **Clay's own lookups weren't needed:** its name-to-domain lookup returned nothing on a 10-row test, which is why the domains were resolved this way.
- **Clay ran only the work-email waterfall**, under Conservative validation. It returned 42 emails, and **41 survived QA (82% of advisers)** for **54.1 credits, about 1.3 credits per usable email**. Findymail found 35 of them.
- **QA catches what validation can't.** One validated address was a Yahoo mailbox for the wrong person. The name check is tuned so nicknames and initials (`wes`, `amn`) aren't falsely rejected.

## Pipeline

```
SEC bulk ADV (2011–2024) ─┐
SEC adviser roster (today) ┼─► DuckDB ─► staging ─► targets (Tier A/B/C) ─► private target list
SEC Form D (last 4 qtrs) ─┘                     ├─► backtest + market map ─► outputs/findings.md
                                                 └─► score v2 (train 2014–17, test 2018–21) ─► outputs/score_v2.md
current per-firm Form ADV PDFs (2025–26) ─► refresh Tier A ─► forward test + shortlist ─► outputs/refresh.md
shortlist ─► contacts.py (Schedule A + verified domains + MX) ─► Clay email waterfall ─► QA ─► outputs/enrichment.md
```

- `ingest.py` pulls only the tables it needs out of the multi-GB SEC bulk zips (HTTP range reads, not full downloads), politely: an identified User-Agent, a rate limit, and retries.
- `sql/` holds plain SQL models: staging, then targeting tiers, then the backtest.
- `build.py` runs the models and writes the aggregate findings (committed) and the contact-level target list (gitignored).
- `score_v2.py` fits the out-of-time logistic regression, compares it with v1, and ranks today's targets.
- `contacts.py` picks each firm's finance contact from Schedule A and checks domains for mail; `clay.py` pushes rows to Clay by webhook and scores the export with a QA pass.
- `refresh.py` pulls each Tier A firm's current Form ADV, parses its private-fund section (PyMuPDF; Yes/No checkboxes are read from structure because they don't survive text extraction), and builds the shortlist.

## Run it

```bash
cd fund-signal-engine
uv sync
echo 'SEC_USER_AGENT="Your Name you@example.com"' > .env   # SEC requires an identified client
uv run fse-ingest     # ~5 min, ~2 GB on disk under data/
uv run fse-build
uv run fse-score
uv run fse-refresh    # ~10 min: one PDF per Tier A adviser, cached under data/
uv run fse-clay push  # needs CLAY_WEBHOOK_URL in .env; then build the waterfall per docs/
uv run fse-clay report --credits <used> --actions <used>
```

## Data handling

Everything comes from public SEC filings. The repo commits only aggregate statistics. Contact-level output (adviser names, compliance-officer names, websites) is written to `data/private/` and never committed.

## Roadmap

1. ~~Targeting spine + backtest~~
2. ~~Score v2 on an out-of-time split~~
3. ~~Refresh Tier A against current per-firm ADV filings, plus a forward test~~
4. ~~Enrichment: SEC-sourced contacts + Clay email waterfall, with QA and cost per usable email~~
5. Personalized openers generated from each fund's own filing data (written, not sent)
6. Daily n8n job: new filings → dedupe → score → Slack alert
7. Public dashboard: the fund-administration market map
