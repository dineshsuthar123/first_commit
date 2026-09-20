import asyncio
from contextlib import asynccontextmanager
import json
import os
import secrets
from threading import Event
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, model_validator

from engine.campaign import explore
from engine.cli import campaign_path, failure_case, load_campaign
from engine.evidence import ReplayManifest, export_bundle, manifest_for, replay, upload_bundle
from engine.models import BOUNDS, Operation, Strict, Variant
from engine.reducer import reduce_case
from engine.runner import data_root, write_json
from fixtures.payment import ROOT, db_config

VARIANTS = {
    "local_dedup": "Read local success → provider without key → persist success",
    "per_attempt_key": "New provider key for every delivery attempt → persist success",
    "mark_before": "Persist paid first → call provider; a retry may skip the charge",
    "stable_key": "Stable stateproof:payment:v1:{operationId} provider key → persist success",
}
active = None
tasks = set()
cancel_flags = {}


@asynccontextmanager
async def lifespan(app):
    global active
    active = None
    # A supervisor restart must not leave stale RUNNING jobs presented as live work.
    interruption = "control service restarted before completion"
    for folder in ("jobs", "campaigns"):
        for path in (data_root() / folder).glob("*.json"):
            item = json.loads(path.read_text())
            if item.get("lifecycle") == "RUNNING":
                item["lifecycle"] = "INTERRUPTED"
                if folder == "jobs":
                    item["error"] = interruption
                else:
                    item.setdefault("diagnostics", []).append(interruption)
                write_json(path, item)
    yield
    for flag in cancel_flags.values():
        flag.set()
    if tasks:
        done, pending = await asyncio.wait(tasks, timeout=20)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


app = FastAPI(title="StateProof", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.method in ("POST", "DELETE", "PUT", "PATCH"):
        if os.getenv("STATEPROOF_READ_ONLY", "0") == "1":
            return JSONResponse({"detail": "This deployment is read-only. Run trusted fixtures through the operator CLI."}, status_code=403)
        token = os.getenv("STATEPROOF_TOKEN")
        if token and not secrets.compare_digest(request.headers.get("authorization", ""), "Bearer " + token):
            return JSONResponse({"detail": "A valid operator token is required."}, status_code=401)
        origin = request.headers.get("origin")
        if origin and origin != f'{request.url.scheme}://{request.headers.get("host")}':
            return JSONResponse({"detail": "Cross-origin mutations are disabled."}, status_code=403)
        body = await request.body()
        if len(body) > 262144:
            return JSONResponse({"detail": "Request exceeds 256 KiB limit"}, status_code=413)
    return await call_next(request)


def campaign(identifier):
    try:
        return load_campaign(identifier)
    except (OSError, ValueError):
        raise HTTPException(404, "Campaign not found")


def job_path(identifier):
    # Reuse strict ID validation without accepting a filesystem path from the client.
    return data_root() / "jobs" / campaign_path(identifier).name


def _mark_campaign_terminal(identifier, lifecycle, error):
    try:
        saved = load_campaign(identifier)
    except (OSError, ValueError):
        return
    saved["lifecycle"] = lifecycle
    saved.setdefault("diagnostics", []).append(error)
    write_json(campaign_path(identifier), saved)


def start_job(kind, work, identifier=None, *, campaign_id=None, source_case=None, source_case_label=None):
    global active
    if active:
        raise HTTPException(409, "Another job is active. Wait or cancel it first.")
    if len(list((data_root() / "jobs").glob("*.json"))) >= 500:
        raise HTTPException(507, "Local job retention limit reached; export and archive data before continuing")
    identifier = identifier or uuid.uuid4().hex
    flag = Event()
    cancel_flags[identifier] = flag
    active = identifier
    initial = {"id": identifier, "kind": kind, "lifecycle": "RUNNING", "result": None,
               "campaignId": campaign_id, "sourceCaseId": source_case and source_case["worldId"],
               "sourceCaseLabel": source_case_label or (source_case and source_case.get("label", "case"))}
    write_json(job_path(identifier), initial)

    async def execute():
        global active
        job = dict(initial)
        try:
            job["result"] = await work(flag)
            result_lifecycle = job["result"].get("lifecycle") if isinstance(job["result"], dict) else None
            job["lifecycle"] = result_lifecycle if result_lifecycle in ("CANCELLED", "INTERRUPTED", "FAILED") else ("CANCELLED" if flag.is_set() else "FINISHED")
        except asyncio.CancelledError:
            job.update(lifecycle="INTERRUPTED", error="control service interrupted the active job")
            if kind == "campaign" and campaign_id:
                _mark_campaign_terminal(campaign_id, "INTERRUPTED", job["error"])
            raise
        except Exception as e:
            terminal = "CANCELLED" if flag.is_set() else "FAILED"
            job.update(lifecycle=terminal, error=f"{type(e).__name__}: {e}")
            if kind == "campaign" and campaign_id:
                _mark_campaign_terminal(campaign_id, terminal, job["error"])
        finally:
            write_json(job_path(identifier), job)
            cancel_flags.pop(identifier, None)
            active = None
    task = asyncio.create_task(execute())
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return initial


class CampaignRequest(Strict):
    variant: Variant = "local_dedup"
    operation: Operation = Field(default_factory=Operation)


class ReplayRequest(Strict):
    campaignId: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    caseId: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    manifest: ReplayManifest | None = None
    comparisonVariant: Variant | None = None

    @model_validator(mode="after")
    def one_source(self):
        if (self.campaignId is None) == (self.manifest is None):
            raise ValueError("provide exactly one of campaignId or manifest")
        if self.manifest is not None and self.caseId is not None:
            raise ValueError("caseId is valid only with campaignId")
        return self


@app.get("/api/health")
async def health():
    import psycopg
    try:
        await asyncio.to_thread(lambda: psycopg.connect(**db_config()).close())
        return {"status": "ok", "workerBuilt": (ROOT / "worker/build/PaymentWorker.class").exists()}
    except Exception:
        raise HTTPException(503, "PostgreSQL unavailable")


@app.get("/api/fixtures")
def fixtures():
    return {"fixtures": [{"id": "payment-v1", "name": "Payment capture", "seededBenchmark": True}],
            "variants": VARIANTS, "bounds": BOUNDS, "readOnly": os.getenv("STATEPROOF_READ_ONLY") == "1",
            "tokenRequired": bool(os.getenv("STATEPROOF_TOKEN")), "activeJob": active}


@app.get("/api/campaigns")
def campaigns():
    paths = sorted((data_root() / "campaigns").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]
    return [{k: c.get(k) for k in ("id", "variant", "lifecycle", "counts", "executed")} for c in [json.loads(p.read_text()) for p in paths]]


@app.post("/api/campaigns", status_code=202)
async def create_campaign(body: CampaignRequest):
    identifier = uuid.uuid4().hex
    return start_job("campaign", lambda flag: explore(body.variant, body.operation, flag, identifier), identifier,
                     campaign_id=identifier)


@app.get("/api/campaigns/{identifier}")
def get_campaign(identifier: str):
    return campaign(identifier)


@app.get("/api/campaigns/{identifier}/events")
def events(identifier: str, after: int = -1):
    if after < -1:
        raise HTTPException(422, "Invalid event cursor")
    recorded = [{**e, "caseWorldId": c["worldId"]} for c in campaign(identifier)["cases"] for e in c["events"]]
    return {"events": [{**e, "cursor": i} for i, e in enumerate(recorded) if i > after][:512], "total": len(recorded)}


@app.post("/api/campaigns/{identifier}/reduce", status_code=202)
async def reduce_campaign(identifier: str):
    saved = campaign(identifier)
    case = failure_case(saved)
    if not case:
        raise HTTPException(409, "No evaluated violation to reduce")
    async def work(flag):
        saved["reduction"] = await reduce_case(case, flag)
        write_json(campaign_path(identifier), saved)
        return saved["reduction"]
    return start_job("reduce", work, campaign_id=identifier, source_case=case)


@app.post("/api/replays", status_code=202)
async def create_replay(body: ReplayRequest):
    if body.manifest:
        manifest = body.manifest.model_dump()
        source_case = None
        source_label = None
    else:
        saved = campaign(body.campaignId)
        candidates = list(saved["cases"])
        if saved.get("reduction"):
            candidates.append(saved["reduction"]["case"])
        if body.caseId:
            source_case = next((case for case in candidates if case["worldId"] == body.caseId), None)
            if source_case is None:
                raise HTTPException(422, "caseId does not belong to the campaign")
        else:
            # Compatibility default for API/CLI callers. The browser always sends caseId.
            source_case = failure_case(saved) or next((c for c in saved["cases"] if c["verdict"] == "PASS_WITHIN_BOUNDS"), None)
        if not source_case:
            raise HTTPException(409, "No evaluated case to replay")
        manifest = manifest_for(source_case)
        reduced = saved.get("reduction", {}).get("case")
        source_label = ("reduced failure · " + source_case.get("label", "case")
                        if reduced and reduced["worldId"] == source_case["worldId"] else source_case.get("label", "case"))
    from engine.evidence import validate_manifest
    try:
        validate_manifest(manifest)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return start_job("comparison" if body.comparisonVariant else "replay",
                     lambda flag: replay(manifest, body.comparisonVariant, flag),
                     campaign_id=body.campaignId, source_case=source_case, source_case_label=source_label)


@app.get("/api/campaigns/{identifier}/evidence")
def evidence(identifier: str):
    saved = campaign(identifier)
    if saved["lifecycle"] == "RUNNING":
        raise HTTPException(409, "Wait for campaign completion before exporting")
    path = export_bundle(saved)
    return FileResponse(path, media_type="application/zip", filename=path.name)


@app.post("/api/campaigns/{identifier}/upload", status_code=202)
async def upload(identifier: str):
    if not os.getenv("EVIDENCE_BUCKET"):
        raise HTTPException(409, "S3 is not configured")
    saved = campaign(identifier)
    async def work(flag):
        return await asyncio.to_thread(upload_bundle, export_bundle(saved), identifier)
    return start_job("upload", work, campaign_id=identifier)


@app.get("/api/jobs/{identifier}")
def get_job(identifier: str):
    try:
        return json.loads(job_path(identifier).read_text())
    except (ValueError, OSError):
        raise HTTPException(404, "Job not found")


@app.post("/api/jobs/{identifier}/cancel")
async def cancel(identifier: str):
    if identifier not in cancel_flags:
        raise HTTPException(409, "Job is not active")
    cancel_flags[identifier].set()
    return {"id": identifier, "cancellationRequested": True}


if (ROOT / "frontend/dist").exists():
    app.mount("/", StaticFiles(directory=ROOT / "frontend/dist", html=True), name="console")
