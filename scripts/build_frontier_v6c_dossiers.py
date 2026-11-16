"""Build the24 fixed long dossiers after source audit; no inference calls."""
from pathlib import Path
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from retrace.dossier_v6c import wrap_dossier


def build(corpus):
    selected=set(corpus['long_context_subset_ids'])
    records=[]
    for case in corpus['cases']:
        if case['id'] not in selected:continue
        position={1:.2,4:.4,5:.6,8:.8}[case['within_family_index']]
        seed=int(hashlib.sha256(case['id'].encode()).hexdigest()[:8],16)
        result=wrap_dossier(case['public']['source_documents'],seed=seed,position_fraction=position)
        all_ids=[x for values in case['public']['registry'].values() for x in values]
        for doc in (result['source_documents'][0],result['source_documents'][-1]):
            if any(identifier in doc['text'] for identifier in all_ids):raise ValueError('Filler registry collision')
        records.append({'case_id':case['id'],**result})
    if len(records)!=24:raise ValueError('Expected24 long dossiers')
    return {'schema':'retrace.frontier-v6c-dossiers.v1','cases':records,
            'reference_encoding':'cl100k_base','dossier_body_tokens_each':16384,
            'provider_input_tokens':'Measured separately; reference count excludes prompt/citation-index overhead.'}


if __name__=='__main__':
    source=ROOT/'data/frontier-v6c-staged.json'
    result=build(json.loads(source.read_text(encoding='utf-8')))
    result['source_corpus_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    with (ROOT/'data/frontier-v6c-dossiers.json').open('x',encoding='utf-8',newline='\n') as f:
        json.dump(result,f,indent=2,ensure_ascii=False);f.write('\n')
    print('Created24 exact reference-token dossiers; original source strings preserved.')
