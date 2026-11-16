"""Render one constructed mechanism figure from the preserved scalar certificate.

Uses bundled reportlab. No empirical logs, provider calls, or old-file writes.
"""
from hashlib import sha256
import json
from pathlib import Path
from reportlab.graphics.shapes import Drawing, Rect, String, Line
from reportlab.graphics import renderPDF, renderSVG
from reportlab.lib.colors import HexColor

ROOT = Path(__file__).resolve().parents[1]
CERT = 'results/frontier-v6j-offline/separation-certificate.json'
CERT_SHA = '1b6a062ed1594bd1172176d429a62a41483034bf30e086a5ee9f70e8e7dbbb7d'
PDF = 'output/pdf/retrace-masked-witness-v6.pdf'
SVG = 'report/v6l-assets/masked-witness.svg'
RECEIPT = 'report/v6l-assets/masked-witness-source.json'


def draw():
    raw = (ROOT/CERT).read_bytes()
    assert sha256(raw).hexdigest() == CERT_SHA
    proof = json.loads(raw)
    assert proof['passed'] is True and proof['model_experiment'] is False
    masked = proof['masked_prerequisite']
    assert masked['all_pure_withdrawal_subsets_agree'] is True
    assert masked['clarification_cost_before'] == 0
    assert masked['clarification_cost_at_typed_witness'] == 1
    states = [(False, [], 'No action (P is vetoed)'),
              (False, ['Q'], 'Withdraw Q only'),
              (True, [], "Release P's document veto only"),
              (True, ['Q'], 'Release that veto AND withdraw Q')]
    rows = []
    for release, withdrawn, action in states:
        matches = [r for r in masked['truth_table']
                   if r['release_document_P'] is release and r['withdraw'] == withdrawn]
        assert len(matches) == 1
        row = matches[0]
        assert row['different'] is (row['G_supported'] != row['H_supported'])
        rows.append({**row, 'action': action,
                     'unit_cost_question_needed': int(row['different'])})

    for name in (PDF, SVG, RECEIPT):
        assert not (ROOT/name).exists(), 'Exclusive figure output required'
        (ROOT/name).parent.mkdir(parents=True, exist_ok=True)
    d = Drawing(468, 252)
    dark, muted = HexColor('#17222C'), HexColor('#44515B')
    border, shade = HexColor('#ABB4BA'), HexColor('#EDF2F5')

    def text(x, y, value, size=8.6, bold=False, anchor='start', color=dark):
        d.add(String(x, y, value, fontName='Helvetica-Bold' if bold else 'Helvetica',
                     fontSize=size, fillColor=color, textAnchor=anchor))

    d.add(Rect(0, 0, 468, 252, fillColor=HexColor('#FFFFFF'), strokeColor=None))
    text(12, 235, 'Agreement can hide a prerequisite', 13, True)
    text(12, 218, "P and Q are originally eligible; only P's document veto is active.", 8.7)
    left, right, top, header, height = 12, 456, 203, 29, 30
    boundaries = [12, 212, 294, 376, 456]
    centers = [(boundaries[i]+boundaries[i+1])/2 for i in range(4)]
    d.add(Rect(left, top-header, right-left, header, fillColor=shade, strokeColor=None))
    text(20, 185, 'Hypothetical action', 9, True)
    text(centers[1], 185, 'G: P suffices', 8.8, True, 'middle')
    text(centers[2], 185, 'H: P AND Q', 8.8, True, 'middle')
    text(centers[3], 185, 'Question cost', 8.8, True, 'middle')
    for i, row in enumerate(rows):
        y = top-header-(i+1)*height
        if row['different']:
            d.add(Rect(left, y, right-left, height, fillColor=shade, strokeColor=None))
        text(20, y+11, row['action'], 8.5, row['different'])
        for j, key in ((1, 'G_supported'), (2, 'H_supported')):
            text(centers[j], y+11, 'Supported' if row[key] else 'Unsupported',
                 8.6, row['different'], 'middle')
        text(centers[3], y+11, '1 / ask' if row['different'] else '0 / stop',
             8.8, row['different'], 'middle')
        d.add(Line(left, y, right, y, strokeColor=border, strokeWidth=0.5))
    text(12, 38, 'Question: "Must Q also be available?" One unit; decisive, accurate answer assumed.', 8.2)
    text(12, 24, 'Supported means under declared links. Unsupported does not assert falsity.', 8.2, color=muted)
    text(12, 10, 'Constructed mechanism example, not a model result. Other vetoes remain intact.', 8.2, color=muted)
    renderPDF.drawToFile(d, str(ROOT/PDF))
    with (ROOT/SVG).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(renderSVG.drawToString(d))
    receipt = {'schema': 'retrace.constructed-mechanism-figure.v1', 'empirical': False,
               'api_calls': 0, 'source': {'path': CERT, 'sha256': CERT_SHA}, 'rows': rows,
               'cost_scope': 'One declared binary question distinguishes the two readings; cost0 iff their support agrees, otherwise1. Accurate decisive answers assumed.',
               'outputs': {name: {'sha256': sha256((ROOT/name).read_bytes()).hexdigest(),
                                  'bytes': (ROOT/name).stat().st_size} for name in (PDF, SVG)}}
    with (ROOT/RECEIPT).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(receipt, stream, indent=2); stream.write('\n')
    print(json.dumps({'created': [PDF, SVG, RECEIPT], 'empirical': False, 'api_calls': 0}))


if __name__ == '__main__': draw()
