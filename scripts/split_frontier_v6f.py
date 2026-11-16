"""Lossless study views of a combined journal; original lines remain byte-identical."""
from pathlib import Path
import argparse,hashlib,json


def unique(items):
    out={}
    for key,value in items:
        if key in out:raise ValueError('Duplicate JSON key')
        out[key]=value
    return out


def load(raw):
    def invalid(value):raise ValueError('Nonfinite JSON')
    return json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def split(primary_sessions,regression_sessions,requests,responses,output):
    paths={'primary_sessions':Path(primary_sessions),'regression_sessions':Path(regression_sessions),
           'requests':Path(requests),'responses':Path(responses)}
    raw={name:path.read_bytes() for name,path in paths.items()}
    slots={};counts={}
    for study in ('primary','regression'):
        rows=load(raw[study+'_sessions']);counts[study]=len(rows)
        for row in rows:
            if row['slot_id'] in slots:raise ValueError('Duplicate or cross-study slot')
            slots[row['slot_id']]=study
    grouped={study:{kind:[] for kind in ('requests','responses')} for study in counts};mapping=[]
    for kind in ('requests','responses'):
        if raw[kind] and not raw[kind].endswith(b'\n'):raise ValueError('Truncated journal')
        seen=set()
        for line_number,line in enumerate(raw[kind].splitlines(keepends=True),1):
            if not line.strip():raise ValueError('Empty journal line')
            row=load(line);slot=row['slot_id']
            if slot not in slots or slot in seen:raise ValueError('Unknown or duplicate outcome slot')
            seen.add(slot);study=slots[slot];grouped[study][kind].append(line)
            mapping.append({'journal':kind,'source_line':line_number,'study':study,
                            'view_line':len(grouped[study][kind]),'slot_id':slot,'line_sha256':sha(line)})
    output=Path(output)
    if output.exists():raise FileExistsError('Study view output already exists')
    output.mkdir(parents=True,exist_ok=False)
    files=[]
    for study in grouped:
        for kind,lines in grouped[study].items():
            name=study+'-'+kind+'.jsonl';content=b''.join(lines)
            with (output/name).open('xb') as f:f.write(content)
            files.append({'path':name,'sha256':sha(content),'records':len(lines),'study':study,'journal':kind})
    manifest={'schema':'retrace.frontier-v6f-lossless-study-views.v1',
              'sources':{name:{'path':str(paths[name].resolve()),'sha256':sha(data)} for name,data in raw.items()},
              'planned':counts,'files':files,'line_mapping':mapping,
              'scope':'Every original journal line belongs to exactly one study view. Lines are copied byte-for-byte; raw journals are neither modified nor filtered in place. Missing scheduled slots remain missing and are scored against the complete schedule.'}
    with (output/'manifest.json').open('x',encoding='utf-8',newline='\n') as f:json.dump(manifest,f,indent=2);f.write('\n')
    return manifest


if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--primary-sessions',type=Path,default=root/'data/frontier-v6f-sessions.json')
    parser.add_argument('--regression-sessions',type=Path,default=root/'data/frontier-v6f-regression-sessions.json')
    parser.add_argument('--requests',type=Path,default=root/'results/frontier-v6f/combined/requests.jsonl')
    parser.add_argument('--responses',type=Path,default=root/'results/frontier-v6f/combined/responses.jsonl')
    parser.add_argument('--output',type=Path,default=root/'results/frontier-v6f/study-views')
    args=parser.parse_args();result=split(**vars(args))
    print(json.dumps({'planned':result['planned'],'files':result['files']},indent=2))
