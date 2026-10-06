[← Fund Signal Engine](README.md)

# Case study: finding the funds that still do their own books

<!-- Loom walkthrough: add the link here once recorded -->

## The problem

Say you sell fund accounting software or services. Your best prospects are small private equity and real estate funds that still do their own quarterly accounting rather than paying a fund administrator. No bought contact list can tell you which funds those are. A list tells you a fund exists. It doesn't tell you who does its books.

## The approach

The SEC already records the answer. Every adviser's Form ADV lists each private fund it manages and says whether that fund uses an outside administrator. The approach was to build the target list from that filing, test whether the targeting actually predicts buying, and only then spend money finding contacts.

1. **Target from the regulatory record.** I took 2,014,331 fund records (2011–2024) and narrowed them to active US managers with $20M–$500M across 1–5 funds, where every PE/RE fund is self-administered. That left 280 firms.
2. **Test the score against real outcomes.** A fund that later reports an administrator has bought the service, so ADV history provides the closed-won data that a portfolio project normally lacks.
   - **v1 failed.** I fixed its scoring rules before looking at the data, and they barely beat random. It's still published as it was.
   - **v2** learned from 20 filing attributes on 2014–17 funds and was graded on 2018–21 funds it had never seen.
3. **Forward-test on the real future.** The model's data stops at Dec 2024. I parsed each firm's current filing (2025–26) to see who actually bought, then removed those firms from the list. That left 63 firms that pass the filter and still do their own books.
4. **Enrich cheaply.** Contacts and domains came free from SEC filings, research checked against the filings, and DNS. Clay ran only the email waterfall, with my own QA on top of its validation.
5. **Draft the outreach.** One opener per firm, built by rules from facts in that firm's own filing. Nothing was sent.

## Results

| | |
|---|---|
| Fund records screened | **2.0M** → 280 Tier A firms → 63 on the outreach shortlist |
| Score v2 vs v1, on held-out years | AUC **0.597 vs 0.528**. The bottom 40% by score bought at 7.6%, the top 60% at 16.0% (**2.1x**). |
| Forward test (2025–26 outcomes) | Firms that passed the filter bought at **20% vs 9%** for those that failed (one-sided Fisher's exact, **p = 0.011**) |
| Contacts from public data | **49 of 50** firms got a named person at no cost; 14 of the final contacts hold finance titles |
| Verified emails | **41 of 50 (82%)** for **54.1 Clay credits**, about **1.3 credits per usable email** |
| Problems caught that Clay's validation missed | **1** wrong-person address and **4** website domains that can't receive mail |

## What I learned

- **The most valuable finding was a risk, not a lead list.** Most funds that do their own books look like the funds that historically never outsourced it. The market with the problem is largely the market least likely to pay someone else to fix it. That's worth knowing before writing a single email, and it's the first question to put to real buyers.
- **Use paid tools at the last mile only.** Clay's company lookups returned nothing on these firms, while SEC filings gave named executives with titles for free. Clay was well worth it for the one step it's best at, finding emails, and cost about 5% of a trial's credits.
- **Validation isn't verification.** An address can accept mail and still belong to the wrong person. A name and domain check on every result caught what the email providers' validation passed.

## What I'd do next

- Run the refresh as a daily job: new filings → score → alert, so a firm launching a self-administered fund is flagged within days.
- Test the opener against discovery calls, which are the real proof of whether the pain exists.
- Publish the fund-administration market map as a small public dashboard.

**Go deeper:** [full write-up](README.md) · [results](outputs/findings.md) · [scoring model](outputs/score_v2.md) · [forward test](outputs/refresh.md) · [enrichment](outputs/enrichment.md) · [openers](outputs/openers.md) · [code](src/fund_signal_engine/)
