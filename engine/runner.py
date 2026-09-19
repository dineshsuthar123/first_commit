import asyncio
from collections import deque
import json
import os
from pathlib import Path
import sys
import time
import uuid

import httpx

from engine.models import BOUNDS, CasePlan, Verdict
from engine.properties import evaluate
from fixtures.payment import PaymentFixture, ROOT


def data_root():
    path = Path(os.getenv("STATEPROOF_DATA", str(ROOT / "data")))
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


class BoundaryMissing(Exception):
    pass


class Cancelled(Exception):
    pass


async def bounded_read(stream, output):
    while chunk := await stream.read(2048):
        output.append(chunk.decode(errors="replace"))


async def stop(process):
    if process and process.returncode is None:
        process.kill()
        await asyncio.wait_for(process.wait(), 5)


async def run_case(plan: CasePlan, cancel=None, fixture=None):
    fixture = fixture or PaymentFixture()
    world_id = uuid.uuid4().hex
    schema = "sp_" + world_id
    directory = data_root() / "worlds" / world_id
    directory.mkdir(parents=True)
    result = {"worldId": world_id, "plan": plan.model_dump(), "verdict": None,
              "events": [], "properties": [], "observation": None, "diagnostics": [], "lifecycle": "RUNNING"}
    processes = []
    drains = []
    logs = []
    started = time.monotonic()
    initialized = False

    def event(kind, **fields):
        result["events"].append({"seq": len(result["events"]), "type": kind, **fields})

    def check_cancel():
        if cancel and cancel.is_set():
            raise Cancelled("cancelled by caller")

    async def launch(command, **kwargs):
        p = await asyncio.create_subprocess_exec(*command, cwd=ROOT, stdin=asyncio.subprocess.PIPE,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **kwargs)
        processes.append(p)
        output = deque(maxlen=16)
        logs.append((p.pid, output))
        drains.append(asyncio.create_task(bounded_read(p.stderr, output)))
        return p

    async def read(p):
        deadline = time.monotonic() + BOUNDS["attemptTimeoutSeconds"]
        task = asyncio.create_task(p.stdout.readline())
        try:
            while not task.done():
                check_cancel()
                if time.monotonic() > deadline:
                    raise TimeoutError("process protocol deadline exceeded")
                await asyncio.wait({task}, timeout=.1)
            line = task.result()
            if not line:
                await p.wait()
                raise RuntimeError(f"unexpected process exit: {p.returncode}")
            if len(line) > 16384:
                raise RuntimeError("protocol line too long")
            return json.loads(line)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    try:
        check_cancel()
        await asyncio.to_thread(fixture.reset, schema)
        initialized = True
        provider = await launch([sys.executable, "-u", "-m", "provider.server", "--db", str(directory / "provider.sqlite")])
        ready = await read(provider)
        if ready.get("type") != "ready":
            raise RuntimeError("invalid provider startup protocol")
        url = f'http://127.0.0.1:{ready["port"]}'
        event("provider_started", pid=provider.pid, port=ready["port"])
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            async def ledger():
                r = await client.get(url + "/ledger")
                r.raise_for_status()
                return r.json()

            known_effects = set()
            delivered = set()
            operations = {o.operationId: o for o in plan.operations}
            for action in plan.actions:
                check_cancel()
                worker = await launch(fixture.worker_command(), env=fixture.worker_env(schema, url))
                event("delivery", operationId=action.operationId, attempt=action.attempt, pid=worker.pid)
                delivered.add(action.operationId)
                message = {"operation": operations[action.operationId].model_dump(), "variant": plan.variant,
                           "attempt": action.attempt, "attemptId": f"{world_id}:{action.operationId}:{action.attempt}"}
                worker.stdin.write((json.dumps(message) + "\n").encode())
                await worker.stdin.drain()
                reached = False
                deadline = time.monotonic() + BOUNDS["attemptTimeoutSeconds"]
                while True:
                    if time.monotonic() > deadline:
                        raise TimeoutError("attempt budget exceeded")
                    e = await read(worker)
                    if e.get("operationId") != action.operationId or e.get("attempt") != action.attempt:
                        raise RuntimeError("protocol identity mismatch")
                    kind = e.pop("type")
                    event(kind, **e)
                    if kind == "checkpoint":
                        captures = await ledger()
                        for capture in captures:
                            if capture["effectId"] not in known_effects:
                                known_effects.add(capture["effectId"])
                                event("effect_committed", **capture)
                        if action.fault and all(e.get(k) == v for k, v in action.fault.model_dump(exclude={"decision"}).items()):
                            await stop(worker)
                            if worker.returncode is None or provider.returncode is not None:
                                raise RuntimeError("injected termination not confirmed or provider died")
                            reached = True
                            event("worker_terminated", pid=worker.pid, returncode=worker.returncode,
                                  boundary=action.fault.model_dump(), survivingLedger=await ledger())
                            break
                        worker.stdin.write(b'{"decision":"continue"}\n')
                        await worker.stdin.drain()
                    elif kind == "ack":
                        await asyncio.wait_for(worker.wait(), 5)
                        if worker.returncode != 0:
                            raise RuntimeError(f"worker exited after ack: {worker.returncode}")
                        break
                    elif kind != "provider_response":
                        raise RuntimeError(f"unknown protocol event: {kind}")
                if action.fault and not reached:
                    raise BoundaryMissing("expected checkpoint was not reached")
                # Preserve earliest post-delivery duplicate and stop additional workload.
                captures = await ledger()
                duplicates = [op for op in operations if sum(r["operationId"] == op for r in captures) > 1]
                if duplicates:
                    event("earliest_duplicate_observation", operationIds=duplicates, ledger=captures)
                    break
            observation = await asyncio.to_thread(fixture.observe, schema, await ledger())
            result["observation"] = observation.model_dump()
            result["properties"] = [p.model_dump() for p in evaluate([o for o in plan.operations if o.operationId in delivered], observation)]
            result["verdict"] = Verdict.VIOLATION if any(not p["passed"] for p in result["properties"]) else Verdict.PASS
    except BoundaryMissing as e:
        result["verdict"] = Verdict.DIVERGED
        result["diagnostics"].append(str(e))
    except (TimeoutError, Cancelled) as e:
        result["verdict"] = Verdict.INCONCLUSIVE
        result["diagnostics"].append(str(e))
        if isinstance(e, Cancelled):
            result["lifecycle"] = "CANCELLED"
    except Exception as e:
        result["verdict"] = Verdict.ERROR
        result["diagnostics"].append(f"{type(e).__name__}: {e}")
    finally:
        for process in reversed(processes):
            await stop(process)
        await asyncio.gather(*drains, return_exceptions=True)
        result["logs"] = [{"pid": pid, "stderr": "".join(log)} for pid, log in logs]
        if initialized:
            try:
                await asyncio.to_thread(fixture.cleanup, schema)
            except Exception as e:
                result["diagnostics"].append(f"schema cleanup failed: {e}")
                result["verdict"] = Verdict.ERROR
        if result["lifecycle"] == "RUNNING":
            result["lifecycle"] = "FINISHED"
        result["elapsedSeconds"] = round(time.monotonic() - started, 3)
        write_json(directory / "result.json", result)
    return result
