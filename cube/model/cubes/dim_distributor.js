const tenantSchemaDistributor = () => {
  const ctx = typeof COMPILE_CONTEXT !== 'undefined' ? COMPILE_CONTEXT : {};
  return ctx.securityContext?.schemaName || 'public';
};

cube('dim_distributor', {
  sql: `SELECT * FROM ${tenantSchemaDistributor()}.dim_distributor`,

  dimensions: {
    dist_id:          { sql: 'dist_id',          type: 'number', primaryKey: true },
    distributor_code: { sql: 'distributor_code', type: 'string' },
    distributor_name: { sql: 'distributor_name', type: 'string' },
    channel_type:     { sql: 'channel_type',     type: 'string' },
    beat_plan:        { sql: 'beat_plan',         type: 'string' },
    geo_id:           { sql: 'geo_id',            type: 'number' },
  },
});
