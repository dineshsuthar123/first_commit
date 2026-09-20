# Validation report

Recorded September 20, 2026 from the repaired working tree. These are new executions of this implementation against isolated storage, not inherited results. The seeded fixture establishes only the stated bounded behavior.

## Environment and artifact identity

- Host: Windows with Docker Desktop, WSL2 Linux containers.
- Packaged runner: Python 3.13.7; Amazon Corretto 21.0.8.9.1; PostgreSQL 17.6.
- Final execution build SHA-256: `863b21915e95a16db8ad783e683fd9f7ba873ffdd061521bef2aa1394a0e4f41`.
- Recorded example campaign: `97a92b74cf4c46d5ba27e4e491a4e4c7`.
- Example ZIP SHA-256: `3efe5bdf90c82ec10884696cdafe9520c2180205e3967b3903d65784539d83fc`.
- Replay manifest schema: 2.

## Executed checks

| Check | Actual result |
| --- | --- |
| Clean frontend install | `npm ci`: 72 packages, 0 reported vulnerabilities |
| Frontend production build | TypeScript and Vite 6.4.3 passed; 28 modules transformed |
| Full packaged Python suite | **26 passed** in 134.98s; one upstream Starlette/AnyIO deprecation warning |
| Corretto runtime | OpenJDK 21.0.8, Corretto-21.0.8.9.1 |
| Chromium browser suite | **4 passed** in 41.0s; Playwright 1.58.2 / Chromium 145.0.7632.6 |
| Fresh saved-failure replay gate | **30/30 matched**, zero divergences |
| Fresh stable-key comparison gate | **30/30 passed**, zero operational failures |
| Standalone evidence verifier | Schema-2 example verified; 12 worlds independently evaluated |
| Same-build replay | Matched the saved `PROPERTY_VIOLATION` contract |
| Changed-build probe | Returned `DIVERGED` with `same-build digest mismatch` after adding a temporary engine artifact; the artifact was then removed |
| AWS execution / S3 transfer | Not run; outside this repair task |

Commands run:

```sh
docker compose up --build -d --wait
docker compose exec -T -e STATEPROOF_DATA=/app/data/review-fix-tests control python -m pytest -q
docker compose exec -T control java -version

# From frontend/
npm ci
npm run build
npx playwright install chromium
npx playwright test

docker compose exec -T -e STATEPROOF_DATA=/app/data/review-fix-validation control python -m scripts.validate_replays
python -m scripts.verify_evidence examples/evidence.zip
```

The Python suite covers real JVM termination and durable persistence, all four variants, exact replay targeting and ownership rejection, job context and campaign failure terminalization, CLI exit policy, canonical durable outcome matching, per-attempt key normalization, deletion reduction, and cross-file evidence consistency. Controlled archive mutations confirm that contradictory campaign copies/counts, missing world records, checksums-only bundles, and contradictory manifest outcomes fail verification. A coherent operational-only bundle reports `businessEvaluation: not_evaluated`.

The browser suite retains the real end-to-end exploration/reduction/replay/comparison/download test. It also exercises hash deep links and Back/Forward navigation, explicit reduced-case request bodies, reload recovery through durable job context, a controlled failed-job rendering path, connection recovery, cancellation, and a 390px viewport. [Machine-readable browser results](browser-validation.json) and the [current screenshot](console.png) are retained.

## Matrix counts

Each campaign runs two controls plus six observed crash sites. Failing implementations additionally run one mixed workload; counts include it:

| Variant | Executed | Pass | Violation | Inconclusive/error/diverged |
| --- | ---: | ---: | ---: | ---: |
| `local_dedup` | 9 | 7 | 2 | 0 |
| `per_attempt_key` | 9 | 7 | 2 | 0 |
| `mark_before` | 9 | 6 | 3 | 0 |
| `stable_key` | 8 | 8 | 0 | 0 |

These are executed cases, not percentages of a distributed state space. Both normal controls passed for every variant. Fresh campaign IDs and build fingerprints are in [matrix-results.json](matrix-results.json).

[replay-validation.json](replay-validation.json) contains all 60 fresh world IDs, verdicts, matches, and durations. The median individual world duration was **1.686 seconds** on this host.

## Remaining limits

Only the `payment-v1` fixture and declared execution grammar are validated. The explorer does not cover concurrency, multiple crashes, network faults, or arbitrary repositories. Evidence consistency and deterministic replay are not proof of authorship or full-machine determinism. No cloud deployment, repository publication, video upload, or hackathon submission was performed.
