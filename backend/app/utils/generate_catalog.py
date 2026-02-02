import yaml
from pathlib import Path

# Determine the project root and backend directory relative to this script
CURRENT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CURRENT_DIR.parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

SCHEMA_DIR = PROJECT_ROOT / "cube" / "model" / "cubes"
OUTPUT_PATH = BACKEND_DIR / "catalog" / "catalog.yaml"

DEFAULT_GRANULARITIES = ["day", "week", "month", "quarter", "year"]

# Logical time windows supported by the system (not schema-derived)
TIME_WINDOWS = {
    "today": True,
    "yesterday": True,
    "last_7_days": True,
    "last_30_days": True,
    "last_90_days": True,
    "month_to_date": True,
    "quarter_to_date": True,
    "year_to_date": True,
    "last_month": True,
    "last_quarter": True,
    "last_year": True,
}

def load_yaml(path: Path):
    with open(path, "r") as f:
        return yaml.safe_load(f)

def generate_catalog(schema_dir: Path) -> dict:
    catalog = {
        "metrics": {},
        "dimensions": {},
        "time_dimensions": {},
        "time_windows": TIME_WINDOWS.copy(),
    }

    for schema_file in schema_dir.glob("*.yml"):
        data = load_yaml(schema_file)
        if not data or "cubes" not in data:
            continue

        for cube in data["cubes"]:
            cube_name = cube["name"]

            # ---------------- metrics ----------------
            for measure in cube.get("measures", []):
                metric_id = f"{cube_name}.{measure['name']}"
                catalog["metrics"][metric_id] = True

            # ---------------- dimensions & time dimensions ----------------
            for dim in cube.get("dimensions", []):
                dim_id = f"{cube_name}.{dim['name']}"

                if dim.get("type") == "time":
                    catalog["time_dimensions"][dim_id] = {
                        "granularities": list(DEFAULT_GRANULARITIES)
                    }
                else:
                    catalog["dimensions"][dim_id] = True

    return catalog

def write_catalog(catalog: dict, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        yaml.dump(catalog, f, sort_keys=False)

if __name__ == "__main__":
    catalog = generate_catalog(SCHEMA_DIR)
    write_catalog(catalog, OUTPUT_PATH)
    print(f"catalog.yaml generated at {OUTPUT_PATH}")
