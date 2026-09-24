# Administrative language contract

This document is the canonical vocabulary for `administrative-orchestrator`.

It defines what the product's durable nouns mean, which distinctions must remain explicit, and where Administrative semantics stop. Milestone names, staging layouts, migration names, provider brands, and historical compatibility identifiers are evidence or implementation history; they are not part of this language contract.

The code and persisted records remain authoritative for exact field shapes. This contract owns their product meaning.

## 1. One sentence model

Administrative turns observed organizational input into a qualified administrative matter, closes the applicable policy and authority questions, derives explicit business obligations, delegates bounded physical execution to World Runtime, independently verifies resulting reality, and closes or reopens the matter without collapsing uncertainty into success.

```text
source reality
  -> observation
  -> interpretation
  -> candidate
  -> admission
  -> AdministrativeCase
  -> facts / policy / authority
  -> GovernanceBasis
  -> AdministrativeObligationSet
  -> ExecutionAuthorization / EffectRecord
  -> World Runtime
  -> external reality
  -> realization evidence
  -> ConfirmedOutcome
  -> CompletionAssessment
  -> complete / wait / reconcile / reopen
```

A meeting commitment is a second entry shape into the same responsibility model: a qualified commitment becomes durable administrative state and persistent Runtime responsibility, but commitment creation itself does not imply external Work or an effect.

## 2. Perception and evidence

### IntakeReceipt

A durable record that a source event crossed an authenticated intake boundary. It proves receipt and bounded source-verification facts. It does not prove that the event's content is true.

### SourceArtifact

An immutable captured source object, referenced by digest and storage identity. The source artifact is evidence material, not an interpretation of that material.

### DocumentRepresentation

A deterministic or bounded derived representation of a source artifact, such as extracted text. It must retain lineage to the artifact and must not overwrite the source.

### EvidenceSpan

An exact locator into a source artifact or representation used to support an interpretation or candidate claim.

### InterpretationRecord

A durable record of model or parser interpretation over identified source material. Interpretation is an epistemic output: it can propose structure, intent, facts, commitments, or classifications, but it carries no organizational authority by itself.

The required distinction is:

```text
source authenticity != content truth
SourceArtifact != DocumentRepresentation
DocumentRepresentation != EvidenceSpan
EvidenceSpan != InterpretationRecord
InterpretationRecord != authoritative fact
```

## 3. Candidate and admission

### CandidateAdministrativeRequest

A proposed administrative request inferred from source material. It is not yet an `AdministrativeRequest` and cannot directly create a case, authority, Runtime Work, or external effect.

### CandidateFactAssertion

A proposed fact with source lineage. Candidate authority is intentionally limited to claim-like or attestation-candidate states. `AUTHORITATIVE` is not a candidate value.

### CandidateCaseUpdate

A proposed update to an already admitted case. It does not silently mutate the case; it remains reviewable until an authorized path applies the update.

### CandidateCommitment

A proposed commitment extracted from source evidence. Classification distinguishes explicit self-commitment from ambiguity, aspiration, suggestion, information, and assignment to another person. Only a separately qualified and admitted commitment becomes formal administrative state.

### IntakeAssessment

The disposition over a candidate: admit, clarify, informational, unsupported, duplicate, ambiguous, or require human review. A model may suggest an assessment; a model suggestion is not admission authority.

### PromotionRecord

The durable lineage proving which candidate and final assessment produced a formal `AdministrativeRequest` / `AdministrativeCase` path.

Admission means only that a candidate is qualified to enter the formal Administrative model. Admission is not proof that every candidate fact is true, and it is unrelated to World Runtime Work admission.

```text
Candidate != AdministrativeRequest
model confidence != admission authority
admission != fact authority
Administrative admission != Runtime Work admission
```

## 4. Request, case, and facts

### AdministrativeRequest

The formal organizational request admitted or submitted through a supported ingress. It records requester, channel, expressed intent, and source reference. A request is the trigger for work; it is not the durable business matter itself.

### AdministrativeCase

The durable administrative matter. A case survives processes, conversations, models, retries, and provider sessions. It owns current case state and references the current fact/policy/authority world.

`case_id` is stable identity. `version` is the optimistic/concurrency and state-history version. `authority_epoch` is a monotonic invalidation clock for authority-sensitive closure: when facts, evidence, policy, reassessment, or another authority-relevant dependency changes in a way that invalidates prior closure, a prior authority epoch must not silently authorize the new world.

```text
request identity != case identity
case version != authority epoch
new case state != permission to reuse stale authority
```

### EvidenceRef

A bounded reference to observed information with source, fact owner, observation time, and optional source version or digest. Evidence is data, not instruction.

### FactAssertion

A field-level assertion with provenance and authority classification.

Canonical authority classes are:

- `CLAIM`: asserted but not independently established;
- `ATTESTED`: accepted testimony from an eligible source under an explicit procedure;
- `AUTHORITATIVE`: observed from the approved system or owner for that fact.

An authoritative value cannot be minted merely by model confidence, transport authentication, or human admission of a request.

### FactSnapshot

The immutable current projection of facts relied upon by a case at one point in its history. Replacing current facts creates new history; it does not erase the old snapshot.

## 5. Identity, policy, and authority

### Principal

An actor identity recognized by Administrative. A transport subject, IdP user, speaker label, email address, or provider-native sender is not automatically a Principal.

### IdentityBinding

A time-bounded mapping from an external identity to an Administrative Principal. Identity binding answers who an external subject resolves to; it does not answer what that Principal may decide.

### RoleAssignment

A time-bounded role held by a Principal in an organizational scope.

### Delegation

An explicitly bounded transfer of role-use eligibility. Delegation changes eligibility; it does not itself record a decision or authorize an effect.

### PolicyRef / PolicyEvaluation

`PolicyRef` selects an immutable policy version and its ownership/effective context. `PolicyEvaluation` applies current case facts to that policy and determines the next governed disposition.

### Decision

A Principal's bounded judgment over an exact case version, authority epoch, policy, role, and scope. A Decision is not an execution authorization.

### ApprovalSatisfaction

The durable proof that the policy's required decision roles, quorum, and distinct-principal constraints are satisfied by a specific set of Decisions. One approving Decision is not equivalent to multi-party approval satisfaction.

### GovernanceBasis

The frozen basis for acting on a satisfied approval world. It binds the current fact dependencies, policy definition, organizational scope, qualified Principals/roles/delegations, approval satisfaction, authority epoch, and transaction qualifications where applicable.

`GovernanceBasis` is revalidated before authority-sensitive execution, verification, and completion. A changed dependency makes the old basis stale even if a provider operation would still technically succeed.

### ExecutionAuthorization

The Administrative server-minted exact-scope authorization used to plan an Administrative effect. It is bound to the current case/epoch, subject, target system, allowed operations, policy, authority class, supporting Decision or `ApprovalSatisfaction`, issuer, and optional expiry/revocation.

`ExecutionAuthorization` is the canonical Administrative term. It is distinct from World Runtime runtime authorization, which is owned by Kernel.

```text
external identity != Principal
Principal != RoleAssignment
RoleAssignment / Delegation != Decision
Decision != ApprovalSatisfaction
ApprovalSatisfaction != GovernanceBasis
GovernanceBasis != ExecutionAuthorization
ExecutionAuthorization != Runtime authorization
```

## 6. Qualification

Qualification is a family of explicit eligibility checks, not a universal authority object.

Examples include:

- speaker-to-Principal resolution;
- vendor/master-data qualification;
- duplicate and three-way-match assessment;
- evidence completeness;
- current identity/role/delegation eligibility.

A qualification may be a required input to governance, but qualification alone does not create a Decision, `ApprovalSatisfaction`, `ExecutionAuthorization`, Runtime Work, or external effect.

## 7. Obligations, effects, and reality

### AdministrativeObligation

One business condition that the current case must satisfy. It identifies subject, target system or domain state, required operation/postcondition, authority class, and fulfillment mode.

### AdministrativeObligationSet

The frozen set of required obligations for one case and authority epoch under one `GovernanceBasis`. Completion is assessed against this set; it is not inferred from whatever effects happened to be planned.

An obligation may be fulfilled by:

- `EXTERNAL_EFFECT_VERIFIED`: a matching external effect plus independent realization/outcome evidence;
- `DOMAIN_STATE_VERIFIED`: verified Administrative domain state without pretending that local state is an external effect.

### EffectRecord

Administrative's typed business effect intent and lineage record. It records what bounded external change is intended and which Administrative authorization supports it. It does not prove that external reality changed.

Physical provider execution, retry permission, runtime authorization, and generic recovery belong to World Runtime after cut-over.

### EffectRealizationAssessment

The explicit Administrative assessment of whether the intended effect is observed in authoritative reality. `VERIFIED` requires evidence. `UNKNOWN`, `NOT_VERIFIED`, and `MISMATCH` remain distinct.

### ConfirmedOutcome

A bounded Administrative semantic result derived from verified realization evidence. A provider response, transport acceptance, Runtime execution result, or object existence is not by itself a `ConfirmedOutcome`.

```text
AdministrativeObligation != Runtime Work
EffectRecord != external reality
provider success != realized effect
realized effect != ConfirmedOutcome
OUTCOME_UNKNOWN != retry permission
```

An `OUTCOME_UNKNOWN`-triggered investigation is admissible only after the
Administrative boundary verifies a matching persisted Kernel execution
projection and a terminal Runtime reconciliation resolution. A non-empty string
is not by itself a reconciliation fact. Any residual ambiguity is then
Administrative investigation input, not execution permission.

## 8. Completion and responsibility

### CompletionAssessment

The deterministic assessment that every required obligation for the current `GovernanceBasis` is satisfied by the correct kind of proof. It names missing, uncovered, or mismatched obligations instead of smoothing them into success.

`CaseStatus.COMPLETED` means the declared Administrative completion contract is satisfied for the current bounded matter. It is not a universal statement that every downstream human or organizational consequence is finished.

### Persistent Runtime responsibility

Persistent responsibility is Runtime-owned. Administrative may cause or reference Runtime responsibility for obligations or commitments, and may provide completion evidence to Runtime assessment/decision/discharge protocol, but Administrative does not redefine Runtime responsibility state.

### Responsibility discharge

Responsibility discharge is a separate transition after the required Administrative evidence exists. Workflow return, effect completion, case completion, and responsibility discharge are deliberately non-equivalent.

```text
workflow finished != case completed
case completed != responsibility discharged
responsibility discharged != history erased
```

## 9. Commitment language

### SpeakerPrincipalResolution

The explicit resolution from a source speaker identity to an Administrative Principal, with provider subject and basis. A display name or speaker label is not authority.

### CommitmentRecord

The formal admitted self-commitment. It binds the committer Principal, exact action, offset-aware due time and its basis, case/authority epoch, optional scope/beneficiary, and Runtime responsibility references.

A formal commitment may become `OVERDUE` without becoming failed. Authorized late fulfillment can satisfy the commitment while preserving overdue history. Revision or cancellation invalidates stale timers/reminders.

### CommitmentFulfillmentAttestation

An authorized attestation or evidence-backed statement that the committed obligation has been fulfilled. The allowed fulfiller is governed separately from source interpretation.

```text
speaker label != Principal
suggestion != commitment
assignment-to-other != explicit self-commitment
overdue != failure
fulfillment != responsibility discharge
```

## 10. Communication language

### CommunicationDraftRecord

A frozen outbound content artifact with recipient, channel, generator identity, storage reference, digest, and size. Draft creation is not a communication effect.

### CommunicationEffectRecord

The durable Administrative delivery lineage for a communication event. Delivery states distinguish prepared, transport accepted, delivery confirmed, retrying, permanent failure, and outcome unknown. Provider message reference and content/recipient digests support reconciliation.

`read_state` is separate. A provider delivery confirmation does not prove that a human read or understood the content.

```text
draft != send authority
transport_accepted != delivery_confirmed
delivery_confirmed != human_read
lost ACK != permission to create a new event identity
```

The transport gateway remains transport-only; it does not own Administrative intent, authority, completion, or responsibility semantics.

## 11. Case lifecycle and reopen

Core case states are:

```text
RECEIVED
GATHERING_FACTS
READY_FOR_POLICY
AWAITING_DECISION
AUTHORIZED
EXECUTING
VERIFYING
RECONCILING
WAITING
REOPEN_REQUIRED
COMPLETED
CANCELLED
FAILED
```

Not every case traverses every state. A state may be skipped only when the corresponding semantic requirement is genuinely absent, never merely because an adapter returned success.

Canonical reopen reasons include no applicable policy, policy conflict, required facts that cannot be obtained within the represented procedure, unresolved authority, subject change, unresolved outcome ambiguity, reality mismatch, scope expansion, unknown risk dimension, and stale governance.

`REOPEN_REQUIRED` means the previous framing or closure is no longer sufficient. It does not itself authorize a new effect. Fresh closure is required before acting again.

## 12. Investigation and governed reframing

An investigation is a bounded Administrative response to a model or closure
insufficiency. It is not a second execution engine and it is not a source of
authority.

### InvestigationTrigger

A durable fact explaining why the current Administrative model cannot safely
continue closure. Trigger classes include ambiguous evidence, conflicting
facts, missing qualification or authority, policy underspecification,
unexpected reality, unresolved outcome, verification contradiction, stalled
obligation, commitment conflict, late evidence, and human-requested review.
`OUTCOME_UNKNOWN` may enter this path only after a Runtime reconciliation
reference exists.

### InvestigationRequest

A bounded, tenant-scoped request to investigate one case at one authority
epoch. It records the question, permitted evidence references, current fact /
governance / obligation / commitment references, creator, status, and hard
round/model/evidence budgets. It describes what needs to be learned, never a
physical action to perform.

### InvestigationProposal

An advisory result from a model or investigation engine. It may contain
hypotheses, ambiguities, missing evidence, read-only query recommendations,
human questions, possible reframings, possible reopen targets, uncertainty,
and model provenance. It cannot create a Decision, ApprovalSatisfaction,
ExecutionAuthorization, Runtime Work, authoritative fact, or provider effect.

### InvestigationEvidenceRequest / InvestigationEvidence

An `InvestigationEvidenceRequest` records a bounded request for additional
evidence. `InvestigationEvidence` records what was added, its source, owner,
version/digest references, and actor. Neither object changes case facts or
authority by itself.

### ReframingProposal

A versioned proposal that the current problem frame may be wrong. It preserves
the old frame and evidence lineage and cannot mutate `AdministrativeCase`
truth without a separate qualified Administrative transition.

### ReopenAssessment / ReopenRecord

`ReopenAssessment` is the deterministic or human disposition over an
investigation: preserve closure, require reopen, require human review,
insufficient evidence, or superseded. `ReopenRecord` is the append-only fact
that an authorized reopen occurred. It advances `authority_epoch`, records
which decisions/governance/obligations/authorizations/commitments became
historical, and never deletes or rewrites an old Effect, Outcome, or
Commitment.

```text
Investigation != Authority
Hypothesis != Fact
Recommendation != Decision
ReframingProposal != Reframe
ReopenRecommendation != ReopenAuthority
Reopen != DeleteHistory
New interpretation != new authoritative evidence
```

## 13. Non-negotiable distinctions

```text
Source authenticity != content truth
SourceArtifact != InterpretationRecord
InterpretationRecord != Candidate
Candidate != AdministrativeRequest
AI confidence != admission authority
Admission != authoritative fact
External identity != Principal
Principal != organizational authority
Recommendation != Decision
Decision != ApprovalSatisfaction
ApprovalSatisfaction != GovernanceBasis
GovernanceBasis != ExecutionAuthorization
ExecutionAuthorization != Runtime authorization
AdministrativeObligation != Runtime Work
Effect dispatch != realized effect
Provider success != ConfirmedOutcome
Completion != responsibility discharge
CandidateCommitment != CommitmentRecord
DeliveryConfirmed != HumanRead
OUTCOME_UNKNOWN != retry permission
Exception != permission to improvise
Investigation != authority
Hypothesis != fact
ReframingProposal != reframe
ReopenAssessment != ReopenRecord
Reopen != deletion
```

If a future feature cannot be described without collapsing one of these distinctions, the feature is not yet qualified to enter the model.

## 14. Field ownership rule

For every persisted decision-relevant field, the system must make it possible to answer:

```text
Where did this value come from?
Who owns the authoritative fact?
Which source/version/digest was relied upon?
How was it qualified or validated?
Which case/authority epoch used it?
Where may it be used?
What event can invalidate that use?
```

AI-derived values remain interpretations or candidates until a separate admission and fact-authority path establishes how they may enter the formal model.

## 15. Compatibility identifiers

Some migrations, staging directories, tests, workflow names, policy identifiers, and API/wire values contain historical milestone labels. They remain stable when changing them would break replay, persisted identity, acceptance evidence, or external callers.

Those strings are compatibility identifiers only. New product documentation and new semantic APIs must use the vocabulary in this contract rather than deriving meaning from a milestone number.
