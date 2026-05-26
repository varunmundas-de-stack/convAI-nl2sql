const tenantSchemaSecondary = () => {
  const ctx = typeof COMPILE_CONTEXT !== 'undefined' ? COMPILE_CONTEXT : {};
  return ctx.securityContext?.schemaName || 'public';
};

cube('fact_secondary_sales', {
  sql: `SELECT * FROM ${tenantSchemaSecondary()}.fact_secondary_sales`,

  joins: {
    dim_geography:   { sql: `${CUBE}.geo_id = ${dim_geography}.geo_id`,           relationship: 'many_to_one' },
    dim_product:     { sql: `${CUBE}.product_id = ${dim_product}.product_id`,     relationship: 'many_to_one' },
    dim_salesorg:    { sql: `${CUBE}.org_id = ${dim_salesorg}.org_id`,            relationship: 'many_to_one' },
    dim_distributor: { sql: `${CUBE}.dist_id = ${dim_distributor}.dist_id`,       relationship: 'many_to_one' },
    dim_customer:    { sql: `${CUBE}.customer_id = ${dim_customer}.customer_id`,  relationship: 'many_to_one' },
    dim_period:      { sql: `${CUBE}.period_id = ${dim_period}.period_id`,        relationship: 'many_to_one' },
  },

  dimensions: {
    id:               { sql: `invoice_id`,       type: `string`, primaryKey: true },
    asm_name:         { sql: `asm_name`,         type: `string` },
    brand:            { sql: `brand`,            type: `string` },
    category:         { sql: `category`,         type: `string` },
    city:             { sql: `city`,             type: `string` },
    currency:         { sql: `currency`,         type: `string` },
    distributor_code: { sql: `distributor_code`, type: `string` },
    distributor_name: { sql: `distributor_name`, type: `string` },
    invoice_id:       { sql: `invoice_id`,       type: `string` },
    invoice_line_id:  { sql: `invoice_line_id`,  type: `string` },
    pack_size:        { sql: `pack_size`,        type: `string` },
    product_desc:     { sql: `product_desc`,     type: `string` },
    retailer_code:    { sql: `retailer_code`,    type: `string` },
    retailer_name:    { sql: `retailer_name`,    type: `string` },
    retailer_type:    { sql: `retailer_type`,    type: `string` },
    route_code:       { sql: `route_code`,       type: `string` },
    route_name:       { sql: `route_name`,       type: `string` },
    salesrep_code:    { sql: `salesrep_code`,    type: `string` },
    salesrep_name:    { sql: `salesrep_name`,    type: `string` },
    sku_code:         { sql: `sku_code`,         type: `string` },
    so_name:          { sql: `so_name`,          type: `string` },
    state:            { sql: `state`,            type: `string` },
    sub_category:     { sql: `sub_category`,     type: `string` },
    uom:              { sql: `uom`,              type: `string` },
    zone:             { sql: `zone`,             type: `string` },
    zsm_name:         { sql: `zsm_name`,         type: `string` },
    created_at:       { sql: `created_at`,       type: `time` },
    invoice_date:     { sql: `invoice_date`,     type: `time` },
  },

  measures: {
    count:       { type: `count` },
    billed_qty:  { sql: `billed_qty`,  type: `sum` },
    gross_value: { sql: `gross_value`, type: `sum` },
    net_value:   { sql: `net_value`,   type: `sum` },
    tax_value:   { sql: `tax_value`,   type: `sum` },
  },
});
