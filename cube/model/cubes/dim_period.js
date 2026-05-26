const tenantSchemaPeriod = () => {
  const ctx = typeof COMPILE_CONTEXT !== 'undefined' ? COMPILE_CONTEXT : {};
  return ctx.securityContext?.schemaName || 'public';
};

cube('dim_period', {
  sql: `SELECT * FROM ${tenantSchemaPeriod()}.dim_period`,

  dimensions: {
    period_id:      { sql: `period_id`,      type: `number`, primaryKey: true },
    date:           { sql: `date`,           type: `time` },
    fiscal_week:    { sql: `fiscal_week`,    type: `number` },
    fiscal_month:   { sql: `fiscal_month`,   type: `number` },
    fiscal_quarter: { sql: `fiscal_quarter`, type: `number` },
    fiscal_year:    { sql: `fiscal_year`,    type: `number` },
    is_ytd:         { sql: `is_ytd`,         type: `boolean` },
  },
});
