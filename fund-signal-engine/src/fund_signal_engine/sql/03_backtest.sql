-- Backtest: no outreach means no closed-won data. The public-record substitute:
-- a self-administered fund that later reports an outside administrator has
-- *bought* fund-admin services. Question: does the score, measured at a base
-- year, predict which self-administered PE/RE funds buy within 3 years?
--
-- PRE-REGISTERED SCORE v1 (fixed before looking at outcomes; 1 point each):
--   audited      fund gets an annual audit (auditor pressure exposes the close)
--   mid_size     adviser's private fund assets $20M-$500M (needs help, lacks staff)
--   small_mgr    adviser reports 1-5 private funds (no back-office team)
--   growing      fund gross assets up >= 25% on the prior year (close load rising)
--
-- Score v2 (score_v2.py) is learned on 2014-2017 base years and tested on 2018-2021.

-- One row per fund per year: its last filing that year.
CREATE OR REPLACE TABLE fund_year AS
WITH per_filing AS (
    SELECT filing_id, regime, count(*) AS adviser_funds, sum(gross_assets) AS adviser_assets,
           count(*) FILTER (has_admin) AS adviser_funds_with_admin
    FROM fund_obs GROUP BY ALL
)
SELECT o.*, year(o.filed_on) AS yr, p.adviser_funds, p.adviser_assets, p.adviser_funds_with_admin
FROM fund_obs o JOIN per_filing p USING (filing_id, regime)
WHERE nullif(o.fund_id, '') IS NOT NULL AND o.filed_on IS NOT NULL
QUALIFY row_number() OVER (PARTITION BY o.fund_id, year(o.filed_on) ORDER BY o.filed_on DESC, o.filing_id DESC) = 1;

-- Signals as of each fund-year, using only information available that year.
CREATE OR REPLACE TABLE fund_features AS
SELECT *,
       -- data starts 2011, so ages are left-censored for funds older than that
       yr - min(yr) OVER (PARTITION BY fund_id)                              AS fund_age,
       CASE WHEN lag(yr) OVER w = yr - 1 AND lag(gross_assets) OVER w > 0
            THEN gross_assets / lag(gross_assets) OVER w - 1 END             AS asset_growth,
       adviser_funds_with_admin > 0                                          AS adviser_uses_admin_elsewhere,
       fund_type = 'Real Estate Fund'                                        AS is_real_estate,
       regime = 'IA'                                                         AS sec_registered
FROM fund_year
WINDOW w AS (PARTITION BY fund_id ORDER BY yr);

CREATE OR REPLACE TABLE backtest AS
SELECT b.*,
       b.yr                                                   AS base_year,
       b.audited                                              AS f_audited,
       b.adviser_assets BETWEEN 20e6 AND 500e6                AS f_mid_size,
       b.adviser_funds BETWEEN 1 AND 5                        AS f_small_mgr,
       coalesce(b.asset_growth >= 0.25, false)                AS f_growing,
       o.has_admin                                            AS switched,
       o.filing_id                                            AS outcome_filing_id,
       o.regime                                               AS outcome_regime,
       o.reference_id                                         AS outcome_reference_id
FROM fund_features b
JOIN fund_year o ON o.fund_id = b.fund_id AND o.yr = b.yr + 3
WHERE b.fund_type IN ('Private Equity Fund', 'Real Estate Fund')
  AND b.has_admin = false
  AND o.has_admin IS NOT NULL
  AND b.yr BETWEEN 2014 AND 2021
-- one observation per fund (its first eligible base year) so funds aren't double-counted
QUALIFY row_number() OVER (PARTITION BY b.fund_id ORDER BY b.yr) = 1;

ALTER TABLE backtest ADD COLUMN score INTEGER;
UPDATE backtest SET score = f_audited::INT + f_mid_size::INT + f_small_mgr::INT + f_growing::INT;

-- Which administrators won the funds that switched (for the market map).
CREATE OR REPLACE TABLE switch_winners AS
SELECT a.admin_key, min(a.administrator) AS administrator, count(DISTINCT bt.fund_id) AS funds_won
FROM backtest bt
JOIN fund_admin_obs a ON a.filing_id = bt.outcome_filing_id AND a.regime = bt.outcome_regime
                     AND a.reference_id = bt.outcome_reference_id
WHERE bt.switched
GROUP BY 1;

-- Today's self-administered PE/RE funds at target advisers, with the same signals.
CREATE OR REPLACE TABLE current_fund_features AS
SELECT f.*, t.tier
FROM fund_features f
JOIN latest_filing l USING (filing_id, regime)
JOIN targets t ON t.crd = l.crd
WHERE f.fund_type IN ('Private Equity Fund', 'Real Estate Fund')
  AND f.has_admin = false;
