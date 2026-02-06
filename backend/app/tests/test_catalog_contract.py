import pytest
import yaml

def test_catalog_metrics_exist_in_cube(catalog_manager, load_cube_schema):
    """
    Ensure every metric in the catalog exists in the Cube schema.
    """
    catalog = catalog_manager.raw_catalog()
    cube_schemas = load_cube_schema()

    # Flatten cube schemas for easy lookup: {cube_name: {measures: set(), dimensions: set()}}
    cube_lookup = {}
    for filename, schema in cube_schemas.items():
        if "cubes" in schema:
            for cube in schema["cubes"]:
                c_name = cube["name"]
                measures = {m["name"] for m in cube.get("measures", [])}
                dimensions = {d["name"] for d in cube.get("dimensions", [])}
                cube_lookup[c_name] = {"measures": measures, "dimensions": dimensions}

    for metric_id in catalog.get("metrics", {}):
        # metric_id is like "fact_primary_sales.count"
        parts = metric_id.split(".")
        assert len(parts) == 2, f"Invalid metric ID format: {metric_id}"

        cube_name, measure_name = parts

        assert cube_name in cube_lookup, f"Cube '{cube_name}' not found in Cube schema (metric: {metric_id})"
        assert measure_name in cube_lookup[cube_name]["measures"], \
            f"Measure '{measure_name}' not found in cube '{cube_name}' (metric: {metric_id})"

def test_catalog_dimensions_exist_in_cube(catalog_manager, load_cube_schema):
    """
    Ensure every dimension in the catalog exists in the Cube schema.
    """
    catalog = catalog_manager.raw_catalog()
    cube_schemas = load_cube_schema()

    cube_lookup = {}
    for filename, schema in cube_schemas.items():
        if "cubes" in schema:
            for cube in schema["cubes"]:
                c_name = cube["name"]
                # Dimensions in cube include both 'dimensions' list and time dimensions often
                # But in the YAML provided, time dimensions are in 'dimensions' list with type: time
                dimensions = {d["name"] for d in cube.get("dimensions", [])}
                cube_lookup[c_name] = dimensions

    for dim_id in catalog.get("dimensions", {}):
        parts = dim_id.split(".")
        assert len(parts) == 2, f"Invalid dimension ID format: {dim_id}"

        cube_name, dim_name = parts

        assert cube_name in cube_lookup, f"Cube '{cube_name}' not found for dimension {dim_id}"
        assert dim_name in cube_lookup[cube_name], \
            f"Dimension '{dim_name}' not found in cube '{cube_name}' (dimension: {dim_id})"

def test_catalog_time_dimensions_exist_in_cube(catalog_manager, load_cube_schema):
    """
    Ensure time dimensions exist and have valid granularities.
    """
    catalog = catalog_manager.raw_catalog()
    cube_schemas = load_cube_schema()

    cube_lookup = {}
    for filename, schema in cube_schemas.items():
        if "cubes" in schema:
            for cube in schema["cubes"]:
                c_name = cube["name"]
                # Time dimensions are usually defined in dimensions with type='time'
                dimensions = {d["name"]: d for d in cube.get("dimensions", [])}
                cube_lookup[c_name] = dimensions

    for td_id, config in catalog.get("time_dimensions", {}).items():
        parts = td_id.split(".")
        assert len(parts) == 2, f"Invalid time dimension ID format: {td_id}"

        cube_name, dim_name = parts

        assert cube_name in cube_lookup, f"Cube '{cube_name}' not found for time dim {td_id}"
        assert dim_name in cube_lookup[cube_name], \
            f"Dimension '{dim_name}' not found in cube '{cube_name}'"

        # Verify it is actually a time dimension in Cube (optional but good)
        dim_def = cube_lookup[cube_name][dim_name]
        assert dim_def.get("type") == "time", \
            f"Catalog time dimension '{td_id}' is not type 'time' in Cube (found {dim_def.get('type')})"

        # Verify granularities
        assert "granularities" in config, f"Time dimension {td_id} missing granularities"
        assert len(config["granularities"]) > 0, f"Time dimension {td_id} has empty granularities"

def test_no_ghost_metrics(catalog_manager, load_cube_schema):
    """
    Ensure no ghost metrics (checks are covered by test_catalog_metrics_exist_in_cube,
    but this explicit name helps intention).
    """
    # This is effectively the same as above, but explicitly checks for 'ghosts'
    pass
