import asyncio
import unittest
from scripts.probe_adaption_quota_v6h import PacedHeaderTransport, round_passed, slots, SAFE_HEADERS
from retrace.adaption_v6h import validate_slots

class QuotaProbeTests(unittest.TestCase):
    def test_unique_prespecified_rounds(self):
        rows=[s for i in range(3) for s in slots(i)]
        validate_slots(rows)
        self.assertEqual(len({s['slot_id'] for s in rows}),15)
        self.assertEqual({s['input'] for s in rows},{'Reply exactly OK.'})
        self.assertNotIn('authorization',SAFE_HEADERS)
        self.assertNotIn('set-cookie',SAFE_HEADERS)

    def test_failures_prevent_escalation(self):
        s=dict(status='completed',planned=5,issued_attempts=5,first_attempt_completed=5,
               http_429_attempts=0,issued_operational_failures=0,truncated=0,unissued_slot_ids=[])
        self.assertTrue(round_passed(s))
        for k,v in [('http_429_attempts',1),('first_attempt_completed',4),('issued_attempts',6),
                    ('issued_operational_failures',1),('truncated',1),('status','stopped')]:
            self.assertFalse(round_passed({**s,k:v}),k)

    def test_http_admission_spacing_and_header_filter(self):
        class Clock:
            value=0
            def now(self):return self.value
            async def sleep(self,d):self.value+=d
        class Journal:
            rows=[]
            def write(self,r):self.rows.append(r)
        class Content:
            async def iter_chunked(self,n):yield b'data'
        class Response:
            status=200;headers={'content-type':'text/event-stream','x-ratelimit-limit':'3','set-cookie':'SECRET'};content=Content()
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
        class Session:
            def post(self,*args,**kw):return Response()
        async def run():
            c=Clock();j=Journal();t=PacedHeaderTransport('synthetic-key',21,j,c.now,c.sleep);t.session=Session()
            for _ in range(2):
                async for chunk in t({'model':'gemma-4-31b-it'}):pass
            return j.rows
        rows=asyncio.run(run())
        self.assertEqual(rows[2]['gap_seconds'],21)
        self.assertEqual(rows[1]['headers']['x-ratelimit-limit'],'3')
        self.assertNotIn('set-cookie',rows[1]['headers'])

if __name__=='__main__':unittest.main()
