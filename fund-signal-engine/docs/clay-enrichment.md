[← Fund Signal Engine](../README.md)

# Clay enrichment build

This is how the shortlist is enriched in Clay. The Clay trial caps a table at 50 rows, so the top 50 of the 63 shortlisted advisers (by v2 score) are enriched; the 13 lowest-ranked are left out. The waterfall goes company domain → contact → LinkedIn → work email → verification. Rows reach Clay through a webhook (`fse-clay push`). The finished table is exported back to CSV and scored by `fse-clay report`, so the funnel numbers can be reproduced from the export.

**Budget:** a 1,000-credit trial for 50 rows, about 20 credits per row. The design keeps spend low:
- **No paid people search for most rows.** 34 of the 50 already have a named contact from the SEC filing: the Chief Compliance Officer, Form ADV Item 1.J. At small funds that person usually also runs finance or operations.
- **The waterfall stops at the first verified email.**
- **Every column runs on 5 rows first,** so cost per row is known before the full run.

Clay's menu names change from time to time. Where a name below doesn't match exactly, search the enrichment picker for the description.

## 0. Table setup

The webhook rows carry these fields: `shortlist_rank`, `crd`, `company_name`, `state`, `domain`, `linkedin_company_url`, `adv_contact_full_name`, `adv_contact_first_name`, `adv_contact_last_name`, `adv_contact_role`, `private_fund_assets_musd`, `pe_funds`, `re_funds`, `all_funds_audited`, `p_buy_admin_3yr`, `sec_profile_url`.

If they arrive as a single JSON "webhook" column, map each field to its own column first (open the column menu and look for extracting or mapping fields).

**Turn off auto-run** on the table, or on each new column, so nothing spends credits until you choose to run it.

## 1. Company domain → `Domain (final)`

18 of the 50 rows have no usable company domain: 11 list a LinkedIn page as their website, and 7 list nothing or a social profile.

1. Add a company enrichment that takes a **LinkedIn company URL** and returns the website. Run it only where `linkedin_company_url` is filled and `domain` is empty.
2. Add a **company name → domain** enrichment, using `company_name` (and `state` if the enrichment accepts it). Run it only where both `domain` and `linkedin_company_url` are empty.
3. Add a formula column **`Domain (final)`** = `domain`, else the domain from step 1, else the domain from step 2. Strip `https://`, `www.` and any path.

## 2. Contact → `Contact name (final)`, `Contact title`, `Contact source`

1. Where `adv_contact_full_name` is filled (34 rows), the contact is that person: **source = `SEC Form ADV`**, title = `adv_contact_role`.
2. Where it's empty (16 rows), add a **find people at company** search on `Domain (final)`, limited to **1 result**, with title keywords in this priority order: `Chief Financial Officer`, `CFO`, `Controller`, `Chief Operating Officer`, `COO`, `Managing Partner`, `Founder`. **Source = `Clay people search`.**
3. Add formula columns:
   - **`Contact name (final)`**: ADV name, else the people-search name
   - **`Contact first name`** and **`Contact last name`**: the matching first and last names
   - **`Contact title`**: ADV role, else the people-search title
   - **`Contact source`**: as above

## 3. LinkedIn profile → `Contact LinkedIn`

Add a **find person's LinkedIn profile** enrichment using `Contact name (final)` + `company_name` + `Domain (final)`. It gives the email finders a stronger match, and it's a coverage metric in its own right.

## 4. Work email waterfall → `Work email`, `Email status`, `Email provider`

1. Add Clay's **work email waterfall** with inputs `Contact first name`, `Contact last name`, `Domain (final)` (and `Contact LinkedIn` where it accepts one).
2. Keep **stop after first valid result** on, and keep **email validation** on.
3. Name the outputs exactly:
   - **`Work email`**: the address
   - **`Email status`**: the validation result (valid / catch-all / invalid / unknown)
   - **`Email provider`**: which provider in the waterfall returned it

**Run all 50 only after the 5-row test.** Record the credit balance before and after the full run (workspace → Settings → Plans & Billing).

## 5. Export and score

1. Export the table to CSV and save it as `fund-signal-engine/data/private/clay_export.csv`. It's gitignored and never committed.
2. Run:
   ```bash
   uv run fse-clay report --credits <credits used>
   ```
3. That writes [`outputs/enrichment.md`](../outputs/enrichment.md) with the coverage of each step, which source found each contact, which provider found each email, and the cost per verified email.

## Portfolio evidence

Take two screenshots, with every email and name blurred:
- the table's column layout
- the waterfall's provider order

Save them as `docs/img/clay-table.png` and `docs/img/clay-waterfall.png`.
