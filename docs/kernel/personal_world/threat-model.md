# Threat model

Personal World is expected to contain some of the most sensitive long-lived data in a Personal AI OS.
Its trust boundary is therefore intentionally narrower than a normal agent memory store.

## Protected assets

- canonical personal records
- provenance and historical lineage
- sensitive relationships and resource links
- context projections
- disclosure policy
- export bundles

Secrets such as passwords, OAuth refresh tokens, API keys, and private keys are not Personal World
assets and must live in a dedicated secret store. Personal World may retain only opaque credential refs.

## Threats and mitigations

### Service identity spoofing

Threat: a caller forges `X-Service-Identity`.

Mitigation: production v1.0 requires a short-lived signed workload assertion bound to
`X-Service-Identity`, `X-Purpose`, and a bounded timestamp. Local compatibility mode may use bearer
credentials. TLS termination and secret rotation remain deployment responsibilities.

### Cross-purpose disclosure

Threat: a legitimate service asks for unrelated personal context.

Mitigation: DataAccessProfile binds service identity to explicit purposes, allowed record kinds, and a
sensitivity ceiling. Projection and search fail closed when the purpose is not allowed.

### Prompt injection causing context exfiltration

Threat: model-generated text asks the Personal World service for more data.

Mitigation: models do not authenticate directly merely because they can produce text. The calling
service identity and purpose are evaluated outside the prompt. Minimum-necessary projection is the
default API shape.

### Model inference promoted as fact

Threat: a model guess becomes durable truth.

Mitigation: model-inference sources create candidate facts. Revalidation to current is rejected unless
the record type has an explicit accepted-inference rule, currently limited to Preference.

### Malicious domain projection

Threat: one Domain Controller impersonates another or writes domain truth into personal state.

Mitigation: source_domain must match authenticated service identity. Domain ingress produces candidate
personal facts and preserves source object/version metadata; domain lifecycle remains domain-owned.

### Lost update / concurrent writers

Threat: two processes revise the same lineage.

Mitigation: monotonic revision CAS plus a unique lineage/revision database constraint. PostgreSQL locks
the current lineage head during append.

### Historical rewriting

Threat: a correction mutates what the system previously knew.

Mitigation: observations, claims, and record revisions are append-oriented. Prior record revisions are
not rewritten when superseded.

### Erasure overreach

Threat: erasing one subject or record kind deletes a source still used elsewhere.

Mitigation: source redaction occurs only after checking for surviving observation, claim, and record
references across the store. Kind-scoped erasure follows only provenance linked from selected records.

### Derived-index leakage

Threat: a vector index becomes an independent truth store or survives canonical erasure.

Mitigation: retrieval indexes are derived and rebuildable. Production external indexes must support
delete/rebuild from canonical records and must never be the sole source of a personal fact.

### Backup leakage and erasure resurrection

Threat: portable bundles or physical database backups expose personal context, or a pre-erasure
backup is restored and silently resurrects data that the user already erased.

Mitigation: bundle endpoints are admin-only. New bundles after erasure are tested not to contain the
erased values. Physical backups must be encrypted, access controlled and retained for a bounded
operator-defined window. A restore from a point before an erasure must remain isolated until all
post-backup erasure obligations have been replayed. The repository CI performs both logical bundle
restore and physical `pg_dump` / `pg_restore` drills; it does not claim that backup retention itself
can be enforced by the application process.

## Residual risks after v1.0

- workload HMAC secrets still require external rotation/secret management; mTLS is not implemented here;
- field-level cryptographic encryption is not implemented in the repository baseline;
- purpose strings are explicit contracts but not a general policy language;
- domain-specific sensitivity classification still depends on the submitting integration;
- external semantic/vector indexes require their own deletion conformance tests.


### Cross-subject access

Threat: a caller uses a valid service identity to address another person's UUID.

Mitigation: production startup requires one `PERSONAL_WORLD_ROOT_SUBJECT_ID`. Subject-bearing API
surfaces and portable bundle import/export fail closed if data crosses that root.
