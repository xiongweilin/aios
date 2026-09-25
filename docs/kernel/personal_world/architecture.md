# Architecture

## Mission

Personal World is the durable, user-owned representation of one person's evolving world.
It preserves personal continuity across models, agents, consoles, processes, and time.

It answers:

- What is known about this person?
- Why is it known?
- Is it still current?
- Where is the authoritative source?
- May this information be projected for this purpose?

It does not decide what should happen in the world and does not grant execution authority.

## Ownership boundary

Personal World owns:

- provenance
- observations and claims
- qualified personal facts
- preferences
- relationships
- external resource links
- temporal lineage
- freshness / revalidation state
- sensitivity classification
- purpose-limited context projection
- derived retrieval over canonical personal records

It does not own:

- Decision, Authorization, Mandate, Responsibility, Work, Run, Effect, Outcome
- provider execution or domain lifecycle
- agent routing or model routing
- secrets or credentials
- model-private memory

## Core non-substitution rules

1. Source != Observation != Claim != current personal state.
2. Historical validity != current validity.
3. Projection != canonical truth.
4. Personal context != authority.
5. Domain projection != domain ownership.
6. Model inference != accepted personal truth.
7. Derived retrieval index != canonical storage.

## Canonical data path

```text
Human / Domain / External source
        |
        v
SourceDescriptor
        |
        v
Observation
        |
        v
Claim
        |
        v
Qualification / admission
        |
        v
Personal Record Revision
        |
        v
Current lineage head
        |
        v
Purpose-limited ContextProjection
        |
        v
Cognitive plane
```

Observations and claims are immutable. Personal records evolve by appending revisions. A correction does
not rewrite prior revisions.

## Public record kinds

The v1.0 baseline intentionally exposes only four top-level personal record kinds:

- PersonalFact
- Preference
- Relationship
- ResourceLink

A new domain concept should normally remain in its Domain Controller and be referenced through a
ResourceLink or domain-namespaced projection. Personal World must not become a universal business ontology.

## Temporal model

Every record can carry:

- observed_at
- recorded_at
- valid_from
- valid_until

As-of reads select the latest recorded revision that was known and valid at the requested moment.
Current reads select the latest non-erased lineage head.

## Domain boundary

A Domain Controller can submit a `DomainPersonalProjection`. Personal World records the source,
observation, claim, and a candidate personal fact. It does not copy domain lifecycle authority.

Example:

```text
Travel Controller owns:
ticket issued / cancelled / refunded

Personal World may retain:
this person has a relationship to travel:booking:123
```

## Runtime boundary

World Runtime and Personal World are independent durable systems:

```text
Personal World:
What is the person's world?

World Runtime:
What durable agency exists, and why may it continue?
```

Runtime may reference Personal World records as basis material. It must not copy their ownership.
Personal World must not issue Runtime authorization.

## Projection boundary

Callers never need unrestricted personal state. They request a purpose-limited projection.

Projection filtering considers:

- authenticated service identity
- declared purpose
- allowed record kinds
- sensitivity ceiling
- requested scope
- qualification state
- optional retrieval query

A projection is disposable and may always be rebuilt from canonical state.

## Storage

SQLite is supported for local single-node operation. PostgreSQL is supported for shared durable
operation. Revision writes use expected-revision CAS; PostgreSQL additionally locks the current
lineage head before append.

Bundle export preserves stable IDs and lineage. Import is intentionally restore-only and requires
an empty target store.

## Retrieval

The built-in retrieval implementation is derived from canonical records. It combines lexical overlap
with deterministic hashed-vector similarity. It can be discarded and rebuilt without loss of truth.

A future external vector index must obey the same rule.


## Deployment identity and root subject

The v1.0 production profile binds one service instance to one root personal subject. This is an
instance boundary, not a new semantic object. Other people may appear as relationship targets, but
cannot be addressed as additional Personal World subjects in the same production instance.

Production workload authentication is short-lived and signed. Workload authentication,
DataAccessProfile disclosure policy, and the root-subject boundary remain distinct from Runtime
authority.
