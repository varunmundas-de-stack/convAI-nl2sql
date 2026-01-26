# Intent Validation System - Summary

## Overview

The intent validation system is the **critical security/safety layer** that ensures:
> **"The LLM cannot cause unsafe execution."**

## Architecture

```
Raw Intent Dict (from LLM)
    ↓
IntentValidator.validate()
    ↓
[Structural Validation] → MalformedIntentError
    ↓
[Catalog Validation] → UnknownMetric/Dimension/TimeWindowError
    ↓
[Ambiguity Check] → AmbiguousMetric/DimensionError
    ↓
Validated Intent Object ✓
```

## Components

### 1. Intent Model (`backend/app/models/intent.py`)
**Purpose**: Canonical intent contract

**Key Classes**:
- `IntentType` enum: `SNAPSHOT`, `TREND`
- `Intent`: Main schema with validation
- `TimeDimension`: Time field + granularity
- `TimeRange`: Named window OR explicit dates
- `Filter`: Dimension + operator + value

**Constraints Enforced**:
- ✓ Exactly one metric required
- ✓ TREND requires `time_dimension` and `time_range`
- ✓ No extra fields allowed (`Config.extra = "forbid"`)
- ✓ Filter operator/value type matching

### 2. Intent Errors (`backend/app/services/intent_errors.py`)
**Purpose**: Centralized failure taxonomy

**Error Codes**:
```python
class IntentErrorCode(str, Enum):
    # Catalog validation
    UNKNOWN_METRIC = "UNKNOWN_METRIC"
    UNKNOWN_DIMENSION = "UNKNOWN_DIMENSION"
    UNKNOWN_TIME_DIMENSION = "UNKNOWN_TIME_DIMENSION"
    INVALID_TIME_WINDOW = "INVALID_TIME_WINDOW"
    INVALID_GRANULARITY = "INVALID_GRANULARITY"
    
    # Ambiguity
    AMBIGUOUS_METRIC = "AMBIGUOUS_METRIC"
    AMBIGUOUS_DIMENSION = "AMBIGUOUS_DIMENSION"
    
    # Structural
    MALFORMED_INTENT = "MALFORMED_INTENT"
    INVALID_FILTER = "INVALID_FILTER"
    INVALID_TIME_RANGE = "INVALID_TIME_RANGE"
    
    # Scope
    OUT_OF_SCOPE_INTENT = "OUT_OF_SCOPE_INTENT"
    UNSUPPORTED_INTENT_TYPE = "UNSUPPORTED_INTENT_TYPE"
```

**Error Structure**:
```python
{
    "error_code": "UNKNOWN_METRIC",
    "error_type": "UnknownMetricError",
    "message": "Unknown metric: 'total_sales'. Did you mean: total_quantity?",
    "field": "metric",
    "value": "total_sales",
    "suggestions": ["total_quantity", "transaction_count"],
    "metadata": {}
}
```

### 3. Intent Validator (`backend/app/services/intent_validator.py`)
**Purpose**: Semantic validation gate

**Validation Steps**:
1. **Structural** - Parse dict → Intent (Pydantic)
2. **Metric** - Exists in catalog, unambiguous
3. **Dimensions** - All group_by fields exist
4. **Time Dimension** - Exists, valid granularity
5. **Time Range** - Valid window if specified
6. **Filters** - All filter dimensions exist

**Usage**:
```python
from backend.app.services.catalog_manager import CatalogManager
from backend.app.services.intent_validator import validate_intent

catalog = CatalogManager("catalog.yaml")

raw_intent = {
    "intent_type": "snapshot",
    "metric": "total_quantity",
    "time_range": {"window": "last_7_days"}
}

try:
    intent = validate_intent(raw_intent, catalog)
    # Intent is now safe to execute
except IntentValidationError as e:
    # Handle validation failure
    error_response = e.to_dict()
    print(f"Validation failed: {e.ERROR_CODE}")
```

## Validation Rules

| Rule | Error Raised | Example |
|------|--------------|---------|
| Metric not in catalog | `UnknownMetricError` | `"total_sales"` → suggest `"total_quantity"` |
| Dimension not in catalog | `UnknownDimensionError` | `"country"` → suggest `"region"`, `"state"` |
| Time dimension not in catalog | `UnknownTimeDimensionError` | `"order_date"` → suggest `"invoice_date"` |
| Invalid time window | `InvalidTimeWindowError` | `"last_2_weeks"` → suggest valid windows |
| Invalid granularity | `InvalidGranularityError` | `"hourly"` → must be day/week/month/quarter/year |
| Metric matches multiple | `AmbiguousMetricError` | `"sales"` → matches `["total_sales", "net_sales"]` |
| Dimension matches multiple | `AmbiguousDimensionError` | `"type"` → matches `["outlet_type", "sales_type"]` |
| Missing required field | `MalformedIntentError` | TREND without `time_dimension` |
| Invalid filter dimension | `InvalidFilterError` | Filter on non-existent dimension |

## Safety Guarantees

✓ **No SQL Injection**: All fields validated against catalog  
✓ **No Arbitrary Queries**: Only catalog metrics/dimensions allowed  
✓ **No Ambiguity**: Multi-match terms rejected with clear error  
✓ **Type Safety**: Pydantic enforces types at parse time  
✓ **Structural Safety**: Extra fields rejected, required fields enforced  

## Error Handling Best Practices

### For API Responses
```python
from backend.app.services.intent_errors import format_error_response

try:
    intent = validate_intent(raw_intent, catalog)
    return {"success": True, "intent": intent.model_dump()}
except IntentValidationError as e:
    return format_error_response(e)
```

### For Logging
```python
import logging

try:
    intent = validate_intent(raw_intent, catalog)
except IntentValidationError as e:
    logging.error(
        f"Intent validation failed",
        extra={
            "error_code": e.ERROR_CODE.value,
            "field": e.field,
            "value": e.value,
            "suggestions": e.suggestions
        }
    )
```

### For User Feedback
```python
try:
    intent = validate_intent(raw_intent, catalog)
except UnknownMetricError as e:
    # Show user-friendly message with suggestions
    return f"I don't recognize the metric '{e.value}'. Did you mean: {', '.join(e.suggestions)}?"
except MalformedIntentError as e:
    # Ask user to rephrase
    return "I couldn't understand your query. Could you rephrase it?"
```

## Testing

Run quick validation tests:
```bash
python -m backend.app.tests.test_intent_validator_quick
```

## Future Enhancements

1. **Fuzzy Matching**: Use `rapidfuzz` for better suggestions
2. **Business Rules**: Validate business constraints (e.g., "TERTIARY requires outlet")
3. **Value Validation**: Validate filter values against dimension possible_values
4. **Date Validation**: Validate explicit date ranges (format, logical consistency)
5. **Metrics**: Track validation failure rates by error code
