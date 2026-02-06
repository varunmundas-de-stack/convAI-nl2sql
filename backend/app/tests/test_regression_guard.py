import pytest
import json
import yaml
from pathlib import Path

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
SNAPSHOT_DIR.mkdir(exist_ok=True)

def get_snapshot_path(name):
    return SNAPSHOT_DIR / f"{name}.json"

def assert_matches_snapshot(name, data):
    path = get_snapshot_path(name)

    # Normalize data for consistent snapshot (sort keys)
    # data should be JSON serializable

    if not path.exists():
        # First run: create snapshot
        with open(path, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        pytest.fail(f"Snapshot '{name}' did not exist. Created it. Run again to verify.")

    with open(path, "r") as f:
        expected = json.load(f)

    # Compare structure
    # We want to detect changes.
    # If they differ, fail.

    # Use json.dumps to compare string representation with sorted keys
    actual_str = json.dumps(data, indent=2, sort_keys=True)
    expected_str = json.dumps(expected, indent=2, sort_keys=True)

    if actual_str != expected_str:
        # If running in update mode (e.g. UPDATE_SNAPSHOTS=1), update it.
        # But per requirements, we should fail with a message.
        import os
        if os.getenv("UPDATE_SNAPSHOTS"):
            with open(path, "w") as f:
                f.write(actual_str)
            pytest.fail(f"Snapshot '{name}' updated.")
        else:
            pytest.fail(f"Schema or catalog contract changed. Review required. \nDiff (actual vs expected snapshot):\nSnapshot: {path}")

def test_catalog_structure_snapshot(catalog_manager):
    """
    Snapshot test for catalog structure (keys only).
    """
    catalog = catalog_manager.raw_catalog()

    # Extract keys only
    snapshot_data = {
        "metrics": sorted(list(catalog.get("metrics", {}).keys())),
        "dimensions": sorted(list(catalog.get("dimensions", {}).keys())),
        "time_dimensions": sorted(list(catalog.get("time_dimensions", {}).keys())),
        "time_windows": sorted(list(catalog.get("time_windows", {}).keys())),
    }

    assert_matches_snapshot("catalog_structure", snapshot_data)

def test_cube_schema_snapshot(load_cube_schema):
    """
    Snapshot test for Cube schema structure.
    """
    schemas = load_cube_schema()

    snapshot_data = {}
    for filename, schema in schemas.items():
        cubes = []
        for cube in schema.get("cubes", []):
            c_data = {
                "name": cube["name"],
                "measures": sorted([m["name"] for m in cube.get("measures", [])]),
                "dimensions": sorted([d["name"] for d in cube.get("dimensions", [])])
            }
            cubes.append(c_data)
        # Sort cubes by name
        cubes.sort(key=lambda x: x["name"])
        snapshot_data[filename] = cubes

    assert_matches_snapshot("cube_schema_structure", snapshot_data)
