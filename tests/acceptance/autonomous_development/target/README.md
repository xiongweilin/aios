# Autonomous Development V1 acceptance target

This is a deliberately separate, tiny FastAPI target used only for acceptance. It is not the
`autonomous-development` repository and must not be registered in a production database. The
acceptance workflow gives it an independent temporary Git repository, PostgreSQL/DBOS project,
runtime state root, Docker network, image and serving release.

The image uses the pinned official Python 3.14.7 Alpine amd64 builder/runtime digest.
Dependencies are installed as root only in the disposable builder stage and copied into the
explicit non-root UID 65532 runtime image. This HTTP-only target uses ordinary `uvicorn` rather
than `uvicorn[standard]`. The final runtime replaces Alpine's zlib package with a locally built
package from upstream zlib commit `df84af25dc1942490e1d1c899a07619152a46148`, which contains
the upstream fix for CVE-2026-85091.

## Current image definition

- Builder and runtime base: `python:3.14.7-alpine3.24@sha256:4677924bcc0e94505a3270e87cb1601c2af54cd92d021b8dc306618a14333bbe`.
- Direct runtime pins: `fastapi==0.141.1`, `uvicorn==0.53.0`, `anyio==4.15.1`,
  `h11==0.16.0` and `idna==3.20`.
- Replaced Alpine package: `zlib-1.3.2.1-r0`, built from upstream commit
  `df84af25dc1942490e1d1c899a07619152a46148` and verified through Python's zlib runtime.
- The image runs as UID `65532`, stores task reality under `/tmp/aios-acceptance-state`, and exposes
  only the HTTP contract on port `8000`.

The fixed digest and package pins are part of the target definition. A local image ID is evidence
for one build, not a production release identity; record it with the corresponding acceptance
evidence rather than replacing the Dockerfile pins.

## Verification contract

Every accepted build must prove all of the following for the image built from this directory:

1. `/health` returns `{"status":"ok"}` and `/ready` confirms the state root is writable;
2. `/answer?value=  Hello  ` returns the normalized `hello` response;
3. `POST /tasks` persists a completed task record, and `GET /reality/{task_id}` reads that record
   back from storage, including after a container restart;
4. Syft records the fixed `zlib-1.3.2.1-r0` package and the pinned Python dependencies;
5. `grype --fail-on high` exits successfully. Medium/low findings remain visible and are not
   converted into a security exception.
