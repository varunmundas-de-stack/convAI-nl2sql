"""
Isolated GEPA optimization for individual DSPy agents.

This module replaces monolithic whole-pipeline GEPA with per-agent optimization.
Each agent is optimized independently with frozen upstream fixtures, saved as its
own artifact, and later composed into the runtime pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import dspy
from dspy import Example
@dataclass
class ScoreWithFeedback:
    score: float
    feedback: str


from app.models.intent import Intent as CanonicalIntent
from app.models.intent import derive_intent_type

from .agents.classifier.agent import ClassifierModule
from .agents.decomposer.agent import QueryDecomposerModule
from .agents.dimension.agent import DimensionsModule
from .agents.interpreter.agent import QueryInterpreterModule
from .agents.metrics.agent import MetricsModule
from .agents.postprocessing.agent import PostProcessingModule
from .agents.scope.agent import ScopeModule
from .agents.time.agent import TimeModule
from .pipeline import IntentExtractionPipeline
from .schemas import (
    ClassifiedQuery,
    ComparisonConfig,
    DimensionsResult,
    FilterCondition,
    MetricSpec,
    MetricsResult,
    PostProcessingResult,
    RankingConfig,
    ScopeResult,
    TimeResult,
)
from .training_examples import get_training_examples, get_validation_examples

logger = logging.getLogger(__name__)


AGENT_ARTIFACTS_DIR = Path(__file__).parent.parent.parent / "models" / "agents"

AGENT_MODULE_ATTRS: Dict[str, str] = {
    "classifier": "classifier",
    "scope": "scope",
    "time": "time",
    "metrics": "metrics",
    "dimensions": "dimensions",
    "post_processing": "post_processing",
    "decomposer": "decomposer",
    "interpreter": "interpreter",
}

AGENT_FACTORIES: Dict[str, Callable[[], dspy.Module]] = {
    "classifier": ClassifierModule,
    "scope": ScopeModule,
    "time": TimeModule,
    "metrics": MetricsModule,
    "dimensions": DimensionsModule,
    "post_processing": PostProcessingModule,
    "decomposer": QueryDecomposerModule,
    "interpreter": QueryInterpreterModule,
}

# Agents with stable gold labels from current training examples.
OPTIMIZABLE_AGENTS: List[str] = [
    "classifier",
    "scope",
    "time",
    "metrics",
    "dimensions",
    "post_processing",
]


def _to_score(score: float, feedback: str) -> ScoreWithFeedback:
    clipped = max(0.0, min(1.0, score))
    return ScoreWithFeedback(score=clipped, feedback=feedback)


def _to_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    return date.today()


def _intent_from_example(example: Example) -> CanonicalIntent:
    outputs = getattr(example, "outputs", {}) or {}
    if "intent" not in outputs:
        raise ValueError("Training example does not include 'intent' output")
    return CanonicalIntent(**outputs["intent"])


def _intent_type_label(intent: CanonicalIntent) -> str:
    derived = derive_intent_type(intent)
    if derived.value == "SNAPSHOT":
        return "SNAPSHOT"
    if derived.value == "DISTRIBUTION":
        return "DISTRIBUTION"
    return derived.value


def _score_time(gold: TimeResult, pred: TimeResult) -> float:
    parts = [
        (0.40, gold.time_window == pred.time_window),
        (0.20, gold.start_date == pred.start_date),
        (0.20, gold.end_date == pred.end_date),
        (0.20, gold.granularity == pred.granularity),
    ]
    return sum(weight for weight, matched in parts if matched)


def _score_metrics(gold: MetricsResult, pred: MetricsResult) -> float:
    gold_names = {m.name for m in gold.metrics}
    pred_names = {m.name for m in pred.metrics}
    if not gold_names and not pred_names:
        selection = 1.0
    else:
        union = len(gold_names | pred_names)
        selection = (len(gold_names & pred_names) / union) if union else 0.0

    gold_aggs = {m.name: m.aggregation for m in gold.metrics}
    pred_aggs = {m.name: m.aggregation for m in pred.metrics}
    shared = gold_names & pred_names
    agg_score = (
        sum(1 for m in shared if gold_aggs.get(m) == pred_aggs.get(m)) / len(shared)
        if shared
        else 0.0
    )
    return (selection * 0.8) + (agg_score * 0.2)


def _score_dimensions(gold: DimensionsResult, pred: DimensionsResult) -> float:
    gold_group = set(gold.group_by or [])
    pred_group = set(pred.group_by or [])
    if not gold_group and not pred_group:
        group_score = 1.0
    else:
        union = len(gold_group | pred_group)
        group_score = (len(gold_group & pred_group) / union) if union else 0.0

    gold_filters = {
        (f.dimension, f.operator, str(f.value))
        for f in (gold.filters or [])
    }
    pred_filters = {
        (f.dimension, f.operator, str(f.value))
        for f in (pred.filters or [])
    }
    if not gold_filters and not pred_filters:
        filter_score = 1.0
    else:
        union = len(gold_filters | pred_filters)
        filter_score = (len(gold_filters & pred_filters) / union) if union else 0.0

    return (group_score * 0.7) + (filter_score * 0.3)


def _score_post_processing(gold: PostProcessingResult, pred: PostProcessingResult) -> float:
    rank_score = 1.0 if (gold.ranking == pred.ranking) else 0.0
    comp_score = 1.0 if (gold.comparison == pred.comparison) else 0.0
    derived_score = 1.0 if gold.derived_metric == pred.derived_metric else 0.0
    return (rank_score * 0.35) + (comp_score * 0.35) + (derived_score * 0.30)


@dataclass
class AgentDatasets:
    trainset: List[Example]
    valset: List[Example]


class AgentGepaOptimizer:
    """
    Per-agent GEPA optimization manager.

    The optimizer compiles each agent module independently and stores one
    artifact per agent under backend/models/agents/<agent>/optimized.json.
    """

    def __init__(
        self,
        pipeline: Optional[IntentExtractionPipeline] = None,
        reflection_lm: Optional[Any] = None,
        artifact_root: Optional[str] = None,
    ):
        self.pipeline = pipeline or IntentExtractionPipeline()
        self.reflection_lm = reflection_lm
        self.artifact_root = Path(artifact_root) if artifact_root else AGENT_ARTIFACTS_DIR
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.config: Dict[str, Any] = {
            "auto": "medium",
            "max_metric_calls": None,
            "use_merge": True,
            "track_stats": True,
            "failure_score": 0.0,
            "perfect_score": 1.0,
            "seed": 42,
        }

    def configure(self, **kwargs) -> "AgentGepaOptimizer":
        self.config.update(kwargs)
        return self

    def set_reflection_lm(self, reflection_lm: Any) -> "AgentGepaOptimizer":
        self.reflection_lm = reflection_lm
        return self

    def optimize_all_agents(
        self,
        agents: Optional[List[str]] = None,
        trainset: Optional[List[Example]] = None,
        valset: Optional[List[Example]] = None,
    ) -> Dict[str, Any]:
        selected = agents or OPTIMIZABLE_AGENTS
        results: Dict[str, Any] = {}
        datasets = self._build_agent_datasets(trainset, valset)
        for agent in selected:
            if agent not in OPTIMIZABLE_AGENTS:
                results[agent] = {"status": "skipped", "reason": "Agent not optimizable with current labels"}
                continue
            try:
                path, details = self.optimize_agent(agent, datasets[agent].trainset, datasets[agent].valset)
                results[agent] = {"status": "optimized", "artifact_path": path, **details}
            except Exception as exc:
                logger.exception("GEPA optimization failed for agent '%s'", agent)
                results[agent] = {"status": "failed", "error": str(exc)}
        return results

    def optimize_agent(
        self,
        agent: str,
        trainset: Optional[List[Example]] = None,
        valset: Optional[List[Example]] = None,
    ) -> tuple[str, Dict[str, Any]]:
        if not self.reflection_lm:
            raise ValueError("reflection_lm must be set before GEPA optimization")
        if agent not in OPTIMIZABLE_AGENTS:
            raise ValueError(f"Unsupported agent '{agent}'. Supported: {OPTIMIZABLE_AGENTS}")
        try:
            from dspy.teleprompt import GEPA
        except ImportError as exc:
            raise ImportError("GEPA not available. Ensure GEPA library is installed.") from exc

        if trainset is None or valset is None:
            datasets = self._build_agent_datasets()
            trainset = datasets[agent].trainset
            valset = datasets[agent].valset

        module = AGENT_FACTORIES[agent]()
        metric = self._metric_for_agent(agent)
        gepa_config = {
            "metric": metric,
            "reflection_lm": self.reflection_lm,
            "use_merge": self.config["use_merge"],
            "track_stats": self.config["track_stats"],
            "failure_score": self.config["failure_score"],
            "perfect_score": self.config["perfect_score"],
            "seed": self.config["seed"],
        }
        if self.config.get("max_metric_calls"):
            gepa_config["max_metric_calls"] = self.config["max_metric_calls"]
        else:
            gepa_config["auto"] = self.config["auto"]

        optimizer = GEPA(**gepa_config)
        compiled_module = optimizer.compile(module, trainset=trainset, valset=valset)

        artifact_path = self._artifact_path(agent)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        compiled_module.save(str(artifact_path))

        details: Dict[str, Any] = {}
        if hasattr(compiled_module, "detailed_results"):
            dr = compiled_module.detailed_results
            details = {
                "candidates_explored": len(dr.candidates),
                "best_candidate_index": dr.best_idx,
                "best_score_achieved": dr.val_aggregate_scores[dr.best_idx],
                "total_metric_calls": dr.total_metric_calls,
            }
        return str(artifact_path), details

    def _artifact_path(self, agent: str) -> Path:
        return self.artifact_root / agent / "optimized.json"

    def _build_agent_datasets(
        self,
        trainset: Optional[List[Example]] = None,
        valset: Optional[List[Example]] = None,
    ) -> Dict[str, AgentDatasets]:
        train_examples = trainset or get_training_examples()
        val_examples = valset or get_validation_examples()
        return {
            agent: AgentDatasets(
                trainset=self._build_examples_for_agent(agent, train_examples),
                valset=self._build_examples_for_agent(agent, val_examples),
            )
            for agent in OPTIMIZABLE_AGENTS
        }

    def _build_examples_for_agent(self, agent: str, examples: List[Example]) -> List[Example]:
        built: List[Example] = []
        for ex in examples:
            built_ex = self._build_single_agent_example(agent, ex)
            if built_ex is not None:
                built.append(built_ex)
        return built

    def _build_single_agent_example(self, agent: str, ex: Example) -> Optional[Example]:
        query = getattr(ex, "query", "")
        previous_context = getattr(ex, "previous_context", "")
        current_date = _to_date(getattr(ex, "current_date", None))
        canonical_intent = _intent_from_example(ex)

        decomposed = self.pipeline.decomposer(query=query, previous_context=previous_context, overrides=None)
        query_text = decomposed.sub_queries[0].text if decomposed.sub_queries else query
        resolved_query = (
            self.pipeline.interpreter(
                current_input=query_text,
                conversation="",
                session_context=str(previous_context or ""),
            )
            if previous_context
            else query_text
        )
        classified = self.pipeline.classifier(query=resolved_query, session_context=previous_context)

        if agent == "classifier":
            gold_classified = ClassifiedQuery(
                original_query=resolved_query,
                query_intent=_intent_type_label(canonical_intent),
                classified_terms=[],
                filter_hints=[],
                explicit_scope=canonical_intent.sales_scope,
            )
            return (
                dspy.Example(
                    query=resolved_query,
                    session_context=previous_context,
                    classified_query=gold_classified,
                ).with_inputs("query", "session_context")
            )

        if agent == "scope":
            return (
                dspy.Example(
                    classified_query=classified,
                    overrides=None,
                    scope_result=ScopeResult(sales_scope=canonical_intent.sales_scope),
                ).with_inputs("classified_query", "overrides")
            )

        gold_time = TimeResult(
            time_window=canonical_intent.time.window if canonical_intent.time else None,
            start_date=canonical_intent.time.start_date if canonical_intent.time else None,
            end_date=canonical_intent.time.end_date if canonical_intent.time else None,
            granularity=canonical_intent.time.granularity if canonical_intent.time else None,
        )

        if agent == "time":
            return (
                dspy.Example(
                    classified_query=classified,
                    current_date=current_date,
                    previous_context=previous_context,
                    overrides=None,
                    time_result=gold_time,
                ).with_inputs("classified_query", "current_date", "previous_context", "overrides")
            )

        gold_metrics = MetricsResult(
            metrics=[MetricSpec(name=m.name, aggregation=m.aggregation) for m in canonical_intent.metrics],
            aggregations=[m.aggregation for m in canonical_intent.metrics],
        )
        if agent == "metrics":
            return (
                dspy.Example(
                    classified_query=classified,
                    sales_scope=canonical_intent.sales_scope,
                    overrides=None,
                    metrics_result=gold_metrics,
                ).with_inputs("classified_query", "sales_scope", "overrides")
            )

        gold_dimensions = DimensionsResult(
            group_by=canonical_intent.group_by,
            filters=[
                FilterCondition(dimension=f.dimension, operator=f.operator, value=f.value)
                for f in (canonical_intent.filters or [])
            ] or None,
        )
        if agent == "dimensions":
            return (
                dspy.Example(
                    classified_query=classified,
                    sales_scope=canonical_intent.sales_scope,
                    previous_context=previous_context,
                    x_axis_values=None,
                    overrides=None,
                    dimensions_result=gold_dimensions,
                ).with_inputs("classified_query", "sales_scope", "previous_context", "x_axis_values", "overrides")
            )

        if agent == "post_processing":
            post = canonical_intent.post_processing
            gold_post = PostProcessingResult(
                ranking=RankingConfig(**post.ranking.model_dump()) if post and post.ranking else None,
                comparison=ComparisonConfig(**post.comparison.model_dump()) if post and post.comparison else None,
                derived_metric=post.derived_metric if post and post.derived_metric else "none",
            )
            return (
                dspy.Example(
                    classified_query=classified,
                    time_result=gold_time,
                    dimensions_result=gold_dimensions,
                    post_processing_result=gold_post,
                ).with_inputs("classified_query", "time_result", "dimensions_result")
            )

        return None

    def _metric_for_agent(self, agent: str):
        output_field = {
            "classifier": "classified_query",
            "scope": "scope_result",
            "time": "time_result",
            "metrics": "metrics_result",
            "dimensions": "dimensions_result",
            "post_processing": "post_processing_result",
        }[agent]

        def metric(gold: Example, pred: Any, trace: Optional[Any] = None, pred_name: Optional[str] = None, pred_trace: Optional[Any] = None):
            try:
                expected = getattr(gold, "outputs", {}).get(output_field)
                if expected is None:
                    return _to_score(0.0, f"Missing gold output '{output_field}'")

                actual = getattr(pred, output_field, pred)

                if agent == "classifier":
                    expected_intent = expected.query_intent if hasattr(expected, "query_intent") else expected.get("query_intent")
                    actual_intent = actual.query_intent if hasattr(actual, "query_intent") else actual.get("query_intent")
                    score = 1.0 if expected_intent == actual_intent else 0.0
                    return _to_score(score, f"classifier intent expected={expected_intent} actual={actual_intent}")

                if agent == "scope":
                    expected_scope = expected.sales_scope if hasattr(expected, "sales_scope") else expected.get("sales_scope")
                    actual_scope = actual.sales_scope if hasattr(actual, "sales_scope") else actual.get("sales_scope")
                    score = 1.0 if expected_scope == actual_scope else 0.0
                    return _to_score(score, f"scope expected={expected_scope} actual={actual_scope}")

                if agent == "time":
                    score = _score_time(TimeResult(**expected.model_dump()), TimeResult(**actual.model_dump()))
                    return _to_score(score, "time fields matched")

                if agent == "metrics":
                    score = _score_metrics(MetricsResult(**expected.model_dump()), MetricsResult(**actual.model_dump()))
                    return _to_score(score, "metrics selection/aggregation matched")

                if agent == "dimensions":
                    score = _score_dimensions(DimensionsResult(**expected.model_dump()), DimensionsResult(**actual.model_dump()))
                    return _to_score(score, "dimensions group_by/filters matched")

                if agent == "post_processing":
                    score = _score_post_processing(
                        PostProcessingResult(**expected.model_dump()),
                        PostProcessingResult(**actual.model_dump()),
                    )
                    return _to_score(score, "post-processing matched")

                return _to_score(0.0, f"Unsupported agent: {agent}")
            except Exception as exc:
                logger.warning("Agent metric failed for %s: %s", agent, exc)
                return _to_score(0.0, f"metric failure: {exc}")

        return metric


def get_agent_artifact_path(agent: str, artifact_root: Optional[Path] = None) -> Path:
    root = artifact_root or AGENT_ARTIFACTS_DIR
    return root / agent / "optimized.json"


def get_available_optimized_agents(artifact_root: Optional[Path] = None) -> List[str]:
    root = artifact_root or AGENT_ARTIFACTS_DIR
    available: List[str] = []
    for agent in OPTIMIZABLE_AGENTS:
        if get_agent_artifact_path(agent, root).exists():
            available.append(agent)
    return available


def load_optimized_agents_into_pipeline(
    pipeline: IntentExtractionPipeline,
    artifact_root: Optional[Path] = None,
) -> List[str]:
    root = artifact_root or AGENT_ARTIFACTS_DIR
    loaded: List[str] = []
    for agent in OPTIMIZABLE_AGENTS:
        path = get_agent_artifact_path(agent, root)
        if not path.exists():
            continue
        module = AGENT_FACTORIES[agent]()
        module.load(str(path))
        setattr(pipeline, AGENT_MODULE_ATTRS[agent], module)
        loaded.append(agent)
    return loaded

