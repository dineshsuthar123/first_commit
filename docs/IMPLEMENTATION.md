# Implementation and acceptance

1. Real execution: isolated PostgreSQL schemas, durable SQLite HTTP provider, Java 21 handler, blocking checkpoints and supervised process termination. Verify controls, gap failure and stable-key repair; commit.
2. Bounded exploration: discover normal-run checkpoints, run all four variants, independent properties, explicit operational errors; commit verified matrix.
3. Evidence: validated manifests, same-build replay and repair comparison, fresh-world deletion reduction, CLI and checksummed export. Run 30 failing and 30 repaired replays; commit.
4. Console: FastAPI orchestration and React interface using real results. Exercise exploration, reduction, replay, cancellation and download in browser; commit.
5. Delivery: Compose clean build, EC2/S3 infrastructure, honest validation report, architecture, attribution and 173-second demo shot list. Cloud provisioning requires an approved account/region/budget and authorization; otherwise record blocker.

Acceptance: controls pass; local_dedup/per_attempt_key duplicate and mark_before missing effect are discovered; stable_key matrix passes; unavailable dependencies/missing checkpoints/corrupt manifests never pass; fresh worlds isolate state while worker restarts preserve it; reduction retains property+operation signature and verifies 1-minimality; CLI/browser export real evidence. No production-bug or universal-determinism claim.

Initial inspection: repository contains only README.md and one initial commit. No workspace AGENTS.md or feasibility files found. Host has Python 3.14.6, Oracle Java 21.0.9, Node 22.17.0, PostgreSQL 18 tools and Docker 29.4.3 / Compose 5.1.3. Docker daemon initially unavailable. Packaged execution targets Amazon Corretto 21.
