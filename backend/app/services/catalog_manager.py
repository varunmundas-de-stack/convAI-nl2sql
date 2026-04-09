"""
Handles loading and querying the semantic catalog that maps natural language
concepts to Cube.js measures and dimensions.

Field Semantics:
- `id`: The Cube.js field identifier (e.g., 'sales_fact.quantity'). Used for API calls.
- `name`: The canonical semantic identifier used internally (e.g., 'total_quantity').

Future considerations:
- `cube_field`: May diverge from `id` when metrics don't 1:1 map to Cube measures
- `semantic_id`: For knowledge graph / ontology integration
- `storage_id`: For caching / persistence layer
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import yaml


class CatalogError(Exception):
    """Exception raised for catalog-related errors."""
    pass


class CatalogManager:
    def __init__(self, catalog_path: str):
        self._catalog = self._load_catalog(catalog_path)

    def _load_catalog(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        required = {"metrics", "dimensions", "time_dimensions", "time_windows"}
        missing = required - data.keys()
        if missing:
            raise ValueError(f"Missing catalog sections: {missing}")

        return data

    # -------- Existence checks --------

    def is_valid_metric(self, metric: str) -> bool:
        return metric in self._catalog["metrics"]

    def is_valid_dimension(self, dimension: str) -> bool:
        return dimension in self._catalog["dimensions"]

    def is_valid_time_dimension(self, time_dim: str) -> bool:
        return time_dim in self._catalog["time_dimensions"]

    def is_valid_time_window(self, window: str) -> bool:
        return window in self._catalog["time_windows"]

    # -------- Time helpers --------

    def get_time_granularities(self, time_dim: str) -> list[str]:
        return self._catalog["time_dimensions"][time_dim].get("granularities", [])


        # --------------- Raw Access ---------------

    def raw_catalog(self) -> Dict:
        """Return the raw catalog dictionary."""
        return self._catalog

    def get_section(self, section_name: str) -> Any:
        """Get a specific section from the catalog."""
        return self._catalog.get(section_name)
