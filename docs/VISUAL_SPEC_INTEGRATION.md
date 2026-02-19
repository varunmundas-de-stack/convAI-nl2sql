# Frontend Visual Spec Integration

## Summary

Complete rewrite of the frontend ChartRenderer component to consume the new backend VisualSpec format, including support for:
- All chart types (bar, line, pie, number_card, table)
- Contextual coloring (point_colors)
- Threshold markers
- Trend slopes with visual indicators
- Executive summary (from refined_insights)
- Annotations with severity levels
- Primary/secondary values

## Files Modified

### 1. `frontend/src/components/ChartRenderer.tsx`
**COMPLETE REWRITE**

#### New Interface
```typescript
interface ChartRendererProps {
    visual_spec?: VisualSpec;
    refined_insights?: RefinedInsights;
}
```

#### What It Renders

**From `visual_spec`:**
- ✅ `chart_type` - Determines which renderer to use
- ✅ `title` - Main heading
- ✅ `subtitle` - Secondary heading
- ✅ `x_axis` - Axis labels, values, type
- ✅ `y_axis` - Axis labels, format, type
- ✅ `series` - Data with point_colors and point_emphasis
- ✅ `annotations` - Insights with severity styling
- ✅ `markers` - Outliers, thresholds, trends
- ✅ `primary_value / primary_label` - Key metrics
- ✅ `secondary_value / secondary_label` - Secondary metrics
- ✅ `direction` - Up/down/flat indicators
- ✅ `trend_slope` - Percentage change with arrows

**From `refined_insights`:**
- ✅ `executive_summary` - Collapsible insight panel (blue background)

#### Chart Renderers Implemented

1. **NumberCardRenderer** (Built-in)
   - Large primary value display
   - Gradient background
   - Trend indicator with arrow and percentage
   - Secondary value in bordered section

2. **TableRenderer**
   - Standard HTML table
   - Hover effects
   - Clean styling

3. **BarChartRenderer** (SVG-based)
   - Uses `point_colors` for contextual coloring
   - `point_emphasis` for opacity levels
   - Threshold markers (dashed line at average)
   - Primary/secondary value display above chart
   - Hover effects

4. **LineChartRenderer** (SVG-based)
   - Color based on `color_hint` (positive=green, negative=red)
   - Trend slope badge with arrow
   - Primary value display
   - Smooth line paths with circles at data points

5. **PieChartRenderer** (SVG-based)
   - Auto-calculated percentages
   - Color legend
   - Labeled segments

#### Severity Styling
```typescript
critical → Red background
high → Orange background
medium → Yellow background
low → Gray background
```

#### Trend Indicators
```typescript
up → Green badge with TrendingUp icon
down → Red badge with TrendingDown icon
flat → Gray badge with Minus icon
```

### 2. `frontend/src/services/api.ts`
**Updated transformation logic**

**NEW:**
```typescript
// Prioritize visual_spec (new format)
if (backendResponse.visual_spec) {
    return {
        type: "chart",
        chartType: backendResponse.visual_spec.chart_type,
        data: {
            visual_spec: backendResponse.visual_spec,
            refined_insights: backendResponse.refined_insights || null,
        },
    };
}
```

**OLD (still supported as fallback):**
```typescript
// Legacy visualization format
if (backendResponse.visualization) {
    // ... existing logic
}
```

### 3. `frontend/src/components/MessageBubble.tsx`
**Updated ChartRenderer invocation**

**Before:**
```typescript
<ChartRenderer data={responseData} />
```

**After:**
```typescript
<ChartRenderer 
    visual_spec={responseData.data?.visual_spec} 
    refined_insights={responseData.data?.refined_insights}
/>
```

## Example Renders

### Number Card with Trend
```
┌─────────────────────────────────────┐
│ Total Sales                         │
│ 1.2M          ↗ 5.2%               │
│                                     │
│ ─────────────────────────────────── │
│ Mumbai (Top)                        │
│ 420.0K                             │
└─────────────────────────────────────┘
```

### Bar Chart with Contextual Colors
```
┌─────────────────────────────────────┐
│ Total Total Sales: 1.0M             │
│ Mumbai (Top): 420.0K                │
│                                     │
│     ┃                               │
│  42 ┃ (green - top contributor)    │
│  0K ┃                               │
│     ┃       ┃       ┃       ┃      │
│  25 ┃       ┃       ┃       ┃      │
│  0K ┃       ┃       ┃       ┃      │
│     ┴───────┴───────┴───────┴──────│
│   Mumbai  Delhi  Blr   Chennai     │
│                                     │
│ ---- Average: 269.0 (threshold) --- │
└─────────────────────────────────────┘
```

### Executive Summary Panel
```
┌─────────────────────────────────────┐
│ ▼ Executive Summary                 │
├─────────────────────────────────────┤
│ Mumbai is the dominant market,      │
│ accounting for 42% of sales. This   │
│ indicates high concentration risk.  │
└─────────────────────────────────────┘
```

### Annotations with Severity
```
┌─────────────────────────────────────┐
│ 🔴 ↗ Mumbai drives nearly half of   │
│      total sales and warrants       │
│      strategic focus                │
└─────────────────────────────────────┘
```

## Color Mappings (from backend)

The frontend now respects `point_colors` from the backend:

```typescript
Top contributor    → #10b981 (green)
High/Critical outlier → #ef4444 (red)
Medium outlier     → #f59e0b (amber)
Bottom performer   → #94a3b8 (slate)
Default            → #3b82f6 (blue)
```

## Threshold Markers

When outliers are detected, threshold markers show as:
- Dashed horizontal line at the mean value
- Label: "Average: 269.0"
- Subtle emphasis (gray, semi-transparent)

## Responsive Design

All charts:
- Use SVG with viewBox for auto-scaling
- Responsive width (100%)
- Consistent padding and spacing
- Mobile-friendly layouts

## Browser Compatibility

- No Plotly.js dependency (pure SVG/HTML/CSS)
- No SSR issues
- Works on all modern browsers
- Fast initial render

## Testing

To test the integration:

1. **Backend**: Ensure `visual_spec` is in response
   ```bash
   curl http://localhost:8000/query -X POST -H "Content-Type: application/json" \
     -d '{"query": "Show me sales by region"}'
   ```

2. **Frontend**: Check console for visual_spec
   ```javascript
   // In browser console after query
   console.log(backendResponse.visual_spec);
   console.log(backendResponse.refined_insights);
   ```

3. **Visual Check**:
   - Number cards should show large values with trend badges
   - Bar charts should have colored bars for top contributors/outliers
   - Threshold lines should appear when outliers exist
   - Executive summary should be collapsible
   - Annotations should have colored backgrounds based on severity

## Migration Notes

### Backward Compatibility

The system maintains backward compatibility:
1. `visual_spec` is checked FIRST (new format)
2. `visualization` is checked as FALLBACK (legacy format)
3. Raw data tables still work
4. Text responses still work

### Breaking Changes

**None for existing queries** - all legacy behavior preserved.

**New queries** will use the new visual_spec format automatically.

## Next Steps

1. ✅ Backend sends `visual_spec` and `refined_insights`
2. ✅ Frontend consumes and renders visual_spec
3. ⏳ Add animations (fade-in, hover effects)
4. ⏳ Add export functionality (PNG, SVG, CSV)
5. ⏳ Add drill-down interactions
6. ⏳ Add theme customization

## Performance

- **No external chart libraries** - Pure SVG rendering
- **Small bundle size** - Removed Plotly.js dependency
- **Fast initial render** - No heavy JS processing
- **Smooth interactions** - CSS transitions only
