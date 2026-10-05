# GTM Portfolio: Fund Signal Engine

A go-to-market signal engine built entirely on public SEC data. It finds small private-equity and real-estate fund managers that still run their own quarterly close, without an outside fund administrator, and backtests the targeting against what those funds actually did next.

The buyer it targets is the controller or CFO at a sub-$500M PE/RE fund, plus the boutique fund administrators who serve them. The pipeline stops before outreach: nothing here sends email.

**Results: [`outputs/findings.md`](outputs/findings.md)**

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
- **An open question for discovery calls:** mid-size, self-administered managers are *less* likely to buy existing administration services. Is that because the pain is low, or because current offerings don't fit them? The data can't tell those apart; conversations can.

## Pipeline

```
SEC bulk ADV (2011–2024) ─┐
SEC adviser roster (today) ┼─► DuckDB ─► staging ─► targets (Tier A/B/C) ─► private target list
SEC Form D (last 4 qtrs) ─┘                     └─► backtest + market map ─► outputs/findings.md
```

- `ingest.py` pulls only the tables it needs out of the multi-GB SEC bulk zips (HTTP range reads, not full downloads), politely: an identified User-Agent, a rate limit, and retries.
- `sql/` holds plain SQL models: staging, then targeting tiers, then the backtest.
- `build.py` runs the models and writes the aggregate findings (committed) and the contact-level target list (gitignored).

## Run it

```bash
uv sync
echo 'SEC_USER_AGENT="Your Name you@example.com"' > .env   # SEC requires an identified client
uv run fse-ingest     # ~5 min, ~2 GB on disk under data/
uv run fse-build
```

## Data handling

Everything comes from public SEC filings. The repo commits only aggregate statistics. Contact-level output (adviser names, compliance-officer names, websites) is written to `data/private/` and never committed.

## Roadmap

1. ~~Targeting spine + backtest~~
2. Enrichment waterfall on a 50-row sample: domain → person → email → verification, with coverage and cost per step
3. Personalized openers generated from each fund's own filing data (written, not sent)
4. Daily n8n job: new filings → dedupe → score → Slack alert
5. Public dashboard: the fund-administration market map
