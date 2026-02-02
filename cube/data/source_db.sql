DROP TABLE IF EXISTS fact_secondary_sales CASCADE;
DROP TABLE IF EXISTS fact_primary_sales CASCADE;
DROP TABLE IF EXISTS dim_partner CASCADE;
DROP TABLE IF EXISTS dim_sales_hierarchy CASCADE;
DROP TABLE IF EXISTS dim_product CASCADE;
DROP TABLE IF EXISTS dim_geography CASCADE;

-- 1. Dimension: Geography (Supports the 6 Zones, 12 States requirement)
CREATE TABLE dim_geography (
    geo_id SERIAL PRIMARY KEY,
    zone_name VARCHAR(50),      -- e.g., 'North Zone', 'South Zone'
    state_name VARCHAR(50),     -- e.g., 'Delhi', 'Tamil Nadu'
    city_name VARCHAR(50)
);

-- 2. Dimension: Product (Supports "Cigarettes" vs "Groceries" & different UOMs)
CREATE TABLE dim_product (
    sku_id SERIAL PRIMARY KEY,
    category_name VARCHAR(50),  -- e.g., 'Cigarettes', 'Staples', 'Oils'
    brand_name VARCHAR(50),     -- e.g., 'Classic', 'Aashirwaad'
    sku_name VARCHAR(100),      -- e.g., 'Aashirwaad Aata 5kg'
    uom VARCHAR(20)             -- e.g., 'Packs', 'Kg', 'Ltr' (Critical for volume adaptation)
);

-- 3. Dimension: Sales Hierarchy (Supports RBAC: SalesRep -> SO -> AM -> ZM)
-- This table defines the reporting structure. For RBAC, you would filter data based on these IDs.
CREATE TABLE dim_sales_hierarchy (
    hierarchy_id SERIAL PRIMARY KEY,
    sales_rep_name VARCHAR(100),
    sales_officer_name VARCHAR(100), -- Reports to
    area_manager_name VARCHAR(100),  -- Reports to
    zonal_manager_name VARCHAR(100), -- Reports to
    zone_id INT REFERENCES dim_geography(geo_id)
);

-- 4. Dimension: Partners (Warehouses, Distributors, Retailers)
CREATE TABLE dim_partner (
    partner_id SERIAL PRIMARY KEY,
    partner_type VARCHAR(20),   -- 'Warehouse', 'Distributor', 'Retailer'
    partner_name VARCHAR(100),
    geo_id INT REFERENCES dim_geography(geo_id)
);

-- 5. Fact Table: Primary Sales (Company Warehouse -> Distributor)
CREATE TABLE fact_primary_sales (
    transaction_id SERIAL PRIMARY KEY,
    invoice_date DATE,
    invoice_number VARCHAR(50),
    
    -- Links to Dimensions
    warehouse_id INT REFERENCES dim_partner(partner_id), -- Source
    distributor_id INT REFERENCES dim_partner(partner_id), -- Destination
    sku_id INT REFERENCES dim_product(sku_id),
    
    -- Metrics
    volume_qty DECIMAL(10, 2),  -- Quantity in UOM (e.g., 500 Kg or 1000 Packs)
    gross_value DECIMAL(15, 2),
    tax_amount DECIMAL(15, 2),
    net_value DECIMAL(15, 2)
);

-- 6. Fact Table: Secondary Sales (Distributor -> Retailer)
-- "Includes distributor and retailer info, route codes, SalesRep hierarchy"
CREATE TABLE fact_secondary_sales (
    transaction_id SERIAL PRIMARY KEY,
    invoice_date DATE,
    invoice_number VARCHAR(50),
    
    -- Links to Dimensions
    distributor_id INT REFERENCES dim_partner(partner_id), -- Source
    retailer_id INT REFERENCES dim_partner(partner_id),    -- Destination
    sku_id INT REFERENCES dim_product(sku_id),
    hierarchy_id INT REFERENCES dim_sales_hierarchy(hierarchy_id), -- Links transaction to specific SalesRep/Team
    
    -- Route & Logistics
    route_code VARCHAR(50),
    
    -- Metrics (Flexible for different product types)
    volume_qty DECIMAL(10, 2),   -- Dynamic interpretation based on dim_product.uom
    gross_value DECIMAL(15, 2),
    tax_amount DECIMAL(15, 2),
    net_value DECIMAL(15, 2)
);



-- 1. Populate Geography (6 Zones, 12 States)
INSERT INTO dim_geography (zone_name, state_name, city_name)
VALUES 
('North Zone', 'Delhi', 'New Delhi'), ('North Zone', 'Punjab', 'Ludhiana'),
('South Zone', 'Tamil Nadu', 'Chennai'), ('South Zone', 'Karnataka', 'Bangalore'),
('East Zone', 'West Bengal', 'Kolkata'), ('East Zone', 'Odisha', 'Bhubaneswar'),
('West Zone', 'Maharashtra', 'Mumbai'), ('West Zone', 'Gujarat', 'Ahmedabad'),
('Central Zone', 'Madhya Pradesh', 'Indore'), ('Central Zone', 'Chhattisgarh', 'Raipur'),
('North East Zone', 'Assam', 'Guwahati'), ('North East Zone', 'Meghalaya', 'Shillong');

-- 2. Populate Products (Mixed Categories: Cigarettes & Staples)
INSERT INTO dim_product (category_name, brand_name, sku_name, uom)
VALUES 
('Cigarettes', 'Classic', 'Classic Milds 20s', 'Packs'),
('Cigarettes', 'Gold Flake', 'Gold Flake Kings', 'Packs'),
('Staples', 'Aashirwaad', 'Aashirwaad Select Atta 5kg', 'Kg'),
('Staples', 'Aashirwaad', 'Aashirwaad Salt 1kg', 'Kg'),
('Oils', 'Sunfeast', 'Sunfeast YiPPee!', 'Packs'),
('Oils', 'Fortune', 'Refined Soyabean Oil 1L', 'Ltr');

-- 3. Populate Sales Hierarchy (RBAC: SalesRep -> SO -> AM -> ZM)
-- Generating 10 hierarchies linked to random zones
INSERT INTO dim_sales_hierarchy (sales_rep_name, sales_officer_name, area_manager_name, zonal_manager_name, zone_id)
SELECT 
    'SalesRep_' || seq, 
    'SalesOfficer_' || (seq % 5 + 1), -- 1 SO manages multiple Reps
    'AreaManager_' || (seq % 3 + 1),  -- 1 AM manages multiple SOs
    'ZonalManager_' || (seq % 2 + 1), -- 1 ZM manages multiple AMs
    (seq % 6 + 1) -- Assign to one of the 6 Zones roughly
FROM generate_series(1, 20) AS seq;

-- 4. Populate Partners (Warehouses, Distributors, Retailers)
-- A. Company Warehouses (Sources for Primary Sales)
INSERT INTO dim_partner (partner_type, partner_name, geo_id)
SELECT 'Warehouse', 'Central Warehouse ' || seq, (seq % 12 + 1)
FROM generate_series(1, 5) AS seq;

-- B. Distributors (Targets for Primary, Sources for Secondary)
-- "25 Distributors" as requested
INSERT INTO dim_partner (partner_type, partner_name, geo_id)
SELECT 'Distributor', 'Distributor Agency ' || seq, (seq % 12 + 1)
FROM generate_series(1, 25) AS seq;

-- C. Retailers (Targets for Secondary)
-- "100 Retailers per distributor" approx -> generating 2500 retailers
INSERT INTO dim_partner (partner_type, partner_name, geo_id)
SELECT 'Retailer', 'Retail Shop ' || seq, (seq % 12 + 1)
FROM generate_series(1, 2500) AS seq;

-- 5. Generate Fact Data: Primary Sales (Warehouse -> Distributor)
INSERT INTO fact_primary_sales (invoice_date, invoice_number, warehouse_id, distributor_id, sku_id, volume_qty, gross_value, tax_amount, net_value)
SELECT 
    CURRENT_DATE - (floor(random() * 30)::int), -- Random date in last 30 days
    'INV-PRI-' || seq,
    (SELECT partner_id FROM dim_partner WHERE partner_type = 'Warehouse' ORDER BY random() LIMIT 1),
    (SELECT partner_id FROM dim_partner WHERE partner_type = 'Distributor' ORDER BY random() LIMIT 1),
    (SELECT sku_id FROM dim_product ORDER BY random() LIMIT 1),
    (random() * 1000)::int, -- Volume
    (random() * 50000)::decimal(15,2), -- Gross Value
    (random() * 5000)::decimal(15,2),  -- Tax
    (random() * 55000)::decimal(15,2)  -- Net Value
FROM generate_series(1, 500) AS seq; -- 500 Primary Invoices

-- 6. Generate Fact Data: Secondary Sales (Distributor -> Retailer)
-- This is the "Main" table for the PoC
INSERT INTO fact_secondary_sales (invoice_date, invoice_number, distributor_id, retailer_id, sku_id, hierarchy_id, route_code, volume_qty, gross_value, tax_amount, net_value)
SELECT 
    CURRENT_DATE - (floor(random() * 30)::int),
    'INV-SEC-' || seq,
    (SELECT partner_id FROM dim_partner WHERE partner_type = 'Distributor' ORDER BY random() LIMIT 1),
    (SELECT partner_id FROM dim_partner WHERE partner_type = 'Retailer' ORDER BY random() LIMIT 1),
    (SELECT sku_id FROM dim_product ORDER BY random() LIMIT 1),
    (SELECT hierarchy_id FROM dim_sales_hierarchy ORDER BY random() LIMIT 1), -- Link to a Sales Rep
    'ROUTE-' || (floor(random() * 50 + 1)::int),
    (random() * 50)::int, -- Smaller volume for retailer sales
    (random() * 5000)::decimal(15,2),
    (random() * 500)::decimal(15,2),
    (random() * 5500)::decimal(15,2)
FROM generate_series(1, 2000) AS seq; -- 2000 Secondary Invoices