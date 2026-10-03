# Precise Semantics

> **Migrated design reference (not the current implementation contract):** Transferred from [guide/engineering/precise-semantics.md](https://github.com/xiongweilin/guide/blob/511c073322c6b38ed2d36b32492836abf4d69b58/engineering/precise-semantics.md) to preserve engineering rationale. Current AIOS behavior, authority, state, and contracts are defined by AIOS's maintained `docs/`, `contracts/`, source, and tests. The conceptual framework belongs to [guide](https://github.com/xiongweilin/guide); this note does not define its foundational ontology.

[English](./precise-semantics.md) | [简体中文](./precise-semantics.zh-CN.md)

> Role: translate "reality — purposeful finite actor — six-dimensional boundary — sufficiency — exploration/decision — action chain" into implementable, verifiable engineering semantics that resist silent substitution.

The engineering goal is not six fields, six tables, or six services, and not a universal `sufficient=true`. The dimensions describe the current boundary; epistemic status cuts across representations; sufficiency gates concrete transitions; exploration and decision are activities; the action chain connects decision to reality and returns feedback.

A semantic distinction does not automatically require an independent class, durable entity, table, or service. Split implementation objects only when independent identity, lifecycle, authority, concurrency, provenance, recovery, or retention materially matters.

## 0. Engineering chain

```text
reality-side input / trigger
→ distinction and current boundary
→ sufficiency check
→ exploration or decision
→ governance basis / authorization
→ execution
→ real-world effect
→ observation
→ verification
→ outcome / obligation completion
→ revalidation / recovery / reopening
```

The chain is not strictly one-way; reality-side feedback may reopen any earlier position.

## 1. Reality is not a database field

- Reality is not an object waiting to be completely serialized.
- The distinguishable range is constrained by sources, sensors, APIs, language, tools, permissions, and capability.
- The distinguished range is what the system has actually formed and can invoke.
- Schemas, enums, labels, ontologies, and policy categories may be default distinctions.
- New tools, permissions, relations, and interfaces can change future distinguishability.

When an open request, reframing, or autonomous trigger changes goal, scope, authority, irreversibility, or completion semantics, preserve at least:

```text
boundary context
- purpose / scope
- current distinctions
- key relations
- causal assumptions
- time scale / validity
- possibility / candidate space
- value / hard constraints
- default assumptions
- unknowns
- sources / versions
```

A fixed, already-sufficient machine contract may avoid repeatedly persisting the full context, but not bypass a materially changed semantic boundary.

## 2. Minimum engineering responsibility of the six dimensions

| Dimension | Preserve at least |
| --- | --- |
| Distinction | objects, fields, categories, scope, problem framing, versions |
| Relation | dependencies, roles, authority, ownership, composition, network, participants |
| Causality | intervention hypotheses, effect paths, dependencies, failure and recovery mechanisms |
| Temporality | ordering, validity, history, delays, windows, path dependence, reopen conditions |
| Possibility | candidates, unknowns, reachability, exclusion grounds, recovery and alternatives |
| Value | goals, hard constraints, rights, commitments, risks, normative conflicts |

Physical one-to-one decomposition is not required. Silent illegal substitution must remain impossible.

## 3. Epistemic status and provenance

External input should distinguish at least:

`raw input → representation → claim → supported / authoritative fact`

Minimum fact claim:

```text
fact claim
- key / value
- source
- source_ref
- source_version
- observed_at
- provenance
- authority: claimed | derived | authoritative
- epistemic_status:
  unverified | supported | disputed | refuted | unknown | needs_revalidation
```

Model extraction, user input, cache, search index, and synchronized copies are not authoritative facts by default.

`record exists != content true`

`high model confidence != source authority`

Current qualification should not be a permanently frozen historical field either.
When a conclusion depends on premises, loss of current qualification in those
premises should propagate through the dependency chain. Independent evidence
with a still-current reality-side basis may remain current. History is retained;
current qualification is recomputed from dependencies.

## 4. Sufficiency mechanism must be preserved

A final "sufficient" state cannot be separated from how it was established.

### Interpretive

```text
interpretive sufficiency
- target_transition
- boundary_version
- scope / purpose / timescale
- evidence / counterevidence
- assumptions / default distinctions
- competing explanations
- residual_unknowns / accepted_risks
- rationale
- accountable_judger
- disposition
- reopen_conditions
```

### Specified

```text
specified sufficiency rule
- rule_id / version
- authority_source
- applicability
- valid_from / valid_until
- required_inputs
- predicate / threshold / guards
- exceptions

specified evaluation
- rule_ref
- input_versions
- result
- unmet_conditions
- evaluator
- evaluated_at
```

`interpretive judgment != specified rule evaluation`

`rule evaluates true != rule applicable / current / authoritative`

Material ambiguity in applicability returns to interpretive sufficiency. Repeated interpretation becomes a machine rule only through explicit rulemaking, versioning, and authority.

Sufficiency is an engineering responsibility, not a required universal payload. A concrete system may realize it through owner-local qualification / admission, explicit basis refs, guards, review cases, and domain acceptance contracts. Those mechanisms must preserve why a transition is currently allowed without introducing a single cross-domain `Sufficiency` object.

## 5. Prohibit semantic shortcuts

| Established | Does not automatically establish |
| --- | --- |
| request received | problem framing sufficient |
| schema contains category | reality has only that boundary |
| data received | content true |
| model confidence high | authoritative fact |
| fact usable | policy satisfied |
| policy satisfied | decision valid |
| decision valid | authorized |
| authorized | executed |
| provider success | real-world effect occurred |
| effect occurred | postcondition verified |
| verification passed | all obligations complete |
| case complete | long-term responsibility discharged |
| historically valid | currently valid |

A field crossing more than one such boundary is a semantic-flattening risk.

## 6. Identity, role, delegation, and authorization

Authentication answers only "who is this?"

Authorization should bind at least:

```text
authorization
- principal
- operation
- resource / subject
- scope
- authority_source
- delegation_ref
- issued_at
- expires_at / revocation_version
```

Roles, titles, historical assignments, and business decisions cannot automatically become current resource permission.

`definition power != judgment power != decision power != execution permission`

## 7. Policy definition, evaluation, and decision

```text
policy version
- policy_id
- version
- owner
- effective_range
- definition_summary

policy evaluation
- policy_version
- input_versions
- result
- rationale / unmet_conditions
- evaluated_at

decision
- decision_id
- subject
- scope
- purpose
- decision_maker
- authority_basis
- boundary_version
- policy_version
- input_versions
- disposition
- created_at
```

A decision binds the boundary, inputs, and policies that supported it at the time.

An old identifier still existing does not mean the decision remains usable now.

Rule applicability, activation, and concrete execution authorization must also remain distinct.

## 8. Governance basis

Consequential decisions or authority grants should preserve a reconstructable basis:

```text
governance basis
- subject / case
- boundary_version
- fact_dependencies
- relation_dependencies
- causal_assumptions
- temporal_validity
- possibility_constraints
- value_constraints
- policy_versions
- required_approvals
- authority_refs
- residual_unknowns
- expected_self_changes
- reopen_conditions
- created_at
```

Its purposes are to reconstruct why something held then and to decide whether it still holds now.

A field expected to change as an effect of execution should not incorrectly invalidate its own basis; genuine prerequisite changes must trigger revalidation.

## 9. State and transition

A consequential transition checks at least:

```text
current_state
+ trigger
+ expected_version
+ preconditions
+ sufficiency_basis
+ current_authorization
+ decision / governance_basis
+ temporal_validity
+ allowed_side_effects
→ next_state
```

A valid endpoint cannot prove a valid transition.

Use versions, ETags, compare-and-swap, optimistic locking, or equivalent for concurrency. On conflict, reread current state instead of allowing last-write-wins to erase a semantic conflict.

## 10. Scope and side effects

Operations should declare:

- what may change;
- what must not change;
- allowed side-effect types;
- target postconditions;
- critical invariants.

After execution, verify both target fields and important non-target fields.

Expanding subject set, authority, scope, or side-effect type requires a new sufficiency / decision / authorization path.

## 11. Temporal validity

Current grounds can become invalid when any of these change:

- source or source version;
- policy version;
- role, delegation, or authorization;
- scope, partition, or assignment;
- model, data, code, or tool;
- dependency, environment, or resource;
- unresolved review;
- key assumption;
- value or rights condition.

Therefore:

`record is recent != dependencies remain valid`

Freshness should check source, dependencies, and the current task rather than
timestamps alone. Staleness is not a universal unusability bit for every fact:
older evidence can remain adequate for a task whose relevant distinctions have
not changed, while recent evidence can still be inadequate if it omits a
task-relevant distinction. Explicit policy, authorization, and deadline expiry
remain strict validity constraints.

## 12. Review, revalidation, reopening, and reauthorization

- **review obligation**: a change occurred that requires another check;
- **revalidation**: determine whether old facts, decisions, grounds, or permissions still apply;
- **reopening**: restore fact acquisition, candidate generation, or governance process;
- **reauthorization**: obtain execution authority again.

Dependency change usually creates review first. It should not rewrite history or manufacture a new decision.

`reopen != automatically authorized`

Cross-version migration requires a separate semantic check. A new version being
able to parse old records establishes data compatibility, not preservation of
the old judgment. Old conclusions remain currently qualified only when an
explicit preservation basis shows that the relevant judgment, external goal, or
constraint is preserved. Otherwise history remains intact while the conclusion
returns to review or revalidation.

## 13. Idempotency and external effects

The same idempotency key can prevent duplicate request processing but cannot prove external side effects are safely repeatable.

```text
execution attempt
- request_id
- decision_ref / authorization_ref
- subject / resource
- operation
- idempotency_key
- expected_postconditions
- provider_ref
- started_at / ended_at
- transport_result
```

Payments, messages, account creation, and permission grants may already have occurred after a timeout.

`transport idempotency != effect idempotence`

Ambiguous results enter reconciliation rather than defaulting to failure or retry.

## 14. Local transactions and external consistency

A database transaction provides local atomicity, not atomic commitment with external reality.

Use transactional outbox, inbox / deduplication, saga, compensation, durable workflow, reconciliation, or another domain-appropriate mechanism.

Regardless of implementation, partial success and unknown effect must be representable.

## 15. Observation reads reality

```text
observation
- authoritative_source
- subject_identity
- source_version
- observed_at
- availability
- freshness
- existence
- state
```

At minimum allow:

`present | missing | unavailable | unknown`

and:

`current | stale | unknown`

Source unavailability is not object absence.

## 16. Verification checks postconditions

```text
verification
- execution / effect_ref
- expected_postconditions
- observation_ref
- disposition:
  verified | missing | inconsistent | unavailable | stale | unknown
- diff
- verifier
- verified_at
```

Verification reads an appropriate reality-side source and checks identity, target state, scope, and unintended side effects.

Executor success output cannot replace reality-side verification.

## 17. Continuous effect provenance

If the system claims "this operation produced this result," it should trace:

`trigger → boundary → sufficiency → decision → authorization → execution → observation → verification → outcome`

A correct endpoint does not prove the causal chain.

## 18. Obligations independent of the planner

The planner should not define what the business requires for completion.

```text
obligation
- obligation_id
- subject
- required_state / action
- authority_class
- required
- source_policy / decision

completion evaluation
- obligation_set_ref
- covered_effects
- verified_results
- missing_obligations
- residual_obligations
- satisfied
```

`verified effect != case complete`

`case complete != responsibility discharged`

## 19. Record type, epistemic status, and lifecycle are orthogonal

Do not collapse record type, epistemic status, and lifecycle into one enum.

Records may carry boundary context, question candidates, evidence, observations, claims, derivations, goals, constraints, experiments, decisions, actions, policies, outcomes, and revisions.

Currently unusable does not mean historically deletable.

## 20. Audit does not rewrite history

Consequential paths should use append-only records or equivalent traceability.

Revocation, rollback, compensation, and reopening create new records rather than deleting old ones.

The system should be able to answer who decided under what boundary, inputs, and rules; who authorized; what executed; what reality became; how it was verified; and why it changed again.

## 21. Semantic entry points are trust boundaries

Content from models, services, users, or other systems must be validated according to source type before entering authoritative semantics.

A positive transition that expands authority, clears a blocker, or creates real-world side effects should stop when provenance, scope, authority, freshness, or traceability is missing.

Stopping means only "cannot proceed now." It must not fabricate the opposite fact.

When a checker, evaluator, or policy system can modify and approve its own
successor, self-approval alone does not establish semantic soundness of that
successor. The engineering trust boundary needs either a non-circular grounded
root or independently checkable preservation evidence showing why the new
version still satisfies the semantic obligations on which current decisions
depend.

## 22. Responsibility roles and failure independence

Distinguish where relevant:

- parsing / extraction;
- inference / candidate generation;
- sufficiency judgment;
- policy evaluation;
- decision;
- authorization;
- execution;
- observation;
- verification;
- reconciliation / recovery;
- review / reopening.

One process may implement several roles, but contracts and records must preserve their differences.

`role separation != failure independence`

Reviewers sharing the same data, models, metrics, identity base, authority source, technical root, or incentive structure should not be counted as independent evidence.

## 23. Multiple version axes

Consider independently at least:

- data / record schema;
- boundary semantics;
- state machine;
- policy rules;
- authorization contract;
- runtime protocol;
- model / evaluator.

`old JSON still parses != semantic compatibility`

Upgrades must inspect changed defaults, authority, scope, historical
interpretation, evaluation criteria, and reopening requirements. If a version
change can alter what counts as a valid judgment, improvement, or usable
evidence, semantic preservation must be explicit rather than inherited by
default.

## 24. Minimum deployable contract

A system that creates reality-side effects needs equivalent semantics for at least:

```text
boundary_context
fact_claim
sufficiency_basis
policy_version / policy_evaluation
decision
governance_basis
authorization
obligation_set
execution_attempt
observation
verification
effect / reconciliation_state
completion_evaluation
review_obligation
audit_record
```

These need not each be independent durable entities.

## 25. Minimum invariants

1. Current representation is not reality.
2. Schema absence is not reality-side impossibility.
3. Model output is not authoritative fact by default.
4. Interpretive and specified sufficiency cannot impersonate each other.
5. Rule satisfaction does not prove applicability, freshness, authority, or normative validity.
6. Historical interpretation cannot silently become deterministic rule.
7. Failure to find a path cannot directly become impossibility.
8. Decision cannot directly create underlying permission.
9. Execution rechecks current authorization and critical dependency versions.
10. A valid endpoint cannot prove a valid transition.
11. Expanded scope requires new sufficiency and authority.
12. Unknown provider result is not automatically failure or safe retry.
13. Verified outcome comes from reality-side readback, not executor self-report.
14. Obligations are independent of the planner.
15. Correction, rollback, and compensation do not delete history.
16. Critical dependency changes trigger review / revalidation.
17. Revalidation does not automatically renew authority; reopening does not authorize action.
18. Completion does not automatically discharge long-term responsibility.
19. Six dimensions need not map one-to-one to fields, services, or layers.
20. Role separation does not automatically create failure independence.
21. Local sufficiency does not automatically establish composition-level sufficiency.
22. A competing framing need not translate into current vocabulary before it can challenge the framework.
23. Retained history does not imply current qualification; invalid premises invalidate dependent conclusions.
24. Data-format compatibility does not imply preservation of old judgments across semantic versions.
25. Evidence freshness is task- and dependency-relative, while explicit policy and authorization expiry remains strict.
26. Self-approval, internal score improvement, or successor acceptance does not by itself establish semantic soundness.

## 26. Minimum conformance tests

At minimum test that:

- default categories cannot be treated as reality's only boundary without grounds;
- materially insufficient problem framing cannot directly enter decision / execution;
- interpretive judgment cannot be consumed as specified-rule result;
- expired, out-of-scope, unauthorized, or insufficiently applicable rules cannot release a transition;
- ambiguous applicability returns to interpretive judgment;
- rulemaking from repeated interpretation creates a new explicit version;
- when candidate space is not sufficiently bounded, no found path remains unknown rather than becoming cannot;
- changes in tools, authority, relations, or interfaces can reopen the boundary;
- high-confidence model claims cannot directly become authoritative facts;
- reviewers sharing common failure sources are not counted as independent redundancy;
- evaluator, policy, or model version changes do not silently preserve old conclusions without a semantic preservation basis;
- a checker approving its own successor is not accepted as sufficient evidence of successor semantic soundness;
- components separately sufficient but composition introducing new assumptions / authority / feedback requires composition-level grounds;
- expired policies, decisions, and permissions are rejected; older facts or evidence remain usable only when they are still adequate for the current task and their critical dependencies remain current;
- operations cannot exceed authorization scope;
- illegal transitions are rejected even when the endpoint is legal;
- expected self-change does not incorrectly invalidate its own governance basis;
- real prerequisite changes trigger revalidation;
- timeout and lost acknowledgment enter reconciliation rather than blind retry;
- provider success with reality-side mismatch cannot confirm success;
- planner omission of an obligation causes completion failure;
- history remains traceable after rollback;
- residual obligations prevent long-term responsibility discharge;
- shared storage for several semantic positions still rejects illegal substitution.

If a theoretical distinction cannot change contracts, transitions, failure paths, or tests, it should not occupy the engineering semantics layer.

## 27. Engineering quality evaluation

Semantic invariants and conformance tests constrain correctness, but passing them alone does not establish the quality of a framework's practical use or of a system implementing it. Concrete use can be evaluated through six task-relevant indicators:

| Indicator | Evaluation question |
| --- | --- |
| **Correctness** | Do distinctions, judgments, actions, and resulting claims remain consistent with available reality-side evidence, intended semantics, and observed outcomes? |
| **Usability** | Can people and systems understand, apply, maintain, and revise the framework without disproportionate friction? |
| **Reliability** | Under repeated use, changing conditions, exceptions, and failures, does the framework continue to provide dependable guidance and support correction or recovery? |
| **Performance** | Does use of the framework produce decisions, coordination, or engineering results with latency, responsiveness, and throughput acceptable for the current task? |
| **Capacity / scalability** | As users, data, tasks, domains, dependencies, and interaction complexity grow, does the framework remain usable without unacceptable degradation? |
| **Efficiency** | Are useful results obtained with proportionate costs in time, computation, money, attention, coordination, maintenance, and foregone opportunities? |

These are indicators of quality in use, not additional theoretical lenses, foundational axioms, or a universal proof of adequacy. Their relevance, measures, acceptance thresholds, and relative weights depend on the task and operating conditions. A good result on one indicator does not establish overall sufficiency; materially deteriorating reality-side results call for reviewing the current grounds and revising the applicable boundaries or contracts.

## 28. Conditional integration of judgment and prediction validation

Where a domain materially relies on forecasts, formal proofs, or evaluations for decision / authorization / execution admission, preserve **applicability conditions, sources and model versions, verification method, and current qualification**. Claims of improved empirical forecast quality require ex ante frozen predictions, independently obtained subsequent outcomes, a fixed baseline, and suitable error/calibration comparisons. Unavailable outcomes remain unknown, not fabricated hits.

Existing domain records, evidence references, and audit lineage may carry these responsibilities. Do not introduce a universal Prediction table, global scorer, or mandatory cross-domain probability metric. Formal-model fixtures cannot substitute for reality-side readback; better internal scores do not prove external objective improvement; accurate predictions do not grant decision or execution authority.

Conditional conformance checks:

- Recompute applicable mathematical examples; neither manufacture solutions when nonexistence is proven nor mistake a failed search for a proof.
- Requalify claims after material changes in assumptions, inputs, rules, evaluators, or versions.
- Do not derive empirical forecast verification from an executor's success message; preserve unknown outcomes.
- Do not silently change the baseline, horizon, evaluation population, or loss function when comparing forecast versions.
- Observed outcomes alone do not identify causal effects or modify the authorization chain.

See the [judgment and prediction validation protocol](https://github.com/xiongweilin/guide/blob/main/framework/judgment-validation.md) and [ten multi-actor cases](https://github.com/xiongweilin/guide/blob/main/framework/examples/judgment-prediction-cases.md) for methods and finite regression fixtures.
