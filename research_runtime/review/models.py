# Purpose: Defines independent research-review assignments, claims, specialist/meta reports, hard policy, and feedback records.
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
import uuid

from pydantic import BaseModel, Field, computed_field, model_validator

from research_runtime.planning import canonical_hash
from research_runtime.state import ResearchOutcome, ResearchStage, utc_now


def identifier(prefix: str) -> str:
    return prefix + uuid.uuid4().hex


class ResearchReviewRole(str, Enum):
    META_REVIEWER = "meta_reviewer"
    METHODOLOGY_REVIEWER = "methodology_reviewer"
    STATISTICAL_REVIEWER = "statistical_reviewer"
    EVIDENCE_REPRODUCIBILITY_REVIEWER = "evidence_reproducibility_reviewer"


class ResearchReviewDecision(str, Enum):
    SUPPORTED = "supported"
    NEGATIVE_RESULT = "negative_result"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    RETURN_TO_EXPERIMENT = "return_to_experiment"
    REVISE_PLAN = "revise_plan"


class ClaimType(str, Enum):
    EXPERIMENT_RESULT = "experiment_result"
    METHODOLOGY = "methodology"
    LITERATURE_CONTEXT = "literature_context"
    LIMITATION = "limitation"


class ReviewSeverity(str, Enum):
    INFO = "info"
    MINOR = "minor"
    MAJOR = "major"
    BLOCKING = "blocking"


class ReviewerVerdict(str, Enum):
    PASS = "pass"
    CONCERNS = "concerns"
    BLOCK = "block"


class PolicyRuleStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class EvidenceClaimDraft(BaseModel):
    claim_type: ClaimType
    statement: str = Field(min_length=1)
    outcome: Optional[ResearchOutcome] = None
    core_claim: bool = False
    analysis_artifact_ids: List[str] = Field(default_factory=list)
    experiment_artifact_ids: List[str] = Field(default_factory=list)
    comparison_ids: List[str] = Field(default_factory=list)
    literature_evidence_ids: List[str] = Field(default_factory=list)


class EvidenceClaim(EvidenceClaimDraft):
    claim_id: str = Field(default_factory=lambda: identifier("evidence_claim_"))
    project_id: str
    context_id: str
    analysis_id: str
    analysis_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def claim_hash(self) -> "EvidenceClaim":
        if self.claim_type is ClaimType.EXPERIMENT_RESULT:
            if self.outcome is None or not self.analysis_artifact_ids or not self.comparison_ids:
                raise ValueError("experiment result claim requires outcome, Analysis Artifacts, and comparisons")
        expected = self.calculated_hash()
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("EvidenceClaim hash mismatch")
        self.content_hash = expected
        return self

    def calculated_hash(self) -> str:
        return canonical_hash(self.model_dump(
            mode="json", exclude={"content_hash", "created_at"},
        ))


class ReviewAssignment(BaseModel):
    role: ResearchReviewRole
    focus: List[str] = Field(min_length=1)
    required_record_types: List[str] = Field(min_length=1)

    @model_validator(mode="after")
    def specialist_only(self) -> "ReviewAssignment":
        if self.role is ResearchReviewRole.META_REVIEWER:
            raise ValueError("Meta Reviewer cannot assign itself specialist content review")
        return self


class MetaAssignmentPlan(BaseModel):
    assignments: List[ReviewAssignment] = Field(min_length=3, max_length=3)
    coordination_note: str = Field(min_length=1)

    @model_validator(mode="after")
    def exact_team(self) -> "MetaAssignmentPlan":
        expected = {
            ResearchReviewRole.METHODOLOGY_REVIEWER,
            ResearchReviewRole.STATISTICAL_REVIEWER,
            ResearchReviewRole.EVIDENCE_REPRODUCIBILITY_REVIEWER,
        }
        if {item.role for item in self.assignments} != expected:
            raise ValueError("Meta assignment must cover each independent specialist exactly once")
        return self


class ReviewFinding(BaseModel):
    finding_id: str = Field(default_factory=lambda: identifier("research_finding_"))
    category: str = Field(min_length=1)
    severity: ReviewSeverity
    summary: str = Field(min_length=1)
    record_ids: List[str] = Field(default_factory=list)
    recommended_action: str = Field(min_length=1)


class SpecialistReviewDraft(BaseModel):
    verdict: ReviewerVerdict
    proposed_decision: ResearchReviewDecision
    findings: List[ReviewFinding] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    conclusion_boundary: str = Field(min_length=1)


class SpecialistReviewReport(BaseModel):
    specialist_review_id: str = Field(default_factory=lambda: identifier("specialist_review_"))
    review_run_id: str
    project_id: str
    context_id: str
    analysis_id: str
    role: ResearchReviewRole
    assignment: ReviewAssignment
    verdict: ReviewerVerdict
    proposed_decision: ResearchReviewDecision
    findings: List[ReviewFinding] = Field(default_factory=list)
    summary: str
    conclusion_boundary: str
    independent_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_id: str
    model: str
    content_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def report_hash(self) -> "SpecialistReviewReport":
        if self.role is ResearchReviewRole.META_REVIEWER or self.assignment.role is not self.role:
            raise ValueError("specialist report role/assignment mismatch")
        expected = self.calculated_hash()
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("SpecialistReviewReport hash mismatch")
        self.content_hash = expected
        return self

    def calculated_hash(self) -> str:
        return canonical_hash(self.model_dump(
            mode="json", exclude={"content_hash", "created_at"},
        ))


class ReviewerPosition(BaseModel):
    role: ResearchReviewRole
    proposed_decision: ResearchReviewDecision
    rationale: str = Field(min_length=1)


class ReviewDisagreement(BaseModel):
    disagreement_id: str = Field(default_factory=lambda: identifier("disagreement_"))
    issue: str = Field(min_length=1)
    positions: List[ReviewerPosition] = Field(min_length=2)
    resolution: str = Field(min_length=1)
    unresolved: bool = False


class MetaReviewDraft(BaseModel):
    proposed_decision: ResearchReviewDecision
    synthesis: str = Field(min_length=1)
    disagreements: List[ReviewDisagreement] = Field(default_factory=list)
    feedback: List[str] = Field(default_factory=list)


class MetaReviewReport(BaseModel):
    meta_review_id: str = Field(default_factory=lambda: identifier("meta_review_"))
    review_run_id: str
    project_id: str
    context_id: str
    analysis_id: str
    assignment_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    specialist_review_ids: List[str] = Field(min_length=3, max_length=3)
    specialist_review_hashes: Dict[str, str]
    proposed_decision: ResearchReviewDecision
    synthesis: str
    disagreements: List[ReviewDisagreement] = Field(default_factory=list)
    feedback: List[str] = Field(default_factory=list)
    independent_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_id: str
    model: str
    content_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def report_hash(self) -> "MetaReviewReport":
        if set(self.specialist_review_ids) != set(self.specialist_review_hashes):
            raise ValueError("Meta review must hash-bind every specialist report")
        expected = self.calculated_hash()
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("MetaReviewReport hash mismatch")
        self.content_hash = expected
        return self

    def calculated_hash(self) -> str:
        return canonical_hash(self.model_dump(
            mode="json", exclude={"content_hash", "created_at"},
        ))


class PolicyRuleResult(BaseModel):
    rule_code: str = Field(min_length=1)
    status: PolicyRuleStatus
    summary: str = Field(min_length=1)
    record_ids: List[str] = Field(default_factory=list)
    forced_decision: Optional[ResearchReviewDecision] = None


class ResearchPolicyDecision(BaseModel):
    policy_decision_id: str = Field(default_factory=lambda: identifier("policy_decision_"))
    review_run_id: str
    project_id: str
    context_id: str
    analysis_id: str
    analysis_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    verification_id: str
    verification_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    meta_review_id: str
    meta_review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rule_results: List[PolicyRuleResult] = Field(min_length=1)
    final_decision: ResearchReviewDecision
    reviewer_decision_overridden: bool
    override_explanation: Optional[str] = None
    feedback: List[str] = Field(default_factory=list)
    content_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def decision_hash(self) -> "ResearchPolicyDecision":
        if self.reviewer_decision_overridden and not self.override_explanation:
            raise ValueError("policy override requires an explanation")
        expected = self.calculated_hash()
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("ResearchPolicyDecision hash mismatch")
        self.content_hash = expected
        return self

    def calculated_hash(self) -> str:
        return canonical_hash(self.model_dump(
            mode="json", exclude={"content_hash", "created_at"},
        ))


class ResearchReviewRecord(BaseModel):
    review_run_id: str = Field(default_factory=lambda: identifier("research_review_"))
    project_id: str
    context_id: str
    analysis_id: str
    analysis_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    scientific_review_id: str
    claim_ids: List[str] = Field(min_length=1)
    assignment_plan: MetaAssignmentPlan
    specialist_review_ids: List[str] = Field(min_length=3, max_length=3)
    meta_review_id: str
    policy_decision_id: str
    final_decision: ResearchReviewDecision
    content_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def record_hash(self) -> "ResearchReviewRecord":
        expected = self.calculated_hash()
        if self.content_hash is not None and self.content_hash != expected:
            raise ValueError("ResearchReviewRecord hash mismatch")
        self.content_hash = expected
        return self

    def calculated_hash(self) -> str:
        return canonical_hash(self.model_dump(
            mode="json", exclude={"content_hash", "created_at"},
        ))


class ResearchReviewAgentRun(BaseModel):
    agent_run_id: str = Field(default_factory=lambda: identifier("research_review_agent_"))
    review_run_id: str
    project_id: str
    context_id: str
    role: ResearchReviewRole
    operation: str
    input_context_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_record_id: str
    provider_id: str
    model: str
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)


class ResearchReviewTransition(BaseModel):
    transition_id: str = Field(default_factory=lambda: identifier("review_transition_"))
    review_run_id: str
    project_id: str
    policy_decision_id: str
    final_decision: ResearchReviewDecision
    from_stage: ResearchStage
    to_stage: ResearchStage
    state_revision_before: int = Field(ge=0)
    state_revision_after: int = Field(ge=0)
    created_at: datetime = Field(default_factory=utc_now)


class ResearchReviewResult(BaseModel):
    record: ResearchReviewRecord
    claims: List[EvidenceClaim]
    specialist_reviews: List[SpecialistReviewReport]
    meta_review: MetaReviewReport
    policy_decision: ResearchPolicyDecision
    verification_id: str
    agent_runs: List[ResearchReviewAgentRun]
