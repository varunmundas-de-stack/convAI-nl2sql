"""
Data Visualizer - Generate visualizations from query results using Claude.

This module takes the visualization type from the intent and the retrieved data
after query execution, then generates visual artifacts by calling Claude.

DESIGN PRINCIPLES:
- Input: visualization_type (from intent) + data (from Cube query)
- Output: Visualization specification (Plotly JSON, SVG, or HTML)
- Claude generates the visualization code/spec based on data patterns
- Supports multiple output formats for flexibility

SUPPORTED VISUALIZATION TYPES:
- bar_chart: Vertical bar chart for comparisons
- line_chart: Line chart for trends over time
- pie_chart: Pie chart for distributions
- number_card: Single metric display
- table: Tabular data display
"""

import json
import logging
from typing import Any, Literal
from pydantic import BaseModel

from app.services.llm_service import call_claude

logger = logging.getLogger(__name__)

# =============================================================================
# TYPES
# =============================================================================

VisualizationType = Literal[
    "bar_chart", 
    "line_chart", 
    "pie_chart", 
    "number_card", 
    "table"
]

OutputFormat = Literal["plotly_json", "svg", "html"]


class VisualizationResult(BaseModel):
    """Result of visualization generation."""
    visualization_type: str
    output_format: str
    content: str  # The actual visualization (Plotly JSON, SVG, or HTML)
    title: str
    description: str | None = None
    error: str | None = None


class VisualizationGenerationError(Exception):
    """Exception raised when a data visualization cannot be generated."""
    pass

# =============================================================================
# PROMPT TEMPLATES
# =============================================================================

VISUALIZATION_PROMPT_TEMPLATE = """You are a data visualization expert. Generate a visualization based on the data provided.

## TASK
Create a {visualization_type} visualization for the following data.

## DATA
```json
{data}
```

## INTENT CONTEXT
- Metric: {metric}
- Dimensions: {dimensions}
- Query: {query}

## OUTPUT FORMAT: {output_format}

{format_instructions}

## REQUIREMENTS
1. Use a clean, professional color palette
2. Include proper axis labels and units
3. Add a descriptive title based on the data
4. Ensure the visualization is responsive
5. Handle edge cases (null values, empty data)

Output ONLY the {output_format} content. No explanation. No markdown code blocks.
"""

FORMAT_INSTRUCTIONS = {
    "plotly_json": """Output a valid Plotly.js JSON specification.
The JSON should contain:
- "data": array of trace objects
- "layout": layout configuration with title, axis labels, colors
- "config": optional configuration (responsive: true)

Example structure:
{
  "data": [{"type": "bar", "x": [...], "y": [...], "marker": {"color": "#4F46E5"}}],
  "layout": {"title": "...", "xaxis": {"title": "..."}, "yaxis": {"title": "..."}, "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)"},
  "config": {"responsive": true}
}""",

    "svg": """Output a valid SVG element.
- Include viewBox for responsiveness
- Use modern colors (#4F46E5 primary, #10B981 success, #EF4444 error)
- Include text labels and axis markers
- Make it self-contained (no external dependencies)""",

    "html": """Output a complete, self-contained HTML snippet.
- Include inline CSS for styling
- Use modern design (rounded corners, shadows, gradients)
- Make it responsive
- For tables, use proper table markup with striped rows
- For number cards, use a prominent display with metric label"""
}


# =============================================================================
# VISUALIZATION GENERATORS
# =============================================================================

def generate_visualization(
    visualization_type: str,
    data: list[dict[str, Any]],
    metric: str | None = None,
    dimensions: list[str] | None = None,
    query: str | None = None,
    output_format: OutputFormat = "plotly_json"
) -> VisualizationResult:
    """
    Generate a visualization from query results.
    
    Args:
        visualization_type: Type of chart (bar_chart, line_chart, etc.)
        data: Query result data (list of row dicts)
        metric: The metric being visualized
        dimensions: The dimensions used for grouping
        query: Original natural language query (for context)
        output_format: Desired output format (plotly_json, svg, html)
    
    Returns:
        VisualizationResult with the generated visualization
    """
    logger.info(f"Generating {visualization_type} visualization ({output_format})")
    
    # Handle empty data
    if not data:
        return _generate_empty_visualization(visualization_type, output_format, query)
    
    # Handle number_card separately (simple display)
    if visualization_type == "number_card":
        return _generate_number_card(data, metric, output_format)
    
    # Handle table separately (no Claude needed for basic tables)
    if visualization_type == "table" and output_format == "html":
        return _generate_table_html(data, metric, dimensions)
    
    # Use Claude to generate the visualization
    try:
        prompt = VISUALIZATION_PROMPT_TEMPLATE.format(
            visualization_type=visualization_type,
            data=json.dumps(data, indent=2, default=str),
            metric=metric or "value",
            dimensions=", ".join(dimensions) if dimensions else "N/A",
            query=query or "Data visualization",
            output_format=output_format,
            format_instructions=FORMAT_INSTRUCTIONS.get(output_format, "")
        )
        
        response = call_claude(prompt)
        content = response.content[0].text.strip()
        
        # Validate JSON output for plotly_json
        if output_format == "plotly_json":
            # Try to parse to ensure it's valid JSON
            try:
                json.loads(content)
            except json.JSONDecodeError:
                # Try to extract JSON from response
                content = _extract_json(content)
        
        # Generate title from context
        title = _generate_title(visualization_type, metric, dimensions, query)
        
        return VisualizationResult(
            visualization_type=visualization_type,
            output_format=output_format,
            content=content,
            title=title,
            description=f"Generated from query: {query}" if query else None
        )
        
    except Exception as e:
        logger.error(f"Visualization generation failed: {e}")
        return VisualizationResult(
            visualization_type=visualization_type,
            output_format=output_format,
            content="",
            title="Visualization Error",
            error=str(e)
        )


def _generate_empty_visualization(
    visualization_type: str, 
    output_format: str,
    query: str | None
) -> VisualizationResult:
    """Generate a placeholder for empty data."""
    
    if output_format == "html":
        content = """
        <div style="padding: 2rem; text-align: center; color: #6B7280; background: #F9FAFB; border-radius: 8px; border: 1px dashed #D1D5DB;">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="margin: 0 auto 1rem;">
                <path d="M3 3v18h18M9 17V9m4 8v-5m4 5V6"/>
            </svg>
            <p style="margin: 0; font-size: 1rem;">No data available</p>
        </div>
        """
    elif output_format == "plotly_json":
        content = json.dumps({
            "data": [],
            "layout": {
                "title": "No data available",
                "annotations": [{
                    "text": "No data to display",
                    "showarrow": False,
                    "xref": "paper",
                    "yref": "paper",
                    "x": 0.5,
                    "y": 0.5,
                    "font": {"size": 20, "color": "#6B7280"}
                }]
            }
        })
    else:
        content = '<svg viewBox="0 0 200 100"><text x="100" y="50" text-anchor="middle" fill="#6B7280">No data</text></svg>'
    
    return VisualizationResult(
        visualization_type=visualization_type,
        output_format=output_format,
        content=content,
        title="No Data",
        description="The query returned no results"
    )


def _generate_number_card(
    data: list[dict[str, Any]], 
    metric: str | None,
    output_format: str
) -> VisualizationResult:
    """Generate a number card for single-value metrics."""
    
    # Extract the first numeric value
    value = None
    label = metric or "Value"
    
    if data and len(data) > 0:
        row = data[0]
        for key, val in row.items():
            if isinstance(val, (int, float)):
                value = val
                label = _format_label(key)
                break
            elif isinstance(val, str):
                try:
                    value = float(val.replace(",", ""))
                    label = _format_label(key)
                    break
                except ValueError:
                    continue
    
    formatted_value = _format_number(value) if value is not None else "N/A"
    
    if output_format == "html":
        content = f"""
        <div style="
            background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%);
            border-radius: 12px;
            padding: 2rem;
            text-align: center;
            color: white;
            box-shadow: 0 4px 6px -1px rgba(79, 70, 229, 0.3);
        ">
            <div style="font-size: 0.875rem; opacity: 0.9; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem;">
                {label}
            </div>
            <div style="font-size: 2.5rem; font-weight: 700; line-height: 1;">
                {formatted_value}
            </div>
        </div>
        """
    elif output_format == "plotly_json":
        content = json.dumps({
            "data": [{
                "type": "indicator",
                "mode": "number",
                "value": value,
                "title": {"text": label},
                "number": {"font": {"size": 60, "color": "#4F46E5"}}
            }],
            "layout": {
                "paper_bgcolor": "rgba(0,0,0,0)",
                "margin": {"t": 50, "b": 50, "l": 50, "r": 50}
            }
        })
    else:
        content = f'<svg viewBox="0 0 200 100"><text x="100" y="40" text-anchor="middle" fill="#4F46E5" font-size="32" font-weight="bold">{formatted_value}</text><text x="100" y="70" text-anchor="middle" fill="#6B7280" font-size="12">{label}</text></svg>'
    
    return VisualizationResult(
        visualization_type="number_card",
        output_format=output_format,
        content=content,
        title=label,
        description=f"Value: {formatted_value}"
    )


def _generate_table_html(
    data: list[dict[str, Any]], 
    metric: str | None,
    dimensions: list[str] | None
) -> VisualizationResult:
    """Generate an HTML table for tabular data."""
    
    if not data:
        return _generate_empty_visualization("table", "html", None)
    
    # Get column headers from first row
    columns = list(data[0].keys())
    
    # Format column headers
    headers = "".join([f'<th style="padding: 12px 16px; text-align: left; font-weight: 600; color: #374151; border-bottom: 2px solid #E5E7EB;">{_format_label(col)}</th>' for col in columns])
    
    # Format rows
    rows = []
    for i, row in enumerate(data):
        bg_color = "#F9FAFB" if i % 2 == 0 else "white"
        cells = "".join([
            f'<td style="padding: 12px 16px; color: #4B5563; border-bottom: 1px solid #E5E7EB;">{_format_cell_value(row.get(col))}</td>' 
            for col in columns
        ])
        rows.append(f'<tr style="background: {bg_color};">{cells}</tr>')
    
    content = f"""
    <div style="overflow-x: auto; border-radius: 8px; border: 1px solid #E5E7EB; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
        <table style="width: 100%; border-collapse: collapse; font-family: system-ui, -apple-system, sans-serif; font-size: 14px;">
            <thead style="background: #F3F4F6;">
                <tr>{headers}</tr>
            </thead>
            <tbody>
                {"".join(rows)}
            </tbody>
        </table>
    </div>
    """
    
    return VisualizationResult(
        visualization_type="table",
        output_format="html",
        content=content,
        title="Query Results",
        description=f"{len(data)} rows returned"
    )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _format_label(key: str) -> str:
    """Format a column key into a human-readable label."""
    # Remove cube prefix (e.g., "fact_secondary_sales.zone" -> "Zone")
    if "." in key:
        key = key.split(".")[-1]
    
    # Convert snake_case to Title Case
    return key.replace("_", " ").title()


def _format_number(value: float | int | None) -> str:
    """Format a number for display."""
    if value is None:
        return "N/A"
    
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    elif abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    elif abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    elif isinstance(value, float):
        return f"{value:,.2f}"
    else:
        return f"{value:,}"


def _format_cell_value(value: Any) -> str:
    """Format a cell value for table display."""
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        return _format_number(value)
    return str(value)


def _generate_title(
    visualization_type: str,
    metric: str | None,
    dimensions: list[str] | None,
    query: str | None
) -> str:
    """Generate a title for the visualization."""
    
    if query:
        # Use query as basis for title (truncate if too long)
        if len(query) <= 50:
            return query
        return query[:47] + "..."
    
    # Generate from metric and dimensions
    metric_label = _format_label(metric) if metric else "Value"
    
    if dimensions and len(dimensions) > 0:
        dim_label = _format_label(dimensions[0])
        return f"{metric_label} by {dim_label}"
    
    return metric_label


def _extract_json(content: str) -> str:
    """Try to extract JSON from a response that may have extra text."""
    # Try to find JSON object in the response
    start = content.find("{")
    end = content.rfind("}") + 1
    
    if start >= 0 and end > start:
        potential_json = content[start:end]
        try:
            json.loads(potential_json)
            return potential_json
        except json.JSONDecodeError:
            pass
    
    # Return original content if extraction fails
    return content


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def generate_plotly_chart(
    visualization_type: str,
    data: list[dict[str, Any]],
    metric: str | None = None,
    dimensions: list[str] | None = None,
    query: str | None = None
) -> dict[str, Any]:
    """
    Generate a Plotly chart specification.
    
    Returns:
        Plotly JSON specification as a dict
    """
    result = generate_visualization(
        visualization_type=visualization_type,
        data=data,
        metric=metric,
        dimensions=dimensions,
        query=query,
        output_format="plotly_json"
    )
    
    if result.error:
        raise ValueError(result.error)
    
    return json.loads(result.content)


def generate_html_visualization(
    visualization_type: str,
    data: list[dict[str, Any]],
    metric: str | None = None,
    dimensions: list[str] | None = None,
    query: str | None = None
) -> str:
    """
    Generate an HTML visualization.
    
    Returns:
        HTML string
    """
    result = generate_visualization(
        visualization_type=visualization_type,
        data=data,
        metric=metric,
        dimensions=dimensions,
        query=query,
        output_format="html"
    )
    
    return result.content
