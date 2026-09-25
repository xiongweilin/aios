"""Cognitive control subsystem.

The migrated meta-cognitive model is the canonical public cognition surface.
The small investigation helper remains available under explicit Investigation*
names and does not compete for semantic ownership.
"""

from .candidates import Candidate, CandidateFrontier, CandidateKind
from .consolidation import (
    ConsolidationAssessment,
    ConsolidationStatus,
    ExperienceCandidate,
    ExperienceConsolidator,
)
from .controller import (
    CognitiveClosure,
    CognitiveController,
    CognitiveHandoffEnvelope,
    ControllerDecision,
    ControllerDecisionKind,
    ControllerState,
    ControllerStatus,
    RevisionAssessment,
    RevisionDisposition,
    RevisionScope,
    controller_capability_result,
    latest_controller_decision,
)
from .engine import MetaControlFrame, MetaControlIntent, MetaControlIntentKind, MetaControllerEngine
from .epistemic import (
    EpistemicAssessment,
    EpistemicIssue,
    EpistemicIssueKind,
    StructuralTension,
    StructuralTensionKind,
    UncertaintyProfile,
)
from .experience import DEFAULT_EXPERIENCE_RULES, ExperienceResolver, ExperienceRule
from .journal import MetaPolicyEvent, MetaPolicyJournal
from .kernel import (
    CognitiveEpisode,
    CognitionEngine,
    InvestigationBudget,
    InvestigationCandidate,
    InvestigationClosureReadiness,
)
from .models import EpistemicMode, EpistemicState, EpistemicStateEstimator
from .planning import (
    ClosureReadiness,
    RevisionDiagnosis,
    RevisionPlanner,
    RevisionTarget,
    SearchBudget,
    SearchPolicy,
    SearchSelection,
)
from .policy import StagedMetaPolicy
from .policy_learning import (
    ExperienceLifecycle,
    ExperienceRecord,
    ExperienceStage,
    PolicyEvaluation,
    PolicyPromoter,
    PolicyRule,
    PolicyRuleStatus,
    PolicyVersion,
)
from .representation import (
    RepresentationMutationKind,
    RepresentationReviser,
    RepresentationRevisionCandidate,
    RepresentationRevisionResult,
    RepresentationState,
)
from .self_model import CapabilityAvailability, CapabilityBelief, SelfModelCalibrator, WorkingSelfModel

__all__ = [
    "Candidate", "CandidateFrontier", "CandidateKind", "CapabilityAvailability",
    "CapabilityBelief", "ClosureReadiness", "CognitiveClosure", "CognitiveController",
    "CognitiveEpisode", "CognitiveHandoffEnvelope", "CognitionEngine",
    "ConsolidationAssessment", "ConsolidationStatus", "ControllerDecision",
    "ControllerDecisionKind", "ControllerState", "ControllerStatus",
    "DEFAULT_EXPERIENCE_RULES", "EpistemicAssessment", "EpistemicIssue",
    "EpistemicIssueKind", "EpistemicMode", "EpistemicState", "EpistemicStateEstimator",
    "ExperienceCandidate", "ExperienceConsolidator", "ExperienceLifecycle",
    "ExperienceRecord", "ExperienceResolver", "ExperienceRule", "ExperienceStage",
    "InvestigationBudget", "InvestigationCandidate", "InvestigationClosureReadiness",
    "MetaControlFrame", "MetaControlIntent", "MetaControlIntentKind", "MetaControllerEngine",
    "MetaPolicyEvent", "MetaPolicyJournal", "PolicyEvaluation", "PolicyPromoter",
    "PolicyRule", "PolicyRuleStatus", "PolicyVersion", "RepresentationMutationKind",
    "RepresentationReviser", "RepresentationRevisionCandidate", "RepresentationRevisionResult",
    "RepresentationState", "RevisionAssessment", "RevisionDiagnosis", "RevisionDisposition",
    "RevisionPlanner", "RevisionScope", "RevisionTarget", "SearchBudget", "SearchPolicy",
    "SearchSelection", "SelfModelCalibrator", "StagedMetaPolicy", "StructuralTension",
    "StructuralTensionKind", "UncertaintyProfile", "WorkingSelfModel",
    "controller_capability_result", "latest_controller_decision",
]
