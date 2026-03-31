-- ============================================================================
-- NL2SQL Sales Analytics - Data Population v6
-- 20 months of history: June 2024 – February 2026
--
-- New in v6:
--   • Added 'Personal Care' category with 9 ITC-brand SKUs:
--       Savlon  — Antiseptic Liquid 500ml, Hand Sanitizer 200ml/500ml
--       Fiama   — Shower Gel 250ml, Shampoo 200ml
--       Engage  — Deo Spray 150ml (2 variants)
--       B Natural — Apple Juice 1L, Mixed Fruit Juice 1L
--   • Pharmacy now sells ONLY Personal Care (its legitimate core category)
--   • Pharmacy removed from Aata/Oil — they are not a grocery channel
--   • Eligibility matrix fully updated: 6 retailer types × 6 categories
--   • Personal Care zone skew: South-1/South-2 highest (urban + brand pull)
-- ============================================================================

-- ============================================================================
-- REFERENCE: Geography
-- ============================================================================
CREATE TEMP TABLE ref_zone_state (zone TEXT, state TEXT, city TEXT);
INSERT INTO ref_zone_state VALUES
('South-1','Tamil Nadu',     'Chennai'),
('South-1','Karnataka',      'Bangalore'),
('South-2','Kerala',         'Kochi'),
('South-2','Andhra Pradesh', 'Hyderabad'),
('Central','Madhya Pradesh', 'Indore'),
('Central','Chhattisgarh',   'Raipur'),
('North-1','Delhi',          'New Delhi'),
('North-1','Punjab',         'Ludhiana'),
('North-2','Uttar Pradesh',  'Lucknow'),
('North-2','Rajasthan',      'Jaipur'),
('East',   'West Bengal',    'Kolkata'),
('East',   'Odisha',         'Bhubaneswar');

CREATE TEMP TABLE ref_zone_numbered AS
SELECT zone, state, city,
       ROW_NUMBER() OVER (ORDER BY zone, state) AS zone_idx
FROM ref_zone_state;

-- ============================================================================
-- REFERENCE: Products (now 6 categories, 28 SKUs)
-- Personal Care GST: 18%
-- ============================================================================
CREATE TEMP TABLE ref_product (
  sku_code TEXT, product_desc TEXT, brand TEXT, category TEXT,
  sub_category TEXT, pack_size TEXT, uom TEXT,
  pack_qty DECIMAL(10,2), base_price DECIMAL(10,2),
  tax_rate INT, pop_weight DECIMAL(4,2)
);
INSERT INTO ref_product VALUES
-- Cigarettes (GST 28%)
('CIG001','Gold Flake Kings 20s',    'Gold Flake','Cigarettes','Kings',   '20 sticks','packs',1, 250,28,5.0),
('CIG002','Gold Flake Premium 20s',  'Gold Flake','Cigarettes','Premium', '20 sticks','packs',1, 300,28,3.5),
('CIG003','Navy Cut Filter 20s',     'Navy Cut',  'Cigarettes','Filter',  '20 sticks','packs',1, 180,28,2.5),
('CIG004','Classic Regular 20s',     'Classic',   'Cigarettes','Regular', '20 sticks','packs',1, 220,28,4.0),
('CIG005','Classic Mild 10s',        'Classic',   'Cigarettes','Mild',    '10 sticks','packs',1, 120,28,2.0),
-- Aata (GST 0%)
('ATA001','Aashirvaad Atta 1kg',        'Aashirvaad','Aata','Whole Wheat','1 kg', 'kg', 1,  70, 0,3.0),
('ATA002','Aashirvaad Atta 5kg',        'Aashirvaad','Aata','Whole Wheat','5 kg', 'kg', 5, 320, 0,5.0),
('ATA003','Aashirvaad Atta 10kg',       'Aashirvaad','Aata','Whole Wheat','10 kg','kg',10, 600, 0,4.0),
('ATA004','Aashirvaad Multigrain 1kg',  'Aashirvaad','Aata','Multigrain', '1 kg', 'kg', 1,  90, 0,2.0),
('ATA005','Aashirvaad Select 5kg',      'Aashirvaad','Aata','Select',     '5 kg', 'kg', 5, 380, 0,3.0),
-- Oil (GST 5%)
('OIL001','Fortune Sunflower 1L',    'Fortune','Oil','Sunflower','1 L', 'liters',1, 160, 5,4.0),
('OIL002','Fortune Sunflower 5L',    'Fortune','Oil','Sunflower','5 L', 'liters',5, 750, 5,5.0),
('OIL003','Fortune Refined Soya 1L', 'Fortune','Oil','Soyabean', '1 L', 'liters',1, 130, 5,3.0),
('OIL004','Fortune Rice Bran 1L',    'Fortune','Oil','Rice Bran','1 L', 'liters',1, 195, 5,2.5),
('OIL005','Fortune Mustard 1L',      'Fortune','Oil','Mustard',  '1 L', 'liters',1, 215, 5,3.5),
-- Agarbatti & Matches (GST 12%)
('AGB001','Mangaldeep Bouquet 20s','Mangaldeep','Agarbatti','Fragrance','20 sticks','packs',1, 45,12,3.0),
('AGB002','Mangaldeep Sandal 50s', 'Mangaldeep','Agarbatti','Sandal',  '50 sticks','packs',1, 90,12,2.5),
('AGB003','Aim Match Box 10s',     'Aim',       'Matches',  'Safety',  '10 units', 'packs',1,  6,12,2.0),
-- Personal Care / OTC — ITC brands (GST 18%)
('SAV001','Savlon Antiseptic Liquid 500ml','Savlon',   'Personal Care','Antiseptic','500 ml','packs',1,185,18,4.5),
('SAV002','Savlon Hand Sanitizer 200ml',   'Savlon',   'Personal Care','Sanitizer', '200 ml','packs',1, 99,18,5.0),
('SAV003','Savlon Hand Sanitizer 500ml',   'Savlon',   'Personal Care','Sanitizer', '500 ml','packs',1,199,18,4.0),
('FIA001','Fiama Shower Gel 250ml',        'Fiama',    'Personal Care','Shower Gel','250 ml','packs',1,225,18,3.5),
('FIA002','Fiama Shampoo Damage Repair 200ml','Fiama', 'Personal Care','Shampoo',   '200 ml','packs',1,175,18,3.0),
('ENG001','Engage Spell Deo Spray 150ml',  'Engage',   'Personal Care','Deodorant', '150 ml','packs',1,180,18,3.5),
('ENG002','Engage Tease Deo Spray 150ml',  'Engage',   'Personal Care','Deodorant', '150 ml','packs',1,180,18,3.0),
('BNT001','B Natural Apple Juice 1L',      'B Natural','Personal Care','Juice',     '1 L',   'packs',1,120,18,3.0),
('BNT002','B Natural Mixed Fruit Juice 1L','B Natural','Personal Care','Juice',     '1 L',   'packs',1,120,18,2.5);

-- ============================================================================
-- REFERENCE: Seasonal index
-- ============================================================================
CREATE TEMP TABLE ref_seasonal_index (month_num INT, season_factor DECIMAL(4,2));
INSERT INTO ref_seasonal_index VALUES
(1,1.10),(2,0.95),(3,1.00),(4,1.05),(5,0.90),(6,0.88),
(7,0.92),(8,1.00),(9,1.10),(10,1.30),(11,1.25),(12,1.15);

-- ============================================================================
-- REFERENCE: Day-of-week demand multiplier
-- ============================================================================
CREATE TEMP TABLE ref_dow_factor (dow INT, dow_factor DECIMAL(4,2));
INSERT INTO ref_dow_factor VALUES
(0,0.50),(1,0.95),(2,1.00),(3,1.10),(4,1.20),(5,1.30),(6,1.15);

-- ============================================================================
-- REFERENCE: Category × Zone demand skew
-- ============================================================================
CREATE TEMP TABLE ref_category_zone_skew (category TEXT, zone TEXT, demand_skew DECIMAL(4,2));
INSERT INTO ref_category_zone_skew VALUES
('Cigarettes','South-1',0.95),('Cigarettes','South-2',0.90),
('Cigarettes','Central',1.00),('Cigarettes','North-1',1.15),
('Cigarettes','North-2',1.20),('Cigarettes','East',   1.10),
('Aata','South-1',0.60),('Aata','South-2',0.55),
('Aata','Central',1.10),('Aata','North-1',1.40),
('Aata','North-2',1.35),('Aata','East',   0.85),
('Oil','South-1',1.30),('Oil','South-2',1.25),
('Oil','Central',1.00),('Oil','North-1',0.85),
('Oil','North-2',0.80),('Oil','East',   1.10),
('Agarbatti','South-1',1.20),('Agarbatti','South-2',1.15),
('Agarbatti','Central',1.10),('Agarbatti','North-1',0.95),
('Agarbatti','North-2',0.90),('Agarbatti','East',   1.05),
('Matches','South-1',1.00),('Matches','South-2',1.00),
('Matches','Central',1.00),('Matches','North-1',1.00),
('Matches','North-2',1.00),('Matches','East',   1.00),
-- Personal Care: metros and South skew higher (urban consumption, brand pull)
('Personal Care','South-1',1.25),('Personal Care','South-2',1.20),
('Personal Care','Central',0.90),('Personal Care','North-1',1.15),
('Personal Care','North-2',0.95),('Personal Care','East',   1.05);

-- ============================================================================
-- REFERENCE: Sales hierarchy
-- ============================================================================
CREATE TEMP TABLE ref_sales_hierarchy AS
SELECT
  'SR' || LPAD(g::TEXT,3,'0')                AS salesrep_code,
  'SalesRep ' || g                            AS salesrep_name,
  'SO-'  || LPAD(((g-1)/5  +1)::TEXT,2,'0') AS so_name,
  'ASM-' || LPAD(((g-1)/10 +1)::TEXT,2,'0') AS asm_name,
  'ZSM-' || LPAD(((g-1)/10 +1)::TEXT,2,'0') AS zsm_name,
  ((g-1) % 12) + 1                           AS zone_idx
FROM generate_series(1,60) g;

-- ============================================================================
-- REFERENCE: Distributors
-- ============================================================================
CREATE TEMP TABLE ref_distributor AS
SELECT
  'D' || LPAD(g::TEXT,3,'0')             AS distributor_code,
  'Distributor ' || g || ' - ' || z.city AS distributor_name,
  z.zone, z.state, z.city, z.zone_idx
FROM generate_series(1,25) g
JOIN ref_zone_numbered z ON z.zone_idx = ((g-1) % 12) + 1;

-- ============================================================================
-- REFERENCE: Retailers
-- ============================================================================
CREATE TEMP TABLE ref_retailer AS
SELECT
  d.distributor_code, d.distributor_name,
  'R' || d.distributor_code || '-' || LPAD(r::TEXT,3,'0') AS retailer_code,
  'Retailer ' || r || ' (' ||
    (ARRAY['Modern Trade','General Trade','Kirana','Wholesaler','Pharmacy','Supermarket'])[1+(r%6)] ||
    ')' AS retailer_name,
  (ARRAY['Modern Trade','General Trade','Kirana','Wholesaler','Pharmacy','Supermarket'])[1+(r%6)] AS retailer_type,
  d.zone, d.state, d.city, d.zone_idx
FROM ref_distributor d, generate_series(1,100) r;

-- ============================================================================
-- REFERENCE: Time dimension
-- ============================================================================
CREATE TEMP TABLE ref_dates AS
SELECT d::DATE AS invoice_date
FROM generate_series('2024-06-01'::DATE,'2026-03-31'::DATE,'1 day'::INTERVAL) d;

-- ============================================================================
-- REFERENCE: Retailer × Category eligibility matrix
--
-- Cigarettes  → Kirana ✓, General Trade ✓, Wholesaler ✓
--               Modern Trade ✗, Supermarket ✗, Pharmacy ✗
-- Aata        → all except Pharmacy ✗
-- Oil         → all except Pharmacy ✗
-- Agarbatti   → all except Pharmacy ✗
-- Matches     → all except Pharmacy ✗
-- Personal Care → ALL channels; Pharmacy is the primary channel (3.0×)
-- ============================================================================
CREATE TEMP TABLE ref_retailer_category (
  retailer_type TEXT, category TEXT, eligible BOOLEAN, qty_mult DECIMAL(4,2)
);
INSERT INTO ref_retailer_category VALUES
-- Cigarettes: tobacconist channels only
('Kirana',        'Cigarettes', TRUE,  1.5),
('General Trade', 'Cigarettes', TRUE,  1.2),
('Wholesaler',    'Cigarettes', TRUE,  2.0),
('Modern Trade',  'Cigarettes', FALSE, 0.0),
('Supermarket',   'Cigarettes', FALSE, 0.0),
('Pharmacy',      'Cigarettes', FALSE, 0.0),
-- Aata: grocery channels only
('Kirana',        'Aata', TRUE,  1.0),
('General Trade', 'Aata', TRUE,  1.2),
('Wholesaler',    'Aata', TRUE,  3.0),
('Modern Trade',  'Aata', TRUE,  1.5),
('Supermarket',   'Aata', TRUE,  2.0),
('Pharmacy',      'Aata', FALSE, 0.0),
-- Oil: grocery channels only
('Kirana',        'Oil', TRUE,  1.0),
('General Trade', 'Oil', TRUE,  1.2),
('Wholesaler',    'Oil', TRUE,  3.0),
('Modern Trade',  'Oil', TRUE,  1.5),
('Supermarket',   'Oil', TRUE,  2.0),
('Pharmacy',      'Oil', FALSE, 0.0),
-- Agarbatti: non-pharmacy only
('Kirana',        'Agarbatti', TRUE,  1.2),
('General Trade', 'Agarbatti', TRUE,  1.0),
('Wholesaler',    'Agarbatti', TRUE,  2.5),
('Modern Trade',  'Agarbatti', TRUE,  1.0),
('Supermarket',   'Agarbatti', TRUE,  1.5),
('Pharmacy',      'Agarbatti', FALSE, 0.0),
-- Matches: non-pharmacy only
('Kirana',        'Matches', TRUE,  1.5),
('General Trade', 'Matches', TRUE,  1.2),
('Wholesaler',    'Matches', TRUE,  4.0),
('Modern Trade',  'Matches', TRUE,  0.8),
('Supermarket',   'Matches', TRUE,  1.0),
('Pharmacy',      'Matches', FALSE, 0.0),
-- Personal Care: all channels; Pharmacy is primary
('Pharmacy',      'Personal Care', TRUE,  3.0),
('Supermarket',   'Personal Care', TRUE,  2.5),
('Modern Trade',  'Personal Care', TRUE,  2.0),
('Wholesaler',    'Personal Care', TRUE,  2.0),
('General Trade', 'Personal Care', TRUE,  1.2),
('Kirana',        'Personal Care', TRUE,  0.8);


-- ============================================================================
-- POPULATE: Primary Sales (Company Warehouse → Distributor)
-- ============================================================================
INSERT INTO fact_primary_sales (
  companywh_code, companywh_name,
  distributor_code, distributor_name,
  city, state, zone,
  so_name, asm_name, zsm_name,
  invoice_id, invoice_line_id, invoice_date,
  sku_code, product_desc, brand, category, sub_category, pack_size, uom,
  billed_qty, billed_volume, billed_weight,
  currency, gross_value, net_value, tax_value, tax_rate
)
SELECT
  'WH-' || (1 + (src.zone_idx % 3)) AS companywh_code,
  'ITC Warehouse ' || (ARRAY['Chennai','Delhi','Mumbai'])[1 + (src.zone_idx % 3)] AS companywh_name,
  src.distributor_code, src.distributor_name,
  src.city, src.state, src.zone,
  src.so_name, src.asm_name, src.zsm_name,
  'PRI-' || src.distributor_code || '-' || TO_CHAR(src.invoice_date,'YYYYMMDD') || '-' || src.inv_num AS invoice_id,
  'L1' AS invoice_line_id,
  src.invoice_date,
  src.sku_code, src.product_desc, src.brand,
  src.category, src.sub_category, src.pack_size, src.uom,
  rnd.final_qty AS billed_qty,
  CASE WHEN src.category = 'Oil'  THEN (rnd.final_qty * src.pack_qty)::INT ELSE NULL END AS billed_volume,
  CASE WHEN src.category = 'Aata' THEN (rnd.final_qty * src.pack_qty)::INT ELSE NULL END AS billed_weight,
  'INR',
  (rnd.final_qty * src.base_price * rnd.zpf)::INT AS gross_value,
  (rnd.final_qty * src.base_price * rnd.zpf * (1 - rnd.tdisc/100.0))::INT AS net_value,
  (rnd.final_qty * src.base_price * rnd.zpf * (1 - rnd.tdisc/100.0) * src.tax_rate/100.0)::INT AS tax_value,
  src.tax_rate
FROM (
  SELECT
    d.distributor_code, d.distributor_name,
    d.city, d.state, d.zone, d.zone_idx,
    h.so_name, h.asm_name, h.zsm_name,
    dt.invoice_date,
    CEIL(EXTRACT(DAY FROM dt.invoice_date) / 7.0)::INT AS inv_num,
    p.sku_code, p.product_desc, p.brand,
    p.category, p.sub_category, p.pack_size, p.uom,
    p.pack_qty, p.base_price, p.tax_rate, p.pop_weight,
    COALESCE(si.season_factor, 1.0) AS season_factor,
    COALESCE(czs.demand_skew,  1.0) AS demand_skew,
    COALESCE(dw.dow_factor,    1.0) AS dow_factor
  FROM ref_distributor d
  CROSS JOIN ref_product p
  CROSS JOIN (SELECT invoice_date FROM ref_dates WHERE EXTRACT(DOW FROM invoice_date) BETWEEN 1 AND 5) dt
  JOIN      ref_sales_hierarchy h      ON h.zone_idx   = d.zone_idx
  LEFT JOIN ref_seasonal_index si      ON si.month_num = EXTRACT(MONTH FROM dt.invoice_date)
  LEFT JOIN ref_category_zone_skew czs ON czs.category = p.category AND czs.zone = d.zone
  LEFT JOIN ref_dow_factor dw          ON dw.dow        = EXTRACT(DOW FROM dt.invoice_date)
  WHERE (ABS(hashtext(d.distributor_code || p.sku_code || dt.invoice_date::TEXT)) % 10000) 
        < LEAST(400, 60 * p.pop_weight::INT)
) src
CROSS JOIN LATERAL (
  SELECT
    (0.88 + random() * 0.27)::NUMERIC AS zpf,
    (8    + random() * 4)::NUMERIC    AS tdisc,
    GREATEST(1, (
      CASE src.category
        WHEN 'Cigarettes'    THEN  10 + (random() * 40) 
        WHEN 'Aata'          THEN   5 + (random() * 25) 
        WHEN 'Oil'           THEN   8 + (random() * 32) 
        WHEN 'Agarbatti'     THEN  20 + (random() * 80) 
        WHEN 'Matches'       THEN  40 + (random() * 110)
        WHEN 'Personal Care' THEN  10 + (random() * 40) 
        ELSE                        5 + (random() * 20) 
      END
      * src.season_factor
      * src.demand_skew
      * src.dow_factor
      * (0.5 + (-LN(LEAST(random() + 0.001, 0.999)) * 0.4))
    )::INT) AS final_qty
) rnd;


-- ============================================================================
-- POPULATE: Secondary Sales (Distributor → Retailer)
-- INNER JOIN on ref_retailer_category enforces hard eligibility.
-- ============================================================================
INSERT INTO fact_secondary_sales (
  distributor_code, distributor_name,
  retailer_code, retailer_name, retailer_type,
  route_code, route_name,
  salesrep_code, salesrep_name, so_name, asm_name, zsm_name,
  city, state, zone,
  invoice_id, invoice_line_id, invoice_date,
  sku_code, product_desc, brand, category, sub_category, pack_size, uom,
  billed_qty, billed_volume, billed_weight,
  currency, gross_value, net_value, tax_value, tax_rate
)
SELECT
  src.distributor_code, src.distributor_name,
  src.retailer_code, src.retailer_name, src.retailer_type,
  'RT-' || LPAD((1 + (ABS(hashtext(src.retailer_code)) % 50))::TEXT,2,'0') AS route_code,
  'Route ' || (1 + (ABS(hashtext(src.retailer_code)) % 50))                AS route_name,
  src.salesrep_code, src.salesrep_name,
  src.so_name, src.asm_name, src.zsm_name,
  src.city, src.state, src.zone,
  'SEC-' || src.retailer_code || '-' || TO_CHAR(src.invoice_date,'YYYYMMDD') || '-' || src.inv_num AS invoice_id,
  'L1' AS invoice_line_id,
  src.invoice_date,
  src.sku_code, src.product_desc, src.brand,
  src.category, src.sub_category, src.pack_size, src.uom,
  rnd.final_qty AS billed_qty,
  CASE WHEN src.category = 'Oil'  THEN (rnd.final_qty * src.pack_qty)::INT ELSE NULL END AS billed_volume,
  CASE WHEN src.category = 'Aata' THEN (rnd.final_qty * src.pack_qty)::INT ELSE NULL END AS billed_weight,
  'INR',
  (rnd.final_qty * src.base_price * rnd.zpf)::INT AS gross_value,
  (rnd.final_qty * src.base_price * rnd.zpf * (1 - rnd.tdisc/100.0))::INT AS net_value,
  (rnd.final_qty * src.base_price * rnd.zpf * (1 - rnd.tdisc/100.0) * src.tax_rate/100.0)::INT AS tax_value,
  src.tax_rate
FROM (
  SELECT
    r.distributor_code, r.distributor_name,
    r.retailer_code, r.retailer_name, r.retailer_type,
    r.city, r.state, r.zone, r.zone_idx,
    h.salesrep_code, h.salesrep_name,
    h.so_name, h.asm_name, h.zsm_name,
    dt.invoice_date,
    CEIL(EXTRACT(DAY FROM dt.invoice_date) / 14.0)::INT AS inv_num,
    p.sku_code, p.product_desc, p.brand,
    p.category, p.sub_category, p.pack_size, p.uom,
    p.pack_qty, p.base_price, p.tax_rate, p.pop_weight,
    COALESCE(si.season_factor,  1.0) AS season_factor,
    COALESCE(czs.demand_skew,   1.0) AS demand_skew,
    COALESCE(dw.dow_factor,     1.0) AS dow_factor,
    rc.qty_mult                       AS type_multiplier
  FROM ref_retailer r
  CROSS JOIN ref_product p
  JOIN ref_retailer_category rc        -- INNER JOIN = hard eligibility gate
    ON  rc.retailer_type = r.retailer_type
    AND rc.category      = p.category
    AND rc.eligible      = TRUE
  CROSS JOIN (SELECT invoice_date FROM ref_dates WHERE EXTRACT(DOW FROM invoice_date) BETWEEN 1 AND 5) dt
  JOIN      ref_sales_hierarchy h      ON h.zone_idx      = r.zone_idx
  LEFT JOIN ref_seasonal_index si      ON si.month_num    = EXTRACT(MONTH FROM dt.invoice_date)
  LEFT JOIN ref_category_zone_skew czs ON czs.category    = p.category AND czs.zone = r.zone
  LEFT JOIN ref_dow_factor dw          ON dw.dow           = EXTRACT(DOW FROM dt.invoice_date)
  WHERE (ABS(hashtext(r.retailer_code || p.sku_code || dt.invoice_date::TEXT)) % 10000)
        < LEAST(120, 20 * p.pop_weight::INT)
) src
CROSS JOIN LATERAL (
  SELECT
    (0.92 + random() * 0.16)::NUMERIC AS zpf,
    (10   + random() * 8)::NUMERIC    AS tdisc,
    GREATEST(1, (
      CASE src.category
        WHEN 'Cigarettes'    THEN  1 + (random() * 9) 
        WHEN 'Aata'          THEN  1 + (random() * 9) 
        WHEN 'Oil'           THEN  1 + (random() * 9) 
        WHEN 'Agarbatti'     THEN  3 + (random() * 17)
        WHEN 'Matches'       THEN  5 + (random() * 25)
        WHEN 'Personal Care' THEN  2 + (random() * 8) 
        ELSE                       1 + (random() * 4) 
      END
      * src.type_multiplier
      * src.season_factor
      * src.demand_skew
      * src.dow_factor
      * (0.5 + (-LN(LEAST(random() + 0.001, 0.999)) * 0.4))
    )::INT) AS final_qty
) rnd;


-- ============================================================================
-- Summary
-- ============================================================================
DO $$
DECLARE
  p_count INT;
  s_count INT;
BEGIN
  SELECT COUNT(*) INTO p_count FROM fact_primary_sales;
  SELECT COUNT(*) INTO s_count FROM fact_secondary_sales;
  RAISE NOTICE '=== Data Population v6 Complete ===';
  RAISE NOTICE 'Primary Sales Records  : %', p_count;
  RAISE NOTICE 'Secondary Sales Records: %', s_count;
  RAISE NOTICE 'Date Range             : 2024-06-01 to 2026-02-28';
END $$;