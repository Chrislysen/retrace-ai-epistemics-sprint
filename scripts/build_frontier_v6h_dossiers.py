"""New24 source-preserving16K-reference-token wrappers; old dossiers untouched."""
from pathlib import Path
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.build_frontier_v6d_dossiers import build as wrap
from hashlib import sha256


def build(corpus):
    result=wrap(corpus)
    result['schema']='retrace.frontier-v6h-dossiers.v1'
    return result


if __name__=='__main__':
    source=ROOT/'data/frontier-v6h-corpus.json';result=build(json.loads(source.read_text(encoding='utf-8')))
    result['source_corpus_sha256']=sha256(source.read_bytes()).hexdigest()
    path=ROOT/'data/frontier-v6h-dossiers.json'
    with path.open('x',encoding='utf-8',newline='\n') as stream:json.dump(result,stream,ensure_ascii=False,indent=2);stream.write('\n')
    print(json.dumps({'dossiers':len(result['cases']),'sha256':sha256(path.read_bytes()).hexdigest()}))
