"""Strict SSE and retained-carry tests; synthetic transport only, zero API calls."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts.run_frontier_v6d import integrity

from retrace.adaption_v6d import (BASELINE,BASELINE_LEDGER,BASELINE_SHA256,MODEL_PRICING,
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
        for kind in ("error","response.failed","response.incomplete","response.cancelled"):
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,"terminal_error"):
                self.decode(frame({"type":kind,"message":"failed"}))
        event=completed();event["response"]["status"]="incomplete"
        with self.assertRaisesRegex(ValueError,"invalid_completed"):self.decode(frame(event))

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

    def test_prior_ledger_replay_keeps_four_unknown_bounds(self):
        before=(ROOT/BASELINE_LEDGER).read_bytes()
        evidence=verify_prior_ledger(ROOT/BASELINE_LEDGER)
        self.assertEqual(evidence["carry_credits"],"42.77759328")
        self.assertEqual(evidence["unknown_full_bounds_retained"],4)
        self.assertEqual(evidence["unknown_bound_credits"],"1.785756296")
        self.assertEqual(hashlib.sha256(before).hexdigest(),BASELINE_SHA256)
        self.assertEqual((ROOT/BASELINE_LEDGER).read_bytes(),before)

    def test_cli_authorization_cannot_reset_or_change_prior_ledger(self):
        authorization=json.loads((ROOT/"data/frontier-v6d-authorization.json").read_text(encoding="utf-8"))
        models=json.loads((ROOT/"data/frontier-v6c-model-availability.json").read_text(encoding="utf-8"))
        self.assertEqual(integrity(authorization,models),487)
        for key,value in (("historical_conservative_carry_credits","40.98826224"),
                          ("prior_ledger_sha256","0"*64),
                          ("prior_ledger_path","results/other/ledger.jsonl")):
            changed=deepcopy(authorization);changed[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):integrity(changed,models)

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

    async def run_mock(self,slots,transport,**settings):
        return await run_slots(slots,api_key=KEY,output_dir=self.path/"run",ledger=self.ledger,transport=transport,
                               global_interval=0,model_interval=0,**settings)

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
        self.assertEqual(summary["stop_reasons"],["stream_missing_completed_event"])
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
        async def fake(body):
            yield {"http_status":200,"content_type":"text/event-stream"}
            if body["model"]==MODEL:
                await asyncio.sleep(.01);yield frame({"type":"error"})
            else:
                await asyncio.sleep(.03);yield stream_bytes(second)
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
        self.assertGreaterEqual(self.ledger.accounted,nano("42.77759328"))
        self.assertEqual(self.ledger.prior_evidence["unknown_full_bounds_retained"],4)
        self.ledger.close()
        self.ledger=RollingLedger(self.path/"budget",baseline_path=ROOT/BASELINE_LEDGER)
        self.addCleanup(self.ledger.close)
        self.assertEqual(self.ledger.prior_evidence["carry_credits"],BASELINE)


if __name__=="__main__":unittest.main()
