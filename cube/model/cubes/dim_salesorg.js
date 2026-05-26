const tenantSchemaSalesOrg = () => {
  const ctx = typeof COMPILE_CONTEXT !== 'undefined' ? COMPILE_CONTEXT : {};
  return ctx.securityContext?.schemaName || 'public';
};

cube('dim_salesorg', {
  sql: `SELECT * FROM ${tenantSchemaSalesOrg()}.dim_salesorg`,

  dimensions: {
    org_id:   { sql: `org_id`,   type: `number`, primaryKey: true },
    so_code:  { sql: `so_code`,  type: `string` },
    asm_name: { sql: `asm_name`, type: `string` },
    zsm_name: { sql: `zsm_name`, type: `string` },
    zone:     { sql: `zone`,     type: `string` },
  },
});
