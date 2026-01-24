-- =====================================================
-- DIMENSION TABLES
-- =====================================================

-- Territory Dimension
CREATE TABLE territories (
    territory_id SERIAL PRIMARY KEY,
    territory_code VARCHAR(20) UNIQUE NOT NULL,
    territory_name VARCHAR(100) NOT NULL,
    state VARCHAR(50),
    region VARCHAR(50), -- North, South, East, West
    zone VARCHAR(50), -- Metro, Urban, Rural
    is_active BOOLEAN DEFAULT TRUE
);

-- SKU (Stock Keeping Unit) Dimension
CREATE TABLE skus (
    sku_id SERIAL PRIMARY KEY,
    sku_code VARCHAR(50) UNIQUE NOT NULL,
    sku_name VARCHAR(200) NOT NULL,
    brand VARCHAR(100),
    category VARCHAR(100), -- Beverages, Snacks, Dairy, etc.
    sub_category VARCHAR(100),
    pack_size VARCHAR(50), -- 250ml, 500ml, 1L, etc.
    mrp DECIMAL(10,2),
    is_active BOOLEAN DEFAULT TRUE
);

-- Distributor Dimension
CREATE TABLE distributors (
    distributor_id SERIAL PRIMARY KEY,
    distributor_code VARCHAR(50) UNIQUE NOT NULL,
    distributor_name VARCHAR(200) NOT NULL,
    territory_id INTEGER REFERENCES territories(territory_id),
    distributor_type VARCHAR(50), -- Super Stockist, C&F Agent, Regular
    credit_limit DECIMAL(12,2),
    onboarding_date DATE,
    is_active BOOLEAN DEFAULT TRUE
);

-- Outlet Dimension (Retailers)
CREATE TABLE outlets (
    outlet_id SERIAL PRIMARY KEY,
    outlet_code VARCHAR(50) UNIQUE NOT NULL,
    outlet_name VARCHAR(200) NOT NULL,
    outlet_type VARCHAR(50), -- Kirana, Modern Trade, Institution, Pharmacy
    territory_id INTEGER REFERENCES territories(territory_id),
    distributor_id INTEGER REFERENCES distributors(distributor_id),
    beat_code VARCHAR(20), -- Sales beat/route
    onboarding_date DATE,
    is_active BOOLEAN DEFAULT TRUE
);

-- Date Dimension (for time intelligence)
CREATE TABLE date_dim (
    date_id INTEGER PRIMARY KEY,
    full_date DATE UNIQUE NOT NULL,
    day_of_week INTEGER,
    day_name VARCHAR(10),
    day_of_month INTEGER,
    day_of_year INTEGER,
    week_of_year INTEGER,
    month_number INTEGER,
    month_name VARCHAR(10),
    quarter INTEGER,
    year INTEGER,
    is_weekend BOOLEAN,
    fiscal_year INTEGER,
    fiscal_quarter INTEGER,
    fiscal_month INTEGER
);

-- =====================================================
-- FACT TABLE
-- =====================================================

-- Sales Fact Table
CREATE TABLE sales_fact (
    sales_id SERIAL PRIMARY KEY,
    invoice_number VARCHAR(50) UNIQUE NOT NULL,
    invoice_date DATE NOT NULL,
    date_id INTEGER REFERENCES date_dim(date_id),
    
    -- Sales Type
    sales_type VARCHAR(20) NOT NULL, -- PRIMARY, SECONDARY, TERTIARY
    
    -- Dimensions
    sku_id INTEGER REFERENCES skus(sku_id),
    territory_id INTEGER REFERENCES territories(territory_id),
    distributor_id INTEGER REFERENCES distributors(distributor_id),
    outlet_id INTEGER REFERENCES outlets(outlet_id), -- NULL for primary sales
    
    -- Measures
    quantity INTEGER NOT NULL,
    base_price DECIMAL(10,2) NOT NULL, -- Price per unit before discounts
    gross_amount DECIMAL(12,2) NOT NULL, -- quantity * base_price
    discount_amount DECIMAL(12,2) DEFAULT 0,
    scheme_discount DECIMAL(12,2) DEFAULT 0, -- Trade schemes
    tax_amount DECIMAL(12,2) DEFAULT 0,
    net_amount DECIMAL(12,2) NOT NULL, -- Final amount after discounts + tax
    
    -- Additional context
    sales_rep_code VARCHAR(50),
    is_credit BOOLEAN DEFAULT FALSE,
    
    CONSTRAINT chk_sales_type CHECK (sales_type IN ('PRIMARY', 'SECONDARY', 'TERTIARY'))
);

-- =====================================================
-- INDEXES FOR PERFORMANCE
-- =====================================================

CREATE INDEX idx_sales_fact_date ON sales_fact(invoice_date);
CREATE INDEX idx_sales_fact_date_id ON sales_fact(date_id);
CREATE INDEX idx_sales_fact_sales_type ON sales_fact(sales_type);
CREATE INDEX idx_sales_fact_sku ON sales_fact(sku_id);
CREATE INDEX idx_sales_fact_territory ON sales_fact(territory_id);
CREATE INDEX idx_sales_fact_distributor ON sales_fact(distributor_id);
CREATE INDEX idx_sales_fact_outlet ON sales_fact(outlet_id);

-- =====================================================
-- SAMPLE DATA INSERTION
-- =====================================================

-- Insert Territories
INSERT INTO territories (territory_code, territory_name, state, region, zone) VALUES
    ('TN-CHE-01', 'Chennai Central', 'Tamil Nadu', 'South', 'Metro'),
    ('TN-CHE-02', 'Chennai North', 'Tamil Nadu', 'South', 'Metro'),
    ('TN-MDU-01', 'Madurai', 'Tamil Nadu', 'South', 'Urban'),
    ('KA-BLR-01', 'Bangalore East', 'Karnataka', 'South', 'Metro'),
    ('KA-BLR-02', 'Bangalore West', 'Karnataka', 'South', 'Metro'),
    ('MH-MUM-01', 'Mumbai Central', 'Maharashtra', 'West', 'Metro'),
    ('MH-PUN-01', 'Pune', 'Maharashtra', 'West', 'Urban'),
    ('DL-NCR-01', 'Delhi NCR', 'Delhi', 'North', 'Metro');

-- Insert SKUs
INSERT INTO skus (sku_code, sku_name, brand, category, sub_category, pack_size, mrp) VALUES
    ('BEV-COL-250', 'Cola 250ml', 'FreshCo Cola', 'Beverages', 'Carbonated Drinks', '250ml', 20.00),
    ('BEV-COL-500', 'Cola 500ml', 'FreshCo Cola', 'Beverages', 'Carbonated Drinks', '500ml', 40.00),
    ('BEV-COL-1L', 'Cola 1L', 'FreshCo Cola', 'Beverages', 'Carbonated Drinks', '1L', 70.00),
    ('BEV-JUI-200', 'Mango Juice 200ml', 'NatureFresh', 'Beverages', 'Juice', '200ml', 25.00),
    ('BEV-JUI-1L', 'Mango Juice 1L', 'NatureFresh', 'Beverages', 'Juice', '1L', 100.00),
    ('SNK-CHP-50', 'Potato Chips 50g', 'CrunchTime', 'Snacks', 'Chips', '50g', 20.00),
    ('SNK-CHP-100', 'Potato Chips 100g', 'CrunchTime', 'Snacks', 'Chips', '100g', 35.00),
    ('SNK-BIS-100', 'Butter Biscuits 100g', 'GoldenBake', 'Snacks', 'Biscuits', '100g', 30.00),
    ('DAI-MIL-500', 'Fresh Milk 500ml', 'PureDairy', 'Dairy', 'Milk', '500ml', 28.00),
    ('DAI-MIL-1L', 'Fresh Milk 1L', 'PureDairy', 'Dairy', 'Milk', '1L', 52.00);

-- Insert Distributors
INSERT INTO distributors (distributor_code, distributor_name, territory_id, distributor_type, credit_limit, onboarding_date) VALUES
    ('DIST-TN-001', 'Chennai Beverages Dist Pvt Ltd', 1, 'Super Stockist', 5000000.00, '2023-01-15'),
    ('DIST-TN-002', 'Madurai FMCG Distributors', 3, 'Regular', 2000000.00, '2023-03-20'),
    ('DIST-KA-001', 'Bangalore Metro Distributors', 4, 'C&F Agent', 8000000.00, '2023-02-10'),
    ('DIST-MH-001', 'Mumbai Central Distribution', 6, 'Super Stockist', 10000000.00, '2023-01-05'),
    ('DIST-DL-001', 'NCR Food Distributors', 8, 'Regular', 3000000.00, '2023-04-01');

-- Insert Outlets
INSERT INTO outlets (outlet_code, outlet_name, outlet_type, territory_id, distributor_id, beat_code, onboarding_date) VALUES
    -- Chennai outlets
    ('OUT-TN-001', 'Subham Stores', 'Kirana', 1, 1, 'CHE-B1', '2023-02-01'),
    ('OUT-TN-002', 'Metro Supermarket Anna Nagar', 'Modern Trade', 1, 1, 'CHE-B2', '2023-02-15'),
    ('OUT-TN-003', 'Tamil Nadu Medical Store', 'Pharmacy', 1, 1, 'CHE-B1', '2023-03-01'),
    ('OUT-TN-004', 'Amma Mini Mart', 'Kirana', 2, 1, 'CHE-B3', '2023-02-20'),
    ('OUT-TN-005', 'Madurai Provision Store', 'Kirana', 3, 2, 'MDU-B1', '2023-04-01'),
    
    -- Bangalore outlets
    ('OUT-KA-001', 'Indiranagar Supermart', 'Modern Trade', 4, 3, 'BLR-B1', '2023-03-10'),
    ('OUT-KA-002', 'HSR Layout Kirana', 'Kirana', 4, 3, 'BLR-B2', '2023-03-15'),
    ('OUT-KA-003', 'Whitefield Food Bazaar', 'Kirana', 5, 3, 'BLR-B3', '2023-03-20'),
    
    -- Mumbai outlets
    ('OUT-MH-001', 'Andheri Retail Hub', 'Modern Trade', 6, 4, 'MUM-B1', '2023-02-05'),
    ('OUT-MH-002', 'Bandra Corner Store', 'Kirana', 6, 4, 'MUM-B2', '2023-02-10'),
    
    -- Delhi outlets
    ('OUT-DL-001', 'Connaught Place Mart', 'Modern Trade', 8, 5, 'NCR-B1', '2023-05-01'),
    ('OUT-DL-002', 'Rohini Provision Store', 'Kirana', 8, 5, 'NCR-B2', '2023-05-05');

-- Populate Date Dimension (for 2024)
INSERT INTO date_dim (date_id, full_date, day_of_week, day_name, day_of_month, day_of_year, 
                       week_of_year, month_number, month_name, quarter, year, is_weekend, 
                       fiscal_year, fiscal_quarter, fiscal_month)
SELECT 
    TO_CHAR(date_series, 'YYYYMMDD')::INTEGER as date_id,
    date_series::DATE as full_date,
    EXTRACT(DOW FROM date_series)::INTEGER as day_of_week,
    TO_CHAR(date_series, 'Day') as day_name,
    EXTRACT(DAY FROM date_series)::INTEGER as day_of_month,
    EXTRACT(DOY FROM date_series)::INTEGER as day_of_year,
    EXTRACT(WEEK FROM date_series)::INTEGER as week_of_year,
    EXTRACT(MONTH FROM date_series)::INTEGER as month_number,
    TO_CHAR(date_series, 'Month') as month_name,
    EXTRACT(QUARTER FROM date_series)::INTEGER as quarter,
    EXTRACT(YEAR FROM date_series)::INTEGER as year,
    CASE WHEN EXTRACT(DOW FROM date_series) IN (0, 6) THEN TRUE ELSE FALSE END as is_weekend,
    CASE 
        WHEN EXTRACT(MONTH FROM date_series) >= 4 THEN EXTRACT(YEAR FROM date_series)
        ELSE EXTRACT(YEAR FROM date_series) - 1
    END as fiscal_year,
    CASE 
        WHEN EXTRACT(MONTH FROM date_series) BETWEEN 4 AND 6 THEN 1
        WHEN EXTRACT(MONTH FROM date_series) BETWEEN 7 AND 9 THEN 2
        WHEN EXTRACT(MONTH FROM date_series) BETWEEN 10 AND 12 THEN 3
        ELSE 4
    END as fiscal_quarter,
    CASE 
        WHEN EXTRACT(MONTH FROM date_series) >= 4 THEN EXTRACT(MONTH FROM date_series) - 3
        ELSE EXTRACT(MONTH FROM date_series) + 9
    END as fiscal_month
FROM generate_series('2024-01-01'::DATE, '2024-12-31'::DATE, '1 day'::interval) date_series;

-- Insert Sales Fact Data (Mix of Primary, Secondary, Tertiary)

-- PRIMARY SALES (Company → Distributor) - Jan 2024
INSERT INTO sales_fact (invoice_number, invoice_date, date_id, sales_type, sku_id, territory_id, 
                        distributor_id, outlet_id, quantity, base_price, gross_amount, 
                        discount_amount, scheme_discount, tax_amount, net_amount, sales_rep_code, is_credit)
VALUES
    ('PRI-2024-0001', '2024-01-05', 20240105, 'PRIMARY', 1, 1, 1, NULL, 1000, 18.00, 18000.00, 500.00, 200.00, 3132.00, 20432.00, 'SR-001', TRUE),
    ('PRI-2024-0002', '2024-01-05', 20240105, 'PRIMARY', 2, 1, 1, NULL, 800, 36.00, 28800.00, 800.00, 400.00, 4968.00, 32568.00, 'SR-001', TRUE),
    ('PRI-2024-0003', '2024-01-08', 20240108, 'PRIMARY', 3, 4, 3, NULL, 500, 63.00, 31500.00, 1000.00, 500.00, 5400.00, 35400.00, 'SR-003', TRUE),
    ('PRI-2024-0004', '2024-01-10', 20240110, 'PRIMARY', 6, 6, 4, NULL, 2000, 16.00, 32000.00, 1200.00, 800.00, 5400.00, 35400.00, 'SR-004', TRUE);

-- SECONDARY SALES (Distributor → Outlet) - Jan 2024
INSERT INTO sales_fact (invoice_number, invoice_date, date_id, sales_type, sku_id, territory_id, 
                        distributor_id, outlet_id, quantity, base_price, gross_amount, 
                        discount_amount, scheme_discount, tax_amount, net_amount, sales_rep_code, is_credit)
VALUES
    ('SEC-2024-0001', '2024-01-12', 20240112, 'SECONDARY', 1, 1, 1, 1, 100, 19.00, 1900.00, 50.00, 0.00, 333.00, 2183.00, 'SR-101', TRUE),
    ('SEC-2024-0002', '2024-01-12', 20240112, 'SECONDARY', 2, 1, 1, 1, 80, 38.00, 3040.00, 100.00, 0.00, 529.20, 3469.20, 'SR-101', TRUE),
    ('SEC-2024-0003', '2024-01-15', 20240115, 'SECONDARY', 1, 1, 1, 2, 200, 19.00, 3800.00, 150.00, 100.00, 656.10, 4306.10, 'SR-102', FALSE),
    ('SEC-2024-0004', '2024-01-15', 20240115, 'SECONDARY', 3, 1, 1, 2, 150, 66.00, 9900.00, 300.00, 200.00, 1728.00, 11328.00, 'SR-102', FALSE),
    ('SEC-2024-0005', '2024-01-18', 20240118, 'SECONDARY', 6, 4, 3, 6, 300, 17.50, 5250.00, 200.00, 150.00, 901.80, 6001.80, 'SR-103', TRUE);

-- TERTIARY SALES (Outlet → End Consumer) - Jan 2024
INSERT INTO sales_fact (invoice_number, invoice_date, date_id, sales_type, sku_id, territory_id, 
                        distributor_id, outlet_id, quantity, base_price, gross_amount, 
                        discount_amount, scheme_discount, tax_amount, net_amount, sales_rep_code, is_credit)
VALUES
    ('TER-2024-0001', '2024-01-13', 20240113, 'TERTIARY', 1, 1, 1, 1, 24, 20.00, 480.00, 0.00, 0.00, 0.00, 480.00, NULL, FALSE),
    ('TER-2024-0002', '2024-01-13', 20240113, 'TERTIARY', 2, 1, 1, 1, 12, 40.00, 480.00, 0.00, 0.00, 0.00, 480.00, NULL, FALSE),
    ('TER-2024-0003', '2024-01-16', 20240116, 'TERTIARY', 1, 1, 1, 2, 36, 20.00, 720.00, 20.00, 0.00, 0.00, 700.00, NULL, FALSE),
    ('TER-2024-0004', '2024-01-16', 20240116, 'TERTIARY', 3, 1, 1, 2, 18, 70.00, 1260.00, 0.00, 0.00, 0.00, 1260.00, NULL, FALSE);

-- More sales data for February-March 2024 (for trend analysis)
-- February PRIMARY
INSERT INTO sales_fact (invoice_number, invoice_date, date_id, sales_type, sku_id, territory_id, 
                        distributor_id, outlet_id, quantity, base_price, gross_amount, 
                        discount_amount, scheme_discount, tax_amount, net_amount, sales_rep_code, is_credit)
VALUES
    ('PRI-2024-0005', '2024-02-02', 20240202, 'PRIMARY', 1, 1, 1, NULL, 1200, 18.00, 21600.00, 600.00, 300.00, 3726.00, 24426.00, 'SR-001', TRUE),
    ('PRI-2024-0006', '2024-02-05', 20240205, 'PRIMARY', 4, 3, 2, NULL, 600, 22.50, 13500.00, 400.00, 200.00, 2340.00, 15240.00, 'SR-002', TRUE),
    ('PRI-2024-0007', '2024-02-10', 20240210, 'PRIMARY', 7, 4, 3, NULL, 1500, 31.50, 47250.00, 1500.00, 800.00, 8190.90, 53940.90, 'SR-003', TRUE);

-- February SECONDARY
INSERT INTO sales_fact (invoice_number, invoice_date, date_id, sales_type, sku_id, territory_id, 
                        distributor_id, outlet_id, quantity, base_price, gross_amount, 
                        discount_amount, scheme_discount, tax_amount, net_amount, sales_rep_code, is_credit)
VALUES
    ('SEC-2024-0006', '2024-02-08', 20240208, 'SECONDARY', 1, 1, 1, 3, 120, 19.00, 2280.00, 80.00, 0.00, 396.00, 2596.00, 'SR-101', FALSE),
    ('SEC-2024-0007', '2024-02-12', 20240212, 'SECONDARY', 4, 3, 2, 5, 150, 24.00, 3600.00, 120.00, 50.00, 625.40, 4105.40, 'SR-104', TRUE),
    ('SEC-2024-0008', '2024-02-15', 20240215, 'SECONDARY', 7, 4, 3, 7, 200, 33.00, 6600.00, 250.00, 150.00, 1116.00, 7316.00, 'SR-103', TRUE);

-- March PRIMARY
INSERT INTO sales_fact (invoice_number, invoice_date, date_id, sales_type, sku_id, territory_id, 
                        distributor_id, outlet_id, quantity, base_price, gross_amount, 
                        discount_amount, scheme_discount, tax_amount, net_amount, sales_rep_code, is_credit)
VALUES
    ('PRI-2024-0008', '2024-03-03', 20240303, 'PRIMARY', 1, 1, 1, NULL, 1500, 18.00, 27000.00, 800.00, 500.00, 4686.00, 30386.00, 'SR-001', TRUE),
    ('PRI-2024-0009', '2024-03-05', 20240305, 'PRIMARY', 8, 6, 4, NULL, 1000, 27.00, 27000.00, 900.00, 400.00, 4626.00, 30326.00, 'SR-004', TRUE),
    ('PRI-2024-0010', '2024-03-08', 20240308, 'PRIMARY', 9, 8, 5, NULL, 800, 25.20, 20160.00, 600.00, 300.00, 3526.80, 23086.80, 'SR-005', TRUE);

-- March SECONDARY
INSERT INTO sales_fact (invoice_number, invoice_date, date_id, sales_type, sku_id, territory_id, 
                        distributor_id, outlet_id, quantity, base_price, gross_amount, 
                        discount_amount, scheme_discount, tax_amount, net_amount, sales_rep_code, is_credit)
VALUES
    ('SEC-2024-0009', '2024-03-10', 20240310, 'SECONDARY', 1, 1, 1, 4, 180, 19.00, 3420.00, 150.00, 80.00, 571.80, 3761.80, 'SR-105', TRUE),
    ('SEC-2024-0010', '2024-03-12', 20240312, 'SECONDARY', 8, 6, 4, 9, 250, 28.50, 7125.00, 300.00, 150.00, 1201.50, 7876.50, 'SR-106', FALSE),
    ('SEC-2024-0011', '2024-03-15', 20240315, 'SECONDARY', 9, 8, 5, 11, 200, 26.50, 5300.00, 200.00, 100.00, 918.00, 6018.00, 'SR-107', TRUE);
