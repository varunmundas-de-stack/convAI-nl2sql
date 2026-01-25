from pathlib import Path
from typing import Dict, List, Optional
import yaml


class CatalogError(Exception):
    pass


class CatalogManager:
    def __init__(self, catalog_path: str) -> None:
        self.catalog_path = Path(catalog_path)

        if not self.catalog_path.exists():
            raise CatalogError(f"Catalog file not found at {self.catalog_path}")

        self._catalog = self._load_catalog()
        self.build_reverse_indexes()


    def _load_catalog(self) -> Dict:
        with open(self.catalog_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        required_sections = {'metrics', 'dimensions', 'time_dimensions'}
        missing_sections = required_sections - set(data.keys())

        if missing_sections:
            raise CatalogError(f"Missing catalog sections: {missing_sections}")

        return data

    def build_reverse_indexes(self):
        self.metric_index: Dict[str, str] = {}
        self.dimension_index: Dict[str, str] = {}
        self.time_dimension_index: Dict[str, str] = {}

        for metric, metadata in self._catalog['metrics'].items():
            self.metric_index[metric.lower()] = metric
            for synonym in metadata.get('synonyms', []):
                self.metric_index[synonym.lower()] = metric

        for dimension in self._catalog['dimensions'].values():
            self.dimension_index[dimension.lower()] = dimension
            for synonym in dimension.get('synonyms', []):
                self.dimension_index[synonym.lower()] = dimension

        for time_dimension in self._catalog['time_dimensions'].values():
            self.time_dimension_index[time_dimension.lower()] = time_dimension
            for synonym in time_dimension.get('synonyms', []):
                self.time_dimension_index[synonym.lower()] = time_dimension



        # --------------- PUBLIC API ---------------


        def list_metrics(self) -> List[str]:
            return list(self.metric_index.keys())

        def list_dimensions(self) -> List[str]:
            return list(self.dimension_index.keys())

        def list_time_dimensions(self) -> List[str]:
            return list(self.time_dimension_index.keys())

        def resolve_metric(self, name: str) -> Dict:
            key = name.lower()
            if key in self.metric_index:
                metric_name = self.metric_index[key]
                return self._catalog['metrics'][metric_name]
            raise CatalogError(f"Metric '{name}' not found")

        def resolve_dimension(self, name: str) -> Dict:
        key = name.lower()
        if key not in self.dimension_index:
            raise CatalogError(f"Unknown dimension: {name}")

        dim_name = self.dimension_index[key]
        return self._catalog["dimensions"][dim_name]

    def get_metric_cube_field(self, name: str) -> str:
        metric = self.resolve_metric(name)
        if "cube_measure" not in metric:
            raise CatalogError(f"Metric missing cube_measure: {name}")
        return metric["cube_measure"]

    def get_dimension_cube_field(self, name: str) -> str:
        dimension = self.resolve_dimension(name)
        if "cube_dimension" not in dimension:
            raise CatalogError(f"Dimension missing cube_dimension: {name}")
        return dimension["cube_dimension"]

    def get_time_dimension_cube_field(self, name: str) -> str:
        time_dim = self._catalog["time_dimensions"].get(name)
        if not time_dim:
            raise CatalogError(f"Unknown time dimension: {name}")
        return time_dim["cube_dimension"]

    def is_valid_metric(self, name: str) -> bool:
        return name.lower() in self.metric_index

    def is_valid_dimension(self, name: str) -> bool:
        return name.lower() in self.dimension_index

    def raw_catalog(self) -> Dict:
        return self._catalog
