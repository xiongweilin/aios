# Architecture

`administrative-orchestrator` is an external Domain Controller. Its architecture is organized by
semantic ownership rather than process topology or historical milestones.

## 1. System boundary

Administrative owns the organizational meaning of a matter: source lineage, facts, policy,
authority, obligations, intended business effects, authoritative verification, Outcome,
completion, and reopen.

World Runtime owns generic persistent agency and execution.

```text
organizational reality
        |
        v
+---------------- Administrative ----------------+
| perception -> admission -> case               |
| facts / policy / authority                     |
| GovernanceBasis / obligations                  |
| ExecutionAuthorization / EffectRecord          |
+----------------------|-------------------------+
                       |
                       v
                 World Runtime
 Responsibility / Work / Run
 Decision / Mandate / Authorization
 durable attempt / provider / reconciliation
                       |
                       v
                external systems
                       |
                       v
+---------------- Administrative ----------------+
| authoritative read-back                       |
| EffectRealizationAssessment                    |
| ConfirmedOutcome -> completion/reopen          |
+------------------------------------------------+
```

DBOS schedules Administrative workflows durably. Transport/provider adapters carry external
interaction. Neither becomes an alternate owner of business authority or completion.

## 2. Administrative semantic planes

### Perception and admission

```text
provider/source event
 -> IntakeReceipt
 -> SourceArtifact
 -> DocumentRepresentation
 -> EvidenceSpan
 -> InterpretationRecord
 -> Candidate*
 -> IntakeAssessment
 -> PromotionRecord
 -> AdministrativeRequest / AdministrativeCase
```

Source authenticity is not content truth. Interpretation and candidates are not authoritative
facts.

### Case, fact, policy and authority

`AdministrativeCase.version` is state/history concurrency.
`authority_epoch` invalidates authority-sensitive closure.

```text
FactSnapshot
 -> PolicyEvaluation
 -> Principal / RoleAssignment / Delegation
 -> Decision
 -> ApprovalSatisfaction
 -> GovernanceBasis
```

Governance dependencies are revalidated before authority-sensitive action or completion.

### Obligations and effect intent

```text
AdministrativeObligationSet
        |
        +-> DOMAIN_STATE_VERIFIED
        |
        +-> EXTERNAL_EFFECT_VERIFIED
                    |
                    v
          ExecutionAuthorization
                    |
                    v
               EffectRecord
```

`ExecutionAuthorization` is Administrative business authorization. It is distinct from the
generic Runtime Authorization used to cross the provider boundary.

`EffectRecord` is business intent/lineage, not proof that reality changed.

## 3. World Runtime plane

Administrative delegates bounded execution through
`integrations/world_runtime.py`.

For an external effect the bridge establishes:

```text
Responsibility
 -> Work
 -> Run
 -> Decision
 -> Mandate
 -> Runtime Authorization
 -> CapabilityRequest
 -> durable provider attempt
 -> provider invocation
```

World Runtime owns:

- persistent responsibility;
- generic Work and Run;
- generic Decisions, Mandates and Authorizations;
- capability contracts and provider selection;
- durable provider attempts and idempotent completed-result replay;
- ambiguous-result blocking and exact-target reconciliation;
- generic runtime audit/evidence.

Administrative does not reimplement those primitives locally.

World Runtime does not own Administrative obligations, HR/finance semantics,
`ConfirmedOutcome`, or case completion.

## 4. Return path from reality

```text
provider invocation
 -> external reality
 -> independent Administrative read-back
 -> EffectRealizationAssessment
 -> ConfirmedOutcome
 -> CompletionAssessment
```

Provider success is not `ConfirmedOutcome`.

If reality cannot be established, the case remains waiting/unknown, or enters governed
reconciliation/reopen. Uncertainty never becomes success by timeout or retry count.

## 5. Persistent responsibility

Business obligation and generic persistent responsibility are related but non-identical.

```text
Administrative obligation / admitted commitment
 -> Runtime standing Responsibility
 -> Runtime Work
 -> domain completion/fulfillment evidence
 -> Runtime responsibility assessment
 -> explicit Decision
 -> Runtime discharge
```

Case completion can be evidence for responsibility discharge. It is not the discharge event
itself.

## 6. Commitments and communication

A qualified self-commitment enters formal Administrative state and receives a Runtime standing
Responsibility. Creating the commitment does not automatically create an external effect.

Communication preserves frozen content identity and the distinction:

```text
transport_accepted != delivery_confirmed != human_read
```

A Runtime provider result can prove execution acceptance. Administrative read-back owns delivery
qualification.

## 7. Employee and financial domains

Onboarding, offboarding, procurement, invoice/AP preparation and expense reimbursement reuse the
same Administrative authority/obligation/effect/verification language.

Domain Controllers decide what postcondition counts as success. The Runtime only executes the
authorized bounded capability.

## 8. Reconciliation and reopen

```text
OUTCOME_UNKNOWN != retry permission
REOPEN_REQUIRED != execution authorization
compensation != hidden rollback
```

For an ambiguous provider attempt, Administrative investigation requires a matching durable
Runtime execution identity and a terminal Runtime reconciliation result. Arbitrary strings or
model opinions cannot substitute for this evidence.

Reopen addresses a stale or inadequate business framing. It advances the existing
`authority_epoch`, preserves history, and requires fresh governance.

## 9. Cognition boundary

Administrative investigation is a bounded domain workflow. World Runtime may supply generic
cognitive/epistemic primitives, but investigation output cannot mint Administrative facts,
authority, Decisions, Work, effects or completion.

There is no independently authoritative `meta-controller` service in the current topology.

## 10. Repository and process boundaries

`world-runtime` remains a separate repository because it has an independent generic contract
consumed by multiple domains.

Administrative API, Operations API, DBOS worker, Operations Console, product integrations,
migrations, deployment and DR remain in this repository because they share one Administrative
semantic/versioning lifecycle.

A process boundary is not automatically a repository boundary.

## 11. Current invariants

```text
Authentication != Administrative authority
Source authenticity != content truth
Interpretation != authoritative fact
Candidate != formal Administrative state
External identity != Principal
Decision != ApprovalSatisfaction
ApprovalSatisfaction != GovernanceBasis
GovernanceBasis != ExecutionAuthorization
ExecutionAuthorization != Runtime Authorization
AdministrativeObligation != Runtime Work
EffectRecord != external reality
Provider success != ConfirmedOutcome
Runtime execution result != Administrative semantic outcome
OUTCOME_UNKNOWN != retry permission
Case completion != responsibility discharge
Investigation != authority
ReframingProposal != reframe
Reopen != history deletion
```

If a feature requires collapsing one of these distinctions, it is not ready to enter the model.

## 12. Historical identifiers

Historical migration names, acceptance records, tags, policy identifiers, or ADR text can retain
predecessor vocabulary where changing it would corrupt replay or evidence. New code, current
architecture, and current operations use World Runtime vocabulary.
