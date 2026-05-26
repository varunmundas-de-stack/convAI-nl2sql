const tenantSchemaCustomer = () => {
  const ctx = typeof COMPILE_CONTEXT !== 'undefined' ? COMPILE_CONTEXT : {};
  return ctx.securityContext?.schemaName || 'public';
};

cube('dim_customer', {
  sql: `SELECT * FROM ${tenantSchemaCustomer()}.dim_customer`,

  dimensions: {
    customer_id:   { sql: 'customer_id',   type: 'number', primaryKey: true },
    customer_code: { sql: 'customer_code', type: 'string' },
    customer_name: { sql: 'customer_name', type: 'string' },
    channel_type:  { sql: 'channel_type',  type: 'string' },
    tier:          { sql: 'tier',          type: 'string' },
    geo_id:        { sql: 'geo_id',        type: 'number' },
  },
});
