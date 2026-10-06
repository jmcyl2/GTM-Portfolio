[← Fund Signal Engine](../README.md)

# Enrichment: public data first, Clay for the email waterfall

This is how the top 50 shortlisted advisers (the Clay trial caps a table at 50 rows) get a verified work email for their finance contact.

**The design choice is to resolve everything public data can answer before spending credits.**

- **Company domain.**
  - The adviser's Form ADV website field gives 32 of the 50.
  - The other 18 list a LinkedIn page, nothing, or a social profile. They were researched and checked against each filing's address and named people; 16 were verified. Clay's name-to-domain lookup was tried first and returned nothing on a 10-row test.
  - **Every domain must accept mail** (an MX record check).
    - Three domains listed in the filings, and one found in research, have websites but no mail server, so email to them would bounce.
    - One firm has no website that could be verified.
    - Where a firm's mail runs on a different domain from its website (e.g. nrdcequity.com → nrdc.com), the mail domain is used.
  - **Result: 45 of 50 have a usable email domain.**
- **Contact.**
  - Picked from **Schedule A** of the adviser's Form ADV, which lists executive officers and owners with their titles. The current filing is used first, then the 2024 bulk data.
  - The rule prefers finance titles (CFO, controller, treasurer), then operations, compliance, and executives. The buyer of a fund-close product is whoever owns the books.
  - 49 of 50 firms resolve to a named person this way, 17 of them in finance roles, at zero cost.
- **44 of 50 rows reach Clay ready for the email waterfall**, with both a mail-accepting domain and a named contact.
- **Clay** then does only what it's best at: matching LinkedIn profiles, and the multi-provider **work-email waterfall with verification**.

Resolution logic: [`contacts.py`](../src/fund_signal_engine/contacts.py). Hand-off: `fse-clay push`. Scoring: `fse-clay report`.

## 1. Create the table

1. In Clay: **New table → Import → Webhook**. Turn on **auto-extract new columns** if offered, so each field becomes its own column.
2. Put the webhook URL in `.env` as `CLAY_WEBHOOK_URL` and run `uv run fse-clay push`. That sends 50 rows.
3. **Check:** 50 rows, with columns including `company_name`, `domain_final`, `contact_first_name`, `contact_last_name`, `contact_full_name`, `contact_title` and `contact_source`.

## 2. Work-email waterfall → `Work Email`, `Email Provider`

As of October 2026, Clay's interface differs from its docs in a couple of places. This is what was actually used:

1. **Add enrichment** (top right) → search **Work Email** → **Full configuration**.
2. Map the inputs. Clay takes a full name rather than first and last:
   - **Full name** → `contact_full_name`
   - **Company domain** → `domain_final`
   - **Company name** → `company_name`
   - **Company social profile URL** → `linkedin_company_url`
3. Infer-email: **off**, so no guessed addresses.
4. **Validation strategy: Conservative.** Balanced is greyed out on the trial, so only addresses confirmed deliverable are returned and catch-all domains are dropped.
5. **Output name of successful provider: on.**
6. Run 10 rows first. That cost 11 credits for 4 emails from 8 eligible rows. Then run the rest from the column header.

Because the company name is mapped as an input, the waterfall can still find a mailbox for firms with no verified domain. `fse-clay report` flags those, and checks every returned email against the contact's name and the firm's domain (see QA below).

## 3. Optional: LinkedIn profile → `Contact LinkedIn`

Add a person-level LinkedIn lookup using `contact_full_name` + `company_name` + `domain_final`. Run 10 rows first. It adds a coverage metric and gives the email waterfall a stronger match, but costs credits, so it's optional on a trial.

## 4. Export and score

1. Export the table to CSV and save it as `data/private/clay_export.csv` (gitignored).
2. Note the credits used: the balance before minus after, from workspace → Settings → Plans & Billing.
3. Run `uv run fse-clay report --credits <data credits> --actions <actions>`. That writes [`outputs/enrichment.md`](../outputs/enrichment.md) with step-by-step coverage, contact sources, and cost per verified email.

## QA

Validation proves an address accepts mail, not that it belongs to the right person. The report checks every returned email:
- **Free-mail addresses are rejected.** One came back: a Yahoo address for a firm with no domain.
- **The mailbox must plausibly match the contact.** Accepted forms are the name or surname, a short first name (`wes` for Wesley), or initials including middle names or a second surname (`amn`, `ogn`).
- **Emails on a different domain from the firm's website are counted but listed separately.** This is usually the firm's real mail domain or an affiliate's.

## Screenshots

**The table:** 50 rows pushed by webhook, with the waterfall run. Emails are pixelated.

![Clay table](img/clay-table.png)

**Waterfall inputs:** full name, domain, company name, company LinkedIn.

![Waterfall inputs](img/clay-waterfall-inputs.png)

**Provider sequence:** Findymail, Hunter, Prospeo, Kitt, Datagma, Wiza, …

![Waterfall providers](img/clay-waterfall-providers.png)
