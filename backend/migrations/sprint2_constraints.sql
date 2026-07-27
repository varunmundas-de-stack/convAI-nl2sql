-- Sprint 2 DB Constraints Migration
-- Applied manually during Sprint 2 (May 2026).
-- Must be re-run if the database is recreated from scratch.
-- Run as: psql -U postgres -d sales_analytics -f sprint2_constraints.sql

-- ── Dimension table unique business-key constraints ────────────────────────────

ALTER TABLE public.dim_product
    ADD CONSTRAINT IF NOT EXISTS dim_product_sku_code_key UNIQUE (sku_code);

ALTER TABLE public.dim_geography
    ADD CONSTRAINT IF NOT EXISTS dim_geography_zone_state_city_key UNIQUE (zone, state, city);

ALTER TABLE public.dim_salesorg
    ADD CONSTRAINT IF NOT EXISTS dim_salesorg_so_code_key UNIQUE (so_code);

ALTER TABLE public.dim_distributor
    ADD CONSTRAINT IF NOT EXISTS dim_distributor_code_key UNIQUE (distributor_code);

-- ── Fact table natural-key unique constraints (required for ETL ON CONFLICT) ──

ALTER TABLE client_nestle.fact_primary_sales
    ADD CONSTRAINT IF NOT EXISTS fact_primary_sales_uq UNIQUE (invoice_id, invoice_line_id, sku_code);

ALTER TABLE client_nestle.fact_secondary_sales
    ADD CONSTRAINT IF NOT EXISTS fact_secondary_sales_uq UNIQUE (invoice_id, invoice_line_id, sku_code);

ALTER TABLE client_itc.fact_primary_sales
    ADD CONSTRAINT IF NOT EXISTS fact_primary_sales_uq UNIQUE (invoice_id, invoice_line_id, sku_code);

ALTER TABLE client_itc.fact_secondary_sales
    ADD CONSTRAINT IF NOT EXISTS fact_secondary_sales_uq UNIQUE (invoice_id, invoice_line_id, sku_code);

ALTER TABLE client_unilever.fact_primary_sales
    ADD CONSTRAINT IF NOT EXISTS fact_primary_sales_uq UNIQUE (invoice_id, invoice_line_id, sku_code);

ALTER TABLE client_unilever.fact_secondary_sales
    ADD CONSTRAINT IF NOT EXISTS fact_secondary_sales_uq UNIQUE (invoice_id, invoice_line_id, sku_code);

-- ── Data fix ─────────────────────────────────────────────────────────────────

-- Fix is_ytd flag so all past dates are marked as within YTD
UPDATE public.dim_period SET is_ytd = true WHERE date <= CURRENT_DATE;
