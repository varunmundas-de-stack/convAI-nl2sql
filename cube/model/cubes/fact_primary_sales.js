const tenantSchemaPrimary = () => {
  const ctx = typeof COMPILE_CONTEXT !== 'undefined' ? COMPILE_CONTEXT : {};
  return ctx.securityContext?.schemaName || 'public';
};

cube('fact_primary_sales', {
  sql: `SELECT * FROM ${tenantSchemaPrimary()}.fact_primary_sales`,

  dimensions: {
    asm_name: { sql: 'asm_name', type: 'string' },
    brand: { sql: 'brand', type: 'string' },
    category: { sql: 'category', type: 'string' },
    city: { sql: 'city', type: 'string' },
    companywh_code: { sql: 'companywh_code', type: 'string' },
    companywh_name: { sql: 'companywh_name', type: 'string' },
    currency: { sql: 'currency', type: 'string' },
    distributor_code: { sql: 'distributor_code', type: 'string' },
    distributor_name: { sql: 'distributor_name', type: 'string' },
    invoice_id: { sql: 'invoice_id', type: 'string' },
    invoice_line_id: { sql: 'invoice_line_id', type: 'string' },
    pack_size: { sql: 'pack_size', type: 'string' },
    product_desc: { sql: 'product_desc', type: 'string' },
    sku_code: { sql: 'sku_code', type: 'string' },
    so_name: { sql: 'so_name', type: 'string' },
    state: { sql: 'state', type: 'string' },
    sub_category: { sql: 'sub_category', type: 'string' },
    uom: { sql: 'uom', type: 'string' },
    zone: { sql: 'zone', type: 'string' },
    zsm_name: { sql: 'zsm_name', type: 'string' },
    created_at: { sql: 'created_at', type: 'time' },
    invoice_date: { sql: 'invoice_date', type: 'time' },
  },

  measures: {
    count: { type: 'count' },
    billed_qty: { sql: 'billed_qty', type: 'sum' },
    gross_value: { sql: 'gross_value', type: 'sum' },
    net_value: { sql: 'net_value', type: 'sum' },
    tax_value: { sql: 'tax_value', type: 'sum' },
  },
});
