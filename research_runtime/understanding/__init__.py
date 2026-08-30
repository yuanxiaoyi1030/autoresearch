# Purpose: Exposes domain-neutral project understanding, legacy reuse, lineage, and visualization contracts.
from .models import (
    ApprovalStatus, CodeLineageRecord, CodeModification, FigurePanelSpec, FigureSpec,
    LegacyReferenceUse, LegacyReuseAssessment, LineageVerification, MaterialKind,
    ModificationCategory, ModificationClass, ProvenanceRecord, ResearchContext,
    ResearchMaterial, ReuseDisposition, ReuseItem, ReuseRisk, ReuseStrategy, RiskLevel,
    UnderstandingMode, UserResearchConstraints, VisualizationProfile,
)
from .inspector import InspectionResult, StaticProjectInspector
from .service import CodeLineageService, ProjectUnderstandingService, UnderstandingBundle

__all__ = [
    "ApprovalStatus", "CodeLineageRecord", "CodeModification", "FigurePanelSpec", "FigureSpec",
    "LegacyReferenceUse", "LegacyReuseAssessment", "LineageVerification", "MaterialKind",
    "ModificationCategory", "ModificationClass", "ProvenanceRecord", "ResearchContext",
    "ResearchMaterial", "ReuseDisposition", "ReuseItem", "ReuseRisk", "ReuseStrategy",
    "RiskLevel", "UnderstandingMode", "UserResearchConstraints", "VisualizationProfile",
    "CodeLineageService", "InspectionResult", "ProjectUnderstandingService",
    "StaticProjectInspector", "UnderstandingBundle",
]
