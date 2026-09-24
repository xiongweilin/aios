# Predecessor migration acceptance

These fixtures are the accepted V1 deletion snapshots for the three frozen predecessor repositories. They are contract-derived serialized records tied to the exact frozen main SHAs listed in manifest.json.

They are not opaque blobs. CI runs each snapshot through SemanticMigrator and requires:

- every required namespace to be present;
- unresolved == 0;
- rejected == 0;
- the report to be deletion_ready.

An intentionally-skipped record is allowed only where the replacement matrix explicitly states that the old record is a derived projection rather than canonical state. V1 uses this for the world-state BeliefVerdict: Runtime recomputes belief from canonical ClaimRevision, Evidence and Assessment history.

These fixtures prove schema/semantic replacement for an accepted predecessor snapshot. Before physical repository deletion, operators still need either a migration report from any deployed live predecessor state or explicit evidence that no live predecessor state exists.
