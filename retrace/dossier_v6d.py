"""Deterministic neutral dossier dilution with a declared reference tokenizer."""
from __future__ import annotations

import hashlib
import json
from random import Random

TARGET_TOKENS = 16384
ENCODING = 'cl100k_base'


def dossier_body(documents):
    return '\n\n'.join('[' + doc['id'] + ']\n' + doc['text'] for doc in documents)


def neutral_material(seed, count=700):
    rng = Random(seed)
    rooms = ['north gallery','garden room','upper corridor','courtyard','west alcove','east lobby','attic room','stone landing']
    materials = ['linen','brass','cedar','wool','ceramic','copper','cotton','slate']
    colours = ['ochre','pale green','cobalt','cream','brick red','grey','amber','violet']
    objects = ['curtain','bench','vase','cabinet','woven mat','ornament','tile','picture frame']
    seasons = ['spring','summer','autumn','winter']
    paragraphs = []
    for i in range(count):
        room, material, colour, obj, season = (rng.choice(values) for values in (rooms, materials, colours, objects, seasons))
        variants = [
            f'The {room} contained a {colour} {obj} beside a small table. Its {material} surface looked different in the afternoon light. The visitor wrote about the quiet atmosphere during {season}. The paragraph describes the interior and its appearance.',
            f'An illustrated album showed the {room} in {season}. A {obj} appeared near the edge of the photograph, with {colour} fabric in the background. Notes about the {material} ornament occupied the opposite margin. The photographer preferred a wide view of the room.',
            f'A conversation about furnishings mentioned {material}, a {colour} finish, and the shape of a {obj}. Several sketches of the {room} appeared on the table. The discussion wandered toward changing daylight in {season} and the colours visible from the window.',
            f'The walking diary paused at the {room}. A {colour} {obj} and a {material} decoration caught the visitor\'s attention. Footsteps sounded different across the tiled and wooden floors. The final lines recalled a previous visit in {season}.',
            f'A descriptive caption placed the {obj} in the {room}, beside a {colour} panel. Its material was described as {material}. The caption discussed texture, colour and scale in the photograph, followed by a recollection of {season} weather.',
        ]
        paragraphs.append(variants[i % len(variants)])
    return '\n\n'.join(paragraphs)


def wrap_dossier(source_documents, *, seed, position_fraction=.5, target_tokens=TARGET_TOKENS):
    import tiktoken
    if not 0 < position_fraction < 1 or type(target_tokens) is not int or target_tokens < 100:
        raise ValueError('Invalid dossier design')
    if not source_documents or any(set(d) - {'id','text','title'} or not {'id','text'} <= set(d) for d in source_documents):
        raise ValueError('Source documents required')
    wrapper_ids = ['doc-' + hashlib.sha256((str(seed) + ':' + side).encode()).hexdigest()[:12] for side in ('before','after')]
    if any(d['id'] in wrapper_ids for d in source_documents):
        raise ValueError('Wrapper document ID collision')
    enc = tiktoken.get_encoding(ENCODING)
    base = [{'id':d['id'],'text':d['text']} for d in source_documents]
    base_tokens = len(enc.encode(dossier_body(base)))
    if base_tokens >= target_tokens - 100:
        raise ValueError('Source too long for frozen dilution design')
    before_material = enc.encode(neutral_material(seed))
    after_material = enc.encode(neutral_material(seed + 1))
    before_size = int((target_tokens - base_tokens - 30) * position_fraction)
    before = enc.decode(before_material[:before_size])
    def documents(after):
        return [{'id':wrapper_ids[0],'text':before}] + base + [{'id':wrapper_ids[1],'text':after}]
    low, high = 0, len(after_material)
    while low < high:
        mid = (low + high + 1) // 2
        count = len(enc.encode(dossier_body(documents(enc.decode(after_material[:mid])))))
        if count <= target_tokens: low = mid
        else: high = mid - 1
    after = enc.decode(after_material[:low])
    current = len(enc.encode(dossier_body(documents(after))))
    for _ in range(16):
        if current == target_tokens: break
        after += ' note'
        new_count = len(enc.encode(dossier_body(documents(after))))
        if new_count != current + 1:
            raise ValueError('Reference tokenizer padding changed unexpectedly')
        current = new_count
    if current != target_tokens: raise ValueError('Cannot meet exact reference token target')
    wrapped = documents(after)
    body = dossier_body(wrapped)
    # Original source strings and code-point citation offsets are unmodified.
    assert wrapped[1:-1] == base
    return {'source_documents':wrapped, 'measurement':{
        'encoding':ENCODING,'tiktoken_version':tiktoken.__version__,
        'reference_tokens':current,'measurement_text':'[document_id]\\ntext joined by two newlines',
        'provider_token_count_equal_to_reference':False,
        'source_reference_tokens':base_tokens,'position_fraction_design':position_fraction,
        'seed':seed,'wrapper_document_ids':wrapper_ids,'dossier_utf8_sha256':hashlib.sha256(body.encode('utf-8')).hexdigest(),
        'source_documents_sha256':hashlib.sha256(json.dumps(base,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest(),
        'scope':'Synthetic neutral descriptive filler; fixed source text and eligibility semantics. Reference tokenizer only; actual provider usage recorded separately.'}}
