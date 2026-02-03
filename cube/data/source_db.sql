DROP TABLE IF EXISTS fact_secondary_sales CASCADE;
DROP TABLE IF EXISTS fact_primary_sales CASCADE;
DROP TABLE IF EXISTS dim_partner CASCADE;
DROP TABLE IF EXISTS dim_sales_hierarchy CASCADE;
DROP TABLE IF EXISTS dim_product CASCADE;
DROP TABLE IF EXISTS dim_geography CASCADE;


CREATE TABLE fact_secondary_sales (
  -- Partner info
  distributor_code     VARCHAR(50),
  distributor_name     VARCHAR(100),
  retailer_code        VARCHAR(50),
  retailer_name        VARCHAR(150),
  retailer_type        VARCHAR(50), -- ModernTrade, GeneralTrade, Kirana, Wholesaler

  -- Route & sales hierarchy
  route_code           VARCHAR(50),
  route_name           VARCHAR(100),

  salesrep_code        VARCHAR(50),
  salesrep_name        VARCHAR(100),
  so_name              VARCHAR(100),
  asm_name             VARCHAR(100),
  zsm_name             VARCHAR(100),

  -- Geography
  city                 VARCHAR(100),
  state                VARCHAR(100),
  zone                 VARCHAR(50), -- South-1, South-2, Central, North-1, North-2, East

  -- Invoice info
  invoice_id           VARCHAR(50),
  invoice_line_id      VARCHAR(50),
  invoice_date         DATE,

  -- Product info
  sku_code             VARCHAR(50),
  product_desc         VARCHAR(200),
  brand                VARCHAR(100),
  category             VARCHAR(100),
  sub_category         VARCHAR(100),
  pack_size            VARCHAR(50),

  -- Volume metrics
  billed_qty           INT,
  billed_volume        DECIMAL(18,2), -- liters or packs
  billed_weight        DECIMAL(18,2), -- kg

  -- Value metrics
  currency             VARCHAR(10),
  gross_value          DECIMAL(18,2),
  net_value            DECIMAL(18,2),
  tax_value            DECIMAL(18,2),
  tax_rate             DECIMAL(5,2),

  -- Technical
  created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE fact_primary_sales (
  -- Company warehouse
  companywh_code       VARCHAR(50),
  companywh_name       VARCHAR(150),

  -- Distributor
  distributor_code     VARCHAR(50),
  distributor_name     VARCHAR(150),

  -- Geography
  city                 VARCHAR(100),
  state                VARCHAR(100),
  zone                 VARCHAR(50),

  -- Sales hierarchy
  so_name              VARCHAR(100),
  asm_name             VARCHAR(100),
  zsm_name             VARCHAR(100),

  -- Invoice info
  invoice_id           VARCHAR(50),
  invoice_line_id      VARCHAR(50),
  invoice_date         DATE,

  -- Product info
  sku_code             VARCHAR(50),
  product_desc         VARCHAR(200),
  brand                VARCHAR(100),
  category             VARCHAR(100),
  sub_category         VARCHAR(100),
  pack_size            VARCHAR(50),

  -- Volume metrics
  billed_qty           INT,
  billed_volume        DECIMAL(18,2),
  billed_weight        DECIMAL(18,2),

  -- Value metrics
  currency             VARCHAR(10),
  gross_value          DECIMAL(18,2),
  net_value            DECIMAL(18,2),
  tax_value            DECIMAL(18,2),
  tax_rate             DECIMAL(5,2),

  created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- Secondary
CREATE INDEX idx_sec_invoice_date ON fact_secondary_sales(invoice_date);
CREATE INDEX idx_sec_zone ON fact_secondary_sales(zone);
CREATE INDEX idx_sec_category ON fact_secondary_sales(category);
CREATE INDEX idx_sec_salesrep ON fact_secondary_sales(salesrep_code);

-- Primary
CREATE INDEX idx_pri_invoice_date ON fact_primary_sales(invoice_date);
CREATE INDEX idx_pri_zone ON fact_primary_sales(zone);
CREATE INDEX idx_pri_category ON fact_primary_sales(category);

-- ----------------------------------------------------------------------------
-- Populate data
-- ----------------------------------------------------------------------------

CREATE TEMP TABLE ref_zone_state (
  zone TEXT,
  state TEXT,
  city TEXT
);

INSERT INTO ref_zone_state VALUES
('South-1','Tamil Nadu','Chennai'),
('South-1','Karnataka','Bangalore'),
('South-2','Kerala','Kochi'),
('North-1','Delhi','New Delhi'),
('North-1','Punjab','Ludhiana'),
('North-2','Uttar Pradesh','Lucknow'),
('East','West Bengal','Kolkata'),
('East','Odisha','Bhubaneswar'),
('Central','Madhya Pradesh','Indore'),
('Central','Chhattisgarh','Raipur'),
('West','Maharashtra','Mumbai'),
('West','Gujarat','Ahmedabad');

-- Number the zone-state combinations for deterministic assignment
CREATE TEMP TABLE ref_zone_numbered AS
SELECT 
  zone, state, city,
  ROW_NUMBER() OVER (ORDER BY zone, state) AS zone_idx
FROM ref_zone_state;

CREATE TEMP TABLE ref_distributor AS
SELECT
  'D' || LPAD(g::TEXT,3,'0') AS distributor_code,
  'Distributor ' || g AS distributor_name,
  z.zone, z.state, z.city
FROM generate_series(1,25) g
JOIN ref_zone_numbered z ON z.zone_idx = ((g - 1) % 12) + 1;


CREATE TEMP TABLE ref_retailer AS
SELECT
  d.distributor_code,
  'R' || d.distributor_code || '_' || r AS retailer_code,
  'Retailer ' || r || ' of ' || d.distributor_code AS retailer_name,
  (ARRAY['ModernTrade','GeneralTrade','Kirana','Wholesaler'])[1 + floor(random()*4)] AS retailer_type,
  d.zone, d.state, d.city
FROM ref_distributor d,
     generate_series(1,100) r;


CREATE TEMP TABLE ref_product (
  sku_code TEXT,
  product_desc TEXT,
  brand TEXT,
  category TEXT,
  sub_category TEXT,
  pack_size TEXT
);

INSERT INTO ref_product VALUES
('CIG001','Gold Flake Kings','Gold Flake','Cigarettes','Kings','20 sticks'),
('CIG002','Navy Cut','Navy Cut','Cigarettes','Regular','20 sticks'),
('ATA001','Aashirvaad Aata 1kg','Aashirvaad','Aata','Wheat','1 kg'),
('ATA002','Aashirvaad Aata 5kg','Aashirvaad','Aata','Wheat','5 kg'),
('OIL001','Fortune Oil 1L','Fortune','Oil','Sunflower','1 L'),
('OIL002','Fortune Oil 2L','Fortune','Oil','Sunflower','2 L');

CREATE TEMP TABLE ref_sales_hierarchy AS
SELECT
  'SR' || g AS salesrep_code,
  'SalesRep ' || g AS salesrep_name,
  'SO ' || ((g-1)/5 + 1) AS so_name,
  'ASM ' || ((g-1)/10 + 1) AS asm_name,
  'ZSM ' || ((g-1)/20 + 1) AS zsm_name
FROM generate_series(1,60) g;

INSERT INTO fact_primary_sales
SELECT
  'WH01',
  'ITC Central WH',
  d.distributor_code,
  d.distributor_name,
  d.city,
  d.state,
  d.zone,
  h.so_name,
  h.asm_name,
  h.zsm_name,
  'PRI-' || d.distributor_code || '-' || g AS invoice_id,
  g::TEXT AS invoice_line_id,
  CURRENT_DATE - (random()*90)::INT,
  p.sku_code,
  p.product_desc,
  p.brand,
  p.category,
  p.sub_category,
  p.pack_size,
  (10 + random()*50)::INT,
  CASE WHEN p.category='Oil' THEN random()*100 ELSE NULL END,
  CASE WHEN p.category='Aata' THEN random()*200 ELSE NULL END,
  'INR',
  random()*50000,
  random()*45000,
  random()*5000,
  18
FROM ref_distributor d
JOIN ref_product p ON true
JOIN ref_sales_hierarchy h ON true
JOIN generate_series(1,5) g ON true;

INSERT INTO fact_secondary_sales
SELECT
  r.distributor_code,
  d.distributor_name,
  r.retailer_code,
  r.retailer_name,
  r.retailer_type,
  'RT' || (random()*50)::INT,
  'Route ' || (random()*50)::INT,
  h.salesrep_code,
  h.salesrep_name,
  h.so_name,
  h.asm_name,
  h.zsm_name,
  r.city,
  r.state,
  r.zone,
  'SEC-' || r.retailer_code || '-' || g AS invoice_id,
  g::TEXT AS invoice_line_id,
  CURRENT_DATE - (random()*90)::INT,
  p.sku_code,
  p.product_desc,
  p.brand,
  p.category,
  p.sub_category,
  p.pack_size,
  (1 + random()*20)::INT,
  CASE WHEN p.category='Oil' THEN random()*20 ELSE NULL END,
  CASE WHEN p.category='Aata' THEN random()*50 ELSE NULL END,
  'INR',
  random()*5000,
  random()*4500,
  random()*500,
  18
FROM ref_retailer r
JOIN ref_distributor d ON d.distributor_code = r.distributor_code
JOIN ref_product p ON true
JOIN ref_sales_hierarchy h ON true
JOIN generate_series(1,3) g ON true;
