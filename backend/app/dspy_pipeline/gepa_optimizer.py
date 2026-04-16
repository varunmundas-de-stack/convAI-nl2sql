"""
Compatibility wrapper for GEPA optimization.

Legacy whole-pipeline GEPA has been replaced by isolated per-agent GEPA in
agent_gepa_optimizer.py. This module preserves prior entry points while
delegating to the new implementation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .agent_gepa_optimizer import (
    AGENT_ARTIFACTS_DIR,
    OPTIMIZABLE_AGENTS,
    AgentGepaOptimizer,
)
from .pipeline import IntentExtractionPipeline


class GepaIntentOptimizer:
    """
    Backward-compatible facade for isolated agent GEPA optimization.
    """

    def __init__(
        self,
        pipeline: Optional[IntentExtractionPipeline] = None,
        reflection_lm: Optional[Any] = None,
        log_dir: Optional[str] = None,
    ):
        self._optimizer = AgentGepaOptimizer(
            pipeline=pipeline,
            reflection_lm=reflection_lm,
            artifact_root=log_dir or str(AGENT_ARTIFACTS_DIR),
        )
        self.optimized_pipeline = self._optimizer.pipeline
        self.optimization_results: Dict[str, Any] = {}
        self.config: Dict[str, Any] = self._optimizer.config

    def configure(self, **kwargs) -> "GepaIntentOptimizer":
        self._optimizer.configure(**kwargs)
        self.config = self._optimizer.config
        return self

    def set_reflection_lm(self, reflection_lm: Any) -> "GepaIntentOptimizer":
        self._optimizer.set_reflection_lm(reflection_lm)
        return self

    def optimize(self, trainset=None, valset=None, resume: bool = True) -> IntentExtractionPipeline:
        self.optimization_results = self._optimizer.optimize_all_agents(trainset=trainset, valset=valset)
        return self._optimizer.pipeline

    def optimize_component(self, component_name: str, trainset=None, valset=None) -> IntentExtractionPipeline:
        self.optimization_results = self._optimizer.optimize_all_agents(
            agents=[component_name],
            trainset=trainset,
            valset=valset,
        )
        return self._optimizer.pipeline

    def run_ablation_study(self, components: Optional[List[str]] = None, trainset=None, valset=None) -> Dict[str, Any]:
        selected = components or OPTIMIZABLE_AGENTS
        return self._optimizer.optimize_all_agents(agents=selected, trainset=trainset, valset=valset)

    def compare_with_bootstrap(self, trainset=None, valset=None) -> Dict[str, Any]:
        return {
            "mode": "isolated_agents",
            "note": "Whole-pipeline GEPA vs bootstrap comparison is deprecated.",
            "results": self._optimizer.optimize_all_agents(trainset=trainset, valset=valset),
        }

    def save_optimized_pipeline(self, path: Optional[str] = None) -> str:
        # Per-agent optimizer persists artifacts automatically per agent.
        return path or str(AGENT_ARTIFACTS_DIR)

    def load_optimized_pipeline(self, path: str) -> IntentExtractionPipeline:
        # Loading is handled by config.PipelineManager via per-agent artifacts.
        return self._optimizer.pipeline

    def get_optimization_status(self) -> Dict[str, Any]:
        return {
            "mode": "isolated_agents",
            "artifact_root": str(self._optimizer.artifact_root),
            "results": self.optimization_results,
        }


def create_gepa_optimizer(
    reflection_lm: Any,
    pipeline: Optional[IntentExtractionPipeline] = None,
    **config,
) -> GepaIntentOptimizer:
    optimizer = GepaIntentOptimizer(pipeline=pipeline, reflection_lm=reflection_lm)
    if config:
        optimizer.configure(**config)
    return optimizer


def quick_gepa_optimize(
    reflection_lm: Any,
    pipeline: Optional[IntentExtractionPipeline] = None,
) -> IntentExtractionPipeline:
    optimizer = create_gepa_optimizer(
        reflection_lm=reflection_lm,
        pipeline=pipeline,
        auto="light",
        track_stats=True,
    )
    return optimizer.optimize()


def production_gepa_optimize(
    reflection_lm: Any,
    pipeline: Optional[IntentExtractionPipeline] = None,
) -> IntentExtractionPipeline:
    optimizer = create_gepa_optimizer(
        reflection_lm=reflection_lm,
        pipeline=pipeline,
        auto="heavy",
        track_stats=True,
        use_merge=True,
    )
    return optimizer.optimize()

