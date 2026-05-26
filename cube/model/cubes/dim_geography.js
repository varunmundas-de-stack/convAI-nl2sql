const tenantSchemaGeo = () => {
  const ctx = typeof COMPILE_CONTEXT !== 'undefined' ? COMPILE_CONTEXT : {};
  return ctx.securityContext?.schemaName || 'public';
};

cube('dim_geography', {
  sql: `SELECT * FROM ${tenantSchemaGeo()}.dim_geography`,

  dimensions: {
    geo_id:    { sql: `geo_id`,    type: `number`, primaryKey: true },
    zone:      { sql: `zone`,      type: `string` },
    state:     { sql: `state`,     type: `string` },
    city:      { sql: `city`,      type: `string` },
    territory: { sql: `territory`, type: `string` },
    geo_level: { sql: `geo_level`, type: `string` },
  },
});
