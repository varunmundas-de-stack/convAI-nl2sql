"""
Shared utilities for pivoting and merging data for visualizations.
"""

from typing import Any, Tuple

def strip_cube_prefix(field: str | None) -> str:
    """
    Strip cube prefix from field, e.g. "fact_secondary_sales.net_value" -> "net_value"
    """
    if not field:
        return ""
    if "." in field:
        return field.split(".", 1)[1]
    return field

def pivot_rows(rows: list[dict[str, Any]], index: str, columns: str | list[str], values: str) -> Tuple[list[dict], list[str]]:
    """
    Group rows by index dimension (X axis).
    For each X value, map column values -> metric values.
    Return (pivoted_rows, stack_keys).
    """
    idx_clean = strip_cube_prefix(index)
    
    if isinstance(columns, str):
        columns = [columns]
        
    cols_clean = [strip_cube_prefix(c) for c in columns]
    val_clean = strip_cube_prefix(values)
    
    pivot_map = {}
    stack_keys_set = set()
    
    for row in rows:
        idx_val = row.get(index, row.get(idx_clean))
        if idx_val is None:
            continue
            
        str_idx = str(idx_val)
        
        # Build compound stack key
        col_vals = []
        for c, c_clean in zip(columns, cols_clean):
            v = row.get(c, row.get(c_clean))
            col_vals.append(str(v) if v is not None else "unknown")
            
        str_col = " - ".join(col_vals)
        
        val_metric = row.get(values, row.get(val_clean, 0))
        
        if str_idx not in pivot_map:
            pivot_map[str_idx] = {
                idx_clean: idx_val
            }
            
        pivot_map[str_idx][str_col] = val_metric
        stack_keys_set.add(str_col)
        
    stack_keys = sorted(list(stack_keys_set))
    
    pivoted_rows = []
    for str_idx, row_dict in pivot_map.items():
        for k in stack_keys:
            if k not in row_dict:
                row_dict[k] = 0
        pivoted_rows.append(row_dict)
        
    return pivoted_rows, stack_keys


def merge_dual_query(primary: list[dict[str, Any]], comparison: list[dict[str, Any]], group_by: list[str], metric: str) -> list[dict[str, Any]]:
    """
    Merge primary and comparison rows by group_by key tuple.
    Append {metric}_comparison and {metric}_growth_pct to each row.
    """
    metric_clean = strip_cube_prefix(metric)
    
    def _make_key(row):
        return tuple(str(row.get(g, row.get(strip_cube_prefix(g), ""))) for g in group_by)
        
    comp_map = {}
    for row in comparison:
        comp_map[_make_key(row)] = row.get(metric, row.get(metric_clean, 0.0))
        
    merged = []
    for row in primary:
        new_row = dict(row)
        key = _make_key(row)
        
        curr_val = row.get(metric, row.get(metric_clean))
        prev_val = comp_map.get(key, 0.0)
        
        try:
            curr_float = float(curr_val) if curr_val is not None else 0.0
        except (ValueError, TypeError):
            curr_float = 0.0
            
        try:
            prev_float = float(prev_val) if prev_val is not None else 0.0
        except (ValueError, TypeError):
            prev_float = 0.0
            
        # Ensure clean dimension keys exist for frontend mapping
        for g in group_by:
            g_clean = strip_cube_prefix(g)
            new_row[g_clean] = row.get(g, row.get(g_clean))
            
        # Ensure clean metric keys exist for SeriesConfig mapping
        new_row[metric_clean] = curr_float
        new_row[f"{metric_clean}_comparison"] = prev_float
        
        if prev_float != 0.0:
            growth = round(((curr_float - prev_float) / prev_float) * 100.0, 2)
            new_row[f"{metric_clean}_growth_pct"] = growth
        else:
            new_row[f"{metric_clean}_growth_pct"] = None
            
        merged.append(new_row)
        
    return merged
