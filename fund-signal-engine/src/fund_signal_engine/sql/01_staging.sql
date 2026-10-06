-- Staging: one clean, typed table per concept. Raw tables are all-VARCHAR.

CREATE OR REPLACE TABLE filings AS
SELECT regime,
       try_cast(FilingID AS BIGINT)                                         AS filing_id,
       trim("1E1")                                                          AS crd,
       trim("1A")                                                           AS adviser_name,
       try_strptime(split_part(trim(DateSubmitted), ' ', 1), '%m/%d/%Y')::DATE AS filed_on,
       nullif(trim("1F1-State"), '')                                        AS state,
       nullif(trim("1F1-Country"), '')                                      AS country
FROM (SELECT 'ERA' AS regime, * FROM raw_era_base
      UNION ALL BY NAME
      SELECT 'IA' AS regime, * FROM raw_ia_base)
WHERE nullif(trim("1E1"), '') IS NOT NULL;

-- Every private fund row on every filing, 2011-2024 (Schedule D 7.B.(1)).
CREATE OR REPLACE TABLE fund_obs AS
SELECT fl.regime, fl.filing_id, fl.crd, fl.adviser_name, fl.filed_on,
       trim(f."Fund ID")                                                    AS fund_id,
       trim(f.ReferenceID)                                                  AS reference_id,
       trim(f."Fund Name")                                                  AS fund_name,
       nullif(trim(f."Fund Type"), '')                                      AS fund_type,
       try_cast(replace(f."Gross Asset Value", ',', '') AS DOUBLE)          AS gross_assets,
       f."Annual Audit" = 'Y'                                               AS audited,
       CASE f.Administrator WHEN 'Y' THEN true WHEN 'N' THEN false END      AS has_admin,
       nullif(trim(f.Country), '')                                          AS fund_country,
       -- extra fund attributes used as candidate signals by the v2 score
       try_cast(replace(f.Owners, ',', '') AS INTEGER)                      AS owners,
       try_cast(f."%Owned Non-US" AS DOUBLE)                                AS pct_non_us,
       try_cast(f."%Owned You or Related" AS DOUBLE)                        AS pct_owned_related,
       try_cast(f."% Assets Valued" AS DOUBLE)                              AS pct_third_party_valued,
       try_cast(replace(f."Minimum Investment", ',', '') AS DOUBLE)         AS min_investment,
       f."Fund of Funds" = 'Y'                                              AS fund_of_funds,
       f."Master Fund" = 'Y' OR f."Feeder Fund" = 'Y'                       AS master_feeder,
       f."3(c)(7) Exclusion" = 'Y'                                          AS qualified_purchasers_only,
       f.GAAP = 'Y'                                                         AS gaap,
       f."FS Distributed" = 'Y'                                             AS fs_distributed,
       f.Marketing = 'Y'                                                    AS uses_placement_agent
FROM (SELECT 'ERA' AS regime, * FROM raw_era_funds
      UNION ALL BY NAME
      SELECT 'IA' AS regime, * FROM raw_ia_funds) f
JOIN filings fl ON fl.filing_id = try_cast(f.FilingID AS BIGINT) AND fl.regime = f.regime;

CREATE OR REPLACE TABLE fund_admin_obs AS
SELECT fl.regime, fl.filing_id, fl.crd, fl.filed_on,
       trim(a.ReferenceID)                AS reference_id,
       trim(a."Name of Administrator")    AS administrator,
       -- collapse 'X, LLC' / 'X LLC' / 'X, Inc.' into one key
       trim(regexp_replace(regexp_replace(regexp_replace(upper(a."Name of Administrator"),
            '[^A-Z0-9& ]', ' ', 'g'),
            '\b(LLC|L L C|INC|LP|L P|LLP|LTD|LIMITED|CO|CORP|CORPORATION|COMPANY|THE)\b', ' ', 'g'),
            '\s+', ' ', 'g'))         AS admin_key,
       nullif(trim(a.City), '')           AS admin_city,
       nullif(trim(a.State), '')          AS admin_state,
       nullif(trim(a.Country), '')        AS admin_country
FROM (SELECT 'ERA' AS regime, * FROM raw_era_admins
      UNION ALL BY NAME
      SELECT 'IA' AS regime, * FROM raw_ia_admins) a
JOIN filings fl ON fl.filing_id = try_cast(a.FilingID AS BIGINT) AND fl.regime = a.regime;

CREATE OR REPLACE TABLE filing_contacts AS
SELECT regime, try_cast(FilingID AS BIGINT) AS filing_id,
       nullif(trim("1J1 Name"), '') AS cco_name
FROM (SELECT 'ERA' AS regime, * FROM raw_era_contacts
      UNION ALL BY NAME
      SELECT 'IA' AS regime, * FROM raw_ia_contacts);

-- Who is registered or exempt-reporting with the SEC right now.
CREATE OR REPLACE TABLE roster AS
SELECT trim("Organization CRD#")                                                AS crd,
       trim("Primary Business Name")                                            AS firm_name,
       status,
       nullif(trim("Website Address"), '')                                      AS website,
       nullif(trim("Main Office State"), '')                                    AS state,
       nullif(trim("Main Office Country"), '')                                  AS country,
       try_cast(replace(trim("Total Gross Assets of Private Funds"), ',', '') AS DOUBLE) AS private_fund_assets,
       try_cast(trim("Count of Private Funds - 7B(1)") AS INTEGER)              AS private_fund_count,
       source_file
FROM (SELECT 'registered' AS status, * FROM raw_roster_registered
      UNION ALL BY NAME
      SELECT 'exempt' AS status, * FROM raw_roster_exempt);
