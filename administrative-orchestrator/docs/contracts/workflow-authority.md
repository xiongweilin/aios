# Governed workflow authority contract

This document defines the authority path shared by Administrative case kinds. It is intentionally independent of any one vertical slice, provider, or delivery milestone.

The canonical noun definitions live in `docs/contracts/domain-model.md`. This document owns how those nouns are allowed to compose into action.

## 1. Entry

A formal administrative workflow begins only after an authenticated ingress or an authorized admission path has created an `AdministrativeRequest` and durable `AdministrativeCase`.

Unstructured source material may exist before that point as receipts, artifacts, representations, evidence spans, interpretations, and candidates. None of those objects is an Administrative authority object.

```text
source event
  -> IntakeReceipt / SourceArtifact / InterpretationRecord
  -> candidate
  -> IntakeAssessment
  -> PromotionRecord
  -> AdministrativeRequest
  -> AdministrativeCase
```

Direct authenticated requests may enter at `AdministrativeRequest`; they do not need to simulate an intake candidate chain.

## 2. Main case states

```text
received
-> gathering_facts
-> ready_for_policy
-> awaiting_decision
-> authorized
-> executing
-> verifying
-> reconciling
-> completed
```

Cross-cutting states:

```text
waiting
reopen_required
failed
cancelled
```

A workflow need not traverse every state. Skipping a state is valid only when the semantic requirement represented by that state is absent under current policy, never because a transport or provider returned success.

## 3. Closure path before an external effect

The normal governed effect path is:

```text
current AdministrativeCase
        |
        v
current facts + provenance
        |
        v
current PolicyRef / PolicyEvaluation
        |
        v
current Principal / RoleAssignment / Delegation eligibility
        |
        v
Decision set
        |
        v
ApprovalSatisfaction               (when policy requires approval)
        |
        v
GovernanceBasis
        |
        v
AdministrativeObligationSet
        |
        v
ExecutionAuthorization
        |
        v
EffectRecord
        |
        v
Agent Kernel capability / Work / runtime authorization
        |
        v
physical RealityBoundary
```

Each arrow is a qualification boundary. Possessing an object on the left does not grant permission to mint the object on the right unless the transition's invariants are satisfied.

`GovernanceBasis` and `ExecutionAuthorization` are different closure layers. The basis freezes the facts/policy/organizational authority world relied upon. The authorization grants exact Administrative effect scope inside that still-current world. Kernel subsequently owns runtime authorization for physical execution.

## 4. Actors and semantic owners

| Concern | Semantic owner | Required distinction |
| --- | --- | --- |
| transport authentication | ingress/provider boundary | authenticated source != content truth |
| source capture and lineage | Administrative intake plane | artifact != interpretation |
| interpretation/extraction | bounded model/parser path | interpretation != candidate authority |
| candidate admission | deterministic rule or authorized human path | admission != authoritative fact |
| authoritative business facts | approved system/fact owner through Administrative reader | claim != authoritative observation |
| policy version and evaluation | Administrative policy plane | policy definition != evaluation |
| principal identity | Administrative identity projection | external subject != Principal |
| role/delegation eligibility | Administrative authority plane | eligibility != Decision |
| business judgment | qualified Principal | Decision != approval satisfaction |
| multi-party closure | Administrative authority plane | Decision set -> ApprovalSatisfaction |
| frozen governance dependencies | Administrative governance plane | approval != still-current basis |
| business completion requirements | Administrative obligation derivation | effect plan != obligation set |
| Administrative effect scope | Administrative server | ExecutionAuthorization != Kernel runtime authorization |
| persistent responsibility | Agent Kernel | obligation/commitment != Work |
| provider execution/recovery | Agent Kernel | execution ambiguity != retry permission |
| physical effect boundary | Agent Kernel RealityBoundary | dispatch != reality |
| authoritative read-back | independent verifier / source owner | provider success != verification |
| semantic outcome | Administrative verifier | Kernel evidence != ConfirmedOutcome |
| case completion | Administrative completion evaluator | outcome != completion |
| responsibility discharge | Kernel assessment/decision/transition protocol | case complete != responsibility discharged |
| transport delivery | transport gateway/provider | transport accepted != delivered/read |
| reopen | Administrative governed path | failure/reopen != fresh effect authority |

## 5. Facts and authority invalidation

Every authority-sensitive closure is bound to the current `authority_epoch`. A change that invalidates the facts, evidence, policy, scope, subject, or governance assumptions relied upon must prevent stale decisions, approvals, governance bases, and effect authorizations from silently carrying forward.

Case `version` and `authority_epoch` are not interchangeable. Ordinary state progress may advance case version without creating a new authority world; an authority-invalidating transition must advance or otherwise invalidate the relevant authority basis.

External governance dependencies are also revalidated through `GovernanceBasis`. A technically current case object cannot make stale organization/policy facts safe.

## 6. Obligations before effects

Administrative derives what must become true before it plans how to make it true.

```text
facts + policy + governance
          |
          v
AdministrativeObligationSet
          |
          +-> DOMAIN_STATE_VERIFIED obligation
          |
          +-> EXTERNAL_EFFECT_VERIFIED obligation
                    |
                    v
          ExecutionAuthorization
                    |
                    v
                EffectRecord
```

The obligation set is not reverse-engineered from effects after execution. An effect that is not linked to the required obligation cannot satisfy that obligation merely because it succeeded.

Compensation and correction are new governed work. They require their own current authority and evidence; they are not hidden rollback semantics.

## 7. Reality verification and completion

The return path is:

```text
Kernel execution evidence
        |
        v
fresh authoritative read-back
        |
        v
EffectRealizationAssessment
        |
        v
ConfirmedOutcome
        |
        v
CompletionAssessment over AdministrativeObligationSet
        |
        +-> COMPLETED
        +-> WAITING / RECONCILING / REOPEN_REQUIRED / FAILED
```

`EffectRealizationAssessment.UNKNOWN`, an unavailable verifier, lost provider acknowledgement, or inconsistent read-back remains explicit uncertainty. It cannot be converted into success by workflow replay.

Completion is bounded to the declared Administrative obligations. A completed case can still have Kernel responsibility requiring a separate discharge decision.

## 8. Commitment path

An admitted self-commitment uses the same authority discipline but does not manufacture an external effect merely because the commitment exists.

```text
EvidenceSpan
  -> CandidateCommitment(explicit_self_commitment)
  -> SpeakerPrincipalResolution
  -> authorized admission
  -> meeting-commitment AdministrativeCase
  -> CommitmentRecord
  -> persistent Kernel responsibility
```

A suggestion, aspiration, ambiguous statement, information, or assignment to another person cannot take this path as an explicit self-commitment.

Due-time revision or cancellation invalidates stale timers and reminders. `OVERDUE` records temporal state; it is not equivalent to failure. Fulfillment and responsibility discharge remain separate.

## 9. Outbound communication path

Governed communication is an effect with an additional content-integrity boundary:

```text
fixed/bounded draft generation
  -> CommunicationDraftRecord
  -> frozen content digest
  -> current Administrative authority
  -> Kernel capability / execution identity
  -> transport-only gateway
  -> provider
  -> canonical provider read-back
  -> CommunicationEffectRecord delivery state
```

The same durable event identity is reconciled after a lost acknowledgement. A lost acknowledgement is not permission to mint a new delivery identity and send again.

```text
draft != send authority
transport_accepted != delivery_confirmed
delivery_confirmed != human_read
```

## 10. Investigation and governed reframing path

When the current case model cannot support safe closure, Administrative may
open a bounded investigation without granting a new execution path:

```text
anomaly / conflict / missing qualification
        |
        v
InvestigationTrigger
        |
        v
InvestigationRequest
        |
        v
bounded InvestigationClient / advisory investigation adapter
        |
        v
schema-validated InvestigationProposal
        |
        +-> read-only evidence request / human question
        +-> ReframingProposal
        +-> ReopenAssessment
                    |
          +---------+---------+
          v                   v
   PRESERVE_CLOSURE       authorized REOPEN
                              |
                              v
                     authority_epoch + 1
                              |
                              v
                    fresh facts / policy / authority
                              |
                              v
                         new closure
```

The advisory boundary receives only bounded references and constraints. It
does not receive provider-write credentials, unrestricted tenant data, the
Administrative database, or Kernel action APIs. Its output is untrusted
advice. `ReopenAssessment` is not a reopen; `ReopenRecord` is created only by
an authorized Administrative path.

`OUTCOME_UNKNOWN` first follows Kernel historical execution/read-back
reconciliation. Investigation is allowed only when an explicit reconciliation
reference shows that an Administrative-level ambiguity remains. A model
opinion cannot substitute for provider evidence. The request boundary verifies
the reference against the case's persisted Kernel execution projection and a
terminal Kernel recovery resolution; an arbitrary caller-supplied string is not
accepted as reconciliation evidence.

Every reopen must advance the single existing `authority_epoch`, preserve old
Effect/Outcome/Commitment history, and fence stale authorization by epoch.
Case completion, responsibility discharge, and reopen remain separate
transitions.

## 11. Invalid shortcuts

The implementation must reject or fail closed on at least these semantic shortcuts:

```text
source authenticity -> content truth
interpretation -> authoritative fact
candidate -> AdministrativeCase without admission
external sender/speaker label -> Principal
role membership -> Decision
Decision -> multi-party approval satisfaction
ApprovalSatisfaction -> effect without current GovernanceBasis
GovernanceBasis -> unlimited effect scope
ExecutionAuthorization -> Kernel runtime authorization
AdministrativeObligation -> Kernel Work
request -> physical provider effect
provider success -> ConfirmedOutcome
Kernel execution evidence -> Administrative completion without semantic read-back
OUTCOME_UNKNOWN -> blind resend
REOPEN_REQUIRED -> new effect without fresh closure
commitment candidate -> persistent responsibility without qualification/admission
transport accepted -> human read
workflow return -> responsibility discharge
investigation proposal -> Decision / Authorization / Work
reframing proposal -> case mutation
reopen recommendation -> RealityBoundary
OUTCOME_UNKNOWN -> model guess
old authority epoch -> new physical effect
```

## 12. Evidence required for closure

A case may be declared complete only when the current case kind's obligation set is satisfied with the required proof mode and no blocking reconciliation difference remains.

For an external-effect obligation this normally requires:

- a current obligation under the current `GovernanceBasis`;
- a matching Administrative `EffectRecord` and obligation link;
- current authority lineage;
- Kernel-owned physical execution/recovery identity;
- independent authoritative read-back;
- a verified `EffectRealizationAssessment`;
- the required bounded `ConfirmedOutcome`.

For a domain-state obligation it requires the corresponding verified Administrative domain-state fulfillment, not a fake external effect.

A UI success message, HTTP status, workflow return value, provider receipt, transport acceptance, or historical approval cannot satisfy these requirements by itself.

## 12. Audit minimum

For each material transition retain stable references sufficient to reconstruct:

- source/request identity and admission lineage when applicable;
- case identity, version, and authority epoch;
- fact/evidence versions relied upon;
- policy/version and qualification inputs;
- Principal/role/delegation basis;
- Decisions and `ApprovalSatisfaction`;
- `GovernanceBasis`;
- `AdministrativeObligationSet`;
- `ExecutionAuthorization` and `EffectRecord` where external action exists;
- Kernel responsibility/Work/execution references where applicable;
- read-back evidence and realization assessment;
- `ConfirmedOutcome` and `CompletionAssessment`;
- reconciliation, reopen, fulfillment, communication, and responsibility-discharge lineage where applicable.

Historical milestone or provider-specific identifiers may appear in immutable audit or compatibility records, but they do not define the semantics above.
