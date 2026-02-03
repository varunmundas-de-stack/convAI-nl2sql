# app/services/intent_normalizer.py
import copy
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# METRIC NORMALIZATION
# =============================================================================

METRIC_MAP = {
    # --------------------
    # COUNT METRICS
    # --------------------
    "transaction_count": {
        "PRIMARY": "fact_primary_sales.count",
        "SECONDARY": "fact_secondary_sales.count",
    },
    "count": {
        "PRIMARY": "fact_primary_sales.count",
        "SECONDARY": "fact_secondary_sales.count",
    },

    # --------------------
    # VOLUME METRICS
    # --------------------
    "billed_qty": {
        "PRIMARY": "fact_primary_sales.billed_qty",
        "SECONDARY": "fact_secondary_sales.billed_qty",
    },
    "volume_qty": {  # Legacy alias
        "PRIMARY": "fact_primary_sales.billed_qty",
        "SECONDARY": "fact_secondary_sales.billed_qty",
    },
    "quantity": {  # Natural language alias
        "PRIMARY": "fact_primary_sales.billed_qty",
        "SECONDARY": "fact_secondary_sales.billed_qty",
    },
    "billed_volume": {
        "PRIMARY": "fact_primary_sales.billed_volume",
        "SECONDARY": "fact_secondary_sales.billed_volume",
    },
    "billed_weight": {
        "PRIMARY": "fact_primary_sales.billed_weight",
        "SECONDARY": "fact_secondary_sales.billed_weight",
    },

    # --------------------
    # VALUE METRICS
    # --------------------
    "net_value": {
        "PRIMARY": "fact_primary_sales.net_value",
        "SECONDARY": "fact_secondary_sales.net_value",
    },
    "net_sales_value": {  # Legacy alias
        "PRIMARY": "fact_primary_sales.net_value",
        "SECONDARY": "fact_secondary_sales.net_value",
    },
    "gross_value": {
        "PRIMARY": "fact_primary_sales.gross_value",
        "SECONDARY": "fact_secondary_sales.gross_value",
    },
    "gross_sales_value": {  # Legacy alias
        "PRIMARY": "fact_primary_sales.gross_value",
        "SECONDARY": "fact_secondary_sales.gross_value",
    },
    "tax_value": {
        "PRIMARY": "fact_primary_sales.tax_value",
        "SECONDARY": "fact_secondary_sales.tax_value",
    },
    "tax_amount": {  # Legacy alias
        "PRIMARY": "fact_primary_sales.tax_value",
        "SECONDARY": "fact_secondary_sales.tax_value",
    },
}



# =============================================================================
# DIMENSION NORMALIZATION
# =============================================================================

DIMENSION_MAP = {
    # --------------------
    # GEOGRAPHY (embedded in fact tables)
    # --------------------
    "city": {
        "PRIMARY": "fact_primary_sales.city",
        "SECONDARY": "fact_secondary_sales.city",
    },
    "state": {
        "PRIMARY": "fact_primary_sales.state",
        "SECONDARY": "fact_secondary_sales.state",
    },
    "zone": {
        "PRIMARY": "fact_primary_sales.zone",
        "SECONDARY": "fact_secondary_sales.zone",
    },
    "territory": {  # Natural language alias for zone
        "PRIMARY": "fact_primary_sales.zone",
        "SECONDARY": "fact_secondary_sales.zone",
    },
    "region": {  # Natural language alias for zone
        "PRIMARY": "fact_primary_sales.zone",
        "SECONDARY": "fact_secondary_sales.zone",
    },

    # --------------------
    # PARTNER / DISTRIBUTOR
    # --------------------
    "distributor_code": {
        "PRIMARY": "fact_primary_sales.distributor_code",
        "SECONDARY": "fact_secondary_sales.distributor_code",
    },
    "distributor_name": {
        "PRIMARY": "fact_primary_sales.distributor_name",
        "SECONDARY": "fact_secondary_sales.distributor_name",
    },
    "distributor": {  # Natural language alias
        "PRIMARY": "fact_primary_sales.distributor_name",
        "SECONDARY": "fact_secondary_sales.distributor_name",
    },
    "retailer_code": "fact_secondary_sales.retailer_code",
    "retailer_name": "fact_secondary_sales.retailer_name",
    "retailer": "fact_secondary_sales.retailer_name",  # Natural language alias
    "retailer_type": "fact_secondary_sales.retailer_type",
    "companywh_code": "fact_primary_sales.companywh_code",
    "companywh_name": "fact_primary_sales.companywh_name",
    "warehouse": "fact_primary_sales.companywh_name",  # Natural language alias

    # --------------------
    # PRODUCT
    # --------------------
    "sku_code": {
        "PRIMARY": "fact_primary_sales.sku_code",
        "SECONDARY": "fact_secondary_sales.sku_code",
    },
    "product_desc": {
        "PRIMARY": "fact_primary_sales.product_desc",
        "SECONDARY": "fact_secondary_sales.product_desc",
    },
    "product": {  # Natural language alias
        "PRIMARY": "fact_primary_sales.product_desc",
        "SECONDARY": "fact_secondary_sales.product_desc",
    },
    "brand": {
        "PRIMARY": "fact_primary_sales.brand",
        "SECONDARY": "fact_secondary_sales.brand",
    },
    "category": {
        "PRIMARY": "fact_primary_sales.category",
        "SECONDARY": "fact_secondary_sales.category",
    },
    "sub_category": {
        "PRIMARY": "fact_primary_sales.sub_category",
        "SECONDARY": "fact_secondary_sales.sub_category",
    },
    "pack_size": {
        "PRIMARY": "fact_primary_sales.pack_size",
        "SECONDARY": "fact_secondary_sales.pack_size",
    },

    # --------------------
    # SALES HIERARCHY
    # --------------------
    "salesrep_code": "fact_secondary_sales.salesrep_code",
    "salesrep_name": "fact_secondary_sales.salesrep_name",
    "sales_rep": "fact_secondary_sales.salesrep_name",  # Natural language alias
    "so_name": {
        "PRIMARY": "fact_primary_sales.so_name",
        "SECONDARY": "fact_secondary_sales.so_name",
    },
    "sales_officer": {  # Natural language alias
        "PRIMARY": "fact_primary_sales.so_name",
        "SECONDARY": "fact_secondary_sales.so_name",
    },
    "asm_name": {
        "PRIMARY": "fact_primary_sales.asm_name",
        "SECONDARY": "fact_secondary_sales.asm_name",
    },
    "area_manager": {  # Natural language alias
        "PRIMARY": "fact_primary_sales.asm_name",
        "SECONDARY": "fact_secondary_sales.asm_name",
    },
    "zsm_name": {
        "PRIMARY": "fact_primary_sales.zsm_name",
        "SECONDARY": "fact_secondary_sales.zsm_name",
    },
    "zonal_manager": {  # Natural language alias
        "PRIMARY": "fact_primary_sales.zsm_name",
        "SECONDARY": "fact_secondary_sales.zsm_name",
    },

    # --------------------
    # ROUTE
    # --------------------
    "route_code": "fact_secondary_sales.route_code",
    "route_name": "fact_secondary_sales.route_name",
    "route": "fact_secondary_sales.route_name",  # Natural language alias

    # --------------------
    # INVOICE
    # --------------------
    "invoice_id": {
        "PRIMARY": "fact_primary_sales.invoice_id",
        "SECONDARY": "fact_secondary_sales.invoice_id",
    },
    "invoice_number": {  # Legacy alias
        "PRIMARY": "fact_primary_sales.invoice_id",
        "SECONDARY": "fact_secondary_sales.invoice_id",
    },
}

# =============================================================================
# TIME DIMENSION NORMALIZATION
# =============================================================================

TIME_DIMENSION_MAP = {
    "invoice_date": {
        "PRIMARY": "fact_primary_sales.invoice_date",
        "SECONDARY": "fact_secondary_sales.invoice_date",
    }
}


# =============================================================================
# NORMALIZER
# =============================================================================

def normalize_intent(raw_intent: dict) -> dict:
    """
    Normalize semantic intent fields into Cube catalog IDs.

    Input  : raw intent dict (LLM output)
    Output : normalized intent dict (cube.field everywhere)

    This function MUST run before validation.
    """

    logger.info("Normalizing intent")

    intent = copy.deepcopy(raw_intent)

    # -------------------------------------------------------------------------
    # Metric
    # -------------------------------------------------------------------------
    metric = intent.get("metric")
    if metric in METRIC_MAP:
        intent["metric"] = resolve_metric(metric, intent["sales_scope"])

    # -------------------------------------------------------------------------
    # Group by
    # -------------------------------------------------------------------------
    if intent.get("group_by"):
        intent["group_by"] = [
            resolve_dimension(dim, intent["sales_scope"])
            for dim in intent["group_by"]
        ]
        # validate_group_by(intent["group_by"], intent["sales_scope"])

    # -------------------------------------------------------------------------
    # Filters
    # -------------------------------------------------------------------------
    if intent.get("filters"):
        for f in intent["filters"]:
            if isinstance(f, dict):
                dim = f.get("dimension")
                if dim in DIMENSION_MAP:
                    f["dimension"] = resolve_dimension(dim, intent["sales_scope"])
            else:
                dim = getattr(f, "dimension", None)
                if dim in DIMENSION_MAP:
                    f.dimension = resolve_dimension(dim, intent["sales_scope"])

    # -------------------------------------------------------------------------
    # Time dimension
    # -------------------------------------------------------------------------
    if intent.get("time_dimension"):
        td = intent["time_dimension"]
        if isinstance(td, dict):
            dim = td.get("dimension")
            if dim in TIME_DIMENSION_MAP:
                td["dimension"] = resolve_time_dimension(dim, intent["sales_scope"])
        else:
            dim = getattr(td, "dimension", None)
            if dim in TIME_DIMENSION_MAP:
                td.dimension = resolve_time_dimension(dim, intent["sales_scope"])


    return intent

def resolve_metric(semantic_metric: str, sales_scope: str) -> str:
    try:
        return METRIC_MAP[semantic_metric][sales_scope]
    except KeyError:
        raise UnknownMetricError(
            f"Metric '{semantic_metric}' not valid for scope '{sales_scope}'"
        )


def resolve_dimension(semantic_dim: str, sales_scope: str | None = None) -> str:
    target = DIMENSION_MAP.get(semantic_dim)

    if target is None:
        raise UnknownDimensionError(f"Unknown dimension: '{semantic_dim}'")

    if isinstance(target, dict):
        if not sales_scope:
            raise InvalidDimensionError(
                f"Dimension '{semantic_dim}' requires sales_scope"
            )
        return target[sales_scope]

    return target


def resolve_time_dimension(semantic_td: str, sales_scope: str) -> str:
    try:
        return TIME_DIMENSION_MAP[semantic_td][sales_scope]
    except KeyError:
        raise UnknownTimeDimensionError(
            f"Time dimension '{semantic_td}' not valid for scope '{sales_scope}'"
        )


# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

class UnknownMetricError(Exception):
    pass

class UnknownDimensionError(Exception):
    pass

class InvalidDimensionError(Exception):
    pass

class UnknownTimeDimensionError(Exception):
    pass
