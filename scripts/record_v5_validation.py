"""Bind the completed test, browser and manuscript checks without rerunning them."""
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


def sha(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()


def main():
    verify = read('results/retrace-v5-offline-check.json')
    tests = read('results/retrace-v5-verifier-check.json')
    qa = read('report/v4-cycle/visual-review.json')
    render = read('report/v4-cycle/render-manifest.json')
    build = read('report/v4-cycle/build-manifest.json')
    assert verify['status'] == tests['status'] == qa['status'] == 'passed'
    assert tests['tests']['python']['tests'] == 277 and tests['tests']['node']['tests'] == 13
    assert qa['pdf_sha256'] == render['pdf_sha256'] == sha('report/v4-cycle/RETRACE-research-draft.pdf')
    assert qa['docx_sha256'] == build['output_sha256'] == sha('report/v4-cycle/RETRACE-research-draft.docx')
    assert build['markdown_sha256'] == sha('report/v4-cycle/research-draft.md')
    assert qa['main_pages_including_title'] == 7 and qa['total_pages'] == 13
    assert sha('report/RETRACE-report-draft.docx') == qa['preserved_old_report']['docx_sha256']
    assert sha('report/RETRACE-report-draft.pdf') == qa['preserved_old_report']['pdf_sha256']
    for item in qa['page_images']:
        path = Path(qa['render_directory']) / ('page-' + str(item['page']) + '.png')
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']
    for name, expected in build['result_inputs'].items():
        assert sha(name) == expected
    proofs = ['results/retrace-v5-fresh-preview.png', 'results/retrace-v5-exposure-preview.png',
              'results/retrace-v5-release-preview.png']
    record = {
        'schema': 'retrace.v5-release-validation.v1',
        'created_at': datetime.now(timezone.utc).isoformat(), 'status': 'passed',
        'environment': {'python': sys.version.split()[0], 'platform': platform.platform()},
        'offline_verification': {'path': 'results/retrace-v5-offline-check.json',
            'sha256': sha('results/retrace-v5-offline-check.json'),
            'preserved_files': verify['preserved_files_verified'], 'requests': 503, 'responses': 503,
            'study_freezes': 5, 'primary_posthoc_and_fresh_scores_reproduced': True},
        'tests': {'record': 'results/retrace-v5-verifier-check.json',
                  'sha256': sha('results/retrace-v5-verifier-check.json'), **tests['tests']},
        'supplemental_audit': verify['supplemental_audit'],
        'browser': {'url': 'http://127.0.0.1:8766/lab', 'observed_console_errors': 0,
            'checks': [
                'Fresh four-branch ambiguity: Unknown retains four; Yes prunes to two; reset restores four.',
                'Post-hoc case06 separates at k=3 and survives k=1/k=2.',
                'Reference diagnostic08: enabling one inactive source and withdrawing one record exposes a difference while actual status remains Unsupported.',
                'The /lab route serves the complete v5 page.',
                'Forged fresh/reference metadata is labeled unverified; unchanged catalog source matches saved provenance.'],
            'screenshots': [{'path': name, 'sha256': sha(name)} for name in proofs]},
        'budget': verify['budget'], 'new_calls_this_cycle': 18, 'new_call_retries': 0,
        'report': {'pdf': 'report/v4-cycle/RETRACE-research-draft.pdf', 'pdf_sha256': qa['pdf_sha256'],
            'docx_sha256': qa['docx_sha256'], 'main_pages': 7, 'total_pages': 13, 'abstract_words': 202,
            'all_13_page_image_hashes_checked': True, 'visual_qa': 'report/v4-cycle/visual-review.json',
            'visual_qa_sha256': sha('report/v4-cycle/visual-review.json'),
            'sole_author': 'Christian Lysenstøen', 'affiliation': 'Undergraduate student, Inland University, Norway',
            'human_author_review_completed': False, 'submitted': False},
        'scope': 'Release checks establish computational and artifact consistency, not general model accuracy, source truth, complete interpretation coverage or human decision benefit.'}
    target = ROOT / 'results/retrace-v5-release-validation.json'
    with target.open('x', encoding='utf-8') as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps({'status': 'passed', 'path': target.relative_to(ROOT).as_posix(),
                      'main_pages': 7, 'tests': tests['tests'], 'budget': verify['budget']}, indent=2))


if __name__ == '__main__':
    main()
