# Epistemic repair loop

The personal incident-repair profile owns a domain-local epistemic and repair loop. It does not import or project into `world_runtime.cognition`.

World Runtime remains the owner of universal durable Responsibility, DomainAssignment, Decision, governance, and audit semantics. The control-plane loop communicates with it only through the public HTTP contracts.

## Domain loop

```text
World Runtime Responsibility / DomainAssignment
    -> PersonalController
    -> RepairEpistemicProfile
       - RepairIssue
       - RepairTension
       - RepairCandidate
       - RepairSelfModel
       - RepairIntent
    -> bounded diagnosis (reason.generate)
    -> RepairClosure
    -> local DomainWork / DomainRun
    -> bounded concrete provider
    -> reality observation / verification
    -> RepairRevision
    -> close / wait / explicit reopen
    -> typed DomainReport
    -> World Runtime assessment / Decision / discharge
```

A first diagnosis is an evidence-acquisition problem. When reality contradicts the current repair closure and the controller is reopened, the profile marks candidate-space incompleteness and repeated-reopen tension. The next pass must change the working distinctions instead of repeating the same root-cause partition.

The line-ending cleanup case is a concrete representation-revision example: repository `dirty` state alone is not a sufficient semantic distinction. The domain first separates semantic content change from line-ending representation noise.

## Authority ceiling

The entire epistemic profile is non-authority-bearing.

```text
RepairIssue          -/-> truth
RepairCandidate      -/-> qualification
RepairIntent         -/-> universal Decision
RepairIntent         -/-> universal Authorization
RepairClosure        -/-> universal Responsibility
CapabilityBelief     -/-> capability authority
ProviderSuccess      -/-> target recovery
RepresentationChange -/-> effect authorization
```

The profile may decide what the control-plane domain should investigate next. It may not create universal semantic authority.

Effectful work must pass through the domain controller's bounded work lifecycle and concrete provider boundary. Universal completion is reported separately to World Runtime.

## Domain-local hard gates

The local controller fails closed across its policy/execution seam:

- controller decisions are bound to the current controller/version;
- a closure requires explicit basis, acceptance criteria and verification plan;
- Work cannot be proposed without an active closure;
- a revision requires observed work or verification reality;
- close requires verification evidence;
- failed diagnosis waits rather than inventing a closure;
- a closed controller does not restart implicitly;
- owner follow-up reopens through an explicit revision path.

These are control-plane domain invariants, not universal Runtime semantics.

## World Runtime boundary

At startup, `WorldRuntimeClient` verifies the exact external contract surface:

```text
runtime protocol 4.0
semantic-language 0.2.0
request-authentication-v2
transition-authority-v1
read-authorization-v1
persistent-responsibility-v3
responsibility-assessment-v3
responsibility-discharge-v3
work-admission-v4
decision-record-v4
mandate-registration-v4
authorization-issue-v4
domain-effect-execution-v3
domain-assignment-v3
domain-report-v3
```

Mismatch fails closed.

The bridge uses those contracts to:

1. create the universal Responsibility;
2. offer and accept the DomainAssignment;
3. run the control-plane-specific lifecycle locally;
4. submit typed basis/evidence/outcome references;
5. propose assignment completion;
6. request responsibility assessment;
7. record the universal Decision;
8. discharge the universal Responsibility.

No Runtime Python package is imported or pinned.

## Persistence and restart

`DomainJournal` persists only domain-local controller, work, run and observation state.

It may survive process restart and repair stale local execution claims. It does not reconstruct universal Responsibility, Decision, Evidence, Outcome, Goal, Authorization, or Strategy state.

That separation is the architectural invariant:

```text
rich domain semantics
!=
second universal semantic owner
```
