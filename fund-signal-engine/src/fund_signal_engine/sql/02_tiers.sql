-- Current targeting: which small PE/RE managers run their own close?
-- Fund-level detail comes from each adviser's most recent bulk filing (<= 2024-12);
-- size and active status come from the current monthly roster.

CREATE OR REPLACE TABLE latest_filing AS
SELECT * FROM filings
QUALIFY row_number() OVER (PARTITION BY crd ORDER BY filed_on DESC NULLS LAST, filing_id DESC, regime DESC) = 1;  -- same filing listed as ERA and IA: the IA registration is current

CREATE OR REPLACE TABLE adviser_profile AS
WITH funds AS (
    SELECT filing_id, regime,
           count(*)                                                                    AS n_funds_2024,
           sum(gross_assets)                                                           AS private_fund_assets_2024,
           count(*) FILTER (fund_type IN ('Private Equity Fund', 'Real Estate Fund'))  AS n_pe_re,
           count(*) FILTER (fund_type = 'Private Equity Fund')                         AS n_pe,
           count(*) FILTER (fund_type = 'Real Estate Fund')                            AS n_re,
           count(*) FILTER (fund_type IN ('Private Equity Fund', 'Real Estate Fund') AND NOT has_admin) AS n_pe_re_self_admin,
           count(*) FILTER (fund_type IN ('Private Equity Fund', 'Real Estate Fund') AND audited)       AS n_pe_re_audited
    FROM fund_obs GROUP BY ALL
)
SELECT l.crd, l.regime, l.adviser_name, l.filed_on AS fund_detail_as_of,
       f.* EXCLUDE (filing_id, regime),
       r.crd IS NOT NULL                                            AS active_now,
       r.status, r.website, r.state, r.country,
       coalesce(r.private_fund_assets, f.private_fund_assets_2024)  AS private_fund_assets,
       coalesce(r.private_fund_count, f.n_funds_2024)               AS private_fund_count,
       c.cco_name
FROM latest_filing l
JOIN funds f USING (filing_id, regime)
LEFT JOIN roster r ON r.crd = l.crd
LEFT JOIN filing_contacts c ON c.filing_id = l.filing_id AND c.regime = l.regime;

-- Tier A: every PE/RE fund self-administered. B: some. C: none (control group).
CREATE OR REPLACE TABLE targets AS
SELECT *,
       CASE WHEN n_pe_re_self_admin = n_pe_re THEN 'A'
            WHEN n_pe_re_self_admin > 0      THEN 'B'
            ELSE 'C' END                                   AS tier,
       n_pe_re_audited = n_pe_re                           AS all_audited
FROM adviser_profile
WHERE n_pe_re > 0
  AND active_now
  AND country = 'United States'
  AND private_fund_assets BETWEEN 20e6 AND 500e6
  AND private_fund_count BETWEEN 1 AND 5;

-- Buyer B: US administrators serving PE/RE funds of currently active advisers.
CREATE OR REPLACE TABLE administrators AS
SELECT a.admin_key,
       min(a.administrator)                                        AS administrator,
       min(a.admin_state)                                          AS admin_state,
       count(DISTINCT f.fund_id)                                         AS pe_re_funds,
       count(DISTINCT f.crd)                                             AS advisers
FROM fund_admin_obs a
JOIN latest_filing l ON l.filing_id = a.filing_id AND l.regime = a.regime
JOIN fund_obs f ON f.filing_id = a.filing_id AND f.regime = a.regime AND f.reference_id = a.reference_id
JOIN roster r ON r.crd = a.crd
WHERE f.fund_type IN ('Private Equity Fund', 'Real Estate Fund')
  AND coalesce(a.admin_country, 'United States') = 'United States'
GROUP BY 1;
