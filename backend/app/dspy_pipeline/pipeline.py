import dspy
import logging
import time
from datetime import date
from typing import Optional, Union, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

from .modules import (
    QueryDecomposerModule,
    ClassifierModule,
    ScopeModule,
    TimeModule,
    MetricsModule,
    DimensionsModule,
    PostProcessingModule,
    AssemblerModule,
)
from .clarification_tool import ClarificationRequired, MultipleClarificationsRequired
from .schemas import Intent, DecomposedQuery
from app.services.drill_detector import DrillResult, detect_drill


# =============================================================================
# THREAD LOCAL PIPELINE STATE (FOR QCO RESOLVER)
# =============================================================================
import threading

_pipeline_state = threading.local()

def get_stored_agent_results() -> Optional[Dict[str, Any]]:
    return getattr(_pipeline_state, 'agent_results', None)

def clear_stored_agent_results() -> None:
    if hasattr(_pipeline_state, 'agent_results'):
        del _pipeline_state.agent_results

def store_agent_results(results: Dict[str, Any]) -> None:
    _pipeline_state.agent_results = results

# =============================================================================
# CONTEXT INJECTION MANAGER
# =============================================================================

class ContextInjectingPipelineManager:
    """
    Manages selective execution of pipeline agents based on drill patterns.

    Only re-executes agents that need fresh results based on context injection
    and drill detection, using cached results from QCO for agents that don't
    need re-execution.

    FIX: No longer instantiates its own module copies. Receives module
    references from IntentExtractionPipeline to avoid duplicate instances
    and ensure compiled/optimized weights are shared correctly.
    """

    MAX_CACHE_STALENESS = 3

    def __init__(self, scope, time, metrics, dimensions):
        # FIX (Problem 1): Accept module references instead of instantiating
        # new copies. This ensures the pipeline and manager share the same
        # DSPy module instances — critical for optimization and compilation.
        self.scope = scope
        self.time = time
        self.metrics = metrics
        self.dimensions = dimensions

    def execute_with_plan(
        self,
        classified_query,
        previous_qco,
        plan,
        overrides,
        current_date=None
    ) -> Dict[str, Any]:

        agents_to_run = plan["run"]
        logger.info(f"[Planner] Agents to run: {agents_to_run}")

        results = {}

        # --- REUSE FROM CACHE ---
        if previous_qco:
            if "scope" not in agents_to_run and previous_qco.cached_scope_result:
                results["scope"] = self._restore("scope", previous_qco)

            if "time" not in agents_to_run and previous_qco.cached_time_result:
                results["time"] = self._restore("time", previous_qco)

            if "metrics" not in agents_to_run and previous_qco.cached_metrics_result:
                results["metrics"] = self._restore("metrics", previous_qco)

            if "dimensions" not in agents_to_run and previous_qco.cached_dimensions_result:
                results["dimensions"] = self._restore("dimensions", previous_qco)

        # --- RUN REQUIRED AGENTS ---
        fresh = self._execute_selective_agents(
            classified_query,
            agents_to_run,
            previous_qco,
            overrides,
            current_date
        )

        results.update(fresh)

        return results

    def _restore(self, agent_name, qco):
        try:
            if agent_name == "scope":
                from .schemas import ScopeResult
                return ScopeResult(**qco.cached_scope_result)

            if agent_name == "time":
                from .schemas import TimeResult
                return TimeResult(**qco.cached_time_result)

            if agent_name == "metrics":
                from .schemas import MetricsResult
                return MetricsResult(**qco.cached_metrics_result)

            if agent_name == "dimensions":
                from .schemas import DimensionsResult
                return DimensionsResult(**qco.cached_dimensions_result)

        except Exception as e:
            logger.warning(f"Failed restoring {agent_name}: {e}")
            return None


    def _determine_required_agents(self, drill_result, classified_query, previous_qco) -> List[str]:
        """Determine which agents need re-execution based on drill/drift type."""

        # Fresh query — run all agents
        if not previous_qco:
            return ['scope', 'time', 'metrics', 'dimensions']

        # Intent type changed — re-run all agents
        if classified_query.query_intent != previous_qco.intent_type:
            logger.info(
                f"[Context Injection] Intent changed: "
                f"{previous_qco.intent_type} -> {classified_query.query_intent}"
            )
            return ['scope', 'time', 'metrics', 'dimensions']

        # Drill-specific execution patterns
        if drill_result.case == "dimension_drill":
            logger.info("[Context Injection] Dimension drill — only dimensions needed")
            return ['dimensions']

        elif drill_result.case == "value_drill":
            logger.info("[Context Injection] Value drill — only dimensions needed")
            return ['dimensions']

        elif drill_result.case == "cross_axis":
            logger.info("[Context Injection] Cross-axis drill — only dimensions needed")
            return ['dimensions']

        elif drill_result.case == "time_change":
            logger.info("[Context Injection] Time change — only time needed")
            return ['time']

        # Fall through: detect other changes
        changes = self._detect_other_changes(classified_query, previous_qco)
        agents_needed = []

        if changes.get('new_filters'):
            agents_needed.append('dimensions')
        if changes.get('scope_hints'):
            agents_needed.append('scope')
        if changes.get('metric_changes'):
            agents_needed.extend(['scope', 'metrics'])
        if changes.get('time_hints'):
            agents_needed.append('time')

        result = list(set(agents_needed)) if agents_needed else []

        if not result:
            logger.info("[Context Injection] No changes detected — using fully cached results")

        return result

    def _detect_other_changes(self, classified_query, previous_qco) -> Dict[str, bool]:
        """
        Detect changes that require agent re-execution.

        FIX (Problem 2): Metric change detection now compares resolved catalog
        names from classified_query.metric_hints (normalized by the classifier)
        against previous_qco.metrics, NOT raw user terms. Raw terms like "rev"
        or "sales" will never equal catalog names like "net_value", causing
        metric_changes=True on every follow-up query and forcing unnecessary
        metrics agent re-runs with broken carry-forward context.
        """
        changes = {}

        # Filter change: compare current filter hints against previous resolved filters
        current_filters = {
            fh.dimension: fh.value
            for fh in (classified_query.filter_hints or [])
        }
        previous_filters = {
            f.dimension: f.value
            for f in (previous_qco.filters or [])
        }
        if current_filters != previous_filters:
            changes['new_filters'] = True

        # Scope change: only flag if classifier explicitly resolved a scope
        # and it differs from the previous scope
        if (
            classified_query.explicit_scope
            and classified_query.explicit_scope != previous_qco.sales_scope
        ):
            changes['scope_hints'] = True

        # FIX (Problem 2): Compare classifier's normalized metric hints
        # (already mapped toward catalog names) against previous resolved metrics.
        # Fall back to empty list safely if metric_hints is not present on
        # the classified_query object (backward compatibility).
        current_metric_hints = getattr(classified_query, 'metric_hints', None) or []
        previous_metric_names = {m.name for m in previous_qco.metrics}

        # Only flag metric_changes if the classifier surfaced explicit metric
        # hints that don't overlap with previous resolved metrics at all.
        # Partial overlap (adding a metric) still triggers re-run.
        # No hints (pure follow-up like "now show by brand") does not trigger.
        if current_metric_hints:
            hint_set = set(h.lower().replace(' ', '_') for h in current_metric_hints)
            if not hint_set.intersection(previous_metric_names):
                changes['metric_changes'] = True

        # Time change: only flag if the query contains new explicit time terms
        # AND the previous query had a time range (i.e. this isn't a first-time
        # time specification which would be covered by fresh query logic)
        current_time_terms = [
            t.term for t in (classified_query.classified_terms or [])
            if t.role in ("TIME_RANGE", "TIME_GRANULARITY")
        ]
        if current_time_terms and previous_qco.time_range:
            changes['time_hints'] = True

        return changes

    def _load_cached_agent_results(self, previous_qco, agents_to_run) -> Dict[str, Any]:
        """Load cached results for agents that don't need re-execution."""
        results = {}

        if not previous_qco:
            return results

        if 'scope' not in agents_to_run and getattr(previous_qco, 'cached_scope_result', None):
            if self._is_cache_valid('scope', previous_qco):
                from .schemas import ScopeResult
                try:
                    results['scope'] = ScopeResult(**previous_qco.cached_scope_result)
                except Exception as e:
                    logger.warning(f"[Context Injection] Failed to restore cached scope: {e}")

        if 'time' not in agents_to_run and getattr(previous_qco, 'cached_time_result', None):
            if self._is_cache_valid('time', previous_qco):
                from .schemas import TimeResult
                try:
                    results['time'] = TimeResult(**previous_qco.cached_time_result)
                except Exception as e:
                    logger.warning(f"[Context Injection] Failed to restore cached time: {e}")

        if 'metrics' not in agents_to_run and getattr(previous_qco, 'cached_metrics_result', None):
            if self._is_cache_valid('metrics', previous_qco):
                from .schemas import MetricsResult
                try:
                    results['metrics'] = MetricsResult(**previous_qco.cached_metrics_result)
                except Exception as e:
                    logger.warning(f"[Context Injection] Failed to restore cached metrics: {e}")

        if 'dimensions' not in agents_to_run and getattr(previous_qco, 'cached_dimensions_result', None):
            if self._is_cache_valid('dimensions', previous_qco):
                from .schemas import DimensionsResult
                try:
                    results['dimensions'] = DimensionsResult(**previous_qco.cached_dimensions_result)
                except Exception as e:
                    logger.warning(f"[Context Injection] Failed to restore cached dimensions: {e}")

        return results

    def _is_cache_valid(self, agent_name: str, previous_qco) -> bool:
        """Check if a cached agent result is still valid using slot metadata."""
        slot_metadata = getattr(previous_qco, 'slot_metadata', {}) or {}

        if agent_name not in slot_metadata:
            return False

        slot_meta = slot_metadata[agent_name]
        current_turn = getattr(previous_qco, 'turn_index', 0)

        staleness = current_turn - slot_meta.turn
        if staleness > self.MAX_CACHE_STALENESS:
            logger.info(f"[Context Injection] Cache for '{agent_name}' is stale (age: {staleness} turns)")
            return False

        if slot_meta.source == "tombstone":
            logger.info(f"[Context Injection] Cache for '{agent_name}' is tombstoned")
            return False

        return True

    def _execute_selective_agents(
        self,
        classified_query,
        agents_to_run: List[str],
        previous_qco,
        overrides: dict,
        current_date
    ) -> Dict[str, Any]:
        """Execute only the specified agents sequentially and return results."""
        results = {}

        # Determine current scope: use previous QCO scope if scope isn't being re-run
        current_scope = None
        if previous_qco and 'scope' not in agents_to_run:
            current_scope = previous_qco.sales_scope

        if 'scope' in agents_to_run:
            logger.info("[Context Injection] Executing ScopeModule")
            scope_result = self.scope(classified_query=classified_query, overrides=overrides)
            results['scope'] = scope_result
            current_scope = scope_result.sales_scope

        if 'time' in agents_to_run:
            logger.info("[Context Injection] Executing TimeModule")
            results['time'] = self.time(
                classified_query=classified_query,
                current_date=current_date or date.today(),
                previous_context=previous_qco.model_dump(mode='json') if previous_qco else None,
                overrides=overrides,
            )

        if 'metrics' in agents_to_run:
            logger.info("[Context Injection] Executing MetricsModule")
            results['metrics'] = self.metrics(
                classified_query=classified_query,
                sales_scope=current_scope or "SECONDARY",
                overrides=overrides,
            )

        if 'dimensions' in agents_to_run:
            logger.info("[Context Injection] Executing DimensionsModule")
            results['dimensions'] = self.dimensions(
                classified_query=classified_query,
                sales_scope=current_scope or "SECONDARY",
                previous_context=previous_qco.model_dump(mode='json') if previous_qco else None,
                overrides=overrides,
            )

        return results

    def _handle_scope_change_propagation(
        self,
        results: Dict[str, Any],
        classified_query,
        overrides: dict
    ) -> Dict[str, Any]:
        """
        Re-run dimensions when scope changed but dimensions wasn't in agents_to_run.
        Scope determines which dimensions are valid — a scope change invalidates
        the cached dimensions result even if the dimensions themselves didn't change.
        """
        if 'scope' in results:
            logger.info("[Context Injection] Scope changed — re-running DimensionsModule for scope validation")
            results['dimensions'] = self.dimensions(
                classified_query=classified_query,
                sales_scope=results['scope'].sales_scope,
                previous_context=None,
                overrides=overrides,
            )
        return results



# =============================================================================
# MAIN PIPELINE
# =============================================================================

class IntentExtractionPipeline(dspy.Module):
    """
    Orchestrates the full NL → Intent pipeline with compound query support.

    Flow:
        0. Query Decomposer  — split compound queries into sub-queries
        1. Classifier        — determine intent type and extract term hints
        2. Context Injection — selective agent execution based on drill detection
           2a. Scope
           2b. Time
           2c. Metrics
           2d. Dimensions
        3. Post Processing   — ranking, comparison, aggregation config
        4. Assembly          — combine all agent outputs into unified Intent
        5. Final Validation  — Pydantic Intent.model_validate()

    For compound queries, each sub-query runs steps 1–5 sequentially.
    Clarification from any sub-query suspends the entire pipeline immediately.
    """

    def __init__(self):
        super().__init__()
        self.decomposer = QueryDecomposerModule()
        self.classifier = ClassifierModule()

        # FIX (Problem 1): Instantiate modules once here only.
        # ContextInjectingPipelineManager receives references — no duplicate instances.
        self.scope = ScopeModule()
        self.time = TimeModule()
        self.metrics = MetricsModule()
        self.dimensions = DimensionsModule()
        self.post_processing = PostProcessingModule()
        self.assembler = AssemblerModule()

        self.context_manager = ContextInjectingPipelineManager(
            scope=self.scope,
            time=self.time,
            metrics=self.metrics,
            dimensions=self.dimensions,
        )

    def forward(
        self,
        query: str,
        current_date: Optional[date] = None,
        previous_context: Optional[Union[dict, Any]] = None,
        overrides: Optional[dict] = None,
    ) -> Union[Intent, Dict[str, Any]]:
        """
        Process a query through the full pipeline.

        Returns:
            Intent: for single queries
            Dict:   for compound queries with structure:
                        {
                            "type": "compound_query_results",
                            "original_query": str,
                            "total_subqueries": int,
                            "completed_subqueries": [...],
                            "pending_subqueries": [...],
                            "dependencies": {...}
                        }

        Raises:
            ClarificationRequired: for both single and compound queries
                that require user clarification before proceeding.
        """
        overrides = overrides or {}
        logger.info("[DSPy Pipeline] Starting intent extraction pipeline")
        pipeline_start = time.monotonic()

        # -------------------------
        # 0. Query Decomposition
        # -------------------------
        logger.info("[DSPy Pipeline] [0/5] Executing Query Decomposer")
        step_start = time.monotonic()
        decomposed = self.decomposer(query=query, previous_context=previous_context)
        logger.info(
            "[DSPy Pipeline] [0/5] Decomposer completed in %dms | compound=%s | sub_queries=%d",
            int((time.monotonic() - step_start) * 1000),
            decomposed.is_compound,
            len(decomposed.sub_queries),
        )

        if not decomposed.is_compound:
            logger.info("[DSPy Pipeline] Single query path")
            return self._process_single_query(
                decomposed.sub_queries[0].text,
                current_date,
                previous_context,
                overrides,
            )

        logger.info(
            "[DSPy Pipeline] Compound query path — %d sub-queries",
            len(decomposed.sub_queries),
        )
        return self._process_compound_query(decomposed, current_date, previous_context, overrides)

    # -------------------------------------------------------------------------
    # SHARED HELPERS
    # -------------------------------------------------------------------------

    def _resolve_previous_context(self, previous_context) -> Tuple[Any, Optional[str]]:
        """
        FIX (Problem 4): Single canonical method for resolving previous_context
        into a (qco_object, context_str) tuple.

        Previously this 15-line block was duplicated identically in both
        _process_single_query and _process_compound_query. Any future change
        to QCO resolution logic now only needs to happen in one place.
        """
        if not previous_context:
            return None, None

        if hasattr(previous_context, 'to_prompt_context'):
            # Already a QCO object
            return previous_context, previous_context.to_prompt_context()

        if isinstance(previous_context, dict):
            try:
                from app.models.qco import QueryContextObject
                qco = QueryContextObject(**previous_context)
                return qco, qco.to_prompt_context()
            except Exception as e:
                logger.warning(f"[DSPy Pipeline] Failed to convert dict to QCO: {e}")
                return None, str(previous_context)

        # Legacy string format
        return None, str(previous_context)

    def plan_changes(self, classified_query, previous_qco):
        """
        Decide which agents to run vs reuse from previous QCO.
        This is PRE-EXTRACTION logic.
        """

        if not previous_qco:
            return {
                "run": ["scope", "time", "metrics", "dimensions"],
                "reuse": []
            }

        run = []
        reuse = []

        # --- METRIC ---
        metric_terms = [
            t.term for t in (classified_query.classified_terms or [])
            if t.role == "METRIC"
        ]

        if metric_terms:
            run.append("metrics")
        else:
            reuse.append("metrics")

        # --- DIMENSIONS ---
        dim_terms = [
            t.term for t in (classified_query.classified_terms or [])
            if t.role == "DIMENSION"
        ]

        if dim_terms:
            run.append("dimensions")
        else:
            reuse.append("dimensions")

        # --- TIME ---
        time_terms = [
            t.term for t in (classified_query.classified_terms or [])
            if t.role in ("TIME_RANGE", "TIME_GRANULARITY")
        ]

        if time_terms:
            run.append("time")
        else:
            reuse.append("time")

        # --- SCOPE ---
        if classified_query.explicit_scope:
            run.append("scope")
        else:
            reuse.append("scope")

        return {
            "run": list(set(run)),
            "reuse": list(set(reuse))
        }

    def _run_extraction_stages(
        self,
        query_text: str,
        current_date: Optional[date],
        previous_qco,
        overrides: dict,
    ) -> Intent:
        """
        Run stages 1–5 (classify → context injection → post-processing →
        assembly → validation) for a single resolved query text.

        Extracted as a shared helper so both _process_single_query and
        _process_compound_query use identical logic without duplication.

        Raises:
            ClarificationRequired: propagated directly from any agent.
        """

        # -------------------------
        # 1. Classify
        # -------------------------
        logger.info("[DSPy Pipeline] [1/5] Executing Classifier")
        step_start = time.monotonic()
        classified_query = self.classifier(query=query_text, session_context=previous_qco)
        logger.info(
            "[DSPy Pipeline] [1/5] Classifier completed in %dms | intent=%s",
            int((time.monotonic() - step_start) * 1000),
            classified_query,
        )

        # -------------------------
        # 2. Change Planning
        # -------------------------

        plan = self.plan_changes(classified_query, previous_qco)
        
        logger.info(
            "[DSPy Pipeline] [2/5] Context injection completed in %dms",
            int((time.monotonic() - step_start) * 1000),
        )

        # -------------------------
        # 3. Selective Extraction
        # -------------------------
        agent_results = self.context_manager.execute_with_plan(
            classified_query,
            previous_qco,
            plan,
            overrides,
            current_date
        )
        
        # Store agent results for QCO integration later
        store_agent_results(agent_results)

        # -------------------------
        # 4. Build Normalized Intent
        # -------------------------
        normalized_intent = self._build_normalized_intent(agent_results)

        # -------------------------
        # 5. Drill Detection (NOW CORRECT)
        # -------------------------
        drill_result = self._detect_drill(normalized_intent, previous_qco)

        logger.info(f"[DSPy Pipeline] Drill detected: {drill_result.case}")

        # -------------------------
        # 3. Post Processing
        # -------------------------
        logger.info("[DSPy Pipeline] [3/5] Executing Post Processing")
        step_start = time.monotonic()
        post_processing_result = self.post_processing(
            classified_query=classified_query,
            time_result=agent_results.get('time'),
            dimensions_result=agent_results.get('dimensions'),
        )
        logger.info(
            "[DSPy Pipeline] [3/5] Post Processing completed in %dms | output=%s",
            int((time.monotonic() - step_start) * 1000),
            post_processing_result.model_dump_json()
            if hasattr(post_processing_result, "model_dump_json") else str(post_processing_result),
        )

        # -------------------------
        # 4. Assembly
        # -------------------------
        logger.info("[DSPy Pipeline] [4/5] Executing Assembler")
        step_start = time.monotonic()
        intent = self.assembler.forward(
            classified_query=classified_query,
            scope_result=agent_results.get('scope'),
            time_result=agent_results.get('time'),
            metrics_result=agent_results.get('metrics'),
            dimensions_result=agent_results.get('dimensions'),
            post_processing_result=post_processing_result,
        )
        logger.info(
            "[DSPy Pipeline] [4/5] Assembly completed in %dms | output=%s",
            int((time.monotonic() - step_start) * 1000),
            intent.model_dump_json() if hasattr(intent, "model_dump_json") else str(intent),
        )

        # -------------------------
        # 5. Final Validation
        # -------------------------
        logger.info("[DSPy Pipeline] [5/5] Executing Final Validation")
        step_start = time.monotonic()
        intent = Intent.model_validate(intent)
        logger.info(
            "[DSPy Pipeline] [5/5] Validation completed in %dms | output=%s",
            int((time.monotonic() - step_start) * 1000),
            intent.model_dump_json() if hasattr(intent, "model_dump_json") else str(intent),
        )

        return intent

    def _detect_drill(self, intent_dict, previous_qco):
        """
        Detect drill patterns against the previous QCO.
        Returns a DrillResult(case="none") if no previous QCO or detection fails.
        Isolated here to avoid the repeated try/except import block in both
        _process_single_query and _process_compound_query.
        """


        if not previous_qco:
            return DrillResult(case="none")

        try:
            result = detect_drill(intent_dict, previous_qco)
            logger.info(f"[DSPy Pipeline] Drill detection result: {result.case}")
            return result
        except Exception as e:
            logger.warning(f"[DSPy Pipeline] Drill detection failed: {e}")
            return DrillResult(case="none")

    def _build_normalized_intent(self, agent_results):

        metrics_result = agent_results.get("metrics")
        dimensions_result = agent_results.get("dimensions")
        time_result = agent_results.get("time")

        return {
            "metrics": [
                m.name for m in (metrics_result.metrics or [])
            ] if metrics_result and getattr(metrics_result, "metrics", None) else [],

            "group_by": (
                dimensions_result.group_by
                if dimensions_result and dimensions_result.group_by
                else []
            ),

            "filters": [
                {
                    "dimension": f.dimension,
                    "operator": f.operator,
                    "value": f.value
                }
                for f in (dimensions_result.filters or [])
            ] if dimensions_result and dimensions_result.filters else [],

            "time": (
                time_result.time_range
                if time_result and getattr(time_result, "time_range", None)
                else None
            )
        }

    # -------------------------------------------------------------------------
    # SINGLE QUERY PATH
    # -------------------------------------------------------------------------

    def _process_single_query(
        self,
        query_text: str,
        current_date: Optional[date],
        previous_context,
        overrides: dict,
    ) -> Intent:
        """
        Process a single (non-compound) query through the full extraction pipeline.
        ClarificationRequired propagates directly to the caller.
        """
        # FIX (Problem 4): Use shared helper instead of duplicated block
        previous_qco, _ = self._resolve_previous_context(previous_context)

        return self._run_extraction_stages(
            query_text=query_text,
            current_date=current_date,
            previous_qco=previous_qco,
            overrides=overrides,
        )

    # -------------------------------------------------------------------------
    # COMPOUND QUERY PATH
    # -------------------------------------------------------------------------

    def _process_compound_query(
        self,
        decomposed: DecomposedQuery,
        current_date: Optional[date],
        previous_context,
        overrides: dict,
    ) -> Dict[str, Any]:
        """
        Process compound queries by running each sub-query sequentially.

        FIX (Problem 3): ClarificationRequired from any sub-query is now
        re-raised immediately rather than being silently swallowed into
        pending_subqueries. The caller (intent_extractor.py) expects either
        a completed result or a raised ClarificationRequired — it does not
        inspect the pending_subqueries dict for buried clarification requests.

        FIX (Problem 4): Uses shared _resolve_previous_context helper.
        """
        overrides = overrides or {}

        # FIX (Problem 4): Single shared helper, no duplication
        previous_qco, _ = self._resolve_previous_context(previous_context)

        completed_subqueries = []
        pending_subqueries = []
        dependencies = {}

        # Build dependency map
        for sub_query in decomposed.sub_queries:
            if sub_query.dependencies:
                dependencies[sub_query.index] = sub_query.dependencies

        for sub_query in decomposed.sub_queries:
            logger.info(
                f"[DSPy Pipeline] Processing sub-query {sub_query.index}: '{sub_query.text}'"
            )

            # Check if all dependencies have completed
            if sub_query.dependencies:
                completed_indices = {c['index'] for c in completed_subqueries}
                unsatisfied = [
                    dep for dep in sub_query.dependencies
                    if dep not in completed_indices
                ]
                if unsatisfied:
                    logger.info(
                        f"[DSPy Pipeline] Sub-query {sub_query.index} "
                        f"blocked by unsatisfied dependencies: {unsatisfied}"
                    )
                    pending_subqueries.append({
                        "index": sub_query.index,
                        "query": sub_query.text,
                        "blocked_by": unsatisfied,
                        "reason": f"Waiting for sub-queries {unsatisfied} to complete",
                    })
                    continue

            try:
                intent = self._run_extraction_stages(
                    query_text=sub_query.text,
                    current_date=current_date,
                    previous_qco=previous_qco,
                    overrides=overrides,
                )
                completed_subqueries.append({
                    "index": sub_query.index,
                    "query": sub_query.text,
                    "result": intent.model_dump(),
                })
                logger.info(f"[DSPy Pipeline] Sub-query {sub_query.index} completed")

            except ClarificationRequired:
                # FIX (Problem 3): Re-raise immediately. Do not swallow into
                # pending_subqueries. The orchestrator's clarification flow
                # handles suspension and resumption — it expects a raised
                # exception, not a dict with a buried clarification field.
                logger.info(
                    f"[DSPy Pipeline] Sub-query {sub_query.index} requires clarification "
                    f"— suspending compound query pipeline"
                )
                raise

            except Exception as e:
                # Non-clarification errors: record and continue to next sub-query.
                # This allows partial results to be returned for independent
                # sub-queries when one fails with a hard error.
                logger.error(
                    f"[DSPy Pipeline] Sub-query {sub_query.index} failed: "
                    f"{type(e).__name__}: {e}"
                )
                pending_subqueries.append({
                    "index": sub_query.index,
                    "query": sub_query.text,
                    "error": {
                        "type": type(e).__name__,
                        "message": str(e),
                    },
                })

        return {
            "type": "compound_query_results",
            "original_query": decomposed.original_query,
            "total_subqueries": len(decomposed.sub_queries),
            "completed_subqueries": completed_subqueries,
            "pending_subqueries": pending_subqueries,
            "dependencies": dependencies,
        }