"""
Component Selection Strategies for GEPA Optimization.

This module implements intelligent component selection logic for the DSPy
pipeline optimization. It provides performance-based selection, error pattern
analysis, and round-robin strategies with bias toward underperforming components.
"""

import logging
import random
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Set
from collections import defaultdict, Counter
from dataclasses import dataclass

from gepa.proposer.reflective_mutation.base import ReflectionComponentSelector

from .gepa_feedback import get_available_components

logger = logging.getLogger(__name__)

# =============================================================================
# COMPONENT PERFORMANCE TRACKING
# =============================================================================

@dataclass
class ComponentMetrics:
    """Metrics for a specific component."""
    name: str
    scores: List[float]
    error_count: int = 0
    optimization_rounds: int = 0
    last_improvement: float = 0.0
    total_feedback_length: int = 0

    @property
    def average_score(self) -> float:
        """Average score across all evaluations."""
        return sum(self.scores) / len(self.scores) if self.scores else 0.0

    @property
    def score_variance(self) -> float:
        """Variance in scores (higher = less stable)."""
        if len(self.scores) < 2:
            return 0.0
        avg = self.average_score
        return sum((score - avg) ** 2 for score in self.scores) / len(self.scores)

    @property
    def error_rate(self) -> float:
        """Error rate (errors per optimization round)."""
        return self.error_count / max(self.optimization_rounds, 1)

    @property
    def improvement_rate(self) -> float:
        """Rate of improvement per optimization round."""
        return self.last_improvement / max(self.optimization_rounds, 1)

@dataclass
class OptimizationState:
    """State tracking for optimization progress."""
    round_number: int = 0
    component_metrics: Dict[str, ComponentMetrics] = None
    recent_selections: List[str] = None
    global_best_score: float = 0.0
    stagnation_counter: int = 0

    def __post_init__(self):
        if self.component_metrics is None:
            self.component_metrics = {}
        if self.recent_selections is None:
            self.recent_selections = []

# =============================================================================
# BASE COMPONENT SELECTOR
# =============================================================================

class BaseComponentSelector(ReflectionComponentSelector):
    """Base class for component selection strategies."""

    def __init__(self, available_components: Optional[List[str]] = None):
        self.available_components = available_components or get_available_components()
        self.state = OptimizationState()
        self._initialize_metrics()

    def _initialize_metrics(self):
        """Initialize metrics for all components."""
        for component in self.available_components:
            self.state.component_metrics[component] = ComponentMetrics(
                name=component,
                scores=[]
            )

    @abstractmethod
    def select_components(self, **kwargs) -> Set[str]:
        """Select components to optimize in this round."""
        pass

    def update_metrics(self,
                      component_scores: Dict[str, float],
                      component_feedback: Dict[str, str],
                      global_score: float):
        """Update component metrics based on optimization results."""
        self.state.round_number += 1

        for component, score in component_scores.items():
            if component in self.state.component_metrics:
                metrics = self.state.component_metrics[component]
                metrics.scores.append(score)
                metrics.optimization_rounds += 1

                # Update improvement tracking
                if len(metrics.scores) > 1:
                    metrics.last_improvement = score - metrics.scores[-2]

                # Track feedback length as proxy for error complexity
                if component in component_feedback:
                    metrics.total_feedback_length += len(component_feedback[component])

        # Update global tracking
        if global_score > self.state.global_best_score:
            self.state.global_best_score = global_score
            self.state.stagnation_counter = 0
        else:
            self.state.stagnation_counter += 1

# =============================================================================
# PERFORMANCE-BASED SELECTOR
# =============================================================================

class PerformanceBasedSelector(BaseComponentSelector):
    """Selects components based on performance metrics."""

    def __init__(self,
                 available_components: Optional[List[str]] = None,
                 selection_size: int = 1,
                 performance_weight: float = 0.7,
                 variance_weight: float = 0.3):
        super().__init__(available_components)
        self.selection_size = selection_size
        self.performance_weight = performance_weight
        self.variance_weight = variance_weight

    def select_components(self, **kwargs) -> Set[str]:
        """Select components with lowest performance scores."""
        if self.state.round_number < len(self.available_components):
            # First round: ensure each component gets evaluated once
            return {self.available_components[self.state.round_number]}

        # Calculate composite score for each component
        component_priorities = {}

        for name, metrics in self.state.component_metrics.items():
            if not metrics.scores:
                # Never evaluated - high priority
                component_priorities[name] = float('inf')
                continue

            # Lower performance score = higher priority
            performance_priority = 1.0 - metrics.average_score

            # Higher variance = higher priority (unstable components need attention)
            variance_priority = metrics.score_variance

            # Combine priorities
            total_priority = (
                performance_priority * self.performance_weight +
                variance_priority * self.variance_weight
            )

            component_priorities[name] = total_priority

        # Select top components by priority
        sorted_components = sorted(
            component_priorities.items(),
            key=lambda x: x[1],
            reverse=True
        )

        selected = {comp[0] for comp in sorted_components[:self.selection_size]}
        logger.info(f"[PerformanceBasedSelector] Selected components: {selected}")
        logger.debug(f"Component priorities: {component_priorities}")

        return selected

# =============================================================================
# ERROR PATTERN-BASED SELECTOR
# =============================================================================

class ErrorPatternSelector(BaseComponentSelector):
    """Selects components based on error patterns and feedback analysis."""

    def __init__(self,
                 available_components: Optional[List[str]] = None,
                 selection_size: int = 1,
                 error_keywords: Optional[Dict[str, List[str]]] = None):
        super().__init__(available_components)
        self.selection_size = selection_size
        self.error_keywords = error_keywords or self._get_default_error_keywords()
        self.error_pattern_counts = defaultdict(int)

    def _get_default_error_keywords(self) -> Dict[str, List[str]]:
        """Default error keywords for each component."""
        return {
            'classifier': ['intent', 'classification', 'term', 'role', 'mismatch'],
            'scope': ['scope', 'primary', 'secondary'],
            'time': ['time', 'window', 'date', 'granularity', 'constraint'],
            'metrics': ['metric', 'catalog', 'invalid', 'selection'],
            'dimensions': ['dimension', 'group_by', 'filter', 'constraint', 'invalid']
        }

    def select_components(self, **kwargs) -> Set[str]:
        """Select components with most error patterns."""
        feedback_text = kwargs.get('recent_feedback', {})

        # Analyze error patterns in recent feedback
        if feedback_text:
            self._analyze_error_patterns(feedback_text)

        # Calculate error-based priorities
        component_priorities = {}

        for name, metrics in self.state.component_metrics.items():
            priority = 0.0

            # Error rate priority
            priority += metrics.error_rate * 10

            # Pattern-based priority
            for keyword in self.error_keywords.get(name, []):
                priority += self.error_pattern_counts[keyword]

            # Recency bias for recent errors
            if len(metrics.scores) > 0 and metrics.scores[-1] < 0.5:
                priority += 5.0  # Boost priority for recent poor performance

            component_priorities[name] = priority

        # Select top components
        sorted_components = sorted(
            component_priorities.items(),
            key=lambda x: x[1],
            reverse=True
        )

        # Ensure we don't select the same component repeatedly if others need attention
        selected = set()
        for comp, _ in sorted_components:
            if len(selected) >= self.selection_size:
                break
            if comp not in self.state.recent_selections[-3:]:  # Avoid recent selections
                selected.add(comp)

        # If we couldn't avoid recent selections, just take the top ones
        if not selected:
            selected = {comp[0] for comp in sorted_components[:self.selection_size]}

        logger.info(f"[ErrorPatternSelector] Selected components: {selected}")
        logger.debug(f"Error priorities: {component_priorities}")

        return selected

    def _analyze_error_patterns(self, feedback: Dict[str, str]):
        """Analyze feedback text for error patterns."""
        for component, text in feedback.items():
            text_lower = text.lower()

            # Count keyword occurrences
            for keyword in self.error_keywords.get(component, []):
                if keyword in text_lower:
                    self.error_pattern_counts[keyword] += 1

            # Look for specific error indicators
            if 'error' in text_lower or 'failed' in text_lower:
                self.state.component_metrics[component].error_count += 1

# =============================================================================
# ROUND-ROBIN WITH BIAS
# =============================================================================

class BiasedRoundRobinSelector(BaseComponentSelector):
    """Round-robin selection with bias toward underperforming components."""

    def __init__(self,
                 available_components: Optional[List[str]] = None,
                 bias_factor: float = 2.0,
                 min_rounds_per_component: int = 2):
        super().__init__(available_components)
        self.bias_factor = bias_factor
        self.min_rounds_per_component = min_rounds_per_component
        self.component_weights = {comp: 1.0 for comp in self.available_components}
        self.last_selected = None

    def select_components(self, **kwargs) -> Set[str]:
        """Select component using weighted round-robin."""
        self._update_weights()

        # Create weighted selection pool
        weighted_pool = []
        for component in self.available_components:
            # Skip the last selected component to ensure rotation
            if component == self.last_selected and len(self.available_components) > 1:
                continue

            weight = self.component_weights[component]
            # Add component multiple times based on weight
            weighted_pool.extend([component] * max(1, int(weight * 10)))

        # Random selection from weighted pool
        if weighted_pool:
            selected_component = random.choice(weighted_pool)
        else:
            # Fallback: select randomly
            selected_component = random.choice(self.available_components)

        self.last_selected = selected_component

        logger.info(f"[BiasedRoundRobinSelector] Selected component: {selected_component}")
        logger.debug(f"Component weights: {self.component_weights}")

        return {selected_component}

    def _update_weights(self):
        """Update component weights based on performance."""
        for name, metrics in self.state.component_metrics.items():
            base_weight = 1.0

            # Increase weight for poor performers
            if metrics.scores:
                avg_score = metrics.average_score
                if avg_score < 0.7:  # Poor performance threshold
                    base_weight *= self.bias_factor
                elif avg_score > 0.9:  # Good performance - reduce weight
                    base_weight /= self.bias_factor

            # Ensure minimum attention for all components
            if metrics.optimization_rounds < self.min_rounds_per_component:
                base_weight *= 1.5

            self.component_weights[name] = base_weight

# =============================================================================
# ADAPTIVE SELECTOR (LLM-DRIVEN)
# =============================================================================

class AdaptiveSelector(BaseComponentSelector):
    """LLM-driven adaptive component selector."""

    def __init__(self,
                 available_components: Optional[List[str]] = None,
                 selection_lm: Optional[Any] = None):
        super().__init__(available_components)
        self.selection_lm = selection_lm
        self.selection_history = []

    def select_components(self, **kwargs) -> Set[str]:
        """Use LLM to select components based on optimization trajectory."""
        if not self.selection_lm:
            # Fallback to performance-based selection
            logger.warning("No selection LM provided, falling back to performance-based selection")
            fallback_selector = PerformanceBasedSelector(self.available_components)
            fallback_selector.state = self.state
            return fallback_selector.select_components(**kwargs)

        # Prepare context for LLM
        context = self._prepare_selection_context()

        try:
            # Query LLM for component selection
            prompt = self._create_selection_prompt(context)
            response = self.selection_lm(prompt)

            # Parse response
            selected = self._parse_selection_response(response)

            logger.info(f"[AdaptiveSelector] LLM selected components: {selected}")
            return selected

        except Exception as e:
            logger.error(f"LLM selection failed: {e}")
            # Fallback to performance-based selection
            fallback_selector = PerformanceBasedSelector(self.available_components)
            fallback_selector.state = self.state
            return fallback_selector.select_components(**kwargs)

    def _prepare_selection_context(self) -> Dict[str, Any]:
        """Prepare context information for LLM selection."""
        context = {
            'round_number': self.state.round_number,
            'available_components': self.available_components,
            'component_performance': {},
            'recent_selections': self.state.recent_selections[-5:],
            'stagnation_rounds': self.state.stagnation_counter
        }

        for name, metrics in self.state.component_metrics.items():
            context['component_performance'][name] = {
                'average_score': metrics.average_score,
                'optimization_rounds': metrics.optimization_rounds,
                'error_rate': metrics.error_rate,
                'last_improvement': metrics.last_improvement
            }

        return context

    def _create_selection_prompt(self, context: Dict[str, Any]) -> str:
        """Create prompt for LLM component selection."""
        prompt = f"""
You are helping optimize a natural language to SQL intent extraction pipeline.
The pipeline has these components: {', '.join(context['available_components'])}.

Current optimization state:
- Round number: {context['round_number']}
- Recent selections: {context['recent_selections']}
- Rounds without improvement: {context['stagnation_rounds']}

Component Performance:
"""

        for comp, perf in context['component_performance'].items():
            prompt += f"""
{comp}:
  - Average score: {perf['average_score']:.3f}
  - Optimization rounds: {perf['optimization_rounds']}
  - Error rate: {perf['error_rate']:.3f}
  - Last improvement: {perf['last_improvement']:.3f}"""

        prompt += """

Based on this information, which component(s) should be optimized next?
Consider:
1. Components with lowest performance scores
2. Components that haven't been optimized recently
3. Components with high error rates
4. Avoiding recent selections unless necessary

Return ONLY the component name(s), separated by commas if multiple.
Example: "classifier" or "metrics, dimensions"
"""

        return prompt

    def _parse_selection_response(self, response: str) -> Set[str]:
        """Parse LLM response to extract selected components."""
        # Clean and split response
        components = [comp.strip().lower() for comp in response.split(',')]

        # Filter to valid components
        valid_components = {comp for comp in components
                          if comp in self.available_components}

        if not valid_components:
            # Fallback: select lowest performing component
            worst_component = min(
                self.state.component_metrics.items(),
                key=lambda x: x[1].average_score
            )[0]
            valid_components = {worst_component}

        return valid_components

# =============================================================================
# SELECTOR FACTORY
# =============================================================================

class ComponentSelectorFactory:
    """Factory for creating component selectors."""

    _selectors = {
        'performance': PerformanceBasedSelector,
        'error_pattern': ErrorPatternSelector,
        'round_robin': BiasedRoundRobinSelector,
        'adaptive': AdaptiveSelector,
    }

    @classmethod
    def create_selector(cls,
                       strategy: str,
                       available_components: Optional[List[str]] = None,
                       **kwargs) -> BaseComponentSelector:
        """
        Create a component selector.

        Args:
            strategy: Selection strategy ('performance', 'error_pattern', 'round_robin', 'adaptive')
            available_components: Available components to select from
            **kwargs: Additional arguments for selector

        Returns:
            Component selector instance
        """
        if strategy not in cls._selectors:
            raise ValueError(f"Unknown selector strategy: {strategy}. "
                           f"Available: {list(cls._selectors.keys())}")

        selector_class = cls._selectors[strategy]
        return selector_class(available_components=available_components, **kwargs)

    @classmethod
    def get_available_strategies(cls) -> List[str]:
        """Get list of available selection strategies."""
        return list(cls._selectors.keys())

# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_intelligent_selector(strategy: str = 'performance',
                               **kwargs) -> BaseComponentSelector:
    """
    Create an intelligent component selector with default settings.

    Args:
        strategy: Selection strategy to use
        **kwargs: Additional configuration

    Returns:
        Configured component selector
    """
    return ComponentSelectorFactory.create_selector(strategy, **kwargs)

def create_hybrid_selector(primary_strategy: str = 'performance',
                          fallback_strategy: str = 'round_robin') -> BaseComponentSelector:
    """
    Create a hybrid selector that combines multiple strategies.

    This is a simplified implementation - a full hybrid would switch between
    strategies based on optimization progress.
    """
    # For now, return the primary strategy
    # TODO: Implement actual hybrid logic
    return create_intelligent_selector(primary_strategy)