# Contributing

Contributions are welcome when they preserve the Administrative ownership boundary and the repository's current trust model.

Before submitting a change:

1. Keep organizational truth, authority, obligations, Administrative execution authorization, semantic verification, and completion separate from Agent Kernel runtime authority and provider execution.
2. Do not turn AI confidence, authentication, approval, provider success, workflow completion, or transport delivery into a stronger claim than the current evidence supports.
3. Add or update tests for the affected authority, persistence, replay/restart, reconciliation, and verification paths.
4. Prefer changes justified by a concrete administrative workflow or failure mode over new abstractions introduced only for conceptual completeness.
5. Run:

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest -q
```

For changes that touch migrations, DBOS workflows, production connectors, Runtime integration, or Operations surfaces, also run the relevant verification described in `docs/production-operations.md`.

Architectural changes should state which layer owns the new concept, which stronger claims it is explicitly not allowed to make, and what evidence establishes completion.
