from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any


@dataclass
class CompoundQueryProgress:
    """Tracks progress of compound query processing"""
    decomposed_queries: List[str] = field(default_factory=list)
    completed_indices: List[int] = field(default_factory=list)
    pending_index: Optional[int] = None
    completed_results: List[Dict[str, Any]] = field(default_factory=list)
    dependencies: Dict[int, List[int]] = field(default_factory=dict)  # index -> list of indices it depends on


@dataclass
class PipelineState:
    request_id: str
    original_query: str
    intent: dict
    missing_fields: list[str]
    session_id: Optional[str] = None
    # Track resolved clarifications to prevent infinite loops
    resolved_clarifications: Optional[Dict[str, str]] = None
    # Compound query state tracking
    compound_query_state: Optional[CompoundQueryProgress] = None
    # Index of sub-query currently requiring clarification
    pending_subquery_index: Optional[int] = None
    # Results of completed sub-queries
    completed_subquery_results: List[Dict[str, Any]] = field(default_factory=list)

    def is_compound_query(self) -> bool:
        """Check if this is a compound query"""
        return self.compound_query_state is not None

    def get_next_pending_subquery_index(self) -> Optional[int]:
        """Get the next sub-query that needs processing"""
        if not self.is_compound_query():
            return None

        compound_state = self.compound_query_state
        total_queries = len(compound_state.decomposed_queries)

        for i in range(total_queries):
            if i not in compound_state.completed_indices:
                # Check if dependencies are satisfied
                dependencies = compound_state.dependencies.get(i, [])
                if all(dep_idx in compound_state.completed_indices for dep_idx in dependencies):
                    return i
        return None

    def mark_subquery_completed(self, index: int, result: Dict[str, Any]):
        """Mark a sub-query as completed and store its result"""
        if not self.is_compound_query():
            return

        if index not in self.compound_query_state.completed_indices:
            self.compound_query_state.completed_indices.append(index)
            # Ensure the completed_results list is large enough
            while len(self.completed_subquery_results) <= index:
                self.completed_subquery_results.append({})
            self.completed_subquery_results[index] = result

    def is_compound_query_complete(self) -> bool:
        """Check if all sub-queries in compound query are completed"""
        if not self.is_compound_query():
            return True

        compound_state = self.compound_query_state
        total_queries = len(compound_state.decomposed_queries)
        return len(compound_state.completed_indices) == total_queries
