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

These six components are sourced and analyzed within this monorepo.

Each component directory retains its own README and implementation documentation. The root repository is the Git owner for the consolidated source.

## Repository status

No Windows installer or release workflow is currently provided.
The monorepo contains component source and backend APIs; it does not ship a user interface.

## SonarCloud

The root [`sonar-project.properties`](sonar-project.properties) analyzes the six component `src/` and `tests/` trees as project `metratio_aios`. Analysis runs on pushes to `main` and pull requests.
