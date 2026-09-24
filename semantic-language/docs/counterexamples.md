# Counterexamples

Semantic distinctions are promoted only when collapsing them creates a correctness failure.

## Decision is not Authorization

An institution may decide to purchase equipment while the acting principal still lacks authority
to execute the purchase. Recording the Decision must not mint an Authorization.

## Effect is not Outcome

A deployment API may report success while the intended product property remains unchanged.
Provider success and the resulting external Effect do not establish the domain Outcome.

## Responsibility is not Work

A standing responsibility may survive many Work units, retries, process restarts, and provider
changes. Completing one Work item cannot discharge the Responsibility.

## Evidence is not Claim

A telemetry record is evidence about a proposition. It does not become the proposition itself, and
conflicting evidence must remain representable without overwriting the Claim.
