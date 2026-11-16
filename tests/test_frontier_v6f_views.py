from pathlib import Path
import tempfile,json,unittest
from scripts.split_frontier_v6f import split


class JournalViewTests(unittest.TestCase):
    def setup_files(self,folder):
        root=Path(folder)
        for name,rows in [('primary_sessions',[{'slot_id':'P'}]),('regression_sessions',[{'slot_id':'R'}])]:
            (root/name).write_text(json.dumps(rows),encoding='utf-8')
        # Different spacing/newline conventions must survive exact projection.
        (root/'requests').write_bytes(b'{"slot_id": "R"}\r\n{"slot_id":"P"}\n')
        (root/'responses').write_bytes(b'{"slot_id":"P","issued":false,"error":"history_dependency_truncated"}\n{"slot_id":"R","response_status":"incomplete"}\n')
        return {name:root/name for name in ('primary_sessions','regression_sessions','requests','responses')}|{'output':root/'views'}

    def test_exact_lines_all_outcomes_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            args=self.setup_files(folder);before={k:p.read_bytes() for k,p in args.items() if k!='output'}
            result=split(**args)
            self.assertEqual(len(result['line_mapping']),4)
            self.assertEqual((args['output']/'regression-requests.jsonl').read_bytes(),b'{"slot_id": "R"}\r\n')
            self.assertIn(b'issued":false',(args['output']/'primary-responses.jsonl').read_bytes())
            for key,value in before.items():self.assertEqual(args[key].read_bytes(),value)
            with self.assertRaises(FileExistsError):split(**args)

    def test_unknown_duplicate_or_partial_journal_rejected_before_outputs(self):
        for content in (b'{"slot_id":"UNKNOWN"}\n',b'{"slot_id":"P"}\n{"slot_id":"P"}\n',b'{"slot_id":"P"}',b'{"slot_id":"P","slot_id":"R"}\n'):
            with tempfile.TemporaryDirectory() as folder:
                args=self.setup_files(folder);args['responses'].write_bytes(content)
                with self.assertRaises(ValueError):split(**args)
                self.assertFalse(args['output'].exists())


if __name__=='__main__':unittest.main()
