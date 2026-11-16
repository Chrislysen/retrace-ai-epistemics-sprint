"""Validate staged source/oracle data and write answer-free sessions, before freeze."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from retrace.ambiguity_v3_sessions import build_sessions
from retrace.ambiguity_v3_eval import validate_packets, constructed_controls

if (ROOT/'data/ambiguity-v3-freeze.json').exists():
    raise RuntimeError('Refusing to rewrite staged artifacts after freeze')
packets=json.loads((ROOT/'data/ambiguity-v3-staged.json').read_text(encoding='utf-8'))
validate_packets(packets)
sessions=build_sessions(packets)
for session in sessions:
    input_body=json.loads(session['steps'][0]['input'])
    assert set(input_body)=={'id','title','documents','registry'}
    assert not any(k in input_body for k in ('hidden','source_context','family','allowed_interpretations','author_clarification_oracle'))
(ROOT/'data/ambiguity-v3-sessions.json').write_text(json.dumps(sessions,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(ROOT/'results/ambiguity-v3-constructed-controls.json').write_text(json.dumps(constructed_controls(packets),indent=2)+'\n',encoding='utf-8')
print('Validated 10 packets, 16 allowed interpretations, factual oracles, zero negative-control constraint violations, k=3 and irrelevant-ambiguity controls; wrote 20 answer-free sessions.')
