# app/services/intent_normalizer.py
import copy
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# METRIC MAP
# semantic name → {scope: cube_id}
# =============================================================================

METRIC_MAP = {
    # Count
    "transaction_count": {
        "PRIMARY": "fact_primary_sales.count",
        "SECONDARY": "fact_secondary_sales.count",
    },
    "count": {
        "PRIMARY": "fact_primary_sales.count",
        "SECONDARY": "fact_secondary_sales.count",
    },

    # Volume
    "billed_qty": {
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

    # Value
    "net_value": {
        "PRIMARY": "fact_primary_sales.net_value",
        "SECONDARY": "fact_secondary_sales.net_value",
    },
    "gross_value": {
        "PRIMARY": "fact_primary_sales.gross_value",
        "SECONDARY": "fact_secondary_sales.gross_value",
    },
    "tax_value": {
        "PRIMARY": "fact_primary_sales.tax_value",
        "SECONDARY": "fact_secondary_sales.tax_value",
    },
}


# =============================================================================
# DIMENSION MAP
# semantic name → cube_id (str) or {scope: cube_id}
# =============================================================================

DIMENSION_MAP = {
    # Geography
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

    # Distributor
    "distributor_code": {
        "PRIMARY": "fact_primary_sales.distributor_code",
        "SECONDARY": "fact_secondary_sales.distributor_code",
    },
    "distributor_name": {
        "PRIMARY": "fact_primary_sales.distributor_name",
        "SECONDARY": "fact_secondary_sales.distributor_name",
    },

    # Retailer (secondary only)
    "retailer_code": "fact_secondary_sales.retailer_code",
    "retailer_name": "fact_secondary_sales.retailer_name",
    "retailer_type": "fact_secondary_sales.retailer_type",

    # Warehouse (primary only)
    "companywh_code": "fact_primary_sales.companywh_code",
    "companywh_name": "fact_primary_sales.companywh_name",

    # Product
    "sku_code": {
        "PRIMARY": "fact_primary_sales.sku_code",
        "SECONDARY": "fact_secondary_sales.sku_code",
    },
    "product_desc": {
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

    # Sales hierarchy
    "salesrep_code": "fact_secondary_sales.salesrep_code",
    "salesrep_name": "fact_secondary_sales.salesrep_name",
    "so_name": {
        "PRIMARY": "fact_primary_sales.so_name",
        "SECONDARY": "fact_secondary_sales.so_name",
    },
    "asm_name": {
        "PRIMARY": "fact_primary_sales.asm_name",
        "SECONDARY": "fact_secondary_sales.asm_name",
    },
    "zsm_name": {
        "PRIMARY": "fact_primary_sales.zsm_name",
        "SECONDARY": "fact_secondary_sales.zsm_name",
    },

    # Route (secondary only)
    "route_code": "fact_secondary_sales.route_code",
    "route_name": "fact_secondary_sales.route_name",

    # Invoice
    "invoice_id": {
        "PRIMARY": "fact_primary_sales.invoice_id",
        "SECONDARY": "fact_secondary_sales.invoice_id",
    },
}


# =============================================================================
# TIME DIMENSION MAP
# semantic name → {scope: cube_id}
# =============================================================================

TIME_DIMENSION_MAP = {
    "invoice_date": {
        "PRIMARY": "fact_primary_sales.invoice_date",
        "SECONDARY": "fact_secondary_sales.invoice_date",
    },
}


# =============================================================================
# NORMALIZER
# =============================================================================

def normalize_intent(raw_intent: dict) -> dict:
    """
    Normalize semantic intent fields into Cube catalog IDs.

    Input  : raw intent dict (LLM output, semantic names)
    Output : normalized intent dict (cube.field everywhere)

    MUST run before validation.
    """
    logger.info("Normalizing intent")

    intent = copy.deepcopy(raw_intent)
    scope = intent.get("sales_scope", "SECONDARY")

    # -------------------------------------------------------------------------
    # Metric — legacy single-string field
    # -------------------------------------------------------------------------
    metric = intent.get("metric")
    if metric in METRIC_MAP:
        intent["metric"] = resolve_metric(metric, scope)

    # -------------------------------------------------------------------------
    # Metrics — new list field (each item: {name, aggregation})
    # -------------------------------------------------------------------------
    metrics = intent.get("metrics")
    if metrics and isinstance(metrics, list):
        for m in metrics:
            if isinstance(m, dict):
                name = m.get("name")
                if name in METRIC_MAP:
                    m["name"] = resolve_metric(name, scope)

    # -------------------------------------------------------------------------
    # Group by
    # -------------------------------------------------------------------------
    if intent.get("group_by"):
        intent["group_by"] = [
            resolve_dimension(dim, scope)
            for dim in intent["group_by"]
        ]

    # -------------------------------------------------------------------------
    # Filters
    # -------------------------------------------------------------------------
    if intent.get("filters"):
        for f in intent["filters"]:
            if isinstance(f, dict):
                dim = f.get("dimension")
                if dim in DIMENSION_MAP:
                    f["dimension"] = resolve_dimension(dim, scope)
            else:
                dim = getattr(f, "dimension", None)
                if dim and dim in DIMENSION_MAP:
                    f.dimension = resolve_dimension(dim, scope)

    # -------------------------------------------------------------------------
    # Time — new unified TimeSpec field {dimension, granularity, window, ...}
    # -------------------------------------------------------------------------
    time_spec = intent.get("time")
    if time_spec and isinstance(time_spec, dict):
        dim = time_spec.get("dimension")
        if dim in TIME_DIMENSION_MAP:
            time_spec["dimension"] = resolve_time_dimension(dim, scope)
        elif not dim:
            # LLM omitted dimension — inject default
            time_spec["dimension"] = resolve_time_dimension("invoice_date", scope)

    # -------------------------------------------------------------------------
    # Time dimension — legacy separate field
    # -------------------------------------------------------------------------
    time_dimension = intent.get("time_dimension")
    if time_dimension:
        if isinstance(time_dimension, dict):
            dim = time_dimension.get("dimension")
            if dim in TIME_DIMENSION_MAP:
                time_dimension["dimension"] = resolve_time_dimension(dim, scope)
        else:
            dim = getattr(time_dimension, "dimension", None)
            if dim and dim in TIME_DIMENSION_MAP:
                time_dimension.dimension = resolve_time_dimension(dim, scope)

    # Legacy: time_range without time_dimension → inject default dimension
    time_range = intent.get("time_range")
    if time_range and not time_dimension and not time_spec:
        intent["time_dimension"] = {
            "dimension": resolve_time_dimension("invoice_date", scope),
            "granularity": None,
        }

    return intent


# =============================================================================
# RESOLVERS
# =============================================================================

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
# EXCEPTIONS
# =============================================================================

class UnknownMetricError(Exception):
    pass

class UnknownDimensionError(Exception):
    pass

class InvalidDimensionError(Exception):
    pass

class UnknownTimeDimensionError(Exception):
    pass
