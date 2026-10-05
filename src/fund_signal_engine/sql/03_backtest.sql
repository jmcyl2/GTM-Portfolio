-- Backtest: no outreach means no closed-won data. The public-record substitute:
-- a self-administered fund that later reports an outside administrator has
-- *bought* fund-admin services. Question: does the score, measured at a base
-- year, predict which self-administered PE/RE funds buy within 3 years?
--
-- PRE-REGISTERED SCORE (fixed before looking at outcomes; 1 point each):
--   audited      fund gets an annual audit (auditor pressure exposes the close)
--   mid_size     adviser's private fund assets $20M-$500M (needs help, lacks staff)
--   small_mgr    adviser reports 1-5 private funds (no back-office team)
--   growing      fund gross assets up >= 25% on the prior year (close load rising)

CREATE OR REPLACE TABLE fund_year AS
WITH per_filing AS (
    SELECT filing_id, regime, count(*) AS adviser_funds, sum(gross_assets) AS adviser_assets
    FROM fund_obs GROUP BY ALL
)
SELECT o.*, year(o.filed_on) AS yr, p.adviser_funds, p.adviser_assets
FROM fund_obs o JOIN per_filing p USING (filing_id, regime)
WHERE nullif(o.fund_id, '') IS NOT NULL AND o.filed_on IS NOT NULL
QUALIFY row_number() OVER (PARTITION BY o.fund_id, year(o.filed_on) ORDER BY o.filed_on DESC, o.filing_id DESC) = 1;

CREATE OR REPLACE TABLE backtest AS
SELECT b.fund_id, b.crd, b.regime, b.fund_type, b.yr AS base_year,
       b.gross_assets, b.adviser_funds, b.adviser_assets,
       b.audited                                              AS f_audited,
       b.adviser_assets BETWEEN 20e6 AND 500e6                AS f_mid_size,
       b.adviser_funds BETWEEN 1 AND 5                        AS f_small_mgr,
       coalesce(p.gross_assets > 0 AND b.gross_assets >= 1.25 * p.gross_assets, false) AS f_growing,
       o.has_admin                                            AS switched,
       o.filing_id                                            AS outcome_filing_id,
       o.regime                                               AS outcome_regime,
       o.reference_id                                         AS outcome_reference_id
FROM fund_year b
JOIN fund_year o ON o.fund_id = b.fund_id AND o.yr = b.yr + 3
LEFT JOIN fund_year p ON p.fund_id = b.fund_id AND p.yr = b.yr - 1
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
SELECT a.admin_key, any_value(a.administrator) AS administrator, count(DISTINCT bt.fund_id) AS funds_won
FROM backtest bt
JOIN fund_admin_obs a ON a.filing_id = bt.outcome_filing_id AND a.regime = bt.outcome_regime
                     AND a.reference_id = bt.outcome_reference_id
WHERE bt.switched
GROUP BY 1;
