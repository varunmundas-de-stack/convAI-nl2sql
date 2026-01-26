"""
Catalog Manager for FMCG Sales Analytics NL2SQL System

Handles loading and querying the semantic catalog that maps natural language
concepts to Cube.js measures and dimensions.

Field Semantics:
- `id`: The Cube.js field identifier (e.g., 'sales_fact.quantity'). Used for API calls.
- `name`: The canonical semantic identifier used internally (e.g., 'total_quantity').
- `display_name`: Human-readable label for UI/responses.

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


class AmbiguousResolutionError(CatalogError):
    """Exception raised when a term resolves to multiple catalog items."""
    
    def __init__(self, term: str, matches: List[Dict], item_type: str):
        self.term = term
        self.matches = matches
        self.item_type = item_type
        match_names = [m.get('name', m.get('id', 'unknown')) for m in matches]
        super().__init__(
            f"Ambiguous {item_type} resolution for '{term}'. "
            f"Matches: {match_names}. Please be more specific."
        )


@dataclass
class ResolutionResult:
    """Result of a catalog resolution, including ambiguity info."""
    item: Optional[Dict]
    is_ambiguous: bool
    all_matches: List[Dict]
    item_type: str  # 'metric', 'dimension', 'time_dimension', 'time_window'
    
    @property
    def is_found(self) -> bool:
        return self.item is not None or len(self.all_matches) > 0


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
    
    Ambiguity Handling:
    - When a term matches multiple items, AmbiguousResolutionError is raised
    - Use `resolve_*_safe()` methods for soft resolution that returns all matches
    - Use `find_*()` methods to get all matches without error
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
        
        IMPORTANT: Indexes map to LISTS of items to detect ambiguity.
        The new catalog uses list-based structures with 'id' fields for cube mappings
        and 'aliases' for synonyms.
        """
        # Metric lookup: name/alias -> LIST of metric dicts (for ambiguity detection)
        self._metric_by_name: Dict[str, List[Dict]] = {}
        self._metric_by_id: Dict[str, Dict] = {}  # ID should be unique
        
        # Dimension lookup
        self._dimension_by_name: Dict[str, List[Dict]] = {}
        self._dimension_by_id: Dict[str, Dict] = {}
        
        # Time dimension lookup
        self._time_dimension_by_name: Dict[str, List[Dict]] = {}
        self._time_dimension_by_id: Dict[str, Dict] = {}
        
        # Time window lookup
        self._time_window_by_name: Dict[str, List[Dict]] = {}
        
        # Cross-type collision tracking (term -> set of types it appears in)
        self._cross_type_index: Dict[str, Set[str]] = {}
        
        # Build metric indexes
        for metric in self._catalog.get('metrics', []):
            metric_id = metric.get('id', '')
            metric_name = metric.get('name', '')
            
            # ID should be unique - direct mapping
            self._metric_by_id[metric_id.lower()] = metric
            
            # Names/aliases map to lists for ambiguity detection
            self._add_to_list_index(self._metric_by_name, metric_name.lower(), metric)
            self._track_cross_type(metric_name.lower(), 'metric')
            
            # Index by display_name
            display_name = metric.get('display_name', '')
            if display_name:
                self._add_to_list_index(self._metric_by_name, display_name.lower(), metric)
                self._track_cross_type(display_name.lower(), 'metric')
            
            # Index by aliases
            for alias in metric.get('aliases', []):
                self._add_to_list_index(self._metric_by_name, alias.lower(), metric)
                self._track_cross_type(alias.lower(), 'metric')
        
        # Build dimension indexes
        for dimension in self._catalog.get('dimensions', []):
            dim_id = dimension.get('id', '')
            dim_name = dimension.get('name', '')
            
            self._dimension_by_id[dim_id.lower()] = dimension
            
            self._add_to_list_index(self._dimension_by_name, dim_name.lower(), dimension)
            self._track_cross_type(dim_name.lower(), 'dimension')
            
            display_name = dimension.get('display_name', '')
            if display_name:
                self._add_to_list_index(self._dimension_by_name, display_name.lower(), dimension)
                self._track_cross_type(display_name.lower(), 'dimension')
            
            for alias in dimension.get('aliases', []):
                self._add_to_list_index(self._dimension_by_name, alias.lower(), dimension)
                self._track_cross_type(alias.lower(), 'dimension')
        
        # Build time dimension indexes
        for time_dim in self._catalog.get('time_dimensions', []):
            td_id = time_dim.get('id', '')
            td_name = time_dim.get('name', '')
            
            self._time_dimension_by_id[td_id.lower()] = time_dim
            
            self._add_to_list_index(self._time_dimension_by_name, td_name.lower(), time_dim)
            self._track_cross_type(td_name.lower(), 'time_dimension')
            
            display_name = time_dim.get('display_name', '')
            if display_name:
                self._add_to_list_index(self._time_dimension_by_name, display_name.lower(), time_dim)
                self._track_cross_type(display_name.lower(), 'time_dimension')
        
        # Build time window indexes
        for tw in self._catalog.get('time_windows', []):
            tw_id = tw.get('id', '')
            tw_name = tw.get('name', '')
            
            self._add_to_list_index(self._time_window_by_name, tw_id.lower(), tw)
            self._add_to_list_index(self._time_window_by_name, tw_name.lower(), tw)
            
            for alias in tw.get('aliases', []):
                self._add_to_list_index(self._time_window_by_name, alias.lower(), tw)

    def _add_to_list_index(self, index: Dict[str, List[Dict]], key: str, item: Dict) -> None:
        """Add item to a list-based index, avoiding duplicates."""
        if key not in index:
            index[key] = []
        # Avoid adding the same item twice (by id)
        item_id = item.get('id', '')
        if not any(existing.get('id') == item_id for existing in index[key]):
            index[key].append(item)

    def _track_cross_type(self, term: str, item_type: str) -> None:
        """Track which types a term appears in for cross-type collision detection."""
        if term not in self._cross_type_index:
            self._cross_type_index[term] = set()
        self._cross_type_index[term].add(item_type)

    # --------------- AMBIGUITY DETECTION ---------------

    def has_cross_type_collision(self, term: str) -> bool:
        """Check if a term exists in multiple catalog types (metric AND dimension)."""
        key = term.lower()
        types = self._cross_type_index.get(key, set())
        return len(types) > 1

    def get_cross_type_matches(self, term: str) -> Dict[str, List[Dict]]:
        """
        Get all matches for a term across all catalog types.
        
        Returns:
            Dict mapping type name to list of matching items
        """
        key = term.lower()
        result = {}
        
        if key in self._metric_by_name:
            result['metric'] = self._metric_by_name[key]
        if key in self._dimension_by_name:
            result['dimension'] = self._dimension_by_name[key]
        if key in self._time_dimension_by_name:
            result['time_dimension'] = self._time_dimension_by_name[key]
        if key in self._time_window_by_name:
            result['time_window'] = self._time_window_by_name[key]
        
        return result

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

    # --------------- PUBLIC API: Find Methods (returns all matches) ---------------

    def find_metrics(self, term: str) -> List[Dict]:
        """
        Find all metrics matching a term (name, alias, or ID).
        Returns empty list if no matches. Never raises.
        """
        key = term.lower()
        
        # Check by ID first (unique)
        if key in self._metric_by_id:
            return [self._metric_by_id[key]]
        
        # Check by name/alias (may be multiple)
        return self._metric_by_name.get(key, [])

    def find_dimensions(self, term: str) -> List[Dict]:
        """Find all dimensions matching a term. Returns empty list if no matches."""
        key = term.lower()
        
        if key in self._dimension_by_id:
            return [self._dimension_by_id[key]]
        
        return self._dimension_by_name.get(key, [])

    def find_time_dimensions(self, term: str) -> List[Dict]:
        """Find all time dimensions matching a term."""
        key = term.lower()
        
        if key in self._time_dimension_by_id:
            return [self._time_dimension_by_id[key]]
        
        return self._time_dimension_by_name.get(key, [])

    def find_time_windows(self, term: str) -> List[Dict]:
        """Find all time windows matching a term."""
        key = term.lower()
        return self._time_window_by_name.get(key, [])

    # --------------- PUBLIC API: Safe Resolve Methods (returns ResolutionResult) ---------------

    def resolve_metric_safe(self, name: str) -> ResolutionResult:
        """
        Safely resolve a metric, returning a ResolutionResult with ambiguity info.
        Does not raise on ambiguity - caller can decide how to handle.
        """
        matches = self.find_metrics(name)
        
        if len(matches) == 0:
            return ResolutionResult(None, False, [], 'metric')
        elif len(matches) == 1:
            return ResolutionResult(matches[0], False, matches, 'metric')
        else:
            return ResolutionResult(None, True, matches, 'metric')

    def resolve_dimension_safe(self, name: str) -> ResolutionResult:
        """Safely resolve a dimension, returning ResolutionResult with ambiguity info."""
        matches = self.find_dimensions(name)
        
        if len(matches) == 0:
            return ResolutionResult(None, False, [], 'dimension')
        elif len(matches) == 1:
            return ResolutionResult(matches[0], False, matches, 'dimension')
        else:
            return ResolutionResult(None, True, matches, 'dimension')

    def resolve_time_dimension_safe(self, name: str) -> ResolutionResult:
        """Safely resolve a time dimension."""
        matches = self.find_time_dimensions(name)
        
        if len(matches) == 0:
            return ResolutionResult(None, False, [], 'time_dimension')
        elif len(matches) == 1:
            return ResolutionResult(matches[0], False, matches, 'time_dimension')
        else:
            return ResolutionResult(None, True, matches, 'time_dimension')

    def resolve_time_window_safe(self, name: str) -> ResolutionResult:
        """Safely resolve a time window."""
        matches = self.find_time_windows(name)
        
        if len(matches) == 0:
            return ResolutionResult(None, False, [], 'time_window')
        elif len(matches) == 1:
            return ResolutionResult(matches[0], False, matches, 'time_window')
        else:
            return ResolutionResult(None, True, matches, 'time_window')

    # --------------- PUBLIC API: Strict Resolve Methods (raises on ambiguity) ---------------

    def resolve_metric(self, name: str) -> Dict:
        """
        Resolve a metric by name, alias, or ID.
        
        Args:
            name: Metric name, alias, display_name, or ID
            
        Returns:
            The full metric dictionary
            
        Raises:
            CatalogError: If metric not found
            AmbiguousResolutionError: If multiple metrics match
        """
        result = self.resolve_metric_safe(name)
        
        if result.is_ambiguous:
            raise AmbiguousResolutionError(name, result.all_matches, 'metric')
        
        if not result.is_found:
            raise CatalogError(f"Metric '{name}' not found in catalog")
        
        return result.item

    def resolve_dimension(self, name: str) -> Dict:
        """
        Resolve a dimension by name, alias, or ID.
        
        Raises:
            CatalogError: If dimension not found
            AmbiguousResolutionError: If multiple dimensions match
        """
        result = self.resolve_dimension_safe(name)
        
        if result.is_ambiguous:
            raise AmbiguousResolutionError(name, result.all_matches, 'dimension')
        
        if not result.is_found:
            raise CatalogError(f"Dimension '{name}' not found in catalog")
        
        return result.item

    def resolve_time_dimension(self, name: str) -> Dict:
        """
        Resolve a time dimension by name or ID.
        
        Raises:
            CatalogError: If time dimension not found
            AmbiguousResolutionError: If multiple time dimensions match
        """
        result = self.resolve_time_dimension_safe(name)
        
        if result.is_ambiguous:
            raise AmbiguousResolutionError(name, result.all_matches, 'time_dimension')
        
        if not result.is_found:
            raise CatalogError(f"Time dimension '{name}' not found in catalog")
        
        return result.item

    def resolve_time_window(self, name: str) -> Dict:
        """
        Resolve a time window by name, ID, or alias.
        
        Raises:
            CatalogError: If time window not found
            AmbiguousResolutionError: If multiple time windows match
        """
        result = self.resolve_time_window_safe(name)
        
        if result.is_ambiguous:
            raise AmbiguousResolutionError(name, result.all_matches, 'time_window')
        
        if not result.is_found:
            raise CatalogError(f"Time window '{name}' not found in catalog")
        
        return result.item

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
        """
        dimension = self.resolve_dimension(name)
        cube_field = dimension.get('id')
        
        if not cube_field:
            raise CatalogError(f"Dimension '{name}' missing 'id' field for Cube.js mapping")
        
        return cube_field

    def get_time_dimension_cube_field(self, name: str) -> str:
        """
        Get the Cube.js field identifier for a time dimension.
        """
        time_dim = self.resolve_time_dimension(name)
        cube_field = time_dim.get('id')
        
        if not cube_field:
            raise CatalogError(f"Time dimension '{name}' missing 'id' field for Cube.js mapping")
        
        return cube_field

    def get_time_dimension_granularities(self, name: str) -> List[Dict]:
        """
        Get available granularities for a time dimension.
        """
        time_dim = self.resolve_time_dimension(name)
        return time_dim.get('granularities', [])

    # --------------- PUBLIC API: Validation Methods ---------------

    def is_valid_metric(self, name: str) -> bool:
        """Check if a metric name/alias exists in the catalog."""
        return len(self.find_metrics(name)) > 0

    def is_valid_dimension(self, name: str) -> bool:
        """Check if a dimension name/alias exists in the catalog."""
        return len(self.find_dimensions(name)) > 0

    def is_valid_time_dimension(self, name: str) -> bool:
        """Check if a time dimension name/ID exists in the catalog."""
        return len(self.find_time_dimensions(name)) > 0

    def is_valid_time_window(self, name: str) -> bool:
        """Check if a time window name/ID/alias exists in the catalog."""
        return len(self.find_time_windows(name)) > 0

    def is_unambiguous_metric(self, name: str) -> bool:
        """Check if a term resolves to exactly one metric."""
        return len(self.find_metrics(name)) == 1

    def is_unambiguous_dimension(self, name: str) -> bool:
        """Check if a term resolves to exactly one dimension."""
        return len(self.find_dimensions(name)) == 1

    # --------------- PUBLIC API: Business Context Methods ---------------

    def get_dimension_possible_values(self, name: str) -> List[Dict]:
        """
        Get possible values for a dimension (if defined).
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
        """
        query_lower = query.lower()
        results = []
        
        for metric in self._catalog.get('metrics', []):
            if query_lower in metric.get('name', '').lower():
                results.append(metric)
                continue
            if query_lower in metric.get('display_name', '').lower():
                results.append(metric)
                continue
            if query_lower in metric.get('description', '').lower():
                results.append(metric)
                continue
            if any(query_lower in alias.lower() for alias in metric.get('aliases', [])):
                results.append(metric)
                continue
            if any(query_lower in ex.lower() for ex in metric.get('examples', [])):
                results.append(metric)
                continue
        
        return results

    def search_dimensions(self, query: str) -> List[Dict]:
        """
        Search dimensions by name, alias, description, or examples.
        """
        query_lower = query.lower()
        results = []
        
        for dimension in self._catalog.get('dimensions', []):
            if query_lower in dimension.get('name', '').lower():
                results.append(dimension)
                continue
            if query_lower in dimension.get('display_name', '').lower():
                results.append(dimension)
                continue
            if query_lower in dimension.get('description', '').lower():
                results.append(dimension)
                continue
            if any(query_lower in alias.lower() for alias in dimension.get('aliases', [])):
                results.append(dimension)
                continue
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
