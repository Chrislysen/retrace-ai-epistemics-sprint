import importlib.util
import unittest
from retrace.dossier_v6d import wrap_dossier,dossier_body


@unittest.skipUnless(importlib.util.find_spec('tiktoken'), 'Reference tokenizer available in .venv-v6c')
class DossierTests(unittest.TestCase):
    def test_exact_count_original_quotes_and_reproducible_position(self):
        import tiktoken
        docs=[{'id':'source-one','text':'Evidence ZZABC is copied from original ZZDEF.'},
              {'id':'source-two','text':'Decision ZZJKL requires review ZZMNO.'}]
        packet=wrap_dossier(docs,seed=17,position_fraction=.25)
        self.assertEqual(len(tiktoken.get_encoding('cl100k_base').encode(dossier_body(packet['source_documents']))),16384)
        self.assertEqual(packet['source_documents'][1:-1],docs)
        self.assertTrue(all(d['id'].startswith('doc-') and len(d['id'])==16 for d in (packet['source_documents'][0],packet['source_documents'][-1])))
        self.assertEqual(packet,wrap_dossier(docs,seed=17,position_fraction=.25))
        self.assertNotEqual(packet['measurement']['dossier_utf8_sha256'],wrap_dossier(docs,seed=18,position_fraction=.75)['measurement']['dossier_utf8_sha256'])
        for doc in (packet['source_documents'][0],packet['source_documents'][-1]):
            self.assertNotIn('ZZABC',doc['text'])


if __name__=='__main__': unittest.main()
