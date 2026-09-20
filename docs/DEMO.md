# StateProof demo walkthrough (2:50 target)

The checked-in `demo.webm` is an earlier 172.28-second local recording. Record a new take after this repair if the submitted video must show the current **Evidence explorer**, **Replay selected case**, and **Compare selected with stable key** labels. Keep shortened waits visibly labelled; a saved campaign must be described as saved evidence, not as a live run.

Prepare the real local stack and runtime in a terminal:

```sh
docker compose up --build -d --wait
docker compose exec -T control java -version
```

Open `http://127.0.0.1:8000/#lab` at 1440×1000. The worker runtime shown by `java -version` must be the actual Amazon Corretto runtime from this Compose image.

| Time | Action | Narration |
| --- | --- | --- |
| 0–18 | Show the empty Retry lab, choose `local_dedup`, and keep the amount at `100000` paise. | “StateProof runs a real Java payment consumer against PostgreSQL and an independent SQLite provider ledger. The search is bounded to one worker, one crash, and one retry.” |
| 18–50 | Select **Run exploration**. Show both passing control cases, then open the `after_external_call` failure and its ₹2,000 provider total. | “Normal and ordinary duplicate delivery pass. When the provider commits and the JVM is killed before local success, retrying produces a second ₹1,000 effect.” |
| 50–72 | Show the worker termination event, two provider rows, and application state. | “The process kill and durable rows are recorded evidence. Independent properties evaluate the business outcome.” |
| 72–92 | Open **Evidence explorer** from the sidebar, show its active state and campaign history, then return to the same selected case. | “Evidence explorer is a real navigable view. Direct links, Back and Forward work without losing the selected campaign or case.” |
| 92–118 | Select **Reduce workload** and wait for `4 → 2 actions`. Point out the newly selected `Reduced · …` case and its world ID. | “Reduction reruns fresh worlds and retains the same violation. The result is one-minimal under the documented action grammar.” |
| 118–138 | Select **Replay selected case**. Show the target label/world ID and the matched result. | “Replay names the exact reduced case. The manifest checks its plan, build, verdict, signature, ordered trace, and canonical durable outcomes.” |
| 138–158 | Select **Compare selected with stable key** and show the same target plus the ₹1,000 passing comparison. | “The same fault plan uses a stable logical-operation key. The provider deduplicates retry; this is an explicit benchmark comparison, not automatic repair.” |
| 158–170 | Download the evidence ZIP and show the offline verification command/result. | “The bundle cross-checks campaign summaries, world results, reduction references, SQLite ledgers, replay expectations, and SHA-256 checksums.” |

Save the browser download to a known path, then verify that exact file without starting a worker or database:

```sh
python -m scripts.verify_evidence "C:/Users/Naresh Suthar/Downloads/stateproof-CAMPAIGN_ID.zip"
```

For a reproducible repository artifact, use `python -m scripts.verify_evidence examples/evidence.zip`. Show the final 30+30 record only if it was generated from the displayed build. State the measured results from `docs/replay-validation.json`; do not reuse old numbers after engine changes.

If waits are shortened, cut only within a single campaign and retain the visible campaign ID before and after the cut. End by stating that the result covers the seeded payment fixture and declared bounds, not arbitrary production systems. EC2/S3 remain outside this local demo unless separately authorized and actually executed.
