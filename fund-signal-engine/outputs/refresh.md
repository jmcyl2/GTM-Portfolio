[← Findings](findings.md)

# Forward test: Tier A firms' current Form ADV filings

The SEC's bulk fund data ends in Dec 2024. To see what happened since, each Tier A adviser's current Form ADV was downloaded and its private-fund section read. Those filings are dated Mar 2024 to Sep 2026 (median Mar 2026).

## What changed since 2024

| Status | Advisers | Share |
|---|---|---|
| still self-administered | 243 | 88% |
| hired administrator | 19 | 7% |
| new fund uses administrator | 15 | 5% |

- **hired administrator**: a PE/RE fund that did its own books in 2024 now reports an outside administrator. These advisers have already bought, so they come off the contact list.
- **new fund uses administrator**: the existing funds haven't changed, but a fund launched since 2024 uses an administrator. These come off the list too.
- **still self-administered**: all PE/RE funds still do their own books, so the firm is still a potential customer.

**Contact list: 63 advisers** pass the v2 filter and still do all their own books (`data/private/shortlist.csv`, not committed). These go on to contact finding.

## Did the v2 filter predict who bought?

All of this happened after the years the model was trained and tested on, so it's a real test of its predictions. The numbers are small, so treat the result as a strong sign rather than proof.

| Group | Advisers | Bought administration since 2024 | Rate |
|---|---|---|---|
| Passed v2 filter | 79 | 16 | 20% |
| Failed v2 filter | 198 | 18 | 9% |

Fisher's exact test, one-sided: p = 0.011. That's the chance of a gap at least this big if the filter were useless. 'Bought' means either of the changes above: an existing fund hired an administrator, or a new fund launched with one.

Check on the PDF reading: for each adviser, the number of funds the script found is compared with the 'Total Funds' figure in the filing itself (0 mismatches).

