# AIOS

[![SonarCloud Analysis](https://github.com/xiongweilin/aios/actions/workflows/sonarcloud.yml/badge.svg?branch=main)](https://github.com/xiongweilin/aios/actions/workflows/sonarcloud.yml)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=metratio_aios&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=metratio_aios)
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=metratio_aios&metric=bugs)](https://sonarcloud.io/dashboard?id=metratio_aios&branch=main)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=metratio_aios&metric=vulnerabilities)](https://sonarcloud.io/dashboard?id=metratio_aios&branch=main)
[![Code Smells](https://sonarcloud.io/api/project_badges/measure?project=metratio_aios&metric=code_smells)](https://sonarcloud.io/dashboard?id=metratio_aios&branch=main)

AIOS is the current monorepo for these consolidated source components:

| Component | Directory |
| --- | --- |
| Personal World | [`personal-world/`](personal-world/) |
| World Runtime | [`world-runtime/`](world-runtime/) |
| Semantic Language | [`semantic-language/`](semantic-language/) |
| Control Plane | [`control-plane/`](control-plane/) |
| Autonomous Development | [`autonomous-development/`](autonomous-development/) |
| Administrative Orchestrator | [`administrative-orchestrator/`](administrative-orchestrator/) |

The former standalone repositories for these components have been consolidated into this repository. `agency-console` is not part of the current tree.

Each component directory retains its own README and implementation documentation. The root repository is the Git owner for the consolidated source.

## Repository status

The existing `release-windows.yml` workflow still references pre-consolidation top-level files (`go.mod`, `build.ps1`, and `profiles/`) that are absent here. It is legacy workflow content, not a verified current release pipeline.

## SonarCloud

The root [`sonar-project.properties`](sonar-project.properties) analyzes the six component `src/` and `tests/` trees as project `metratio_aios`. Analysis runs on pushes to `main` and pull requests.
