# Validation report

Recorded September 19–20, 2026. Results below are executions of this implementation, not inherited feasibility results. The seeded fixture establishes only the stated bounded behavior.

## Environment and artifact identity

- Host: Windows with Docker Desktop 4.73.1, Engine 29.4.3, Compose 5.1.3, WSL2 Linux containers.
- Packaged runner: Python 3.13.7; Amazon Corretto **21.0.8.9.1**; PostgreSQL **17.6**; Linux 6.6.87.2-microsoft-standard-WSL2, x86_64, glibc 2.36.
- Initial native slice: Python 3.14.6, Oracle Java 21.0.9, isolated PostgreSQL 18 on localhost:55432. Main packaged results use Corretto, not Oracle Java.
- Final execution build SHA-256: `9c0346924f64cad021088555bb56cc38a08d187a5a1022643c9db7d19cfd7eb0`.
- Recorded example campaign: `3715a9345ee049b59fc0a79d0fe8db22`.
- Example ZIP SHA-256: `f29075e3a7110d8dcef3a61c19e553bf65ba8aa8195dc7d493bed728532f4319`.
- Execution build fingerprints include source/compiled worker artifacts and lockfiles, not UI/docs. Container packaging and documentation can change without changing that fingerprint.

## Executed checks

| Check | Actual result |
| --- | --- |
| Native Milestone 1 integration | 1 passed, 8.13s; four real worlds (normal, duplicate, killed faulty, killed repaired) |
| First Corretto Compose matrix | 8 integration tests passed, 63.60s |
| Initial replay/reducer checks | 2 passed, 24.16s |
| API integration | 2 passed, 24.77s |
| Final complete packaged suite | **15 passed**, 136.65s; one upstream Starlette/AnyIO deprecation warning |
| Final saved failure | **30/30 matched**, zero divergences |
| Same fault plan, stable key | **30/30 passed**, zero errors/inconclusive results |
| Final browser suite | **2 passed**, 35.2s; Chromium 145.0.7632.6 / Playwright 1.58.2 |
| Frontend production build | TypeScript check and Vite 6.4.3 build passed |
| Frontend dependency audit after patch | 0 reported vulnerabilities at install time |
| CloudFormation static lint | cfn-lint 1.40.4, exit 0 |
| AWS execution / S3 transfer | **Not run; authorization/account configuration unavailable** |

Commands actually used (the local `.docker` config directory avoids inaccessible host Docker configuration; normal users can omit it):

```sh
docker --config .docker compose build control
docker --config .docker compose up -d control
docker --config .docker compose exec -T -e STATEPROOF_DATA=/app/data/final-validation control python -m pytest -q
docker --config .docker compose exec -T control python -m scripts.validate_replays
docker --config .docker compose exec -T control java -version
# From frontend/, after pinned npm install and Chromium installation:
npx playwright test
```

The final Python tests exercise real JVM failure/persistence, all four variants, independent properties, key conflict handling, changed operation/amount, missing boundaries, unavailable database, unexpected exit, cancellation, deadline timeout, replay corruption/build mismatch, deletion reduction, evidence checksums and opening standalone exported SQLite databases. A test compiles an intentionally broken `stable_key` implementation whose key varies by attempt: the evaluator discovers the duplicate even though its variant label remains `stable_key`.

Browser checks exercise actual backend exploration, ₹2,000 ledger display, four-to-two reduction, replay match, ₹1,000 repair comparison and downloading a ZIP, plus connection failure/recovery, cancellation and a 390px viewport with no horizontal overflow. There were no browser page errors. The in-app browser reported no available connection; a separate automated Chromium instance performed these checks. [Machine-readable browser results](browser-validation.json) and [actual screenshot](console.png) are retained.

## Matrix counts

Each campaign runs two controls plus six observed crash sites. Failing implementations additionally run one mixed workload; counts include it:

| Variant | Executed | Pass | Violation | Inconclusive/error/diverged |
| --- | ---: | ---: | ---: | ---: |
| local_dedup | 9 | 7 | 2 | 0 |
| per_attempt_key | 9 | 7 | 2 | 0 |
| mark_before | 9 | 6 | 3 | 0 |
| stable_key | 8 | 8 | 0 | 0 |

These are counts of executed cases, not percentages of a distributed state space. Both normal controls passed for every variant. The initial recorded matrix is in [matrix-results.json](matrix-results.json); the final full suite reran and checked this behavior. Fault site selection came from each normal trace. mark_before's local commit appears earlier in its discovered ordering.

The measured mixed workload has four actions (unrelated delivery + ordinary duplicate, target crash delivery + retry). Reduction produced two actions and reran all admissible single deletions; no remaining admissible deletion preserved the target property's violation for that logical operation. This is grammar-relative 1-minimality.

[replay-validation.json](replay-validation.json) retains all 60 run identifiers/verdicts and durations. Median individual world duration was **1.686 seconds** on this host. This is not a cloud speedup or a promised recording duration.

## Failures found and repaired during development

- Docker was initially stopped; starting it enabled the packaged checks. Dependency network access required the tool's approved network path.
- Initial Vite dependency audit found an advisory. Vite was pinned to 6.4.3 and the subsequent install audit reported zero.
- The first browser attempt overlapped API tests using the same storage. TestClient startup marked the live campaign interrupted. Tests now use isolated temporary storage, and the corrected browser suite passed. Interrupted lifecycle is shown explicitly.
- An added independent ledger-opening check found WAL metadata in serialized snapshots. Export now backs up each provider database to a standalone file and switches that copy to DELETE journal mode. The final suite opens all archived ledgers and verifies their row counts.
- A saved manifest from an older container build correctly returned `DIVERGED` when checked against a changed build. Current examples were regenerated after the final engine fixes; rebuilding the image includes them.

## Remaining limitations and blockers

CloudFormation lint and source review are not an AWS deployment. Approved account, region, budget and permission to provision are absent, so EC2 bootstrap, instance-role credential retrieval, live S3 conditional upload and a public URL remain unverified. Follow [infra/README.md](../infra/README.md) after approval.

No narrated 173-second video, YouTube upload or public repository push was performed. The [precise shot list](DEMO.md) is ready. The official submission form exposed only a loading state to the available web reader; no exact cutoff time was verified.

Only one payment fixture and one bounded execution grammar are validated. No SQS, network-response suppression, concurrency, production repositories, unknown-bug discovery, global minimality or full-machine determinism claims are made.
