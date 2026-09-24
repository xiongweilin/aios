# Current system integration matrix — World Runtime 1.1.0

World Runtime 1.1.0 is the first hardening release after the frozen 1.0
governed-agency kernel. Runtime Protocol 4.0 makes three security-relevant
boundaries explicit without moving domain lifecycle ownership into Runtime:
delegated representation is not generic transition authority, terminal
execution state is authoritative for fresh execution, and provider-result reads
are principal/actor isolated.

| Repository / release | Approved SHA | Role |
| --- | --- | --- |
| semantic-language | `eb8c6cb1757256ea9961201bd66ea79952de6134` | universal semantic kernel 0.2 |
| world-runtime 1.1.0 implementation/evidence baseline | `02c83f2a8e8cf68fc27897fec8bb8096b6dd8d39` | Runtime 1.1 / Protocol 4.0 candidate that passed ordinary CI, PostgreSQL integration, and the three-Controller HTTP matrix before freeze-evidence-only commits |
| control-plane | `475cc5b3bbc714e65d71f133f4dfa838b249d817` | Protocol 4.0 Control Plane Controller |
| administrative-orchestrator | `c44ca76daf6e2d9ecd4ab182d170176ff740babb` | Protocol 4.0 Administrative Controller |
| autonomous-development | `7a738277d3bb0bc71a7e620bbfedda6ebd4d9dd9` | Protocol 4.0 Development Controller |

## Release identifiers

- package: `world-runtime 1.1.0`
- Runtime Protocol: `4.0`
- contract catalog: `world-runtime-contracts-v10`
- executable conformance: `world-runtime-conformance-v11`
- Domain Controller protocol: `domain-controller-protocol-v3`
- semantic-language: `0.2.0`

## Protocol 4.0 guarantees

The release preserves the 1.0 ownership split while hardening authority and
execution legality:

- authenticated identity proves the caller but does not by itself create a
  delegated Runtime transition right;
- a delegated caller needs an explicit `authority_ceiling.operation`, with an
  optional resource ceiling, for generic Runtime mutations;
- Mandate/Authorization action-resource qualification remains a separate
  requirement for reality-changing effects;
- terminal Work cannot start a fresh Run;
- terminal Work/Run cannot authorize fresh provider invocation;
- exact committed idempotent replay remains historical replay and does not
  redispatch;
- an already ambiguous historical attempt may still reconcile;
- provider-result/reconciliation reads are bound to effective principal and
  authenticated actor;
- historical provider results without read-binding metadata fail closed except
  to direct configured-root access;
- public command schemas remain closed and whole-agency StateBundle operations
  remain direct-root-only.

## Controller compatibility

The approved Controller commits retain their existing domain ownership:

- Control Plane keeps incident/manual lifecycle, provider routing, concrete
  operational effects, monitoring and repair semantics;
- Administrative keeps case/obligation/authority-epoch semantics;
- Development keeps source/build/deploy/release semantics.

No Controller imports or embeds the World Runtime production package. Runtime
compatibility is exercised over the HTTP contract surface.

## Verification gate

The frozen matrix requires all of the following on the release branch:

- World Runtime ordinary CI;
- World Runtime PostgreSQL integration;
- World Runtime current-system integration against all three approved
  Controller SHAs;
- Control Plane CI including real Runtime HTTP integration;
- Administrative CI and M5 Production Trust;
- Development CI and Security.

Earlier compatibility matrices remain immutable in Git history and release tags; only the current 1.1 matrix stays in the source tree.
