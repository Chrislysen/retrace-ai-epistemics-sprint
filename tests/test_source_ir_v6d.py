from copy import deepcopy
import json
import unittest
from retrace.source_ir_v6d import source_segments,expand_ir,compile_cited_ir


class CitationReferenceTests(unittest.TestCase):
    def fixture(self):
        docs=[{'id':'source','text':'A is locally eligible original evidence. Claim C accepts A alone. Decision D requires C.\n\nA appears here again.'}]
        sid=source_segments(docs)[0]['span_id']
        def prop(pid,kind,target,body): return {'id':pid,'kind':kind,'target':target,'body':body,'scope':'current','polarity':'assert','when':{},'citations':[sid],'bindings':[]}
        ir={'schema':'retrace.source-ir.v6d','entities':[{'id':i,'type':t,'operational':True,'citations':[sid]} for i,t in [('A','evidence'),('C','claim'),('D','decision')]],
            'bindings':[],'choices':[],'combination':{'mode':'cartesian','assignments':[],'citations':[]},
            'propositions':[prop('p1','eligibility','A',{'active':True}),prop('p2','origin','A',{'kind':'root','parents':[]}),
                            prop('p3','support','C',{'expr':{'ref':'A'}}),prop('p4','requirement','D',{'requires':['C']})]}
        return docs,ir

    def test_repeated_source_tokens_have_exact_located_citations(self):
        docs,ir=self.fixture();before=deepcopy(ir)
        result=compile_cited_ir(ir,docs)
        self.assertEqual(result['status'],'compiled')
        self.assertEqual(ir,before)
        citation=result['entities'][0]['citations'][0]
        self.assertEqual(docs[0]['text'][citation['start']:citation['end']],citation['quote'])

    def test_source_change_invalidates_reference(self):
        docs,ir=self.fixture();docs[0]['text']='New first text. '+docs[0]['text']
        with self.assertRaises(ValueError): expand_ir(ir,docs)

    def test_no_quote_or_unknown_reference_fallback(self):
        docs,ir=self.fixture()
        for wrong in ['invented',{'document_id':'source','quote':'A'}]:
            changed=deepcopy(ir);changed['entities'][0]['citations']=[wrong]
            with self.assertRaises(ValueError): expand_ir(changed,docs)

    def test_segmentation_is_lossless_and_offsets_are_unicode_codepoints(self):
        docs=[{'id':'one','text':'😀 A\n\n'+('c'*9000)},{'id':'two','text':'Second source.'}]
        segments=source_segments(docs)
        for doc in docs:
            group=[s for s in segments if s['document_id']==doc['id']]
            self.assertEqual(''.join(s['text'] for s in group),doc['text'])
            for s in group:self.assertEqual(s['text'],doc['text'][s['start']:s['end']])

    def test_expansion_does_not_repair_invalid_semantics(self):
        docs,ir=self.fixture();ir['propositions'][2]['body']={'expr':{'all':[{'ref':'C'},{'ref':'A'}]}}
        with self.assertRaises(ValueError):compile_cited_ir(ir,docs)

    def test_artificial_chunk_boundary_does_not_split_a_valid_identifier(self):
        text=(' ' * 4093)+'ABCD1234 is an evidence record. More text follows.'
        segments=source_segments([{'id':'source','text':text}])
        self.assertEqual(''.join(s['text'] for s in segments),text)
        self.assertTrue(any('ABCD1234' in s['text'] for s in segments))


if __name__=='__main__':unittest.main()
