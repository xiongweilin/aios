# Source lineage

World Runtime V1 semantically replaces three frozen predecessor repositories.

| Predecessor | Frozen main SHA | Disposition |
| --- | --- | --- |
| xiongweilin/meta-controller | 18e1078c1d6971a2232662b6cbded4ffdbc380b0 | cognition algorithms migrated; kernel compiler seam removed |
| xiongweilin/agent-kernel | 001717a117a2987e1b8aa21bda37dddae0f88364 | runtime semantics split into governance/responsibility/execution owners |
| xiongweilin/world-state | 4ed1c35ea14c7fd7d6c40d893c75131e12dbc008 | epistemic semantics migrated into the canonical world ledger |

Old package names, contract IDs, database names and HTTP surfaces are migration inputs only.
They are not World Runtime APIs.

For historical `agent-kernel` Work records, `metadata.standing_responsibility_ref` is an accepted
source-field alias for the canonical responsibility reference only when it exactly matches an
imported `StandingResponsibility` identity. `responsibility_proposal_ref`,
`responsibility_commitment_ref`, and `responsibility_reservation_ref` are not substitutes for
that identity; missing or non-matching references remain unresolved.

Physical repository deletion is gated on:

1. world-runtime and semantic-language CI green;
2. active consumer cutover;
3. account-wide code/dependency references equal zero;
4. state migration or explicit proof that a deployment had no live state;
5. old writers stopped.
