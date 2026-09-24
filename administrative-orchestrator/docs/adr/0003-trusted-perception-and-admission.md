# ADR 0003 — Trusted perception and admission boundary

Status: Accepted

Date: 2026-09-10

## Context

M5 established the Administrative trusted-action path: authenticated
requests become durable Administrative cases, policy and authority are
evaluated, bounded effects are handed to Agent Kernel, and completion is
proved against fresh reality. M6 adds the upstream problem: messages,
documents, and future meeting records are non-structured source material,
not yet Administrative truth.

Without an explicit boundary, an extractor or model could silently turn a
provider event, a displayed sender, or a high-confidence sentence into an
authoritative fact, an approval, or executable work. That would bypass the
M5 authority and verification chain.

## Decision

### 1. One Administrative product repository

M6 remains in the `administrative-orchestrator` product monorepo. The
repository gains an Administrative Intake Plane as an upstream semantic
boundary, implemented under `src/administrative_orchestrator/intake/` when
the durable implementation begins. Inbox, document evidence, and future
meeting shadow support share this repository because they depend on the
same Administrative migrations, identity bindings, admission policy, and
acceptance lifecycle.

Process, image, credential, network, and scale isolation may still be used
at deployment time. Those deployment boundaries do not create new
repositories.

### 2. Canonical intake chain

The M6 chain is:

```text
human / organizational reality
        |
        v
provider event authenticity
        |
        v
IntakeReceipt
        |
        v
SourceArtifact
        |
        v
EvidenceSpan
        |
        v
InterpretationRecord
        |
        +--> CandidateAdministrativeRequest
        +--> CandidateCaseUpdate
        +--> CandidateFactAssertion
                    |
                    v
             IntakeAssessment
                    |
          clarify / review / admit
                    |
                    v
             PromotionRecord
                    |
                    v
          existing IngressReceipt
                    |
                    v
          AdministrativeRequest
                    |
                    v
           existing M5 case path
```

The intake chain is upstream of M5. It does not replace `IngressReceipt`,
`AdministrativeRequest`, `AdministrativeCase`, `FactAuthority`,
`AdministrativeExecutionGrant`, Agent Kernel Work, RealityBoundary,
verification, recovery, or completion.

### 3. Durable object ownership

The following objects are Administrative durable business records. DBOS may
orchestrate fetching, parsing, inference, waiting, retry, and resume, but it
does not become the owner of their truth.

| Object | Meaning | Required boundary |
| --- | --- | --- |
| `IntakeReceipt` | One verified provider delivery | Unique by `(source_system, tenant_ref, source_event_id)`; separate from existing `IngressReceipt` |
| `SourceArtifact` | Immutable captured source representation and provenance | `source_event_id` is not `canonical_source_ref`; raw binary is held by `ArtifactStore`, not PostgreSQL |
| `EvidenceSpan` | Immutable locator into an artifact representation | Promoted claims link to a span or record why no span exists |
| `InterpretationRecord` | Append-only model/parser output | Keeps model/provider/schema/version/digest and evidence references; never overwrites an earlier interpretation |
| `CandidateFactAssertion` | Untrusted candidate fact | Candidate authority is limited to `CLAIM` or `ATTESTED_CANDIDATE`; `AUTHORITATIVE` is not constructible here |
| `CandidateAdministrativeRequest` | Candidate request interpretation | Historical candidates remain; supersession is explicit |
| `CandidateCaseUpdate` | Candidate update for a conversation already bound to a case | Requires human review in M6; it does not rewrite a case or create a duplicate case |
| `IntakeAssessment` | Disposition and basis for a candidate | Final disposition comes from a deterministic rule or authorized human reviewer, not model confidence |
| `PromotionRecord` | Audited candidate-to-Administrative promotion | Uniquely binds an admitted candidate to at most one existing `AdministrativeRequest` |

### 4. Authenticity is not content truth

The provider boundary may prove that a provider delivered an event. It does
not prove that the message body, attachment, displayed sender, or extracted
business statement is true.

Inbox identity resolution therefore follows this chain:

```text
provider event authenticity
        -> canonical provider fetch
        -> provider tenant
        -> provider-native actor identity
        -> directory identity / mapping
        -> Administrative IdentityBinding
        -> Principal
```

`From: ceo@example.com` is source content and is not by itself a Principal.
Provider credentials are perception credentials; they are not Administrative
authority credentials and are not Kernel reality-write credentials.

For the Feishu reference slice, the official SDK long connection hands a
metadata-only envelope through the gateway to the Administrative HTTP
boundary. The long-connection event does not reliably carry the HTTP callback
verification token, so the gateway uses a dedicated transport credential for
this internal handoff. The boundary verifies that credential, and verifies a
provider token too whenever one is present; direct callback mode continues to
require the provider token and optional signature. It then writes a verified
`IntakeReceipt` and `intake.feishu.received` outbox event in one transaction.
The receipt/outbox job payload contains provider delivery metadata only;
message body/content is fetched canonically by the asynchronous worker after
durable acceptance. A duplicate delivery reuses the delivery identity, while
a conflicting reuse fails closed. URL-verification and signed HTTP callback
headers are not part of this long-connection reference slice unless a
separate callback transport is enabled. Canonical fetch, artifact persistence,
identity resolution, interpretation, and candidate projection are not part of
the metadata handoff response path.

### 5. Interpretation is historical and non-authoritative

An artifact can have multiple immutable interpretations:

```text
Artifact A -> profile/model v1 -> Interpretation A
Artifact A -> profile/model v2 -> Interpretation B
```

Both records remain addressable. A later model result cannot mutate the
artifact, erase an earlier interpretation, create `FactAuthority.AUTHORITATIVE`,
mint a Decision, satisfy an Approval, create an
`AdministrativeExecutionGrant`, create Kernel Work, or perform a physical
effect.

All source content is untrusted data, including prompt-injection text. The
Model Gateway port is inference-only and must be configured explicitly; a
development LiteLLM endpoint is not the public Administrative semantic
contract and production configuration must not hard-code `127.0.0.1` or one
provider.

The candidate projection service is a pure boundary: it may select supported
candidate fields and produce a `CandidateProjection` containing
`CandidateAdministrativeRequest`, `CandidateFactAssertion`, and an optional
`DraftResponse`. It cannot persist a request, resolve authority, call a
provider, dispatch a draft, create a Decision or Grant, or submit Kernel Work.
The string `DraftResponse` is therefore not an organizational communication
effect; delivery requires a separate future contract and authority path.

### 6. Admission is explicit and staged

M6 rollout states are:

```text
SHADOW -> HUMAN_CONFIRMED -> BOUNDED_AUTO_ADMISSION
```

`SHADOW` produces source, interpretation, candidate, and a disposition
recommendation without creating an `AdministrativeRequest`.

The primary M6 path is `HUMAN_CONFIRMED`: an authorized reviewer (or a
deterministic rule at a later explicitly enabled boundary) records the final
`IntakeAssessment(ADMIT)`, and one transaction creates the
`PromotionRecord` plus the existing `IngressReceipt`/`AdministrativeRequest`
lineage. LLM confidence is never admission authority.

Bounded auto-admission is not enabled by default and is not required for the
first reference slice. If enabled later, it must require authenticated source,
resolved identity, supported intent, complete required fields, no unresolved
ambiguity, no existing bound case, and an explicit admission policy.

The implemented Operations API exposes this boundary as a separate review and
promotion sequence. A reviewer with the intake-review permission records a
final human `IntakeAssessment(ADMIT)`, then may set `bridge_to_m5=true` only
for `employee-onboarding` and a human-selected non-blank `subject_ref`. The
bridge uses the existing idempotent promotion service and onboarding policy
path, creates the normal `PromotionRecord`/`IngressReceipt`/
`AdministrativeRequest`/case lineage, and preserves every bridged candidate
fact as `FactAuthority.CLAIM`. It does not mint `FactAuthority.AUTHORITATIVE`,
create Kernel Work, perform an external effect, or skip M5 verification and
completion. Replaying the same source identity is idempotent; a different
requester or conflicting lineage is rejected.

Authoritative refresh is a separate M5 operation. The approved HRIS reader
may overlay the authoritative onboarding fields and trigger policy
re-evaluation; request-only intake fields remain claims. Freshness and value
changes are checked before governed transitions. A stale or changed
authoritative dependency blocks continuation and uses the existing
`GOVERNANCE_STALE` reopen/reassessment boundary. Human admission is therefore
permission to enter the governed M5 path, not proof of external-system truth.

### 7. Conversation and meeting boundaries

Inbox semantics are conversation-first: provider, tenant, and thread identify
the `ConversationRef`, which contains message revisions. Before admission,
new messages create new interpretations/candidates and may explicitly
supersede earlier candidates while retaining their history. After admission,
a message for a bound case becomes a `CandidateCaseUpdate` requiring human
review; it does not silently create a second case or rewrite the existing
case.

Meeting remains contract/shadow-only in M6. A future `CandidateCommitment`
may be produced, but a transcript or action item never directly becomes a
responsibility, AdministrativeRequest, or Kernel Work.

### 8. Artifact and storage boundary

`ArtifactStore` is the port for content-addressed raw PDF, MIME, attachment,
and other source representations:

```python
class ArtifactStore(Protocol):
    def put(...): ...
    def get(...): ...
    def verify_digest(...): ...
```

SHA-256 (or the repository's established digest standard) binds the stored
representation to metadata and evidence. PostgreSQL stores metadata,
provenance, digests, storage references, spans, interpretations, candidates,
assessments, and promotion lineage—not raw binary content. Missing objects,
digest mismatch, corruption, and storage unavailability fail closed without
fabricating an interpretation or admission.

The current implementation wires the Feishu canonical file/image fetch into
the provider-neutral attachment processor. `FilesystemArtifactStore` stores
bytes as SHA-256 content-addressed objects outside PostgreSQL, publishes new
objects atomically, and verifies the digest on read; the production worker
mounts a durable named artifact volume. `SourceArtifact` retains MIME/size/
digest/storage-reference metadata and `EvidenceSpan` retains immutable
representation locators. No raw document body belongs in `IntakeReceipt` or
an outbox payload, and no attachment is authoritative merely because it was
stored or interpreted. A real provider attachment run, OCR/document
interpretation, or document-to-Work behavior remains unproven until staging
evidence records it.

### 9. Workflow authority map

| Transition | Owner | Evidence / guard |
| --- | --- | --- |
| Provider delivery -> authenticated event | Provider adapter / deterministic verifier | Signature/token/tenant verification result |
| Event -> `IntakeReceipt` | Intake persistence boundary | Unique delivery key and delivery digest |
| Receipt -> `SourceArtifact` | Intake normalizer + `ArtifactStore` | Canonical source reference, content digest, retention metadata |
| Artifact -> `EvidenceSpan` | Deterministic parser/OCR or bounded extractor | Representation digest and immutable locator |
| Artifact/span -> `InterpretationRecord` | Inference worker through Model Gateway | Model/profile/schema/version, response digest, evidence refs |
| Interpretation -> candidate | Candidate builder | Candidate authority type excludes `AUTHORITATIVE`; source refs required |
| Candidate -> final assessment | Deterministic rule or authorized reviewer | Disposition, basis, reviewer/rule provenance, current candidate version |
| Admitted candidate -> promotion | Transactional admission service | Unique candidate/admission key; existing-case update guard |
| Promotion -> M5 request/case | Existing Administrative ingress/service | Existing M5 identity, fact, policy, authority, obligation, Kernel, verification, and completion gates |

Invalid transitions are fail-closed: model output cannot grant authority;
provider delivery cannot become a unique business request by itself; an
unknown execution result is not retry permission; and candidate state cannot
call Kernel or physical providers directly.

### 10. Provider and cross-repository boundary

M6 PR1 did not choose or implement a provider. PR9 selects Feishu as the
reference provider based on current local evidence. The existing gateway may
only own transport, event authenticity, delivery identity, and explicitly
signed forwarding. The Administrative adapter performs canonical fetch,
source/artifact lineage, identity resolution, interpretation, and candidate
projection after durable acceptance; neither component may persist business
authority, create Administrative cases, or own admission or completion. A
gateway change, if necessary, is a separate compatibility PR;
`agent-kernel`, `meta-controller`, and unrelated repositories are not modified
for M6 convenience.

The current repository also contains a configurable Feishu runtime that builds
the webhook boundary, canonical fetcher, model gateway, and artifact store from
deployment settings and injects the worker processor. Missing processing
dependencies fail closed. A production Feishu credential, canonical-fetch
route, model gateway, artifact root, and identity binding still require fresh
real-staging evidence; this ADR does not assert that those external
integrations have run successfully.

### 11. M5 compatibility and replay matrix

M6 is an upstream additive change. The following M5 gates are rerun only when
their owned boundary changes:

| Changed boundary | Required replay |
| --- | --- |
| Agent Kernel supported pin or Kernel bridge | Kernel recovery/cutover gates |
| OIDC/authentication/JWKS | Identity, discovery, rotation, and authorization gates |
| Odoo/Keycloak readers, writers, or verifiers | Connector ambiguity, reconciliation, and semantic verification gates |
| Artifact/storage topology | DR, RPO/RTO, corruption, and restore gates |
| Intake-only code | M6 intake gates plus normal affected repository CI |

If an intake change crosses an existing M5 production trust boundary, the
relevant real-staging evidence is required; unit tests cannot substitute for
that evidence.

## Consequences

- Non-structured source can be retained and reinterpreted without changing
  Administrative truth in place.
- Human-confirmed admission becomes an explicit, auditable boundary before
  the trusted M5 action path.
- Model/provider failure preserves source evidence and leaves admission
  pending rather than fabricating business state.
- The Administrative monorepo remains the single semantic/versioning owner.
- M6 adds durable contracts and tests without creating a second Work runtime,
  authorization system, retry authority, or RealityBoundary.

M6 remains incomplete until the real-staging evidence record proves the
provider-to-review-to-human-confirmed-M5 path and the applicable M5 external
system behavior. Repository tests, synthetic fixtures, and configuration
presence checks are not a substitute for that record.
