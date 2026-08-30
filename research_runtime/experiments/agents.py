# Purpose: Implements structured Experimental Lead and Research Engineer roles without any shell capability.
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
from typing import Generic, Optional, TypeVar

from research_runtime.llm import LLMMessage, LLMRole, LLMRuntime, LLMStage
from research_runtime.llm.prompts.experiments import (
    experimental_lead_prompt, research_engineer_prompt,
)
from research_runtime.planning import ExperimentPlanRevision, HypothesisRevision, canonical_hash
from research_runtime.understanding import ResearchContext, VisualizationProfile

from .models import EngineerCodePackage, ImplementationTaskGraph


T = TypeVar("T")


EXPERIMENTAL_LEAD_INSTRUCTION = experimental_lead_prompt()
RESEARCH_ENGINEER_INSTRUCTION = research_engineer_prompt()


@dataclass(frozen=True)
class AgentResponse(Generic[T]):
    value: T
    input_context_hash: str
    provider_id: str = "scripted"
    model: str = "scripted"
    input_tokens: int = 0
    output_tokens: int = 0


class ExperimentalLead(ABC):
    @abstractmethod
    def create_tasks(self, context: ResearchContext, hypothesis: HypothesisRevision,
                     plan: ExperimentPlanRevision) -> AgentResponse[ImplementationTaskGraph]:
        raise NotImplementedError


class ResearchEngineer(ABC):
    @abstractmethod
    def implement(self, context: ResearchContext, hypothesis: HypothesisRevision,
                  plan: ExperimentPlanRevision, tasks: ImplementationTaskGraph,
                  visualization_profile: Optional[VisualizationProfile]) -> AgentResponse[EngineerCodePackage]:
        raise NotImplementedError


class LLMExperimentalLead(ExperimentalLead):
    def __init__(self, runtime: LLMRuntime) -> None:
        self.runtime = runtime

    def create_tasks(self, context, hypothesis, plan):
        payload = {
            "research_context": context.model_dump(mode="json"),
            "approved_hypothesis": hypothesis.model_dump(mode="json"),
            "approved_experiment_plan": plan.model_dump(mode="json"),
        }
        return self._call(
            ImplementationTaskGraph, EXPERIMENTAL_LEAD_INSTRUCTION, payload, "experimental_lead",
        )

    def _call(self, output_model, instruction, payload, agent):
        client, route, ledger = self.runtime.client_for(LLMStage.EXPERIMENT_CODE)
        value, result = client.generate_structured(
            [
                LLMMessage(role=LLMRole.SYSTEM, content=instruction),
                LLMMessage(role=LLMRole.USER, content=json.dumps(payload, ensure_ascii=False)),
            ], output_model, route.budget, ledger=ledger,
            metadata={"stage": LLMStage.EXPERIMENT_CODE.value, "agent": agent},
        )
        return AgentResponse(
            value=value, input_context_hash=canonical_hash(payload),
            provider_id=result.provider_id, model=result.model,
            input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens,
        )


class LLMResearchEngineer(ResearchEngineer):
    def __init__(self, runtime: LLMRuntime) -> None:
        self.runtime = runtime

    def implement(self, context, hypothesis, plan, tasks, visualization_profile):
        payload = {
            "research_context": context.model_dump(mode="json"),
            "approved_hypothesis": hypothesis.model_dump(mode="json"),
            "approved_experiment_plan": plan.model_dump(mode="json"),
            "implementation_tasks": tasks.model_dump(mode="json"),
            "approved_visualization_profile": (
                visualization_profile.model_dump(mode="json") if visualization_profile else None
            ),
            "runner_contract": {
                "config_path_env": "AUTORESEARCH_CONFIG_PATH",
                "artifact_dir_env": "AUTORESEARCH_ARTIFACT_DIR",
                "visualization_profile_path_env": "AUTORESEARCH_VISUALIZATION_PROFILE_PATH",
                "stdout_stderr": "captured_by_runtime",
                "network": "disabled",
                "shell": "unavailable",
            },
        }
        client, route, ledger = self.runtime.client_for(LLMStage.EXPERIMENT_CODE)
        value, result = client.generate_structured(
            [
                LLMMessage(role=LLMRole.SYSTEM, content=RESEARCH_ENGINEER_INSTRUCTION),
                LLMMessage(role=LLMRole.USER, content=json.dumps(payload, ensure_ascii=False)),
            ], EngineerCodePackage, route.budget, ledger=ledger,
            metadata={"stage": LLMStage.EXPERIMENT_CODE.value, "agent": "research_engineer"},
        )
        return AgentResponse(
            value=value, input_context_hash=canonical_hash(payload),
            provider_id=result.provider_id, model=result.model,
            input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens,
        )
