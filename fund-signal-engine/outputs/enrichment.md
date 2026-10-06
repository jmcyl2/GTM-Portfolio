[← Findings](findings.md)

# Finding contacts and emails

The top 50 of the 63 advisers on the contact list, by v2 score (Clay's free trial limits a table to 50 rows). Company domains and contact names come from SEC filings first, at no cost. Clay is only used to find work emails, with its waterfall: it tries one email provider after another until one finds a verified address. Method: [`docs/clay-enrichment.md`](../docs/clay-enrichment.md). Summary stats only; names and emails stay in `data/private/`.

| Step | Advisers | Coverage |
|---|---|---|
| Advisers enriched | 50 | 100% |
| Company domain that can receive email (from the filing or found by research, MX record checked) | 45 | 90% |
| Named contact from SEC filings (Form ADV Schedule A or Item 1.J) | 49 | 98% |
| Email found by Clay's waterfall (Conservative setting) | 42 | 84% |
| **Usable after my checks** | 41 | 82% |

**14 of the 41 usable emails belong to a finance-titled contact** (CFO, controller, treasurer, VP finance).

## Checking the emails Clay returned

Clay's validation confirms an address accepts mail, not that it belongs to the right person. So every email is also checked against the contact's name and the firm's verified domain.

| Check | Emails |
|---|---|
| On the verified company domain | 34 |
| On a different domain (the firm's separate mail domain, or an affiliate's) | 4 |
| Firm had no verified domain; Clay matched it from the company name | 3 |
| Rejected: personal address (Gmail, Yahoo, etc.) | 1 |
| Rejected: mailbox doesn't match the contact's name | 0 |

**Which provider found each email (the first one in the waterfall to find it):**

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

- **54.1 Clay data credits** in total: 1.08 per adviser, **1.32 per usable email**. Plus 104 Clay actions, which Clay counts separately from credits.
- Domains and contacts cost nothing. They come from SEC filings, research checked by hand, and a DNS check that each domain can receive email.

