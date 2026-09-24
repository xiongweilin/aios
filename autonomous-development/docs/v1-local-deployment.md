# Historical V1 Local Deployment Record

Status: historical implementation record  
Superseded as current deployment guidance: 2026-09-25

This file preserves the former workstation-specific V1 deployment assumptions for
`autonomous-development`. It is retained for implementation lineage only and must not be used as
the current AIOS deployment contract.

The former runbook assumed a Windows workstation with host-installed development tools, a local
Codex App Server, Docker Desktop, local PostgreSQL/DBOS state, Prometheus, security scanners, and a
separate operator bridge. Those assumptions described one implementation environment; they are
not AIOS-wide semantic requirements.

The current component boundary is documented by:

- [../README.md](../README.md) for component ownership and lifecycle semantics;
- [operator-contract.md](operator-contract.md) for the provider-neutral operator contract;
- [v1-design.md](v1-design.md) for the V1 lifecycle and domain model;
- [../acceptance/target/README.md](../acceptance/target/README.md) for the disposable acceptance
  target that remains in the source tree.

Implementation adapters, acceptance fixtures, Docker-oriented build/deployment paths, or
executor-specific code may still exist in the component. Their presence proves only that those
implementations exist; it does not make a host OS, a particular Agent, Docker Desktop, Prometheus,
or any retired messaging bridge a universal AIOS dependency.

Historical operational details are recoverable from Git history when needed. New deployment
instructions should describe the deployment that is actually supported and verified at the time,
rather than reviving this workstation-specific topology.
