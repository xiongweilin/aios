# Contracts

Current package baseline: **1.0.0**  
Contract manifest: **personal-world-contracts-v1**  
Semantic language baseline: **0.2.0**

## Provenance contracts

### SourceDescriptor

Identifies where information came from. Supported source classes:

- human-explicit
- domain-controller
- external-record
- import
- model-inference
- derived

A SourceDescriptor is not a claim that its content is true.

### Observation

An immutable record that a value was observed from a source at a time.

### Claim

An immutable assertion derived from a source and optionally backed by observations.

A Claim is not automatically a current PersonalFact.

## Personal record contracts

All personal records have:

- stable lineage_id
- monotonic revision
- subject_id
- semantic reference
- value
- source_refs
- optional claim_refs
- temporal scope
- sensitivity
- qualification status
- context and metadata

Qualification statuses:

- candidate
- current
- contested
- revalidation-required
- superseded
- retracted

The physical prior revision is never rewritten to fabricate historical supersession. Lineage order
defines later revision; historical reads preserve the status that was recorded at that time.

## Admission

A record requested as current is downgraded to candidate when its evidence is not eligible.

In particular:

- a model-inference source cannot directly create a current PersonalFact;
- an unaccepted inferred preference remains candidate;
- a preference explicitly represented as accepted-inference may be current;
- domain ingress creates candidate PersonalFacts, preserving domain ownership.

A current record cannot be replaced by a revision backed only by ineligible evidence. Such evidence
must form a separate candidate rather than silently displacing current state.

## Revision

Revision is compare-and-swap:

```text
expected_revision == current_revision
new_revision == current_revision + 1
```

A stale writer receives a conflict and must re-read.

## Projection

A ContextProjection contains:

- included current items
- contested items
- stale / revalidation-required items
- excluded_count
- source references
- purpose and scope

Candidate and retracted records are not silently promoted into normal included context.

## Service trust

Transport callers always provide `X-Service-Identity` and `X-Purpose`. Local/backward-compatible
deployments may use bearer credentials. Production v1.0 uses a short-lived signed workload assertion
(`X-Workload-Timestamp` + `X-Workload-Signature`) bound to service identity and purpose.

Authentication proves the workload identity. DataAccessProfile separately controls which purposes,
record kinds, and sensitivity levels that identity may read. The configured root subject separately
limits the whole Personal World instance to one person.

Authentication, disclosure policy, and root-subject binding are not World Runtime Authorization.

## Domain ingress

A DomainPersonalProjection carries:

- subject_id
- source_domain
- source_object_ref
- source_version
- observed_at
- domain claims

Each DomainClaim may target only one of the four frozen Personal World record kinds:
`fact`, `preference`, `relationship`, or `resource-link`. Relationship claims must supply
`target_ref` and `relation_namespace`; resource-link claims must supply `resource_ref`, `domain`,
and `relation`. Preference claims must preserve their preference origin.

This is not a domain ontology. It is an ingress shape that lets the domain preserve personal meaning
without flattening every domain projection into a generic fact and without adding domain-specific
top-level record kinds.

The HTTP boundary requires source_domain to match the authenticated service identity. Ingress creates
provenance and candidate personal records; it does not declare the domain outcome itself.

## Erasure

Full-subject erasure removes that subject's personal content while retaining only tombstone metadata
where required by storage structure.

Kind-scoped erasure removes only selected record kinds and their directly linked claim/observation
provenance. A source is redacted only when no surviving observation, claim, or record anywhere still
references it.

## Bundle

`personal-world-bundle-v1` is a recovery/export format. IDs, lineage, temporal fields, source links,
and data-access profiles are preserved. Import requires an empty store to avoid hidden merge semantics.


## Temporal reconstruction

`as_of` is deliberately bitemporal rather than a simple "latest revision before timestamp" query.
A record revision is eligible at time `t` only when both are true:

- record-time: `recorded_at <= t`;
- valid-time: `valid_from <= t < valid_until`, where missing bounds are open.

Among eligible revisions in one lineage, the highest revision is selected. A late-arriving correction
may be backdated in valid-time, but it must not appear in an as-of view before its `recorded_at`.
Revalidation, contestation, and retraction therefore create a new revision with a fresh
`recorded_at`; they do not reuse the prior revision's record-time.

## Consumer conformance

Consumer compatibility is frozen independently as **personal-world-conformance-v1**.
A consumer must verify exact contract discovery and preserve the caller purpose. The executable
suite exercises authenticated discovery, human-source admission, correction as a new revision,
purpose-bound projection, and erasure across projection and export surfaces.

The conformance suite does not make a projection authoritative. Consumers must continue to treat
Personal World output as personal context, never Runtime Authorization or domain outcome truth.

## Backup and erasure boundary

Erasure applies immediately to active canonical storage and all newly derived surfaces. Search,
ContextProjection, history and bundles produced after erasure must not expose erased personal
content.

Previously created operational backups are not live Personal World state. They must be encrypted,
access controlled and subject to a bounded retention policy outside this repository. Restoring a
backup taken before an erasure is an exceptional disaster-recovery operation and requires replaying
all erasure obligations that occurred after the backup point before the restored store is exposed.
Portable bundles are intentionally importable only into an empty store; hidden merge semantics are
not permitted.


## Root subject boundary

A production Personal World instance is bound to exactly one `PERSONAL_WORLD_ROOT_SUBJECT_ID`.
All subject-bearing reads, writes, projections, domain ingress, erasure, and bundle import/export fail
closed when they cross that root. Relationship targets and external resource refs do not become
additional Personal World subjects.
