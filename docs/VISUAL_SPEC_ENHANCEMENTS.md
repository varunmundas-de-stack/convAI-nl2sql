# Visual Spec Generator Enhancements

## Summary of Changes

Enhanced the visual spec generator with improved metadata, contextual coloring, axis typing, and better label handling to enable more sophisticated frontend rendering.

## Changes Made

### 1. Enhanced Models

#### DataSeries Model
**Added:**
- `point_colors: Optional[list[str]]` - Per-point color mapping for contextual coloring
  - Enables specific bars to be colored differently (e.g., top contributor in green, outliers in red)

#### Axis Model
**Added:**
- `axis_type: Optional[str]` - Axis scale type ("time", "categorical", "linear")
  - Helps frontend choose appropriate scale (time scale for dates, band scale for categories)

#### VisualSpec Model
**Added:**
- `trend_slope: Optional[float]` - Normalized slope percentage for trend visuals
  - Extracted from trend insights for frontend rendering of trend indicators

### 2. Enhanced Builder Functions

#### Bar Chart Builder (`_build_bar_spec`)
**Enhancements:**
1. **Axis Type Detection**: Automatically detects if x-axis is time-based or categorical
2. **Contextual Coloring**: Uses `_build_color_map()` to assign colors based on insights
   - Top contributors → Green (#10b981)
   - High/Critical outliers → Red (#ef4444)
   - Medium outliers → Amber (#f59e0b)
   - Bottom performers → Slate (#94a3b8)
3. **Primary/Secondary Values**: Populates key metrics for snapshot displays
   - Primary: Total value with metric label
   - Secondary: Top contributor value and name
4. **Clean Labels**: Uses `_clean_label()` to strip table prefixes

#### Line Chart Builder (`_build_line_spec`)
**Enhancements:**
1. **Axis Type Detection**: Same as bar charts
2. **Trend Slope Extraction**: Captures slope from trend insights
3. **Primary Values**: Populates total metric for reference
4. **Clean Labels**: Uses `_clean_label()` for better readability

### 3. Enhanced Marker Generation (`_insights_to_markers`)

**Added:**
- **Threshold Markers**: When outliers are detected, adds a threshold marker at the mean value
  - Shows baseline for comparison
  - Only adds one threshold marker (avoids duplicates)
  - Uses `_format_number()` for readable labels

### 4. New Helper Functions

#### `_clean_label(key: Optional[str]) -> str`
**Purpose**: Remove common table prefixes and format labels
**Examples:**
```python
"fact_secondary_sales.total_sales" → "Total Sales"
"dim_product.product_name" → "Product Name"  
"Sales.Region.Name" → "Name"
```

#### `_build_color_map(insights, x_values) -> dict[str, Optional[str]]`
**Purpose**: Build per-point color map based on insights
**Logic:**
- Top contributor → `#10b981` (green)
- High/Critical outlier → `#ef4444` (red)
- Medium outlier → `#f59e0b` (amber)
- Bottom performer → `#94a3b8` (slate)
- Normal points → `None` (use default)

#### `_format_number(value: float) -> str`
**Purpose**: Format numbers for human display
**Examples:**
```python
1000 → "1.0K"
1500000 → "1.5M"
2500000000 → "2.5B"
123.45 → "123.45"
```

## Visual Spec Output Examples

### Before Enhancement

```python
VisualSpec(
    chart_type=ChartType.BAR,
    x_axis=Axis(
        label="Fact Secondary Sales.Region",
        values=["Mumbai", "Delhi", "Bangalore"],
    ),
    y_axis=Axis(
        label="fact_secondary_sales.total_sales",
        format="number",
    ),
    series=[
        DataSeries(
            label="fact_secondary_sales.total_sales",
            values=[420000, 250000, 180000],
            point_emphasis=[EmphasisLevel.STRONG, EmphasisLevel.NONE, EmphasisLevel.NONE],
        )
    ],
)
```

### After Enhancement

```python
VisualSpec(
    chart_type=ChartType.BAR,
    x_axis=Axis(
        label="Region",  # ✓ Clean label
        values=["Mumbai", "Delhi", "Bangalore"],
        axis_type="categorical",  # ✓ NEW
    ),
    y_axis=Axis(
        label="Total Sales",  # ✓ Clean label
        format="number",
        axis_type="linear",  # ✓ NEW
    ),
    series=[
        DataSeries(
            label="Total Sales",  # ✓ Clean label
            values=[420000, 250000, 180000],
            point_emphasis=[EmphasisLevel.STRONG, EmphasisLevel.NONE, EmphasisLevel.NONE],
            point_colors=["#10b981", None, None],  # ✓ NEW (Mumbai is top contributor)
        )
    ],
    primary_value="1.0M",  # ✓ NEW
    primary_label="Total Total Sales",  # ✓ NEW
    secondary_value="420.0K",  # ✓ NEW
    secondary_label="Mumbai (Top)",  # ✓ NEW
    markers=[
        Marker(
            marker_type=MarkerType.ANNOTATION,
            label="Mumbai accounts for 42% of sales",
            position="Mumbai",
            value=420000,
        ),
    ],
)
```

### Trend Chart Example

```python
VisualSpec(
    chart_type=ChartType.LINE,
    x_axis=Axis(
        label="Month",  # ✓ Clean label
        values=["Jan", "Feb", "Mar", "Apr"],
        format="date",
        axis_type="time",  # ✓ NEW - frontend can use time scale
    ),
    y_axis=Axis(
        label="Total Sales",  # ✓ Clean label
        format="number",
        axis_type="linear",  # ✓ NEW
    ),
    series=[...],
    trend_slope=5.2,  # ✓ NEW - 5.2% upward trend per period
    primary_value="2.4M",  # ✓ NEW
    primary_label="Total Total Sales",  # ✓ NEW
    markers=[
        Marker(
            marker_type=MarkerType.TREND_LINE,
            label="Sales is trending upward (5.2%)",
        ),
    ],
)
```

### Outlier Detection Example

```python
VisualSpec(
    chart_type=ChartType.BAR,
    series=[
        DataSeries(
            values=[100, 120, 115, 900, 110],  # Raipur is outlier
            point_colors=[None, None, None, "#ef4444", None],  # ✓ Red for outlier
        )
    ],
    markers=[
        Marker(
            marker_type=MarkerType.OUTLIER,
            label="Raipur is 3.2σ above average",
            position="Raipur",
            value=900,
        ),
        Marker(
            marker_type=MarkerType.THRESHOLD,  # ✓ NEW
            label="Average: 269.0",  # ✓ NEW
            value=269.0,  # ✓ NEW
        ),
    ],
)
```

## Frontend Impact

The frontend can now:

1. **Choose Appropriate Scales**
   - Use time scale for `axis_type="time"`
   - Use band scale for `axis_type="categorical"`
   - Use linear scale for `axis_type="linear"`

2. **Apply Contextual Colors**
   - Read `point_colors` for per-bar coloring
   - Override with emphasis colors when needed

3. **Show Threshold Lines**
   - Render horizontal line at `marker.value` for THRESHOLD markers
   - Shows baseline for outlier comparison

4. **Display Trend Slopes**
   - Use `trend_slope` to show trend indicator
   - Add slope annotation to chart

5. **Render Key Metrics**
   - Always show `primary_value` and `primary_label` for non-table visuals
   - Show `secondary_value` when available

6. **Cleaner Labels**
   - All labels now use `_clean_label()` removing table prefixes
   - More readable axis labels and series names

## Testing

All imports verified:
```bash
✓ from app.services.visual_spec_generator import generate_visual_spec, ChartType, EmphasisLevel
✓ from app.services.visual_spec_generator import _clean_label, _build_color_map, _format_number
```

## Files Modified

- `backend/app/services/visual_spec_generator.py` - All enhancements applied

## Breaking Changes

**None.** All changes are additive. Existing fields unchanged.
- New optional fields default to `None`
- Frontend can gracefully ignore new fields if not implemented
