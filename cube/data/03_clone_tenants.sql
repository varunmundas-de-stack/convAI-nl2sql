DO $$
DECLARE
  tenant_schema TEXT;
BEGIN
  FOREACH tenant_schema IN ARRAY ARRAY['client_nestle', 'client_itc', 'client_unilever']
  LOOP
    EXECUTE format('DROP TABLE IF EXISTS %I.fact_secondary_sales CASCADE', tenant_schema);
    EXECUTE format('DROP TABLE IF EXISTS %I.fact_primary_sales CASCADE', tenant_schema);

    EXECUTE format(
      'CREATE TABLE %I.fact_secondary_sales AS TABLE public.fact_secondary_sales',
      tenant_schema
    );
    EXECUTE format(
      'CREATE TABLE %I.fact_primary_sales AS TABLE public.fact_primary_sales',
      tenant_schema
    );

    EXECUTE format('CREATE INDEX %I ON %I.fact_secondary_sales(invoice_date)', 'idx_' || tenant_schema || '_sec_invoice_date', tenant_schema);
    EXECUTE format('CREATE INDEX %I ON %I.fact_secondary_sales(zone)', 'idx_' || tenant_schema || '_sec_zone', tenant_schema);
    EXECUTE format('CREATE INDEX %I ON %I.fact_secondary_sales(salesrep_code)', 'idx_' || tenant_schema || '_sec_salesrep', tenant_schema);
    EXECUTE format('CREATE INDEX %I ON %I.fact_secondary_sales(so_name)', 'idx_' || tenant_schema || '_sec_so', tenant_schema);
    EXECUTE format('CREATE INDEX %I ON %I.fact_secondary_sales(asm_name)', 'idx_' || tenant_schema || '_sec_asm', tenant_schema);
    EXECUTE format('CREATE INDEX %I ON %I.fact_secondary_sales(zsm_name)', 'idx_' || tenant_schema || '_sec_zsm', tenant_schema);

    EXECUTE format('CREATE INDEX %I ON %I.fact_primary_sales(invoice_date)', 'idx_' || tenant_schema || '_pri_invoice_date', tenant_schema);
    EXECUTE format('CREATE INDEX %I ON %I.fact_primary_sales(zone)', 'idx_' || tenant_schema || '_pri_zone', tenant_schema);
    EXECUTE format('CREATE INDEX %I ON %I.fact_primary_sales(so_name)', 'idx_' || tenant_schema || '_pri_so', tenant_schema);
    EXECUTE format('CREATE INDEX %I ON %I.fact_primary_sales(asm_name)', 'idx_' || tenant_schema || '_pri_asm', tenant_schema);
    EXECUTE format('CREATE INDEX %I ON %I.fact_primary_sales(zsm_name)', 'idx_' || tenant_schema || '_pri_zsm', tenant_schema);
  END LOOP;
END $$;

INSERT INTO app_meta.insights (
  insight_id, tenant_id, hierarchy_level, title, description, insight_type,
  priority, suggested_action, suggested_query, data_json, expires_at
)
SELECT
  'seed_' || client_id || '_sales_review',
  client_id,
  'all',
  client_name || ' sales review is ready',
  'Review latest primary and secondary sales trends for this tenant.',
  'recommendation',
  'medium',
  'Open the suggested query and inspect sales by zone.',
  'Show net sales by zone for last 30 days',
  '{}'::jsonb,
  CURRENT_TIMESTAMP + INTERVAL '7 days'
FROM app_meta.clients
ON CONFLICT (insight_id) DO UPDATE SET
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  is_active = TRUE,
  expires_at = EXCLUDED.expires_at;
