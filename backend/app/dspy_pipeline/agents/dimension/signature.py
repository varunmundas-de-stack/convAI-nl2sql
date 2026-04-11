import dspy
from app.dspy_pipeline.schemas import DimensionsResult

class ResolveDimensions(dspy.Signature):
    """Resolve dimensions and filters from classified query."""
    original_query: str = dspy.InputField(desc="Original query text")
    classified_terms: str = dspy.InputField(desc="JSON string containing only the classified terms with roles DIMENSION and FILTER_VALUE")
    sales_scope: str = dspy.InputField(desc="Resolved sales scope for dimension validation")
    available_dimensions: str = dspy.InputField(desc="JSON list of available dimensions with name, label, description")
    previous_context: str = dspy.InputField(desc="Previous QCO context as JSON string. empty on first turn")
    x_axis_values: str = dspy.InputField(
        desc="""JSON object with 'dimension' (the catalog field name) and 'values' (list of labels 
        from the previous chart). If a classified FILTER_VALUE term semantically matches or closely matches 
        (ignoring cases, spacing, hyphens, prefixes) any of these values, emit a FilterCondition with that 
        dimension and the EXACT matched value from the 'values' list. 
        Example: if query contains 'north1' and values has 'North-1', output 'North-1'.
        Example Input: {"dimension": "fact_secondary_sales.zone", "values": ["Central", "North", "South"]}"""
    )

    # Output DimensionsResult as JSON
    dimensions_result: DimensionsResult = dspy.OutputField(
    desc="""
    JSON object with DimensionsResult containing:

    group_by:
      - array of dimension names matching the user's intent from available_dimensions.
      - If the user explicitly asks for a specific dimension (e.g. 'country'), return just that one ['country'].
      - If the user uses a VAGUE/GENERIC term that matches multiple specific catalog fields, you MUST return ALL matching candidate fields in the area.
      - NEVER arbitrarily choose just one field if the user's term is generic. Give every valid possibility.
      - A term like 'region' is VAGUE — return ALL geo-related candidates e.g. ['zone', 'region', 'state'].

    filters:
      - array of FilterCondition objects or null
      - If a classified term has role=FILTER_VALUE and its value fuzzy-matches (ignoring hyphens, spaces, typos) an item in x_axis_values,
        it is a filter NOT a dimension.
        Emit: { dimension: <group_by from previous_context>, operator: "equals", values: [<EXACT matched value from x_axis_values>] }
      - CRITICAL: You MUST use the exact string casing and format from x_axis_values. Do NOT use the raw user query string if it differs.
      - NEVER add a FILTER_VALUE term to group_by.

    Rules:
      - Max 2 dimensions for grouping (EXCEPT when returning >2 candidates for a generic/ambiguous term)
      - Never include 'invoice_date'
      - Only use dimensions exactly as named in available_dimensions
      - Respect hierarchy constraints (geo/product)
    """
    )