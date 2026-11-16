"""Additive account-global pre-admission scheduler; no calls at import.

Only run_slots is copied from frozen adaption_v6h. Stream parsing, request bodies,
costs, append-only ledgers and retry policy are imported unchanged. The added
global interval gates reservation/task creation, so pacing never consumes the
180-second attempt timeout. One coordinator is required; the caller must enforce
exclusive account use, a closed previous run, and the prospective execution gate.
Global admission spacing is a local policy, not a verified vendor rate limit.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from copy import deepcopy
import hashlib
from itertools import chain
import json
import math
from pathlib import Path
import time
import uuid

from .adaption_v6h import (
    AiohttpTransport, RollingLedger, CAP, ENDPOINT, KNOWN_ERRORS, MODEL_PRICING,
    PRICING_URL, RETRY_POLICY, VERIFIED_DATE, DurableJSONL, StreamJournal,
    SSEDecoder, build_body, consume_stream, credits, digest, encoded, integer,
    now, plan, request_bound, require, response_text, retry_delay,
    slot_dependencies, strict_event_json, usage_cost, validate_slots,
)

async def run_slots(slots,*,api_key,output_dir,ledger,transport,global_interval,canary=False,model_interval=2.0,
                    per_model_concurrency=8,concurrency=48,timeout_seconds=180,stop_file=None,
                    _clock=None,_sleep=None,_jitter=None):
    """Concurrent DAG scheduler. Explicit 429 attempts are retained and bounded.

    Request intent/reservation precede transport. Every issued attempt has its
    own response row; slot-outcomes has one final scheduled outcome per slot.
    Neither final-output selection nor retries overwrite the first attempt.
    """
    require(type(global_interval) in (int,float) and math.isfinite(global_interval) and 0.5<=global_interval<=60,"invalid_global_interval")
    clock=time.monotonic if _clock is None else _clock
    sleep=asyncio.sleep if _sleep is None else _sleep
    slots=validate_slots(slots,canary=canary)
    require(isinstance(api_key,str) and len(api_key)>=8 and not any(c.isspace() for c in api_key),"invalid_credential")
    require(api_key not in encoded(slots) and api_key not in str(output_dir),"credential_in_configuration")
    integer(concurrency,1,384,"invalid_concurrency");integer(per_model_concurrency,1,64,"invalid_model_concurrency")
    require(0<=model_interval<=60 and 0<timeout_seconds<=180,"invalid_timing")
    require(not ledger.halted,"ledger_halted")
    scrub=lambda text:text.replace(api_key,"[REDACTED_CREDENTIAL]").replace(json.dumps(api_key)[1:-1],"[REDACTED_CREDENTIAL]")
    directory=Path(output_dir);directory.mkdir(parents=True,exist_ok=False);(directory/"streams").mkdir()
    run_id=uuid.uuid4().hex
    manifest={**plan(slots,canary=canary),"run_id":run_id,"created_at":now(),"endpoint":ENDPOINT,
        "models_pricing":MODEL_PRICING,"pricing_source":PRICING_URL,"pricing_verified_date":VERIFIED_DATE,
        "transport_revision":"pre_admission_global_v6h_v1","global_interval_seconds":global_interval,
        "ready_model_order":"deterministic_round_robin_first_appearance; preserve eligible slot order within model",
        "global_pacing_scope":"One coordinator; spacing before reservation and attempt timeout, not a verified provider quota.",
        "model_interval_seconds":model_interval,"per_model_concurrency":per_model_concurrency,"concurrency":concurrency,
        "timeout_seconds":timeout_seconds,"max_retries":2,"store":False,"previous_response_id":None,
        "agentic_memory":False,"tools":False,"stream":True,"budget_before":ledger.snapshot(),"slots":slots,
        "prior_ledger_replay":ledger.prior_evidence,"stop_file":str(stop_file) if stop_file else None,
        "test_hooks":any(x is not None for x in (_clock,_sleep,_jitter))}
    files=[]
    try:
        for name in ("run.json","requests.jsonl","responses.jsonl","slot-outcomes.jsonl"):
            files.append(DurableJSONL(directory/name,scrub=scrub))
        manifest_file,requests,responses,slot_file=files;manifest_file.write(manifest)
        ledger.record({"kind":"run_started","run_id":run_id,"sessions_sha256":digest(slots),"planned":len(slots)})
        stopped=False;stop_reasons=[];cooldown_until=0.0;consecutive_429=0;total_429=0
        completed={};finals={};attempt_rows=[];issued_ids=[];active={};counts=Counter();last_start={}
        last_global_start=-1e20
        model_order=list(dict.fromkeys(slot["model"] for slot in slots))
        model_slots={model:[slot for slot in slots if slot["model"]==model] for model in model_order}
        model_cursor=0
        states={s["slot_id"]:{"attempts":0,"not_before":0.0,"status":"pending"} for s in slots}

        def stop(reason,attempt_id=None):
            nonlocal stopped
            stopped=True
            if reason not in stop_reasons:
                stop_reasons.append(reason)
                try:ledger.record({"kind":"halt","run_id":run_id,"reason":reason,"attempt_id":attempt_id})
                except Exception:
                    if "ledger_write_failure" not in stop_reasons:stop_reasons.append("ledger_write_failure")

        def check_stop_file():
            if stop_file and Path(stop_file).exists():stop("administrative_stop_file")

        def finalize(slot,row):
            key=slot["slot_id"]
            require(key not in finals,"duplicate_slot_outcome")
            out={**row,"slot_final":True,"attempts_issued":states[key]["attempts"],
                "first_attempt_id":next((r["attempt_id"] for r in attempt_rows if r["slot_id"]==key),None)}
            slot_file.write(out);finals[key]=out;states[key]["status"]="done"

        def skipped(slot,reason,blocked=()):
            return {"run_id":run_id,"slot_id":slot["slot_id"],"case_id":slot["case_id"],"model":slot["model"],
                "condition":slot["condition"],"phase":slot["phase"],"issued":False,"terminal_valid":False,
                "model_outcome":reason,"error":reason,"response_status":None,"output_text":"",
                "blocked_dependencies":list(blocked),"at":now()}

        async def attempt(slot,body,attempt_id,bound,attempt_number):
            nonlocal cooldown_until,consecutive_429,total_429
            started=clock();raw=None;parsed=None;cost=None;text="";error=None;status=None;model_outcome=None
            journal=None;decoder=SSEDecoder();model=slot["model"]
            header_delay=None
            def observe_headers(headers):
                nonlocal cooldown_until,header_delay
                if headers["http_status"]==429:
                    header_delay=retry_delay(headers.get("retry_after"),attempt_number-1,jitter=_jitter() if _jitter else None)
                    cooldown_until=max(cooldown_until,clock()+header_delay)
            try:
                journal=StreamJournal(directory/"streams"/(hashlib.sha256(attempt_id.encode()).hexdigest()+".sse"),api_key)
                status,raw=await asyncio.wait_for(consume_stream(transport(body),journal,decoder,observe_headers),timeout=timeout_seconds)
                require(scrub(raw)==raw,"credential_echo_detected")
                parsed=strict_event_json(raw)
                require(parsed.get("model")==model,"response_model_mismatch")
                cost=usage_cost(model,parsed.get("usage"),slot["max_output_tokens"])
                require(cost<=bound,"reservation_bound_breached")
                text=response_text(parsed)
                model_outcome="completed" if parsed["status"]=="completed" else "truncated_max_output_tokens"
            except asyncio.TimeoutError:error="timeout"
            except UnicodeError:error="stream_invalid_utf8"
            except ValueError as exc:
                code=str(exc)
                error=code if code in KNOWN_ERRORS or (code.startswith("http_") and len(code)==8 and code[5:].isdigit()) else "invalid_response"
            except Exception:error="network_or_transport_failure"
            finally:
                if journal:
                    try:journal.close()
                    except Exception:error="stream_journal_failure"
            status=status if status is not None else journal.http_status if journal else None
            is_429=error=="http_429" and status==429
            # A 429 can settle only if its exact complete JSON body contains
            # bounded, internally consistent usage. No absent usage is guessed.
            if is_429 and journal and not journal.redacted:
                try:
                    error_body=strict_event_json(journal.path.read_text(encoding="utf-8"))
                    require(error_body.get("model",model)==model,"response_model_mismatch")
                    candidate_cost=usage_cost(model,error_body.get("usage"),slot["max_output_tokens"])
                    require(candidate_cost<=bound,"reservation_bound_breached")
                    parsed=error_body;cost=candidate_cost
                except (ValueError,UnicodeError,OSError):cost=None
            delay=None
            if is_429:
                total_429+=1;consecutive_429+=1
                delay=header_delay if header_delay is not None else retry_delay(getattr(journal,"retry_after",None),attempt_number-1,jitter=_jitter() if _jitter else None)
                cooldown_until=max(cooldown_until,clock()+delay)
            elif error is None:
                consecutive_429=0
            row={"run_id":run_id,"attempt_id":attempt_id,"attempt_number":attempt_number,"first_attempt":attempt_number==1,
                "slot_id":slot["slot_id"],"case_id":slot["case_id"],"model":model,"condition":slot["condition"],"phase":slot["phase"],
                "issued":True,"terminal_valid":error is None,"model_outcome":model_outcome if error is None else "http_429" if is_429 else "operational_failure",
                "response_status":parsed.get("status") if isinstance(parsed,dict) else None,"http_status":status,"error":error,
                "raw_response":scrub(raw) if isinstance(raw,str) else None,"stream_evidence":journal.metadata() if journal else None,
                "stream_terminal_event":decoder.terminal,"stream_event_count":decoder.event_count,
                "output_text":text if error is None and model_outcome=="completed" else "",
                "partial_output_text":text if error is None and model_outcome=="truncated_max_output_tokens" else "",
                "usage":parsed.get("usage") if isinstance(parsed,dict) else None,"latency_ms":round((clock()-started)*1000,3),
                "at":now(),"reserved_credits":credits(bound),"settled_credits":credits(cost) if cost is not None and (error is None or is_429) else None,
                "retry_after":getattr(journal,"retry_after",None),"retry_cooldown_seconds":delay}
            try:
                responses.write(row);attempt_rows.append(row)
                if cost is not None and (error is None or is_429):
                    ledger.record({"kind":"settle","attempt_id":attempt_id,"accounted_nanocredits":cost,"response_sha256":digest(row),
                        "basis":"explicit_bounded_usage_uncached_no_double_reasoning","model_outcome":row["model_outcome"]})
                elif is_429:
                    ledger.record({"kind":"retain_429","attempt_id":attempt_id,"response_sha256":digest(row),"basis":"explicit_429_no_valid_usage_full_bound_retained"})
                if is_429 and (consecutive_429>=10 or total_429>=20):stop("rate_limit_flood_stop",attempt_id)
                elif error is not None and not is_429:stop(error,attempt_id)
                if is_429 and attempt_number<3 and not stopped:
                    states[slot["slot_id"]].update(status="pending",not_before=cooldown_until)
                else:
                    if error is None and model_outcome=="completed":
                        completed[slot["slot_id"]]={"actual_input":body["input"][-1]["content"],"output_text":text}
                    finalize(slot,row)
            except Exception:stop("response_or_settlement_journal_failure",attempt_id)

        async def guarded_attempt(*args):
            try:await attempt(*args)
            except BaseException:stop("unexpected_attempt_failure",args[2])

        async def scheduler():
            nonlocal last_global_start,model_cursor
            while True:
                check_stop_file()
                for task,(slot,_) in list(active.items()):
                    if task.done():
                        await task;counts[slot["model"]]-=1;del active[task]
                if not stopped:
                    ready_order=model_order[model_cursor:]+model_order[:model_cursor]
                    for slot in chain.from_iterable(model_slots[model] for model in ready_order):
                        key=slot["slot_id"];state=states[key]
                        if state["status"]!="pending":continue
                        deps=slot_dependencies(slot)
                        bad=[d for d in deps if d in finals and d not in completed]
                        if bad:
                            finalize(slot,skipped(slot,"not_issued_dependency_failed",bad));continue
                        if any(d not in completed for d in deps):continue
                        tick=clock();model=slot["model"]
                        if len(active)>=concurrency:break
                        if counts[model]>=per_model_concurrency or tick<max(cooldown_until,state["not_before"],last_start.get(model,-1e20)+model_interval,last_global_start+global_interval):continue
                        check_stop_file()
                        if stopped:break
                        body=build_body(slot,completed);bound=request_bound(model,slot["max_output_tokens"])
                        if ledger.accounted+bound>CAP:
                            # Active reservations may settle below their full
                            # bounds. Drain them before declaring exhaustion;
                            # cheaper ready attempts may still fit meanwhile.
                            if active:continue
                            stop("cumulative_budget_stop");break
                        number=state["attempts"]+1;attempt_id=run_id+":"+key+":attempt-"+str(number)
                        try:
                            ledger.record({"kind":"reserve","attempt_id":attempt_id,"run_id":run_id,"slot_id":key,
                                "attempt_number":number,"model":model,"bound_nanocredits":bound})
                            requests.write({"attempt_id":attempt_id,"slot_id":key,"attempt_number":number,"first_attempt":number==1,"at":now(),
                                "request":body,"request_sha256":digest(body),"reserved_credits":credits(bound),
                                "dependency_bindings":[{"slot_id":d,"final_attempt_id":finals[d].get("attempt_id"),"output_sha256":hashlib.sha256(completed[d]["output_text"].encode()).hexdigest()} for d in deps]})
                        except Exception:stop("reservation_or_request_journal_failure",attempt_id);break
                        state.update(attempts=number,status="running");issued_ids.append(key);last_start[model]=clock();counts[model]+=1
                        last_global_start=last_start[model]
                        model_cursor=(model_order.index(model)+1)%len(model_order)
                        task=asyncio.create_task(guarded_attempt(slot,body,attempt_id,bound,number));active[task]=(slot,attempt_id)
                        break  # Recompute ready-model rotation after every actual admission.
                if not active:
                    if stopped or all(s["status"]=="done" for s in states.values()):break
                    # An earlier-only dependency graph cannot deadlock unless
                    # local bookkeeping failed. Waiting for pacing is allowed.
                    pending=[s for s in slots if states[s["slot_id"]]["status"]=="pending"]
                    if not any(all(d in completed for d in slot_dependencies(s)) for s in pending):
                        stop("dependency_scheduler_deadlock");break
                await sleep(.05)
        task=asyncio.create_task(scheduler())
        try:await asyncio.shield(task)
        except asyncio.CancelledError:
            stop("administrative_run_cancelled");await asyncio.shield(task)
        except BaseException:
            stop("unexpected_scheduler_failure")
        if active:
            await asyncio.shield(asyncio.gather(*active,return_exceptions=True))
        # One durable scheduled outcome for every slot, including administrative
        # closure, exhausted retries, and slots not issued because of a failure.
        for slot in slots:
            key=slot["slot_id"]
            if key in finals:continue
            rows=[r for r in attempt_rows if r["slot_id"]==key]
            if rows:finalize(slot,{**rows[-1],"retry_abandoned_due_global_stop":rows[-1]["model_outcome"]=="http_429"})
            else:finalize(slot,skipped(slot,"issued_without_response" if states[key]["attempts"] else "not_issued_global_stop"))
        first=[r for r in attempt_rows if r["first_attempt"]]
        summary={"schema":"retrace.adaption-v6h-summary.v1","run_id":run_id,"status":"stopped" if stopped else "completed",
            "transport_revision":"pre_admission_global_v6h_v1","global_interval_seconds":global_interval,
            "canary":canary,"stream":True,"models":dict(Counter(s["model"] for s in slots)),"planned":len(slots),
            "issued_attempts":len(issued_ids),"issued_slots":len(set(issued_ids)),"responses":len(attempt_rows),
            "slot_outcomes":len(finals),"completed":len(completed),"stop_reasons":stop_reasons,
            "first_attempt_completed":sum(r["model_outcome"]=="completed" for r in first),
            "first_attempt_valid_terminal_records":sum(r["terminal_valid"] for r in first),
            "first_attempt_truncated":sum(r["model_outcome"]=="truncated_max_output_tokens" for r in first),
            "first_attempt_http_429":sum(r["model_outcome"]=="http_429" for r in first),
            "eventual_completed":len(completed),"valid_terminal_records":sum(r["terminal_valid"] for r in attempt_rows),
            "eventual_terminal_slots":sum(r["terminal_valid"] for r in finals.values()),
            "truncated":sum(r["model_outcome"]=="truncated_max_output_tokens" for r in finals.values()),
            "http_429_attempts":total_429,"issued_operational_failures":sum(r["model_outcome"]=="operational_failure" for r in attempt_rows),
            "dependency_skips":sum(r["model_outcome"]=="not_issued_dependency_failed" for r in finals.values()),
            "unissued_slot_ids":[s["slot_id"] for s in slots if not states[s["slot_id"]]["attempts"]],
            "issued_without_outcome_attempt_ids":[],
            "retries":len(issued_ids)-len(set(issued_ids)),"max_retries_per_slot":2,"retry_policy":deepcopy(RETRY_POLICY),
            "all_scheduled_outcomes_recorded":len(finals)==len(slots),"budget":ledger.snapshot(),"actual_billed_credits":None,
            "completion_definition":"Scheduling closure; first attempts, retries, truncations and final slot outcomes remain separate."}
        # Derive actual orphan attempt IDs from request ledger, not slot counts.
        run_attempts={a for a in ledger.attempts if a.startswith(run_id+":")}
        summary["issued_without_outcome_attempt_ids"]=sorted(run_attempts-{r["attempt_id"] for r in attempt_rows})
        ledger.record({"kind":"run_closed","run_id":run_id,"status":summary["status"],"issued_attempts":len(issued_ids),
            "issued_slots":len(set(issued_ids)),"unissued_slots":len(summary["unissued_slot_ids"]),"administrative":any(r.startswith("administrative_") for r in stop_reasons)})
        summary["budget"]=ledger.snapshot()
        sf=DurableJSONL(directory/"summary.json",scrub=scrub);files.append(sf);sf.write(summary)
        return summary
    finally:
        for file in files:file.close()
