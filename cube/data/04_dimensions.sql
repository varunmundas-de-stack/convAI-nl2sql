-- ============================================================================
-- STAR SCHEMA MIGRATION: Dimension Tables + FK Backfill
-- Run AFTER 01_source_db.sql and 02_populate_data.sql
-- ============================================================================

-- ============================================================================
-- 1. dim_geography
-- ============================================================================
CREATE TABLE dim_geography (
  geo_id      SERIAL PRIMARY KEY,
  zone        VARCHAR(50),
  state       VARCHAR(100),
  city        VARCHAR(100),
  territory   VARCHAR(100),
  geo_level   VARCHAR(20) DEFAULT 'city'
    CHECK (geo_level IN ('national','zone','state','city','territory'))
);

INSERT INTO dim_geography (zone, state, city, territory, geo_level)
SELECT DISTINCT zone, state, city, NULL AS territory, 'city' AS geo_level
FROM fact_secondary_sales
WHERE zone IS NOT NULL
ORDER BY zone, state, city;

-- Add zone-level rollup rows
INSERT INTO dim_geography (zone, state, city, territory, geo_level)
SELECT DISTINCT zone, NULL, NULL, NULL, 'zone'
FROM fact_secondary_sales WHERE zone IS NOT NULL;

-- Add national row
INSERT INTO dim_geography (zone, state, city, territory, geo_level)
VALUES (NULL, NULL, NULL, NULL, 'national');

-- ============================================================================
-- 2. dim_product
-- ============================================================================
CREATE TABLE dim_product (
  product_id   SERIAL PRIMARY KEY,
  sku_code     VARCHAR(50),
  sku_name     VARCHAR(200),
  brand        VARCHAR(100),
  category     VARCHAR(100),
  sub_category VARCHAR(100),
  pack_size    VARCHAR(50)
);

INSERT INTO dim_product (sku_code, sku_name, brand, category, sub_category, pack_size)
SELECT DISTINCT sku_code, product_desc, brand, category, sub_category, pack_size
FROM fact_secondary_sales
WHERE sku_code IS NOT NULL
ORDER BY category, brand, sku_code;

-- ============================================================================
-- 3. dim_salesorg
-- ============================================================================
CREATE TABLE dim_salesorg (
  org_id    SERIAL PRIMARY KEY,
  so_code   VARCHAR(100),
  asm_name  VARCHAR(100),
  zsm_name  VARCHAR(100),
  zone      VARCHAR(50)
);

INSERT INTO dim_salesorg (so_code, asm_name, zsm_name, zone)
SELECT DISTINCT so_name, asm_name, zsm_name, zone
FROM fact_secondary_sales
WHERE so_name IS NOT NULL
ORDER BY zsm_name, asm_name, so_name;

-- ============================================================================
-- 4. dim_distributor
-- ============================================================================
CREATE TABLE dim_distributor (
  dist_id          SERIAL PRIMARY KEY,
  distributor_code VARCHAR(50),
  distributor_name VARCHAR(150),
  channel_type     VARCHAR(50) DEFAULT 'distributor',
  beat_plan        VARCHAR(100),
  geo_id           INT REFERENCES dim_geography(geo_id)
);

INSERT INTO dim_distributor (distributor_code, distributor_name, channel_type, beat_plan, geo_id)
SELECT DISTINCT
  fs.distributor_code,
  fs.distributor_name,
  'distributor',
  NULL,
  dg.geo_id
FROM fact_secondary_sales fs
JOIN dim_geography dg
  ON dg.zone = fs.zone AND dg.state = fs.state AND dg.city = fs.city AND dg.geo_level = 'city'
WHERE fs.distributor_code IS NOT NULL
ORDER BY fs.distributor_code;

-- ============================================================================
-- 5. dim_customer (retailers)
-- ============================================================================
CREATE TABLE dim_customer (
  customer_id   SERIAL PRIMARY KEY,
  customer_code VARCHAR(50),
  customer_name VARCHAR(150),
  channel_type  VARCHAR(50),
  tier          VARCHAR(50),
  geo_id        INT REFERENCES dim_geography(geo_id)
);

INSERT INTO dim_customer (customer_code, customer_name, channel_type, tier, geo_id)
SELECT DISTINCT
  fs.retailer_code,
  fs.retailer_name,
  fs.retailer_type,
  NULL,
  dg.geo_id
FROM fact_secondary_sales fs
JOIN dim_geography dg
  ON dg.zone = fs.zone AND dg.state = fs.state AND dg.city = fs.city AND dg.geo_level = 'city'
WHERE fs.retailer_code IS NOT NULL
ORDER BY fs.retailer_code;

-- ============================================================================
-- 6. dim_period
-- ============================================================================
CREATE TABLE dim_period (
  period_id      SERIAL PRIMARY KEY,
  date           DATE UNIQUE,
  fiscal_week    INT,
  fiscal_month   INT,
  fiscal_quarter INT,
  fiscal_year    INT,
  is_ytd         BOOLEAN
);

INSERT INTO dim_period (date, fiscal_week, fiscal_month, fiscal_quarter, fiscal_year, is_ytd)
SELECT
  d::DATE,
  EXTRACT(WEEK  FROM d::DATE)::INT,
  EXTRACT(MONTH FROM d::DATE)::INT,
  EXTRACT(QUARTER FROM d::DATE)::INT,
  EXTRACT(YEAR  FROM d::DATE)::INT,
  (d::DATE <= CURRENT_DATE AND EXTRACT(YEAR FROM d::DATE) = EXTRACT(YEAR FROM CURRENT_DATE))
FROM generate_series('2024-06-01'::DATE, '2026-03-31'::DATE, '1 day'::INTERVAL) d;

-- ============================================================================
-- ADD FK COLUMNS TO FACT TABLES
-- ============================================================================

-- fact_secondary_sales
ALTER TABLE fact_secondary_sales ADD COLUMN geo_id      INT REFERENCES dim_geography(geo_id);
ALTER TABLE fact_secondary_sales ADD COLUMN product_id  INT REFERENCES dim_product(product_id);
ALTER TABLE fact_secondary_sales ADD COLUMN org_id      INT REFERENCES dim_salesorg(org_id);
ALTER TABLE fact_secondary_sales ADD COLUMN dist_id     INT REFERENCES dim_distributor(dist_id);
ALTER TABLE fact_secondary_sales ADD COLUMN customer_id INT REFERENCES dim_customer(customer_id);
ALTER TABLE fact_secondary_sales ADD COLUMN period_id   INT REFERENCES dim_period(period_id);

-- fact_primary_sales
ALTER TABLE fact_primary_sales ADD COLUMN geo_id     INT REFERENCES dim_geography(geo_id);
ALTER TABLE fact_primary_sales ADD COLUMN product_id INT REFERENCES dim_product(product_id);
ALTER TABLE fact_primary_sales ADD COLUMN org_id     INT REFERENCES dim_salesorg(org_id);
ALTER TABLE fact_primary_sales ADD COLUMN dist_id    INT REFERENCES dim_distributor(dist_id);
ALTER TABLE fact_primary_sales ADD COLUMN period_id  INT REFERENCES dim_period(period_id);

-- ============================================================================
-- BACKFILL FK COLUMNS
-- ============================================================================

-- fact_secondary_sales — geo_id
UPDATE fact_secondary_sales fs
SET geo_id = dg.geo_id
FROM dim_geography dg
WHERE dg.zone = fs.zone AND dg.state = fs.state AND dg.city = fs.city AND dg.geo_level = 'city';

-- fact_secondary_sales — product_id
UPDATE fact_secondary_sales fs
SET product_id = dp.product_id
FROM dim_product dp
WHERE dp.sku_code = fs.sku_code;

-- fact_secondary_sales — org_id
UPDATE fact_secondary_sales fs
SET org_id = ds.org_id
FROM dim_salesorg ds
WHERE ds.so_code = fs.so_name AND ds.asm_name = fs.asm_name AND ds.zsm_name = fs.zsm_name;

-- fact_secondary_sales — dist_id
UPDATE fact_secondary_sales fs
SET dist_id = dd.dist_id
FROM dim_distributor dd
WHERE dd.distributor_code = fs.distributor_code;

-- fact_secondary_sales — customer_id
UPDATE fact_secondary_sales fs
SET customer_id = dc.customer_id
FROM dim_customer dc
WHERE dc.customer_code = fs.retailer_code;

-- fact_secondary_sales — period_id
UPDATE fact_secondary_sales fs
SET period_id = dp.period_id
FROM dim_period dp
WHERE dp.date = fs.invoice_date;

-- fact_primary_sales — geo_id
UPDATE fact_primary_sales fp
SET geo_id = dg.geo_id
FROM dim_geography dg
WHERE dg.zone = fp.zone AND dg.state = fp.state AND dg.city = fp.city AND dg.geo_level = 'city';

-- fact_primary_sales — product_id
UPDATE fact_primary_sales fp
SET product_id = dp.product_id
FROM dim_product dp
WHERE dp.sku_code = fp.sku_code;

-- fact_primary_sales — org_id
UPDATE fact_primary_sales fp
SET org_id = ds.org_id
FROM dim_salesorg ds
WHERE ds.so_code = fp.so_name AND ds.asm_name = fp.asm_name AND ds.zsm_name = fp.zsm_name;

-- fact_primary_sales — dist_id
UPDATE fact_primary_sales fp
SET dist_id = dd.dist_id
FROM dim_distributor dd
WHERE dd.distributor_code = fp.distributor_code;

-- fact_primary_sales — period_id
UPDATE fact_primary_sales fp
SET period_id = dp.period_id
FROM dim_period dp
WHERE dp.date = fp.invoice_date;

-- ============================================================================
-- VALIDATION COUNTS
-- ============================================================================
DO $$
DECLARE r RECORD;
BEGIN
  FOR r IN
    SELECT 'dim_geography'   AS tbl, COUNT(*) AS n FROM dim_geography  UNION ALL
    SELECT 'dim_product',           COUNT(*)        FROM dim_product    UNION ALL
    SELECT 'dim_salesorg',          COUNT(*)        FROM dim_salesorg   UNION ALL
    SELECT 'dim_distributor',       COUNT(*)        FROM dim_distributor UNION ALL
    SELECT 'dim_customer',          COUNT(*)        FROM dim_customer   UNION ALL
    SELECT 'dim_period',            COUNT(*)        FROM dim_period
  LOOP
    RAISE NOTICE '%-20s : %', r.tbl, r.n;
  END LOOP;
END $$;
