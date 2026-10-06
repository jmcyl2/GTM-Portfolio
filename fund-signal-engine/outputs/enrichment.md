[← Findings](findings.md)

# Enrichment funnel

The top 50 of the 63 shortlisted advisers by v2 score (the Clay trial caps a table at 50 rows). Domains and contacts come from public SEC data first; Clay runs only the work-email waterfall. Method: [`docs/clay-enrichment.md`](../docs/clay-enrichment.md). Aggregates only; contact-level output stays in `data/private/`.

| Step | Advisers | Coverage |
|---|---|---|
| Advisers enriched | 50 | 100% |
| Usable company mail domain (ADV website, or verified by research; MX checked) | 45 | 90% |
| Named contact from SEC filings (Form ADV Schedule A / Item 1.J) | 49 | 98% |
| Email returned by the Clay waterfall (Conservative validation) | 42 | 84% |
| **Usable after QA** | 41 | 82% |

**14 of the 41 usable emails belong to a finance-titled contact** (CFO, controller, treasurer, VP finance).

## QA of returned emails

Clay's validation confirms an address will accept mail, not that it is the right person. Every returned email is checked against the contact's name and the firm's verified domain.

| Check | Emails |
|---|---|
| On the verified company domain | 34 |
| On a different domain (firm's mail domain or an affiliate) | 4 |
| Firm had no verified domain; matched from company name | 3 |
| Rejected: personal/free-mail address | 1 |
| Rejected: mailbox doesn't match the contact's name | 0 |

**Which provider found the email (first hit in the waterfall):**

| Provider | Emails |
|---|---|
| Findymail | 35 |
| SMARTe | 2 |
| Enrow | 2 |
| Wiza | 1 |
| Prospeo | 1 |

**Where the contact came from:**

| Source | Advisers |
|---|---|
| SEC Form ADV Schedule A (2024 bulk) | 26 |
| SEC Form ADV Schedule A (current) | 22 |
| SEC Form ADV Item 1.J (2024 bulk) | 1 |

## Cost

- **54.1 Clay data credits** in total: 1.08 per adviser, **1.32 per usable email**. Plus 104 Clay actions.
- Domains and contacts cost nothing: they come from SEC filings, manual verification and a DNS check.

