const tenantSchemaProduct = () => {
  const ctx = typeof COMPILE_CONTEXT !== 'undefined' ? COMPILE_CONTEXT : {};
  return ctx.securityContext?.schemaName || 'public';
};

cube('dim_product', {
  sql: `SELECT * FROM ${tenantSchemaProduct()}.dim_product`,

  dimensions: {
    product_id:   { sql: `product_id`,   type: `number`, primaryKey: true },
    sku_code:     { sql: `sku_code`,     type: `string` },
    sku_name:     { sql: `sku_name`,     type: `string` },
    brand:        { sql: `brand`,        type: `string` },
    category:     { sql: `category`,     type: `string` },
    sub_category: { sql: `sub_category`, type: `string` },
    pack_size:    { sql: `pack_size`,    type: `string` },
  },
});
