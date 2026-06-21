# Abhash Memory Fork Notice

This repository is Abhash's personal self-hosted fork of Mem0 for running a private memory layer on personal infrastructure.

The upstream Mem0 project remains licensed under Apache-2.0. This fork keeps the upstream `LICENSE` and notices intact. Abhash-specific deployment files, branding, and operational configuration are intended for Abhash's personal use and are not a separate public hosted service offering.

Production deployment target:

- Service name: Abhash Memory
- Runtime surface: `server/` FastAPI API and dashboard
- Storage: PostgreSQL with pgvector
- Phase 2: optional graph memory/Neo4j hardening after the base VPS deployment is stable
