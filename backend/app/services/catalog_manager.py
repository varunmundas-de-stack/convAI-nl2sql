"""
Catalog Manager for FMCG Sales Analytics NL2SQL System

Handles loading and querying the semantic catalog that maps natural language
concepts to Cube.js measures and dimensions.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml


class CatalogError(Exception):
    """Exception raised for catalog-related errors."""
    pass


class CatalogManager:
    """
    Manages the semantic catalog for NL2SQL translation.
    
    The catalog contains:
    - Metrics (measures) with their Cube.js mappings
    - Dimensions with their Cube.js mappings
    - Time dimensions and granularities
    - Time windows (predefined date ranges)
    - Intent types (query patterns)
    - Comparison types (YoY, MoM, etc.)
    - Visualization type recommendations
    - Business rules and constraints
    - Common query patterns
    """

    def __init__(self, catalog_path: str) -> None:
        self.catalog_path = Path(catalog_path)

        if not self.catalog_path.exists():
            raise CatalogError(f"Catalog file not found at {self.catalog_path}")

        self._catalog = self._load_catalog()
        self._build_indexes()

    def _load_catalog(self) -> Dict:
        """Load and validate the catalog YAML file."""
        with open(self.catalog_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        required_sections = {'metrics', 'dimensions', 'time_dimensions'}
        missing_sections = required_sections - set(data.keys())

        if missing_sections:
            raise CatalogError(f"Missing catalog sections: {missing_sections}")

        return data

    def _build_indexes(self) -> None:
        """
        Build reverse indexes for fast lookups by name, alias, and examples.
        
        The new catalog uses list-based structures with 'id' fields for cube mappings
        and 'aliases' for synonyms.
        """
        # Metric lookup: name/alias -> metric dict
        self._metric_by_name: Dict[str, Dict] = {}
        self._metric_by_id: Dict[str, Dict] = {}
        
        # Dimension lookup: name/alias -> dimension dict
        self._dimension_by_name: Dict[str, Dict] = {}
        self._dimension_by_id: Dict[str, Dict] = {}
        
        # Time dimension lookup
        self._time_dimension_by_name: Dict[str, Dict] = {}
        self._time_dimension_by_id: Dict[str, Dict] = {}
        
        # Time window lookup
        self._time_window_by_name: Dict[str, Dict] = {}
        
        # Build metric indexes
        for metric in self._catalog.get('metrics', []):
            metric_id = metric.get('id', '')
            metric_name = metric.get('name', '')
            
            # Index by id
            self._metric_by_id[metric_id.lower()] = metric
            
            # Index by name
            self._metric_by_name[metric_name.lower()] = metric
            
            # Index by display_name
            display_name = metric.get('display_name', '')
            if display_name:
                self._metric_by_name[display_name.lower()] = metric
            
            # Index by aliases
            for alias in metric.get('aliases', []):
                self._metric_by_name[alias.lower()] = metric
        
        # Build dimension indexes
        for dimension in self._catalog.get('dimensions', []):
            dim_id = dimension.get('id', '')
            dim_name = dimension.get('name', '')
            
            # Index by id
            self._dimension_by_id[dim_id.lower()] = dimension
            
            # Index by name
            self._dimension_by_name[dim_name.lower()] = dimension
            
            # Index by display_name
            display_name = dimension.get('display_name', '')
            if display_name:
                self._dimension_by_name[display_name.lower()] = dimension
            
            # Index by aliases
            for alias in dimension.get('aliases', []):
                self._dimension_by_name[alias.lower()] = dimension
        
        # Build time dimension indexes
        for time_dim in self._catalog.get('time_dimensions', []):
            td_id = time_dim.get('id', '')
            td_name = time_dim.get('name', '')
            
            # Index by id
            self._time_dimension_by_id[td_id.lower()] = time_dim
            
            # Index by name
            self._time_dimension_by_name[td_name.lower()] = time_dim
            
            # Index by display_name
            display_name = time_dim.get('display_name', '')
            if display_name:
                self._time_dimension_by_name[display_name.lower()] = time_dim
        
        # Build time window indexes
        for tw in self._catalog.get('time_windows', []):
            tw_id = tw.get('id', '')
            tw_name = tw.get('name', '')
            
            self._time_window_by_name[tw_id.lower()] = tw
            self._time_window_by_name[tw_name.lower()] = tw
            
            # Index by aliases
            for alias in tw.get('aliases', []):
                self._time_window_by_name[alias.lower()] = tw

    # --------------- PUBLIC API: List Methods ---------------

    def list_metrics(self) -> List[Dict]:
        """Return list of all metrics."""
        return self._catalog.get('metrics', [])

    def list_metric_names(self) -> List[str]:
        """Return list of all metric names."""
        return [m.get('name', '') for m in self._catalog.get('metrics', [])]

    def list_dimensions(self) -> List[Dict]:
        """Return list of all dimensions."""
        return self._catalog.get('dimensions', [])

    def list_dimension_names(self) -> List[str]:
        """Return list of all dimension names."""
        return [d.get('name', '') for d in self._catalog.get('dimensions', [])]

    def list_time_dimensions(self) -> List[Dict]:
        """Return list of all time dimensions."""
        return self._catalog.get('time_dimensions', [])

    def list_time_windows(self) -> List[Dict]:
        """Return list of all time windows."""
        return self._catalog.get('time_windows', [])

    def list_intent_types(self) -> List[Dict]:
        """Return list of all intent types."""
        return self._catalog.get('intent_types', [])

    def list_comparison_types(self) -> List[Dict]:
        """Return list of all comparison types."""
        return self._catalog.get('comparison_types', [])

    def list_visualization_types(self) -> List[Dict]:
        """Return list of all visualization types."""
        return self._catalog.get('visualization_types', [])

    # --------------- PUBLIC API: Resolve Methods ---------------

    def resolve_metric(self, name: str) -> Dict:
        """
        Resolve a metric by name, alias, or ID.
        
        Args:
            name: Metric name, alias, display_name, or ID
            
        Returns:
            The full metric dictionary
            
        Raises:
            CatalogError: If metric not found
        """
        key = name.lower()
        
        # Try by name/alias first
        if key in self._metric_by_name:
            return self._metric_by_name[key]
        
        # Try by ID
        if key in self._metric_by_id:
            return self._metric_by_id[key]
        
        raise CatalogError(f"Metric '{name}' not found in catalog")

    def resolve_dimension(self, name: str) -> Dict:
        """
        Resolve a dimension by name, alias, or ID.
        
        Args:
            name: Dimension name, alias, display_name, or ID
            
        Returns:
            The full dimension dictionary
            
        Raises:
            CatalogError: If dimension not found
        """
        key = name.lower()
        
        # Try by name/alias first
        if key in self._dimension_by_name:
            return self._dimension_by_name[key]
        
        # Try by ID
        if key in self._dimension_by_id:
            return self._dimension_by_id[key]
        
        raise CatalogError(f"Dimension '{name}' not found in catalog")

    def resolve_time_dimension(self, name: str) -> Dict:
        """
        Resolve a time dimension by name or ID.
        
        Args:
            name: Time dimension name, display_name, or ID
            
        Returns:
            The full time dimension dictionary
            
        Raises:
            CatalogError: If time dimension not found
        """
        key = name.lower()
        
        if key in self._time_dimension_by_name:
            return self._time_dimension_by_name[key]
        
        if key in self._time_dimension_by_id:
            return self._time_dimension_by_id[key]
        
        raise CatalogError(f"Time dimension '{name}' not found in catalog")

    def resolve_time_window(self, name: str) -> Dict:
        """
        Resolve a time window by name, ID, or alias.
        
        Args:
            name: Time window name, ID, or alias
            
        Returns:
            The full time window dictionary
            
        Raises:
            CatalogError: If time window not found
        """
        key = name.lower()
        
        if key in self._time_window_by_name:
            return self._time_window_by_name[key]
        
        raise CatalogError(f"Time window '{name}' not found in catalog")

    # --------------- PUBLIC API: Cube.js Field Methods ---------------

    def get_metric_cube_field(self, name: str) -> str:
        """
        Get the Cube.js field identifier for a metric.
        
        The field is in format 'CubeName.measureName' (e.g., 'sales_fact.count')
        
        Args:
            name: Metric name, alias, or ID
            
        Returns:
            Cube.js field identifier (e.g., 'sales_fact.quantity')
        """
        metric = self.resolve_metric(name)
        cube_field = metric.get('id')
        
        if not cube_field:
            raise CatalogError(f"Metric '{name}' missing 'id' field for Cube.js mapping")
        
        return cube_field

    def get_dimension_cube_field(self, name: str) -> str:
        """
        Get the Cube.js field identifier for a dimension.
        
        The field is in format 'CubeName.dimensionName' (e.g., 'skus.brand')
        
        Args:
            name: Dimension name, alias, or ID
            
        Returns:
            Cube.js field identifier (e.g., 'territories.region')
        """
        dimension = self.resolve_dimension(name)
        cube_field = dimension.get('id')
        
        if not cube_field:
            raise CatalogError(f"Dimension '{name}' missing 'id' field for Cube.js mapping")
        
        return cube_field

    def get_time_dimension_cube_field(self, name: str) -> str:
        """
        Get the Cube.js field identifier for a time dimension.
        
        Args:
            name: Time dimension name or ID
            
        Returns:
            Cube.js field identifier (e.g., 'sales_fact.invoice_date')
        """
        time_dim = self.resolve_time_dimension(name)
        cube_field = time_dim.get('id')
        
        if not cube_field:
            raise CatalogError(f"Time dimension '{name}' missing 'id' field for Cube.js mapping")
        
        return cube_field

    def get_time_dimension_granularities(self, name: str) -> List[Dict]:
        """
        Get available granularities for a time dimension.
        
        Args:
            name: Time dimension name or ID
            
        Returns:
            List of granularity dictionaries with name, display_name, and examples
        """
        time_dim = self.resolve_time_dimension(name)
        return time_dim.get('granularities', [])

    # --------------- PUBLIC API: Validation Methods ---------------

    def is_valid_metric(self, name: str) -> bool:
        """Check if a metric name/alias exists in the catalog."""
        key = name.lower()
        return key in self._metric_by_name or key in self._metric_by_id

    def is_valid_dimension(self, name: str) -> bool:
        """Check if a dimension name/alias exists in the catalog."""
        key = name.lower()
        return key in self._dimension_by_name or key in self._dimension_by_id

    def is_valid_time_dimension(self, name: str) -> bool:
        """Check if a time dimension name/ID exists in the catalog."""
        key = name.lower()
        return key in self._time_dimension_by_name or key in self._time_dimension_by_id

    def is_valid_time_window(self, name: str) -> bool:
        """Check if a time window name/ID/alias exists in the catalog."""
        return name.lower() in self._time_window_by_name

    # --------------- PUBLIC API: Business Context Methods ---------------

    def get_dimension_possible_values(self, name: str) -> List[Dict]:
        """
        Get possible values for a dimension (if defined).
        
        Args:
            name: Dimension name or ID
            
        Returns:
            List of possible value dictionaries with value, label, and description
        """
        dimension = self.resolve_dimension(name)
        return dimension.get('possible_values', [])

    def get_business_rules(self) -> List[Dict]:
        """Return list of business rules from the catalog."""
        return self._catalog.get('business_rules', [])

    def get_query_patterns(self) -> List[Dict]:
        """Return list of common query patterns from the catalog."""
        return self._catalog.get('query_patterns', [])

    def get_metadata(self) -> Dict:
        """Return catalog metadata."""
        return self._catalog.get('metadata', {})

    # --------------- PUBLIC API: Search Methods ---------------

    def search_metrics(self, query: str) -> List[Dict]:
        """
        Search metrics by name, alias, description, or examples.
        
        Args:
            query: Search query string
            
        Returns:
            List of matching metric dictionaries
        """
        query_lower = query.lower()
        results = []
        
        for metric in self._catalog.get('metrics', []):
            # Check name and display_name
            if query_lower in metric.get('name', '').lower():
                results.append(metric)
                continue
            if query_lower in metric.get('display_name', '').lower():
                results.append(metric)
                continue
            
            # Check description
            if query_lower in metric.get('description', '').lower():
                results.append(metric)
                continue
            
            # Check aliases
            if any(query_lower in alias.lower() for alias in metric.get('aliases', [])):
                results.append(metric)
                continue
            
            # Check examples
            if any(query_lower in ex.lower() for ex in metric.get('examples', [])):
                results.append(metric)
                continue
        
        return results

    def search_dimensions(self, query: str) -> List[Dict]:
        """
        Search dimensions by name, alias, description, or examples.
        
        Args:
            query: Search query string
            
        Returns:
            List of matching dimension dictionaries
        """
        query_lower = query.lower()
        results = []
        
        for dimension in self._catalog.get('dimensions', []):
            # Check name and display_name
            if query_lower in dimension.get('name', '').lower():
                results.append(dimension)
                continue
            if query_lower in dimension.get('display_name', '').lower():
                results.append(dimension)
                continue
            
            # Check description
            if query_lower in dimension.get('description', '').lower():
                results.append(dimension)
                continue
            
            # Check aliases
            if any(query_lower in alias.lower() for alias in dimension.get('aliases', [])):
                results.append(dimension)
                continue
            
            # Check examples
            if any(query_lower in ex.lower() for ex in dimension.get('examples', [])):
                results.append(dimension)
                continue
        
        return results

    # --------------- PUBLIC API: Priority/Ranking Methods ---------------

    def get_high_priority_metrics(self) -> List[Dict]:
        """Return metrics marked as high priority."""
        return [
            m for m in self._catalog.get('metrics', [])
            if m.get('priority') == 'high'
        ]

    def get_high_priority_dimensions(self) -> List[Dict]:
        """Return dimensions marked as high priority."""
        return [
            d for d in self._catalog.get('dimensions', [])
            if d.get('priority') == 'high'
        ]

    def get_filterable_dimensions(self) -> List[Dict]:
        """Return dimensions that can be used for filtering."""
        return [
            d for d in self._catalog.get('dimensions', [])
            if d.get('filterable', False)
        ]

    def get_groupable_dimensions(self) -> List[Dict]:
        """Return dimensions that can be used for grouping."""
        return [
            d for d in self._catalog.get('dimensions', [])
            if d.get('groupable', False)
        ]

    # --------------- Raw Access ---------------

    def raw_catalog(self) -> Dict:
        """Return the raw catalog dictionary."""
        return self._catalog

    def get_section(self, section_name: str) -> Any:
        """Get a specific section from the catalog."""
        return self._catalog.get(section_name)
