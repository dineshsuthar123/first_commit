# 173-second recording script

A **172.28-second silent recording with captions** is available at [demo.webm](demo.webm). It captures real local exploration, ledger evidence, reduction, replay, repair comparison and an evidence download. It explicitly labels EC2/S3 as not deployed. No cloud execution is implied. Human voiceover and public/unlisted video upload remain optional submission preparation; nothing has been uploaded.

Reproduce the recording from `frontend/`, with Compose running and Chromium installed: `node scripts/record-demo.mjs`. Verify duration and sample playback with `node scripts/verify-video.mjs`. The following 173-second narration/shot schedule drove the capture; video startup accounts for the slight encoded-duration difference.

Before recording: `docker compose up --build -d --wait`; open localhost:8000 at 1440×1000. Keep a terminal showing `docker compose exec -T control java -version` and the validation report. Start from the empty console. If shortening execution waits, label the cut and retain the campaign ID; never splice unlabelled results from different runs.

| Time | Shot / action | Narration |
| --- | --- | --- |
| 0–15 | Empty console and bounds | “StateProof tests whether retrying a message repeats its business effect. This seeded payment benchmark runs a real Java worker, PostgreSQL and an independent durable provider.” |
| 15–35 | Run exploration; show passing controls and discovered cases | “A normal ₹1,000 payment passes. Ordinary duplicate delivery passes too. We discover checkpoints from execution, kill the worker at each site, then retry once.” |
| 35–60 | Select after_external_call; show ₹2,000 | “The provider committed, then the worker died before local success. Retry charged again. These are real ledger rows, not a scripted result.” |
| 60–82 | Timeline, provider ledger, application state | “The provider survives the worker kill. Independent properties check duplicate effects, matching completion and progress within the attempt budget.” |
| 82–108 | Reduce, show 4 → 2, replay, download | “We remove unrelated actions and rerun fresh worlds, retaining the same violation and operation. The case is deletion-minimal under our grammar. The export pins boundaries, build and evidence checksums.” |
| 108–134 | Compare stable key; show ₹1,000 and key behavior | “The same fault plan now sends a stable logical-operation key. The provider returns the original effect on retry. This is an explicit repair comparison, not automatic code repair.” |
| 134–155 | Actual 30+30 report and Corretto java -version | “The saved failure matched 30 out of 30 fresh worlds. The repaired comparison passed 30 out of 30. Amazon Corretto runs the actual worker in the verified Compose stack.” |
| 155–165 | Actual EC2 campaign/S3 checksum if deployed; otherwise visible blocked note | Verified AWS: “The same stack ran on this EC2 instance; this campaign bundle is in S3 through an instance role.” Otherwise: “EC2 and S3 are prepared, but account and spend authorization are unavailable, so cloud execution is not claimed.” |
| 165–173 | Return to bounds | “Local deduplication cannot close an external-effect gap. These are bounded fixture results, not proof about arbitrary distributed systems.” |

Total **173 seconds / 2:53**, including the intro/outro. Measure the final encoded duration and open the uploaded link in a signed-out browser. History-loaded evidence must be called a saved run. Typical individual replay worlds measured about 1.5–2 seconds on this host; measure recording-host timings rather than asserting a fixed speed.

For the cloud shot, follow `infra/README.md`. Its deploy command actually executes discovery, reduction, replay, repair comparison and upload on EC2. Capture the actual instance/campaign/build IDs and checksum; never expose credentials or presigned-link query tokens. If cloud remains blocked, show Corretto's actual local use and the blocker. Organizers determine track eligibility.
