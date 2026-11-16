"""Strict SSE and retained-carry tests; synthetic transport only, zero API calls."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.run_frontier_v6f import integrity, verify_canary

from retrace.adaption_v6f import (BASELINE,BASELINE_LEDGER,BASELINE_SHA256,MODEL_PRICING,
    RollingLedger,SSEDecoder,StreamJournal,consume_stream,run_slots,verify_prior_ledger,nano,request_bound,usage_cost)

ROOT=Path(__file__).resolve().parents[1]
KEY="synthetic-stream-test-key-only"
MODEL=next(iter(MODEL_PRICING))


def slot(i=0,model=MODEL,**extra):
    return {"slot_id":f"new-{i}","case_id":"new-off-benchmark","model":model,"condition":"test",
            "phase":"extract","instructions":"Public source only","input":"New source text",
            "max_output_tokens":1024,**extra}


def frame(value,**kwargs):
    return ("data: "+json.dumps(value,ensure_ascii=False,**kwargs)+"\n\n").encode()


def completed(model=MODEL,text="answer",usage=True):
    response={"id":"resp-new","status":"completed","model":model,"output_text":text}
    if usage:
        response["usage"]={"input_tokens":100,"output_tokens":20,"total_tokens":120}
    return {"type":"response.completed","sequence_number":2,"response":response}


def stream_bytes(model=MODEL,text="answer",usage=True):
    return (frame({"type":"response.created","sequence_number":0,"response":{"id":"resp-new","status":"in_progress"}})
            +frame({"type":"response.output_text.delta","sequence_number":1,"delta":text})
            +frame(completed(model,text,usage)))


def truncated(model=MODEL,text="partial",usage=True,kind="response.completed"):
    event=completed(model,text,usage);event["type"]=kind
    event["response"]["status"]="incomplete"
    event["response"]["incomplete_details"]={"reason":"max_output_tokens"}
    return frame(event)


async def emit(raw,status=200,content_type="text/event-stream",chunk=37):
    yield {"http_status":status,"content_type":content_type}
    for pos in range(0,len(raw),chunk):
        yield raw[pos:pos+chunk]


class SSETests(unittest.TestCase):
    def decode(self,raw,chunk=1):
        parser=SSEDecoder()
        for pos in range(0,len(raw),chunk): parser.feed(raw[pos:pos+chunk])
        return parser.finish()

    def test_all_utf8_chunk_boundaries_and_complete_response(self):
        raw=stream_bytes(text="A 🧭 café")
        for chunk in (1,2,7,64,99999):
            with self.subTest(chunk=chunk):
                self.assertEqual(self.decode(raw,chunk)["output_text"],"A 🧭 café")

    def test_crlf_multiline_data_comments_and_optional_done(self):
        event=completed()
        pretty=json.dumps(event,indent=2)
        raw=(": heartbeat\r\n\r\n"+"\r\n".join("data: "+line for line in pretty.splitlines())+"\r\n\r\ndata: [DONE]\r\n\r\n").encode()
        self.assertEqual(self.decode(raw)["status"],"completed")

    def test_deltas_done_and_eof_never_prove_completion(self):
        for raw in (b"",frame({"type":"response.output_text.delta","delta":"answer"}),b"data: [DONE]\n\n",
                    frame({"type":"response.output_text.done","text":"answer"})):
            with self.subTest(raw=raw),self.assertRaises(ValueError): self.decode(raw)

    def test_strict_json_duplicate_nonfinite_trailing_and_nonobject(self):
        for raw in (b'data: {"type":"response.created","type":"response.completed"}\n\n',
                    b'data: {"type":"response.created","x":NaN}\n\n',b'data: []\n\n',b'data: garbage\n\n'):
            with self.subTest(raw=raw),self.assertRaises(ValueError): self.decode(raw)

    def test_duplicate_terminal_and_text_after_terminal_reject(self):
        first=frame(completed())
        for rest in (frame(completed()),frame({"type":"response.output_text.delta","delta":"later"}),b"data: [DONE]\n\ndata: [DONE]\n\n"):
            with self.assertRaises(ValueError): self.decode(first+rest)

    def test_error_or_noncompleted_lifecycle_is_not_completed(self):
        for kind in ("error","response.failed","response.cancelled"):
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,"terminal_error"):
                self.decode(frame({"type":kind,"message":"failed"}))
        event=completed();event["response"]["status"]="incomplete"
        with self.assertRaisesRegex(ValueError,"unaccepted_incomplete_reason"):self.decode(frame(event))

    def test_missing_final_id_or_changed_id_reject(self):
        event=completed();event["response"].pop("id")
        with self.assertRaisesRegex(ValueError,"missing_response_id"):self.decode(frame(event))
        earlier=frame({"type":"response.created","response":{"id":"different"}})
        with self.assertRaisesRegex(ValueError,"response_id_changed"):self.decode(earlier+frame(completed()))

    def test_text_mismatch_and_truncated_frame_are_not_repaired(self):
        raw=frame({"type":"response.output_text.delta","delta":"partial"})+frame(completed(text="other"))
        with self.assertRaisesRegex(ValueError,"text_mismatch"):self.decode(raw)
        with self.assertRaisesRegex(ValueError,"truncated_frame"):self.decode(frame(completed()).rstrip(b"\n"))

    def test_event_name_must_match_payload_type(self):
        raw=b"event: response.created\n"+frame(completed())
        with self.assertRaisesRegex(ValueError,"type_mismatch"):self.decode(raw)

    def test_cross_chunk_credential_redaction_and_original_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"raw.sse"
            journal=StreamJournal(path,KEY)
            raw=b"prefix"+KEY.encode()+b"suffix"
            with self.assertRaisesRegex(ValueError,"credential_echo"):
                for value in raw:journal.feed(bytes([value]))
            journal.close()
            self.assertNotIn(KEY,path.read_text())
            self.assertIn("[REDACTED_CREDENTIAL]",path.read_text())
            self.assertTrue(journal.metadata()["credential_redacted"])

    def test_prior_ledger_replay_keeps_seven_unknown_bounds(self):
        before=(ROOT/BASELINE_LEDGER).read_bytes()
        evidence=verify_prior_ledger(ROOT/BASELINE_LEDGER)
        self.assertEqual(evidence["carry_credits"],"42.997746364")
        self.assertEqual(evidence["unknown_full_bounds_retained"],1)
        self.assertEqual(evidence["unknown_bound_credits"],"0.04532224")
        self.assertEqual(evidence["earlier_frozen_ledger"]["unknown_full_bounds_retained"],2)
        self.assertEqual(evidence["earlier_frozen_ledger"]["earlier_frozen_ledger"]["unknown_full_bounds_retained"],4)
        self.assertEqual(evidence["cumulative_inherited_unsettled_attempts"],7)
        self.assertEqual(hashlib.sha256(before).hexdigest(),BASELINE_SHA256)
        self.assertEqual((ROOT/BASELINE_LEDGER).read_bytes(),before)

    def test_cli_authorization_cannot_reset_or_change_prior_ledger(self):
        authorization=json.loads((ROOT/"data/frontier-v6f-authorization.json").read_text(encoding="utf-8"))
        models=json.loads((ROOT/"data/frontier-v6c-model-availability.json").read_text(encoding="utf-8"))
        self.assertEqual(integrity(authorization,models),555)
        for key,value in (("historical_conservative_carry_credits","40.98826224"),
                          ("prior_ledger_sha256","0"*64),
                          ("prior_ledger_path","results/other/ledger.jsonl")):
            changed=deepcopy(authorization);changed[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):integrity(changed,models)

    def test_both_max_token_terminal_event_names_are_explicit_truncation(self):
        for kind in ("response.completed","response.incomplete"):
            response=self.decode(truncated(kind=kind)+b"data: [DONE]\n\n")
            self.assertEqual(response["status"],"incomplete")
            self.assertEqual(response["incomplete_details"]["reason"],"max_output_tokens")

    def test_other_incomplete_reason_and_event_status_mismatch_reject(self):
        event=completed();event["response"]["status"]="incomplete"
        for reason in (None,"content_filter","unknown"):
            event["response"]["incomplete_details"]={"reason":reason}
            with self.assertRaisesRegex(ValueError,"unaccepted_incomplete"):self.decode(frame(event))
        event=completed();event["type"]="response.incomplete"
        with self.assertRaisesRegex(ValueError,"invalid_terminal"):self.decode(frame(event))

    def test_canary_gate_counts_valid_terminal_outcomes_not_semantic_success(self):
        canary={"schema":"retrace.adaption-v6f-summary.v1","stream":True,"canary":True,"status":"completed",
                "planned":10,"issued":10,"responses":10,"valid_terminal_records":10,"completed":6,"truncated":4,
                "issued_operational_failures":0,"dependency_skips":0,"unissued_due_global_halt_slot_ids":[],
                "models":{m:2 for m in MODEL_PRICING}}
        verify_canary(canary)
        for key,value in (("valid_terminal_records",9),("issued_operational_failures",1),("completed",7),("status","stopped")):
            changed=deepcopy(canary);changed[key]=value
            with self.assertRaises(ValueError):verify_canary(changed)

    def test_new_output_ceiling_is_bounded_by_authenticated_models(self):
        from retrace.adaption_v6f import validate_slots
        for maximum in (8192,32768,65536):self.assertEqual(validate_slots([slot(max_output_tokens=maximum)])[0]["max_output_tokens"],maximum)
        with self.assertRaises(ValueError):validate_slots([slot(max_output_tokens=65537)])

    def test_journal_close_failure_still_closes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal=StreamJournal(Path(tmp)/"raw.sse",KEY)
            journal.feed(b"small tail")
            with patch.object(journal,"_save",side_effect=OSError("synthetic disk error")):
                with self.assertRaises(OSError):journal.close()
            self.assertTrue(journal.closed)
            self.assertTrue(journal.file.closed)


class StreamingRunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)
        self.ledger=RollingLedger(self.path/"budget",baseline_path=ROOT/BASELINE_LEDGER)
        self.addCleanup(self.ledger.close)
        self.clock_value=0.0
        self.waits=[]

    def clock(self): return self.clock_value

    async def sleep(self,seconds):
        self.waits.append(seconds);self.clock_value+=seconds
        await asyncio.sleep(0)

    async def run_mock(self,slots,transport,**settings):
        return await run_slots(slots,api_key=KEY,output_dir=self.path/"run",ledger=self.ledger,transport=transport,
                               global_interval=settings.pop("global_interval",0),
                               model_interval=settings.pop("model_interval",0),
                               _clock=self.clock,_sleep=self.sleep,**settings)

    def responses(self):
        return [json.loads(x) for x in (self.path/"run/responses.jsonl").read_text().splitlines()]

    async def test_success_requires_completed_event_and_final_usage(self):
        bodies=[]
        def fake(body):bodies.append(body);return emit(stream_bytes(body["model"]))
        summary=await self.run_mock([slot()],fake)
        self.assertTrue(bodies[0]["stream"])
        self.assertEqual(summary["completed"],1)
        self.assertEqual(self.ledger.accounted,nano(BASELINE)+usage_cost(MODEL,{"input_tokens":100,"output_tokens":20},1024))
        row=self.responses()[0]
        self.assertEqual(row["stream_terminal_event"],"response.completed")
        self.assertEqual(row["stream_event_count"],3)
        self.assertEqual(Path(row["stream_evidence"]["raw_stream_path"]).read_bytes(),stream_bytes())

    async def test_partial_stream_retained_and_bound_not_released(self):
        raw=frame({"type":"response.output_text.delta","delta":"partial"})
        summary=await self.run_mock([slot(),slot(1)],lambda body:emit(raw))
        self.assertEqual(summary["issued"],1)
        self.assertEqual(summary["stop_reasons"],["stream_missing_terminal_event"])
        self.assertEqual(self.ledger.accounted,nano(BASELINE)+request_bound(MODEL,1024))
        row=self.responses()[0]
        self.assertEqual(row["output_text"],"")
        self.assertEqual(Path(row["stream_evidence"]["raw_stream_path"]).read_bytes(),raw)

    async def test_complete_event_without_usage_stops_and_retains_bound(self):
        summary=await self.run_mock([slot(),slot(1)],lambda body:emit(stream_bytes(usage=False)))
        self.assertEqual(summary["stop_reasons"],["missing_usage"])
        self.assertEqual(summary["budget"]["unsettled_attempts"],1)

    async def test_http_504_body_preserved_and_no_retry(self):
        calls=[]
        def fake(body):calls.append(body);return emit(b'{"error":"gateway"}',504,"application/json")
        summary=await self.run_mock([slot(),slot(1)],fake)
        self.assertEqual(len(calls),1)
        self.assertEqual(summary["stop_reasons"],["http_504"])
        row=self.responses()[0]
        self.assertEqual(row["http_status"],504)
        self.assertEqual(Path(row["stream_evidence"]["raw_stream_path"]).read_bytes(),b'{"error":"gateway"}')

    async def test_wrong_content_type_is_not_nonstream_fallback(self):
        raw=json.dumps(completed()["response"]).encode()
        summary=await self.run_mock([slot()],lambda body:emit(raw,200,"application/json"))
        self.assertEqual(summary["stop_reasons"],["stream_wrong_content_type"])
        self.assertEqual(Path(self.responses()[0]["stream_evidence"]["raw_stream_path"]).read_bytes(),raw)

    async def test_error_frame_and_later_received_bytes_preserved(self):
        raw=frame({"type":"error","code":"server_error"})+b": bytes already received in same chunk\n\n"
        summary=await self.run_mock([slot()],lambda body:emit(raw,chunk=len(raw)))
        self.assertEqual(summary["stop_reasons"],["stream_terminal_error"])
        row=self.responses()[0]
        self.assertEqual(row["stream_terminal_event"],"error")
        self.assertEqual(Path(row["stream_evidence"]["raw_stream_path"]).read_bytes(),raw)

    async def test_timeout_keeps_raw_partial_frame_and_stops(self):
        async def fake(body):
            yield {"http_status":200,"content_type":"text/event-stream"}
            yield b"data: {\"type\":\"response.output_text.delta\""
            await asyncio.sleep(1)
        summary=await self.run_mock([slot(),slot(1)],fake,timeout_seconds=.01)
        self.assertEqual(summary["stop_reasons"],["timeout"])
        self.assertEqual(summary["issued"],1)
        self.assertGreater(self.responses()[0]["stream_evidence"]["received_bytes"],0)

    async def test_cross_model_stop_drains_other_completed_stream(self):
        second=list(MODEL_PRICING)[1]
        started=set();both=asyncio.Event()
        async def fake(body):
            yield {"http_status":200,"content_type":"text/event-stream"}
            started.add(body["model"])
            if len(started)==2:both.set()
            await both.wait()
            if body["model"]==MODEL:
                yield frame({"type":"error"})
            else:
                while not self.ledger.halted:await asyncio.sleep(0)
                yield stream_bytes(second)
        summary=await self.run_mock([slot(),slot(1),slot(2,second),slot(3,second)],fake,concurrency=2)
        self.assertEqual(summary["issued"],2)
        self.assertEqual(summary["completed"],1)
        self.assertEqual(summary["budget"]["unsettled_attempts"],1)

    async def test_raw_stream_limit_preserves_received_chunk(self):
        raw=b": received before size check\n\n"
        with patch.object(StreamJournal,"MAX_BYTES",4):
            summary=await self.run_mock([slot()],lambda body:emit(raw,chunk=len(raw)))
        self.assertEqual(summary["stop_reasons"],["stream_size_limit"])
        self.assertEqual(Path(self.responses()[0]["stream_evidence"]["raw_stream_path"]).read_bytes(),raw)

    async def test_new_settlement_does_not_release_inherited_unknowns(self):
        await self.run_mock([slot()],lambda body:emit(stream_bytes()))
        self.assertGreaterEqual(self.ledger.accounted,nano(BASELINE))
        self.assertEqual(self.ledger.prior_evidence["cumulative_inherited_unsettled_attempts"],7)
        self.ledger.close()
        self.ledger=RollingLedger(self.path/"budget",baseline_path=ROOT/BASELINE_LEDGER)
        self.addCleanup(self.ledger.close)
        self.assertEqual(self.ledger.prior_evidence["carry_credits"],BASELINE)

    async def test_truncation_settles_keeps_partial_and_continues_unrelated_slots(self):
        calls=[]
        def fake(body):
            calls.append(body)
            return emit(truncated() if len(calls)==1 else stream_bytes())
        summary=await self.run_mock([slot(),slot(1)],fake)
        first,second=self.responses()
        self.assertEqual(summary["status"],"completed")
        self.assertEqual((summary["valid_terminal_records"],summary["completed"],summary["truncated"]),(2,1,1))
        self.assertEqual(summary["budget"]["unsettled_attempts"],0)
        self.assertEqual(first["model_outcome"],"truncated_max_output_tokens")
        self.assertEqual(first["response_status"],"incomplete")
        self.assertEqual(first["output_text"],"")
        self.assertEqual(first["partial_output_text"],"partial")
        self.assertIsNone(first["error"])
        self.assertTrue(first["terminal_valid"])
        self.assertEqual(second["model_outcome"],"completed")
        self.assertEqual(self.ledger.accounted,nano(BASELINE)+2*usage_cost(MODEL,{"input_tokens":100,"output_tokens":20},1024))

    async def test_dependency_skip_is_durable_unissued_unreserved_and_propagates(self):
        calls=[]
        def fake(body):
            calls.append(body)
            return emit(truncated() if len(calls)==1 else stream_bytes())
        slots=[slot(),slot(1,history_from=["new-0"]),slot(2,history_from=["new-0","new-1"]),slot(3)]
        summary=await self.run_mock(slots,fake)
        rows=self.responses()
        self.assertEqual((summary["planned"],summary["issued"],summary["responses"],summary["dependency_skips"]),(4,2,4,2))
        self.assertEqual(summary["unissued_due_global_halt_slot_ids"],[])
        self.assertEqual(summary["dependency_skipped_slot_ids"],["new-1","new-2"])
        self.assertEqual(len(self.ledger.attempts),2)
        for row in rows[1:3]:
            self.assertEqual(row["model_outcome"],"not_issued_dependency_truncated")
            self.assertFalse(row["issued"])
            for forbidden in ("attempt_id","reserved_credits","usage","settled_credits"):
                self.assertNotIn(forbidden,row)
        self.assertEqual(rows[-1]["slot_id"],"new-3")

    async def test_incomplete_missing_usage_still_halts_without_settlement(self):
        summary=await self.run_mock([slot(),slot(1)],lambda body:emit(truncated(usage=False)))
        self.assertEqual(summary["issued"],1)
        self.assertEqual(summary["valid_terminal_records"],0)
        self.assertEqual(summary["stop_reasons"],["missing_usage"])
        self.assertEqual(summary["budget"]["unsettled_attempts"],1)

    async def test_final_error_after_truncation_rejects_whole_response(self):
        raw=truncated()+frame({"type":"error"})
        summary=await self.run_mock([slot(),slot(1)],lambda body:emit(raw))
        self.assertEqual(summary["valid_terminal_records"],0)
        self.assertEqual(summary["issued_operational_failures"],1)
        self.assertEqual(summary["budget"]["unsettled_attempts"],1)

    async def test_empty_truncation_is_not_replayed_as_history(self):
        summary=await self.run_mock([slot(),slot(1,history_from=["new-0"])],lambda body:emit(truncated(text="")))
        self.assertEqual(summary["completed"],0)
        self.assertEqual(summary["truncated"],1)
        self.assertEqual(summary["dependency_skips"],1)

    async def test_missing_model_identity_is_not_attributed_or_settled(self):
        event=completed();event["response"].pop("model")
        summary=await self.run_mock([slot()],lambda body:emit(frame(event)))
        self.assertEqual(summary["stop_reasons"],["response_model_mismatch"])
        self.assertEqual(summary["valid_terminal_records"],0)
        self.assertEqual(summary["budget"]["unsettled_attempts"],1)

    async def test_initial_cooldown_then_global_and_model_spacing(self):
        starts=[]
        def fake(body):starts.append(self.clock());return emit(stream_bytes(body["model"]))
        summary=await self.run_mock([slot(),slot(1)],fake,global_interval=3.1,model_interval=4.0)
        self.assertGreaterEqual(starts[0],61)
        self.assertGreaterEqual(starts[1]-starts[0],4)
        self.assertEqual(summary["admission_starts"],2)

    async def test_full_actual_history_estimate_is_journal_only(self):
        from retrace.pacing_v6f import estimate_request
        bodies=[]
        def fake(body):bodies.append(body);return emit(stream_bytes(text="Actual assistant 🧭 output"))
        await self.run_mock([slot(input="earlier public text"),slot(1,history_from=["new-0"],
                            instructions="New complete instructions",input="Withdraw the cited source")],fake)
        rows=[json.loads(x) for x in (self.path/"run/requests.jsonl").read_text().splitlines()]
        second=rows[1]
        expected=[{"role":"user","content":"earlier public text"},
                  {"role":"assistant","content":"Actual assistant 🧭 output"},
                  {"role":"user","content":"Withdraw the cited source"}]
        self.assertEqual(bodies[1]["input"],expected)
        self.assertEqual(second["admission_estimate"],estimate_request("New complete instructions",expected,1024))
        self.assertFalse(second["admission_policy"]["quota_verified"])
        self.assertNotIn("admission_estimate",bodies[1]);self.assertNotIn("admission_policy",bodies[1])
        self.assertEqual(set(bodies[1]),{"model","instructions","input","max_output_tokens","temperature",
                                       "store","agentic_memory","tools","tool_choice","stream"})

    async def test_oversized_estimate_halts_without_reservation_or_request(self):
        calls=[]
        with patch("retrace.adaption_v6f.estimate_request",side_effect=ValueError("over125k")):
            summary=await self.run_mock([slot()],lambda body:calls.append(body))
        self.assertEqual(calls,[])
        self.assertEqual(summary["issued"],0)
        self.assertEqual(summary["stop_reasons"],["admission_estimation_failure"])
        self.assertEqual(len(self.ledger.attempts),0)
        self.assertEqual((self.path/"run/requests.jsonl").read_text(),"")

    async def test_actual_429_still_halts_and_retains_full_reservation(self):
        calls=[]
        def fake(body):calls.append(body);return emit(b'{"error":"retry after60seconds"}',429,"application/json")
        summary=await self.run_mock([slot(),slot(1)],fake)
        self.assertEqual(len(calls),1)
        self.assertEqual(summary["stop_reasons"],["http_429"])
        self.assertEqual(summary["budget"]["unsettled_attempts"],1)
        self.assertEqual(summary["retries"],0)

    async def test_quota_wait_releases_lock_and_capacity_for_smaller_model(self):
        # Controlled virtual time: one heavy request starts at61. The next
        # heavy request must wait until122, but another model's small request
        # can start at64.1 while the heavy waiter holds neither shared resource.
        second=list(MODEL_PRICING)[1]
        current=[0.0];pending=[];issued=[]
        def clock():return current[0]
        async def sleep(seconds):
            future=asyncio.get_running_loop().create_future()
            pending.append((current[0]+seconds,future))
            await future
        async def advance(value):
            current[0]=value
            for deadline,future in list(pending):
                if deadline<=value and not future.done():future.set_result(None)
            for _ in range(20):await asyncio.sleep(0)
        async def fake(body):
            issued.append((body["input"][-1]["content"],current[0]))
            async for part in emit(stream_bytes(body["model"])):yield part
        def estimate(instructions,messages,maximum):
            return {"weight":70000 if maximum==65536 else 10000,"quota_verified":False}
        slots=[slot(0,input="heavy-one",max_output_tokens=65536),
               slot(1,input="heavy-two",max_output_tokens=65536),
               slot(2,second,input="small")]
        with patch("retrace.adaption_v6f.estimate_request",side_effect=estimate):
            task=asyncio.create_task(run_slots(slots,api_key=KEY,output_dir=self.path/"run",ledger=self.ledger,
                transport=fake,concurrency=1,global_interval=3.1,model_interval=3.1,_clock=clock,_sleep=sleep))
            for _ in range(20):await asyncio.sleep(0)
            self.assertEqual(issued,[])
            await advance(61)
            self.assertEqual(issued,[("heavy-one",61)])
            await advance(64.1)
            self.assertEqual(issued,[("heavy-one",61),("small",64.1)])
            await advance(122)
            summary=await asyncio.wait_for(task,2)
        self.assertEqual(issued[-1],("heavy-two",122))
        self.assertEqual(summary["completed"],3)


if __name__=="__main__":unittest.main()
