[← Findings](findings.md)

# Tier A refresh: current Form ADV filings

The bulk fund-level data ends Dec 2024. Each Tier A adviser's current Form ADV was pulled and its private-fund section parsed. Filings span Mar 2024 to Sep 2026 (median Mar 2026).

## Status since 2024

| Status | Advisers | Share |
|---|---|---|
| still self-administered | 243 | 88% |
| hired administrator | 19 | 7% |
| new fund uses administrator | 15 | 5% |

- **hired administrator**: a PE/RE fund that was self-administered in 2024 now reports an outside administrator. These advisers have already bought, so they come off the outreach list.
- **new fund uses administrator**: existing funds are unchanged, but a fund launched since 2024 uses an administrator.
- **still self-administered**: still in market.

**Outreach shortlist: 63 advisers** pass the v2 filter and are still fully self-administered (`data/private/shortlist.csv`, not committed). This is the input to enrichment.

## Live check of the v2 filter

These outcomes happened after every year the model was trained or tested on, so they are a genuine forward test. Small numbers: read as directional.

| Group | Advisers | Bought administration since 2024 | Rate |
|---|---|---|---|
| Passed v2 filter | 79 | 16 | 20% |
| Failed v2 filter | 198 | 18 | 9% |

Fisher's exact test, one-sided: p = 0.011. 'Bought' means either status above: an existing fund hired an administrator, or a new fund launched with one.

Parse check: every adviser's parsed fund count matches the filing's own 'Total Funds' figure (0 mismatches).

