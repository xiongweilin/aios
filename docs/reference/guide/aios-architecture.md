# AIOS Architecture

> **Migrated design reference (not the current implementation contract):** Transferred from [guide/engineering/aios-architecture.md](https://github.com/xiongweilin/guide/blob/511c073322c6b38ed2d36b32492836abf4d69b58/engineering/aios-architecture.md) to preserve engineering rationale. Current AIOS behavior, authority, state, and contracts are defined by AIOS's maintained `docs/`, `contracts/`, source, and tests. The conceptual framework belongs to [guide](https://github.com/xiongweilin/guide); this note does not define its foundational ontology.

[English](./aios-architecture.md) | [简体中文](./aios-architecture.zh-CN.md)

> Role: realize "reality — purposeful finite actor — six-dimensional boundary — sufficiency — exploration/decision — action chain" in a long-running autonomous AI system. AIOS is an application of the framework, not its source.

## 1. From framework to runtime

AIOS is itself a purposeful finite actor. It does not implement "reality" as a total ontology and does not claim that personal-world, databases, models, or knowledge graphs contain the whole world.

The runtime needs to preserve:

- **current boundary**: distinction, relation, causality, temporality, possibility, value;
- **epistemic status**: provenance, evidence, unknowns, disputes, versions, freshness;
- **sufficiency basis**: why the current transition is sufficient now;
- **exploration / decision state**: reopen when insufficient, choose when sufficient;
- **action chain**: decision, authorization, execution, real-world effect, observation, verification, outcome, recovery, reopening.

The six dimensions do not map to six services. They are semantic requirements that can be carried by different domain objects.

## 2. Long-running loop

```text
┌────────────────────────────────────┐
│ AIOS: purposeful finite actor                │
│                                    │
│ observe / distinguish boundary     │
│ → sufficiency                      │
│ → explore or decide                │
│ → authorize → execute              │
│ → observe → verify → reconcile     │
└──────────────┬─────────────────────┘
               │ bounded real-world effect
               ▼
            ┌─────────┐
            │ Reality │
            └──┬──────┘
               │ authoritative readback / evidence / unknown
               └────────────────────► AIOS
```

Normal operation does not depend on a human being present. Reality-side feedback can reopen any part of the current boundary.

## 3. Temporary external intervention

```text
Human
  │ query / request / required approval
  ▼
Existing Agent product
(short-lived session)
  │ authoritative inspection / explanation /
  │ bounded authorized repair / verification
  ▼
AIOS machine boundary ─────────────► Reality
  │
  └── report verified state, then disconnect
```

The external Agent:

- is not part of the AIOS runtime;
- does not create or durably own state, responsibility, or authority; it may only exercise bounded authority explicitly granted by AIOS for the session;
- does not own canonical Personal World state or domain-owned state;
- does not pause autonomous AIOS operation when its session ends.

`human present != system operation requires human`

`external Agent explanation != authoritative state`

`external Agent repair != successful recovery`

`provider reconciliation succeeded != domain outcome verified`

`domain outcome verified != domain recovered`

`domain recovered != responsibility discharged`

Provider-level reconciliation establishes only an execution fact. Domain recovery requires domain-owned reality-side observation, outcome qualification, and any required verification.

API / CLI are machine integration and maintenance boundaries, not the primary human management surface.

## 4. Architectural regions

```text
┌────────────────────────────────────────────────────────────────┐
│ AIOS — long-running autonomous purposeful finite actor                   │
│                                                                │
│ personal-world ──purpose-limited context──► internal Agent     │
│      ▲                                      / executor          │
│      │ provenance / revision                    │               │
│      └────────────────────────────────────────► domain admission│
│                                                 │              │
│ semantic-language / world-runtime / domain controllers         │
│ boundary / sufficiency / responsibility / authority /          │
│ action chain / recovery                                        │
└─────────────────────────┬──────────────────────────────────────┘
                          │
                          ▼
                        Reality
     external systems / source / build / deploy / traffic /
     infrastructure / organizational systems

Out of band, only when needed:
Human ⇄ short-lived Agent product ⇄ AIOS machine boundary
```

A container is a deployment boundary, not a durable semantic owner. Internal Agents, executors, model providers, monitoring systems, and external clients remain replaceable.

## 5. Repository and component ownership

| Component | Ownership |
| --- | --- |
| guide | Minimal derivation, conceptual framework, six working lenses, sufficiency, exploration and decision |
| aios | AIOS source monorepo |
| semantic-language | stable cross-domain role vocabulary, references, normalization, non-substitution |
| personal-world | durable personal facts, preferences, relations, resource refs, provenance, revision, freshness, privacy, purpose-limited context |
| world-runtime | durable agency, responsibility, decisions and basis refs, mandates / authorizations, qualification review, execution identity, recovery, reconciliation, history |
| control-plane | operational incidents, diagnosis, repair, monitoring, runtime providers, result evidence |
| administrative-orchestrator | administrative cases, obligations, governance basis, administrative effects, outcomes, completion semantics |
| autonomous-development | software requirements, source, build, test, deploy, canary, promotion, rollback, release semantics |
| Agent / executor | replaceable cognitive or engineering implementation |
| model provider / router | replaceable model access |
| external provider | real-world effects and authoritative external state |

Directories can own independent semantics without becoming separate Git repositories.

## 6. semantic-language: promoted cross-domain role vocabulary

semantic-language stays small and stable. It directly owns only promoted universal role distinctions whose collapse creates concrete cross-domain correctness failure. The broader non-substitution rules below are AIOS-wide engineering invariants; distinctions that have not been promoted remain owner-local and are preserved by the subsystem or domain contract where they matter.

AIOS should preserve, when material:

```text
reality != current representation
distinguishable range != distinguished range
default distinction != sufficient distinction
relation != causality
possible != reachable != controllable != callable
question candidate != sufficiently established question
interpretive sufficiency != specified sufficiency
specified rule satisfied != rule applicable / current / authoritative
evidence != belief
observation != claim
claim != current sufficiently established state
intent candidate != confirmed human intent
human approval action != decision
decision != authorization
authentication != representation
representation != state-transition authority
personal context != execution permission
real-world effect != outcome
provider success != verified reality
projection != authoritative state
historically valid != currently sufficient
interpretation != reality
```

A stable semantic distinction does not automatically require a universal payload, durable entity, table, or service.

Long-running autonomous improvement also needs several progress distinctions:
more historical records or evidence does not imply greater capability; a new
version is not automatically a stronger version; an improved internal score is
not automatically improvement in the external objective; and external-objective
improvement is not by itself evidence of a novel capability.

## 7. personal-world: personal continuity

personal-world owns a person's durable, evolving, provenance-bearing context accepted through owner-local qualification / admission that realizes the framework's sufficiency requirement. The name does not imply that it contains the person's whole distinguishable world, and absence of a record does not imply absence in reality.

```text
source
→ observation
→ claim
→ qualification / admission
→ personal record revision
→ current lineage head
→ purpose-limited context projection
→ Agent / authorized consumer
```

Public personal record types may include:

```text
personal fact
preference
relation
resource link
```

personal-world does not own:

```text
decision
authorization
responsibility
run
real-world effect
domain outcome
provider execution
domain lifecycle
model-private memory
```

Model inference does not automatically become currently qualified Personal World state. Domain projections do not transfer domain ownership. Context projections are not new authoritative personal state.

## 8. Cognitive execution

Cognitive execution is a replaceable boundary:

```text
domain trigger / authorized request
+ purpose-limited personal context
+ domain state
+ runtime constraints
→ Agent / executor
→ boundary review
→ exploration when needed
→ problem / task sufficiency
→ analysis / proposal / implementation candidate / test / review
```

Executor output remains candidate distinctions, evidence, explanations, proposals, implementations, or review results. A newly generated framing does not automatically obtain domain admission.

Model selection and routing are transport / configuration matters; they do not expand authority, real-world effect scope, or durable ownership.

## 9. world-runtime: autonomous continuity

world-runtime sits between sufficiently established work triggers and domain realization:

```text
sufficient work trigger / authorized request
        ↓
governed autonomous capability
        ↓
world-runtime
        ↓
bounded domain realization
        ↓
Reality
```

world-runtime may own:

```text
identity
epistemic-basis refs
responsibility
decision + basis refs
mandate / authorization
qualification binding / review case
work / run
execution identity
provider-attempt identity
reconciliation
recovery
history lineage
```

It does not own personal preferences, interface session state, software release semantics, administrative completion semantics, or provider-specific business semantics.

Domain controllers define domain completion and result meanings.

## 10. Authority path

```text
authenticated actor
→ representation
→ intent / proposal
→ decision
+ current mandate
→ authorization
→ runtime state-transition authority
→ reality-effect authorization
→ durable real-world effect identity
→ provider dispatch
→ Reality
```

An earlier position cannot substitute for a later one.

Knowing a resource does not create permission. Representing a principal does not automatically create transition authority. Transition authority does not automatically create every real-world effect permission. Execution authority does not prove domain outcome.

## 11. Evidence and feedback path

```text
Reality
→ observation
→ evidence
→ domain interpretation / outcome qualification
→ DomainReport + Outcome refs / unknown
→ runtime review / Responsibility assessment
→ current autonomous state
```

Evidence must remain traceable to sources. World Runtime may record or reference domain-owned Outcomes, but it does not reinterpret their domain meaning. Changes in current qualification do not rewrite historical evidence. Material basis changes trigger review / revalidation.

Current qualification is dependency-aware: if a conclusion depends on a premise
that is no longer current, the conclusion cannot remain current merely because
its historical record still exists. Independent reality-grounded evidence may
survive. Evaluator, policy, or model migration also needs an explicit semantic
preservation basis; parse compatibility is not enough to inherit old judgments.

## 12. control-plane

```text
monitoring signal
→ authenticated entry
→ runtime responsibility + domain assignment
→ bounded diagnosis
→ repair-plan sufficiency
→ domain work / run
→ runtime provider
→ reality-side observation
→ repair verification
→ domain report
→ runtime responsibility evaluation / release
```

Diagnosis is not authority. Provider success is not target recovery. Operational completion requires domain evidence.

## 13. administrative-orchestrator

```text
organizational request / evidence
→ administrative case / facts / rules / obligations
→ governance basis
→ administrative execution authorization
→ runtime responsibility / work / permission
→ external administrative system
→ independent readback
→ confirmed outcome
→ completion evaluation
→ runtime responsibility evaluation
```

Rule or approval satisfaction is not runtime authorization. An administrative effect record is not external reality. Case completion does not automatically discharge responsibility.

## 14. autonomous-development

```text
sufficient development goal / admitted request
→ development request
→ personal-world context projection
→ requirements analysis
→ change proposal
→ isolated implementation
→ deterministic verification + independent review
→ immutable build
→ candidate deployment
→ offline evaluation
→ canary
→ promotion or rollback
→ post-promotion observation
→ release version
```

autonomous-development owns:

```text
development goal
product-goal revision
development request
requirements analysis
change proposal
worktree / source semantics
verification gates
build artifact identity
deployment state
traffic exposure
feedback attribution
canary lifecycle
promotion
rollback
release version
```

`Git commit != release version`

`tests pass != promotion authority`

`deployment healthy != product improved`

`canary complete != release finally confirmed`

### Autonomous Development vertical slice

```text
autonomous-development trigger / admitted request
→ request admission
→ personal-world purpose-limited context @ revision
→ requirements analysis / change proposal
→ autonomous-development lifecycle
→ world-runtime governed real-world effects
→ Git / build / deploy / traffic
→ Reality
→ tests / telemetry / deployment readback / release evidence
→ domain outcome / release version / rollback / unknown
→ world-runtime responsibility evaluation / reconciliation
→ next autonomous cycle
```

The configured engineering executor performs bounded implementation work; autonomous-development retains specialist lifecycle and release authority, while world-runtime retains generic responsibility, authorization, durable effect identity, and effect admission.

personal-world inputs bind revisions. Personal context changes do not rewrite historical analysis, but can invalidate the current sufficiency of old analysis.

Autonomous development must distinguish “more system change” from actual
progress. Commit count, version count, archive growth, test score, internal
evaluation score, and frontier replacement establish only their own facts; none
alone proves product-goal improvement or novel capability. Promotion should,
wherever possible, return to a fixed external objective, reality-side readback,
and domain-owned outcome semantics.

If the development process allows checkers, evaluators, or promotion rules to
modify their own successors, acceptance by the current version is not enough to
establish successor soundness. The trust path needs either a non-circular
grounded root or independently checkable preservation evidence showing that the
relevant judgments, goals, and constraints survive migration.

## 15. Reality return path

Every consequential path contains a return path:

```text
Reality
→ observation / provider receipt / external state
→ domain evidence
→ domain-owned Outcome refs / unknown + effect state
→ DomainReport
→ world-runtime reconciliation / Responsibility assessment
→ current autonomous state / next cycle
```

Only when an exception needs human attention is this state projected through a short-lived Agent.

Provider acknowledgment alone cannot terminate the loop. Transport ambiguity remains unknown. Where supported, independent readback confirms reality.

## 16. Three durable continuities

```text
personal continuity = personal-world
autonomous continuity = world-runtime
domain continuity = domain controller
```

semantic-language preserves role distinctions across the three.

External Agent projections are not a fourth durable authority store.

Replacing internal Agents / executors must not replace durable continuity; disconnecting an external client must not stop AIOS; domain controllers can evolve without moving specialist lifecycle semantics into world-runtime; world-runtime can restart without losing durable autonomous state.

## 17. Placement rules

Promote a role distinction into semantic-language only when at least three materially different domains need the same stable cross-domain distinction and collapsing it causes concrete correctness failure. Promotion adds only the role distinction, not domain payloads or lifecycle.

New durable cross-domain autonomous invariants go to world-runtime.

Personal facts, preferences, relations, resource refs, and context lineage go to personal-world.

Specialist lifecycle belongs to domain controllers.

Provider-specific implementation stays under the owning domain.

Agents / executors and model routing remain replaceable and do not become durable state owners by default.

## 18. Extension topology

New executor:

```text
autonomous work / domain request
→ executor selection
  ├─ Agent adapter
  ├─ engineering executor
  └─ specialized executor
```

New domain:

```text
world-runtime
  ├─ control-plane
  ├─ administrative-orchestrator
  ├─ autonomous-development
  └─ future domains
```

New provider:

```text
domain controller
  ├─ API
  ├─ app
  ├─ device
  ├─ infrastructure
  ├─ human
  └─ robot
```

New capability does not automatically require new runtime semantics. A stronger model does not create durable authority. A new domain does not imply a universal domain ontology.

## 19. Stable architecture

```text
guide
  reality / purposeful finite actor
  six-dimensional boundary
  sufficiency
  exploration / decision
  action chain
       │
       ▼
aios/semantic-language
  promoted cross-domain role vocabulary

AIOS
  personal-world ──► internal Agent / executor
         ▲                     │
         │                     ▼
         └────────────── domain admission
                               │
                               ▼
                         world-runtime
                               │
             ┌─────────────────┼──────────────────┐
             ▼                 ▼                  ▼
        control-plane   administrative      autonomous-
                         orchestrator        development
             │                 │                  │
             └─────────────────┼──────────────────┘
                               ▼
                             Reality
                               │
          evidence / readback / result / unknown
                               └──────────────► AIOS

Out of band:
Human → short-lived Agent → AIOS machine boundary
        inspect / explain / authorized repair / verify / report / disconnect
```

AIOS stability comes from durable semantic ownership, reality-side return paths, and the action chain rather than dependence on any particular Agent, model provider, router, or interactive client.
