-- ============================================================================
-- NL2SQL Sales Analytics Schema
-- Denormalized Star Schema (OLAP-optimized)
-- ============================================================================

DROP TABLE IF EXISTS fact_secondary_sales CASCADE;
DROP TABLE IF EXISTS fact_primary_sales CASCADE;

-- ============================================================================
-- FACT: Secondary Sales (Distributor → Retailer)
-- Granularity: Invoice Line Item
-- ============================================================================
CREATE TABLE fact_secondary_sales (
  -- Partner info
  distributor_code     VARCHAR(50),
  distributor_name     VARCHAR(100),
  retailer_code        VARCHAR(50),
  retailer_name        VARCHAR(150),
  retailer_type        VARCHAR(50),

  -- Route & sales hierarchy (for RBAC)
  route_code           VARCHAR(50),
  route_name           VARCHAR(100),

  salesrep_code        VARCHAR(50),
  salesrep_name        VARCHAR(100),
  so_name              VARCHAR(100),    -- Sales Officer
  asm_name             VARCHAR(100),    -- Area Sales Manager
  zsm_name             VARCHAR(100),    -- Zonal Sales Manager

  -- Geography
  city                 VARCHAR(100),
  state                VARCHAR(100),
  zone                 VARCHAR(50),

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
  uom                  VARCHAR(20),     -- Unit of Measure (packs, liters, kg)

  -- Volume metrics
  billed_qty           INT,             -- Number of units
  billed_volume        INT,  -- Liters (for Oil)
  billed_weight        INT,   -- Kilograms (for Aata)

  -- Value metrics
  currency             VARCHAR(10),
  gross_value          INT,
  net_value            INT,
  tax_value            INT,
  tax_rate             INT,

  created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- FACT: Primary Sales (Company Warehouse → Distributor)
-- Granularity: Invoice Line Item
-- ============================================================================
CREATE TABLE fact_primary_sales (
  -- Warehouse info
  companywh_code       VARCHAR(50),
  companywh_name       VARCHAR(150),

  -- Distributor info
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
  uom                  VARCHAR(20),

  -- Volume metrics
  billed_qty           INT,
  billed_volume        INT,
  billed_weight        INT,

  -- Value metrics
  currency             VARCHAR(10),
  gross_value          INT,
  net_value            INT,
  tax_value            INT,
  tax_rate             INT,

  created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- ============================================================================
-- INDEXES for Query Performance
-- ============================================================================

-- Secondary Sales Indexes
CREATE INDEX idx_sec_invoice_date ON fact_secondary_sales(invoice_date);
CREATE INDEX idx_sec_zone ON fact_secondary_sales(zone);
CREATE INDEX idx_sec_state ON fact_secondary_sales(state);
CREATE INDEX idx_sec_category ON fact_secondary_sales(category);
CREATE INDEX idx_sec_brand ON fact_secondary_sales(brand);
CREATE INDEX idx_sec_salesrep ON fact_secondary_sales(salesrep_code);
CREATE INDEX idx_sec_so ON fact_secondary_sales(so_name);
CREATE INDEX idx_sec_asm ON fact_secondary_sales(asm_name);
CREATE INDEX idx_sec_zsm ON fact_secondary_sales(zsm_name);
CREATE INDEX idx_sec_distributor ON fact_secondary_sales(distributor_code);

-- Primary Sales Indexes
CREATE INDEX idx_pri_invoice_date ON fact_primary_sales(invoice_date);
CREATE INDEX idx_pri_zone ON fact_primary_sales(zone);
CREATE INDEX idx_pri_state ON fact_primary_sales(state);
CREATE INDEX idx_pri_category ON fact_primary_sales(category);
CREATE INDEX idx_pri_brand ON fact_primary_sales(brand);
CREATE INDEX idx_pri_distributor ON fact_primary_sales(distributor_code);
CREATE INDEX idx_pri_so ON fact_primary_sales(so_name);
CREATE INDEX idx_pri_asm ON fact_primary_sales(asm_name);
CREATE INDEX idx_pri_zsm ON fact_primary_sales(zsm_name);
