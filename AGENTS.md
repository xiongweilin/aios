# AIOS repository instructions

AIOS is one product and one Python project.

Ownership:

- `semantic_language`: cross-domain semantic distinctions.
- `personal_world` and `world_runtime`: kernel.
- `control_plane`, `administrative_orchestrator`, `autonomous_development`: domains.
- `aios`: composition and product runtime only.

Do not recreate component repositories or top-level component project roots. New Python source belongs under the single `src/` tree and tests under the single `tests/` tree.

AIOS is headless and container-native. UI concerns do not belong here. Agent, model, monitoring and other external systems must remain replaceable integrations.

Preserve semantic boundaries: evidence is not authority, authorization is not effect, provider success is not outcome, and domain completion remains domain-owned.
