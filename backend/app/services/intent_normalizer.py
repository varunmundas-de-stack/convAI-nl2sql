# app/services/intent_normalizer.py
import copy
import logging

logger = logging.getLogger(__name__)

# =============================================================================
# METRIC NORMALIZATION
# =============================================================================

METRIC_MAP: dict[str, str] = {
    "transaction_count": "sales_fact.count",
    "total_quantity": "sales_fact.quantity",
    "distributor_count": "distributors.count",
    "outlet_count": "outlets.count",
    "sku_count": "skus.count",
    "territory_count": "territories.count",
}

# =============================================================================
# DIMENSION NORMALIZATION (NON-TIME)
# =============================================================================

DIMENSION_MAP: dict[str, str] = {
    # Sales fact
    "sales_type": "sales_fact.sales_type",
    "is_credit_sale": "sales_fact.is_credit",
    "sales_rep": "sales_fact.sales_rep_code",
    "invoice_number": "sales_fact.invoice_number",

    # SKU
    "brand": "skus.brand",
    "product_category": "skus.category",
    "product_sub_category": "skus.sub_category",
    "product_name": "skus.sku_name",
    "pack_size": "skus.pack_size",

    # Territory
    "region": "territories.region",
    "state": "territories.state",
    "zone": "territories.zone",
    "territory_name": "territories.territory_name",

    # Outlet
    "outlet_type": "outlets.outlet_type",
    "outlet_name": "outlets.outlet_name",
    "beat_code": "outlets.beat_code",

    # Distributor
    "distributor_name": "distributors.distributor_name",
    "distributor_type": "distributors.distributor_type",
}

# =============================================================================
# TIME DIMENSION NORMALIZATION
# =============================================================================

TIME_DIMENSION_MAP: dict[str, str] = {
    "invoice_date": "sales_fact.invoice_date",
    "calendar_date": "date_dim.full_date",
}



# TIME_WINDOW_TO_DATE_RANGE: dict[str, str] = {
#     "today": "today",
#     "yesterday": "yesterday",
#     "last_7_days": "last 7 days",
#     "last_30_days": "last 30 days",
#     "last_90_days": "last 90 days",
#     "month_to_date": "this month",
#     "quarter_to_date": "this quarter",
#     "year_to_date": "this year",
#     "last_month": "last month",
#     "last_quarter": "last quarter",
#     "last_year": "last year",
# }

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
        intent["metric"] = METRIC_MAP[metric]

    # -------------------------------------------------------------------------
    # Group by
    # -------------------------------------------------------------------------
    if intent.get("group_by"):
        intent["group_by"] = [
            DIMENSION_MAP.get(dim, dim)
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
                    f["dimension"] = DIMENSION_MAP[dim]
            else:
                dim = getattr(f, "dimension", None)
                if dim in DIMENSION_MAP:
                    f.dimension = DIMENSION_MAP[dim]

    # -------------------------------------------------------------------------
    # Time dimension
    # -------------------------------------------------------------------------
    if intent.get("time_dimension"):
        td = intent["time_dimension"]
        if isinstance(td, dict):
            dim = td.get("dimension")
            if dim in TIME_DIMENSION_MAP:
                td["dimension"] = TIME_DIMENSION_MAP[dim]
        else:
            dim = getattr(td, "dimension", None)
            if dim in TIME_DIMENSION_MAP:
                td.dimension = TIME_DIMENSION_MAP[dim]

    # -------------------------------------------------------------------------
    # Time window
    # -------------------------------------------------------------------------
    # if intent.get("time_range"):
    #     if intent.get("time_range").window:
    #         intent["time_range"] = TIME_WINDOW_TO_DATE_RANGE.get(intent["time_range"].window, intent["time_range"].window)
    #         if intent["time_range"] is None:
    #             raise ValueError(f"Invalid time window: {intent["time_range"].window}")
    #     else:
    #         intent["time_range"] = [intent["time_range"].start_date, intent["time_range"].end_date]

    return intent
