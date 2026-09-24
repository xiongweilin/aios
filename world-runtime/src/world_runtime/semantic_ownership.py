from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SemanticOwner:
    concept: str
    owner: str
    durable: bool
    authority_bearing: bool = False


SEMANTIC_OWNERS: tuple[SemanticOwner, ...] = (
    SemanticOwner("Claim", "semantic-language", True),
    SemanticOwner("Evidence", "semantic-language", True),
    SemanticOwner("Unknown", "semantic-language", True),
    SemanticOwner("Conflict", "semantic-language", True),
    SemanticOwner("Goal", "semantic-language", True),
    SemanticOwner("Constraint", "semantic-language", True),
    SemanticOwner("Mandate", "semantic-language", True, True),
    SemanticOwner("Decision", "semantic-language", True, True),
    SemanticOwner("Authorization", "semantic-language", True, True),
    SemanticOwner("Responsibility", "semantic-language", True),
    SemanticOwner("Effect", "semantic-language", True),
    SemanticOwner("Outcome", "semantic-language", True),
    SemanticOwner("Acceptance", "semantic-language", True),
    SemanticOwner("ClaimRevision", "world-runtime/epistemics", True),
    SemanticOwner("EvidenceAssessment", "world-runtime/epistemics", True),
    SemanticOwner("BeliefState", "world-runtime/epistemics", True),
    SemanticOwner("CognitiveControllerState", "world-runtime/cognition", True),
    SemanticOwner("Experience", "world-runtime/memory", True),
    SemanticOwner("StandingResponsibility", "world-runtime/responsibility", True),
    SemanticOwner("ResponsibilityRelation", "world-runtime/responsibility", True),
    SemanticOwner("SemanticTypeDefinition", "world-runtime/ontology", True),
    SemanticOwner("DomainAssignment", "world-runtime/domains", True),
    SemanticOwner("DomainReport", "world-runtime/domains", True),
    SemanticOwner("StrategyAssessment", "world-runtime/strategy", True),
    SemanticOwner("StrategicIssue", "world-runtime/strategy", True),
    SemanticOwner("PortfolioProposal", "world-runtime/strategy", True),
    SemanticOwner("StrategicPortfolio", "world-runtime/strategy", True),
    SemanticOwner("ResourceAllocation", "world-runtime/strategy", True),
    SemanticOwner("ResourceBudgetLine", "world-runtime/strategy", True),
    SemanticOwner("GoalLifecycleTransition", "world-runtime/strategy", True),
    SemanticOwner("QualificationDependency", "world-runtime/qualification", True),
    SemanticOwner("ReviewObligation", "world-runtime/qualification", True),
    SemanticOwner("RevalidationAssessment", "world-runtime/qualification", True),
    SemanticOwner("Work", "world-runtime/execution", True),
    SemanticOwner("Run", "world-runtime/execution", True),
    SemanticOwner("ProviderAttempt", "world-runtime/execution", True),
    SemanticOwner("ProviderResult", "world-runtime/execution", True),
    SemanticOwner("DomainOutcomeQualification", "domain-controller", True),
    SemanticOwner("DomainAcceptance", "domain-controller", True),
)


def validate_semantic_owners(
    owners: tuple[SemanticOwner, ...] = SEMANTIC_OWNERS,
) -> None:
    seen: dict[str, str] = {}
    for entry in owners:
        previous = seen.get(entry.concept)
        if previous is not None and previous != entry.owner:
            raise ValueError(
                f"semantic concept {entry.concept!r} has multiple owners: "
                f"{previous!r} and {entry.owner!r}"
            )
        seen[entry.concept] = entry.owner


def owner_of(concept: str) -> str:
    validate_semantic_owners()
    for entry in SEMANTIC_OWNERS:
        if entry.concept == concept:
            return entry.owner
    raise KeyError(concept)


__all__ = [
    "IMPLEMENTATION_ONLY_PUBLIC_CLASSES",
    "PUBLIC_SEMANTIC_CLASSES",
    "SEMANTIC_OWNERS",
    "PublicSemanticClass",
    "SemanticOwner",
    "owner_of",
    "public_semantic_classification",
    "validate_semantic_owners",
]


@dataclass(frozen=True, slots=True)
class PublicSemanticClass:
    symbol: str
    canonical_concept: str
    owner: str
    authority_bearing: bool
    temporal_role: str
    projection: bool
    semantic_identity: bool


PUBLIC_SEMANTIC_CLASSES: tuple[PublicSemanticClass, ...] = (
    PublicSemanticClass("world_runtime.BeliefState", "BeliefState", "world-runtime/epistemics", False, "current", True, False),
    PublicSemanticClass("world_runtime.ClaimRevision", "ClaimRevision", "world-runtime/epistemics", False, "historical", False, True),
    PublicSemanticClass("world_runtime.EvidenceAssessment", "EvidenceAssessment", "world-runtime/epistemics", False, "historical", False, True),
    PublicSemanticClass("world_runtime.EvidenceRequirement", "EvidenceRequirement", "world-runtime/epistemics", False, "current", False, True),
    PublicSemanticClass("world_runtime.FalsificationCondition", "FalsificationCondition", "world-runtime/epistemics", False, "current", False, True),
    PublicSemanticClass("world_runtime.DomainAssignment", "DomainAssignment", "world-runtime/domains", False, "both", False, True),
    PublicSemanticClass("world_runtime.DomainReport", "DomainReport", "world-runtime/domains", False, "historical", False, True),
    PublicSemanticClass("world_runtime.Experience", "Experience", "world-runtime/memory", False, "both", False, True),
    PublicSemanticClass("world_runtime.SemanticTypeDefinition", "SemanticTypeDefinition", "world-runtime/ontology", False, "both", False, True),
    PublicSemanticClass("world_runtime.StandingResponsibility", "StandingResponsibility", "world-runtime/responsibility", False, "current", True, True),
    PublicSemanticClass("world_runtime.ResponsibilityRelation", "ResponsibilityRelation", "world-runtime/responsibility", False, "both", False, True),
    PublicSemanticClass("world_runtime.StrategyAssessment", "StrategyAssessment", "world-runtime/strategy", False, "historical", False, True),
    PublicSemanticClass("world_runtime.StrategicIssue", "StrategicIssue", "world-runtime/strategy", False, "both", False, True),
    PublicSemanticClass("world_runtime.PortfolioProposal", "PortfolioProposal", "world-runtime/strategy", False, "historical", False, True),
    PublicSemanticClass("world_runtime.StrategicPortfolio", "StrategicPortfolio", "world-runtime/strategy", False, "current", True, True),
    PublicSemanticClass("world_runtime.ResourceAllocation", "ResourceAllocation", "world-runtime/strategy", False, "both", False, True),
    PublicSemanticClass("world_runtime.ResourceBudgetLine", "ResourceBudgetLine", "world-runtime/strategy", False, "current", False, False),
    PublicSemanticClass("world_runtime.GoalLifecycleTransition", "GoalLifecycleTransition", "world-runtime/strategy", False, "historical", False, True),
    PublicSemanticClass("world_runtime.QualificationDependency", "QualificationDependency", "world-runtime/qualification", False, "both", False, True),
    PublicSemanticClass("world_runtime.ReviewObligation", "ReviewObligation", "world-runtime/qualification", False, "both", False, True),
    PublicSemanticClass("world_runtime.RevalidationAssessment", "RevalidationAssessment", "world-runtime/qualification", False, "historical", False, True),
    PublicSemanticClass("world_runtime.Work", "Work", "world-runtime/execution", False, "current", True, True),
    PublicSemanticClass("world_runtime.Run", "Run", "world-runtime/execution", False, "current", True, True),
    PublicSemanticClass("world_runtime.Candidate", "CognitiveCandidate", "world-runtime/cognition", False, "current", False, True),
    PublicSemanticClass("world_runtime.ClosureReadiness", "ClosureReadiness", "world-runtime/cognition", False, "current", True, False),
    PublicSemanticClass("world_runtime.SearchBudget", "SearchBudget", "world-runtime/cognition", False, "current", False, False),
    PublicSemanticClass("world_runtime.cognition.Candidate", "CognitiveCandidate", "world-runtime/cognition", False, "current", False, True),
    PublicSemanticClass("world_runtime.cognition.ClosureReadiness", "ClosureReadiness", "world-runtime/cognition", False, "current", True, False),
    PublicSemanticClass("world_runtime.cognition.EpistemicState", "EpistemicState", "world-runtime/cognition", False, "current", True, True),
    PublicSemanticClass("world_runtime.cognition.ExperienceRule", "ExperienceRule", "world-runtime/cognition", False, "both", False, True),
    PublicSemanticClass("world_runtime.cognition.CandidateFrontier", "CandidateFrontier", "world-runtime/cognition", False, "current", True, False),
    PublicSemanticClass("world_runtime.cognition.CapabilityBelief", "CapabilityBelief", "world-runtime/cognition", False, "current", True, False),
    PublicSemanticClass("world_runtime.cognition.CognitiveClosure", "CognitiveClosure", "world-runtime/cognition", False, "historical", False, True),
    PublicSemanticClass("world_runtime.cognition.CognitiveEpisode", "CognitiveEpisode", "world-runtime/cognition", False, "both", False, True),
    PublicSemanticClass("world_runtime.cognition.CognitiveHandoffEnvelope", "CognitiveHandoffEnvelope", "world-runtime/cognition", False, "historical", False, False),
    PublicSemanticClass("world_runtime.cognition.ConsolidationAssessment", "ConsolidationAssessment", "world-runtime/cognition", False, "historical", False, True),
    PublicSemanticClass("world_runtime.cognition.ControllerDecision", "CognitiveControllerDecision", "world-runtime/cognition", False, "historical", False, True),
    PublicSemanticClass("world_runtime.cognition.ControllerState", "CognitiveControllerState", "world-runtime/cognition", False, "current", True, True),
    PublicSemanticClass("world_runtime.cognition.EpistemicAssessment", "CognitiveEpistemicAssessment", "world-runtime/cognition", False, "historical", False, True),
    PublicSemanticClass("world_runtime.cognition.EpistemicIssue", "EpistemicIssue", "world-runtime/cognition", False, "current", False, True),
    PublicSemanticClass("world_runtime.cognition.ExperienceCandidate", "ExperienceCandidate", "world-runtime/cognition", False, "historical", False, True),
    PublicSemanticClass("world_runtime.cognition.ExperienceRecord", "CognitiveExperienceRecord", "world-runtime/cognition", False, "both", False, True),
    PublicSemanticClass("world_runtime.cognition.MetaControlFrame", "MetaControlFrame", "world-runtime/cognition", False, "current", True, False),
    PublicSemanticClass("world_runtime.cognition.MetaControlIntent", "MetaControlIntent", "world-runtime/cognition", False, "historical", False, True),
    PublicSemanticClass("world_runtime.cognition.MetaPolicyEvent", "MetaPolicyEvent", "world-runtime/cognition", False, "historical", False, True),
    PublicSemanticClass("world_runtime.cognition.PolicyEvaluation", "CognitivePolicyEvaluation", "world-runtime/cognition", False, "historical", False, True),
    PublicSemanticClass("world_runtime.cognition.PolicyRule", "CognitivePolicyRule", "world-runtime/cognition", False, "both", False, True),
    PublicSemanticClass("world_runtime.cognition.PolicyVersion", "CognitivePolicyVersion", "world-runtime/cognition", False, "historical", False, True),
    PublicSemanticClass("world_runtime.cognition.RepresentationRevisionCandidate", "RepresentationRevisionCandidate", "world-runtime/cognition", False, "current", False, True),
    PublicSemanticClass("world_runtime.cognition.RepresentationRevisionResult", "RepresentationRevisionResult", "world-runtime/cognition", False, "historical", False, True),
    PublicSemanticClass("world_runtime.cognition.RepresentationState", "RepresentationState", "world-runtime/cognition", False, "current", True, True),
    PublicSemanticClass("world_runtime.cognition.RevisionAssessment", "RevisionAssessment", "world-runtime/cognition", False, "historical", False, True),
    PublicSemanticClass("world_runtime.cognition.RevisionDiagnosis", "RevisionDiagnosis", "world-runtime/cognition", False, "historical", False, True),
    PublicSemanticClass("world_runtime.cognition.SearchBudget", "SearchBudget", "world-runtime/cognition", False, "current", False, False),
    PublicSemanticClass("world_runtime.cognition.SearchSelection", "SearchSelection", "world-runtime/cognition", False, "historical", False, True),
    PublicSemanticClass("world_runtime.cognition.StructuralTension", "StructuralTension", "world-runtime/cognition", False, "current", False, True),
    PublicSemanticClass("world_runtime.cognition.UncertaintyProfile", "UncertaintyProfile", "world-runtime/cognition", False, "current", True, False),
    PublicSemanticClass("world_runtime.cognition.WorkingSelfModel", "WorkingSelfModel", "world-runtime/cognition", False, "current", True, True),
)


IMPLEMENTATION_ONLY_PUBLIC_CLASSES = frozenset(
    {
        "world_runtime.CapabilityRequest",
        "world_runtime.CapabilityResult",
        "world_runtime.CognitionEngine",
        "world_runtime.DecisionLedger",
        "world_runtime.DomainProtocolService",
        "world_runtime.EvidencePredicate",
        "world_runtime.ExecutionService",
        "world_runtime.GovernanceService",
        "world_runtime.InProcessRealityBoundary",
        "world_runtime.InvestigationBudget",
        "world_runtime.InvestigationCandidate",
        "world_runtime.InvocationContext",
        "world_runtime.LedgerEvent",
        "world_runtime.MemoryService",
        "world_runtime.OntologyRegistry",
        "world_runtime.ProviderDescriptor",
        "world_runtime.ProviderHealth",
        "world_runtime.ProviderRegistry",
        "world_runtime.RecoveryDisposition",
        "world_runtime.RecoveryResolution",
        "world_runtime.RecoveryService",
        "world_runtime.ResponsibilityService",
        "world_runtime.SQLiteLedger",
        "world_runtime.StateBundleService",
        "world_runtime.BundleValidation",
        "world_runtime.WorldRuntime",
        "world_runtime.cognition.CognitiveController",
        "world_runtime.cognition.ExperienceConsolidator",
        "world_runtime.cognition.ExperienceResolver",
        "world_runtime.cognition.InvestigationBudget",
        "world_runtime.cognition.InvestigationCandidate",
        "world_runtime.cognition.MetaControllerEngine",
        "world_runtime.cognition.MetaPolicyJournal",
        "world_runtime.cognition.PolicyPromoter",
        "world_runtime.cognition.RepresentationReviser",
        "world_runtime.cognition.RevisionPlanner",
        "world_runtime.cognition.SearchPolicy",
        "world_runtime.cognition.SelfModelCalibrator",
        "world_runtime.cognition.StagedMetaPolicy",
        "world_runtime.cognition.EpistemicStateEstimator",
    }
)


def public_semantic_classification() -> dict[str, PublicSemanticClass]:
    return {entry.symbol: entry for entry in PUBLIC_SEMANTIC_CLASSES}
