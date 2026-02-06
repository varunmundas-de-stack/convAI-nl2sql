-- ============================================================================
-- NL2SQL Sales Analytics - Data Population
-- 20 months of history: June 2024 – February 2026
-- ============================================================================

-- ============================================================================
-- REFERENCE DATA: Geography (6 Zones, 12 States)
-- ============================================================================
CREATE TEMP TABLE ref_zone_state (
  zone TEXT,
  state TEXT,
  city TEXT
);

INSERT INTO ref_zone_state VALUES
-- South-1 Zone
('South-1', 'Tamil Nadu', 'Chennai'),
('South-1', 'Karnataka', 'Bangalore'),
-- South-2 Zone  
('South-2', 'Kerala', 'Kochi'),
('South-2', 'Andhra Pradesh', 'Hyderabad'),
-- Central Zone
('Central', 'Madhya Pradesh', 'Indore'),
('Central', 'Chhattisgarh', 'Raipur'),
-- North-1 Zone
('North-1', 'Delhi', 'New Delhi'),
('North-1', 'Punjab', 'Ludhiana'),
-- North-2 Zone
('North-2', 'Uttar Pradesh', 'Lucknow'),
('North-2', 'Rajasthan', 'Jaipur'),
-- East Zone
('East', 'West Bengal', 'Kolkata'),
('East', 'Odisha', 'Bhubaneswar');

-- Number the zone-state combinations for deterministic assignment
CREATE TEMP TABLE ref_zone_numbered AS
SELECT 
  zone, state, city,
  ROW_NUMBER() OVER (ORDER BY zone, state) AS zone_idx
FROM ref_zone_state;

-- ============================================================================
-- REFERENCE DATA: Products (ITC-like portfolio)
-- ============================================================================
CREATE TEMP TABLE ref_product (
  sku_code TEXT,
  product_desc TEXT,
  brand TEXT,
  category TEXT,
  sub_category TEXT,
  pack_size TEXT,
  uom TEXT,
  pack_qty DECIMAL(10,2),      -- Numeric value for calculations
  base_price DECIMAL(10,2)     -- Base unit price
);

INSERT INTO ref_product VALUES
-- Cigarettes (count-based: packs)
('CIG001', 'Gold Flake Kings 20s', 'Gold Flake', 'Cigarettes', 'Kings', '20 sticks', 'packs', 1, 250),
('CIG002', 'Gold Flake Premium', 'Gold Flake', 'Cigarettes', 'Premium', '20 sticks', 'packs', 1, 300),
('CIG003', 'Navy Cut Filter', 'Navy Cut', 'Cigarettes', 'Filter', '20 sticks', 'packs', 1, 180),
('CIG004', 'Classic Regular', 'Classic', 'Cigarettes', 'Regular', '20 sticks', 'packs', 1, 220),
('CIG005', 'Classic Mild', 'Classic', 'Cigarettes', 'Mild', '10 sticks', 'packs', 1, 120),

-- Aata (weight-based: kg)
('ATA001', 'Aashirvaad Atta 1kg', 'Aashirvaad', 'Aata', 'Whole Wheat', '1 kg', 'kg', 1, 55),
('ATA002', 'Aashirvaad Atta 5kg', 'Aashirvaad', 'Aata', 'Whole Wheat', '5 kg', 'kg', 5, 250),
('ATA003', 'Aashirvaad Atta 10kg', 'Aashirvaad', 'Aata', 'Whole Wheat', '10 kg', 'kg', 10, 480),
('ATA004', 'Aashirvaad Multigrain 1kg', 'Aashirvaad', 'Aata', 'Multigrain', '1 kg', 'kg', 1, 75),
('ATA005', 'Aashirvaad Select 5kg', 'Aashirvaad', 'Aata', 'Select', '5 kg', 'kg', 5, 320),

-- Oil (volume-based: liters)
('OIL001', 'Fortune Sunflower 1L', 'Fortune', 'Oil', 'Sunflower', '1 L', 'liters', 1, 140),
('OIL002', 'Fortune Sunflower 5L', 'Fortune', 'Oil', 'Sunflower', '5 L', 'liters', 5, 650),
('OIL003', 'Fortune Refined Soya 1L', 'Fortune', 'Oil', 'Soyabean', '1 L', 'liters', 1, 120),
('OIL004', 'Fortune Rice Bran 1L', 'Fortune', 'Oil', 'Rice Bran', '1 L', 'liters', 1, 180),
('OIL005', 'Fortune Mustard 1L', 'Fortune', 'Oil', 'Mustard', '1 L', 'liters', 1, 200),

-- Agarbatti (count-based: packs)
('AGB001', 'Mangaldeep Bouquet', 'Mangaldeep', 'Agarbatti', 'Fragrance', '20 sticks', 'packs', 1, 40),
('AGB002', 'Mangaldeep Sandal', 'Mangaldeep', 'Agarbatti', 'Sandal', '50 sticks', 'packs', 1, 80),
('AGB003', 'Aim Match Box', 'Aim', 'Matches', 'Safety', '10 units', 'packs', 1, 5);

-- ============================================================================
-- REFERENCE DATA: Sales Hierarchy (SR → SO → ASM → ZSM)
-- 60 Sales Reps across 6 zones
-- ============================================================================
CREATE TEMP TABLE ref_sales_hierarchy AS
SELECT
  'SR' || LPAD(g::TEXT, 3, '0') AS salesrep_code,
  'SalesRep ' || g AS salesrep_name,
  'SO-' || LPAD(((g-1)/5 + 1)::TEXT, 2, '0') AS so_name,
  'ASM-' || LPAD(((g-1)/10 + 1)::TEXT, 2, '0') AS asm_name,
  'ZSM-' || LPAD(((g-1)/10 + 1)::TEXT, 2, '0') AS zsm_name,
  ((g - 1) % 12) + 1 AS zone_idx  -- Maps to zone
FROM generate_series(1, 60) g;

-- ============================================================================
-- REFERENCE DATA: Distributors (25 across 12 states)
-- ============================================================================
CREATE TEMP TABLE ref_distributor AS
SELECT
  'D' || LPAD(g::TEXT, 3, '0') AS distributor_code,
  'Distributor ' || g || ' - ' || z.city AS distributor_name,
  z.zone, z.state, z.city,
  z.zone_idx
FROM generate_series(1, 25) g
JOIN ref_zone_numbered z ON z.zone_idx = ((g - 1) % 12) + 1;

-- ============================================================================
-- REFERENCE DATA: Retailers (100 per Distributor = 2,500 total)
-- ============================================================================
CREATE TEMP TABLE ref_retailer AS
SELECT
  d.distributor_code,
  d.distributor_name,
  'R' || d.distributor_code || '-' || LPAD(r::TEXT, 3, '0') AS retailer_code,
  'Retailer ' || r || ' (' || 
    (ARRAY['Modern Trade', 'General Trade', 'Kirana', 'Wholesaler', 'Pharmacy', 'Supermarket'])[1 + (r % 6)] || 
    ')' AS retailer_name,
  (ARRAY['Modern Trade', 'General Trade', 'Kirana', 'Wholesaler', 'Pharmacy', 'Supermarket'])[1 + (r % 6)] AS retailer_type,
  d.zone, d.state, d.city, d.zone_idx
FROM ref_distributor d,
     generate_series(1, 100) r;

-- ============================================================================
-- REFERENCE DATA: Time Dimension (20 months: Jun 2024 - Feb 2026)
-- ============================================================================
CREATE TEMP TABLE ref_dates AS
SELECT d::DATE AS invoice_date
FROM generate_series('2024-06-01'::DATE, '2026-02-28'::DATE, '1 day'::INTERVAL) d;

-- ============================================================================
-- POPULATE: Primary Sales (Company → Distributor)
-- ~2,000 invoices/month × 20 months = ~40,000 total invoice lines
-- Each distributor gets ~4 invoices/month with ~20 SKUs each
-- ============================================================================

INSERT INTO fact_primary_sales
SELECT
  'WH-' || (1 + (d.zone_idx % 3)) AS companywh_code,
  'ITC Warehouse ' || (ARRAY['Chennai', 'Delhi', 'Mumbai'])[1 + (d.zone_idx % 3)] AS companywh_name,
  d.distributor_code,
  d.distributor_name,
  d.city,
  d.state,
  d.zone,
  h.so_name,
  h.asm_name,
  h.zsm_name,
  'PRI-' || d.distributor_code || '-' || TO_CHAR(dt.invoice_date, 'YYYYMMDD') || '-' || inv_num AS invoice_id,
  'L' || line_num AS invoice_line_id,
  dt.invoice_date,
  p.sku_code,
  p.product_desc,
  p.brand,
  p.category,
  p.sub_category,
  p.pack_size,
  p.uom,

  -- Quantity
  (10 + (random() * 90))::INT AS billed_qty,

  -- Volume for Oil
  CASE
    WHEN p.category = 'Oil'
    THEN ((10 + (random() * 90))::INT * p.pack_qty)::INT
    ELSE NULL
  END AS billed_volume,

  -- Weight for Aata
  CASE
    WHEN p.category = 'Aata'
    THEN ((10 + (random() * 90))::INT * p.pack_qty)::INT
    ELSE NULL
  END AS billed_weight,

  'INR' AS currency,

  -- Value metrics (INT)
  ((10 + (random() * 90))::INT * p.base_price)::INT AS gross_value,
  (((10 + (random() * 90))::INT * p.base_price) * 82 / 100)::INT AS net_value,
  (((10 + (random() * 90))::INT * p.base_price) * 18 / 100)::INT AS tax_value,
  18 AS tax_rate

FROM ref_distributor d
CROSS JOIN ref_product p
CROSS JOIN (
  SELECT invoice_date, inv_num
  FROM ref_dates, generate_series(1, 4) inv_num
  WHERE EXTRACT(DAY FROM invoice_date) IN (5, 12, 19, 26)
) dt
CROSS JOIN generate_series(1, 1) line_num
JOIN ref_sales_hierarchy h ON h.zone_idx = d.zone_idx
WHERE random() < 0.15;


-- ============================================================================
-- POPULATE: Secondary Sales (Distributor → Retailer)
-- Higher volume: ~200 invoices per retailer over 20 months
-- ============================================================================

INSERT INTO fact_secondary_sales
SELECT
  r.distributor_code,
  r.distributor_name,
  r.retailer_code,
  r.retailer_name,
  r.retailer_type,
  'RT-' || LPAD((1 + (ABS(hashtext(r.retailer_code)) % 50))::TEXT, 2, '0') AS route_code,
  'Route ' || (1 + (ABS(hashtext(r.retailer_code)) % 50)) AS route_name,
  h.salesrep_code,
  h.salesrep_name,
  h.so_name,
  h.asm_name,
  h.zsm_name,
  r.city,
  r.state,
  r.zone,
  'SEC-' || r.retailer_code || '-' || TO_CHAR(dt.invoice_date, 'YYYYMMDD') || '-' || inv_num AS invoice_id,
  'L' || line_num AS invoice_line_id,
  dt.invoice_date,
  p.sku_code,
  p.product_desc,
  p.brand,
  p.category,
  p.sub_category,
  p.pack_size,
  p.uom,

  -- Quantity
  (1 + (random() * 19))::INT AS billed_qty,

  -- Volume for Oil
  CASE
    WHEN p.category = 'Oil'
    THEN ((1 + (random() * 19))::INT * p.pack_qty)::INT
    ELSE NULL
  END AS billed_volume,

  -- Weight for Aata
  CASE
    WHEN p.category = 'Aata'
    THEN ((1 + (random() * 19))::INT * p.pack_qty)::INT
    ELSE NULL
  END AS billed_weight,

  'INR' AS currency,

  -- Value metrics (INT)
  ((1 + (random() * 19))::INT * p.base_price)::INT AS gross_value,
  (((1 + (random() * 19))::INT * p.base_price) * 82 / 100)::INT AS net_value,
  (((1 + (random() * 19))::INT * p.base_price) * 18 / 100)::INT AS tax_value,
  18 AS tax_rate

FROM ref_retailer r
CROSS JOIN ref_product p
CROSS JOIN (
  SELECT invoice_date, inv_num
  FROM ref_dates, generate_series(1, 2) inv_num
  WHERE EXTRACT(DOW FROM invoice_date) IN (1, 3, 5)
) dt
CROSS JOIN generate_series(1, 1) line_num
JOIN ref_sales_hierarchy h ON h.zone_idx = r.zone_idx
WHERE random() < 0.008;

-- ============================================================================
-- Summary Statistics
-- ============================================================================
DO $$
DECLARE
  primary_count INT;
  secondary_count INT;
BEGIN
  SELECT COUNT(*) INTO primary_count FROM fact_primary_sales;
  SELECT COUNT(*) INTO secondary_count FROM fact_secondary_sales;
  
  RAISE NOTICE '=== Data Population Complete ===';
  RAISE NOTICE 'Primary Sales Records: %', primary_count;
  RAISE NOTICE 'Secondary Sales Records: %', secondary_count;
  RAISE NOTICE 'Date Range: 2024-06-01 to 2026-02-28';
END $$;