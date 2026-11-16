"""Author-declared, unreviewed ambiguity cases. Never modifies earlier corpora."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def graph(ids, active, copies, claims, decisions):
    return {'evidence':[{'id':ids[k],'kind':'copy' if k in copies else 'root','active':k in active,
                         'parents':[ids[x]for x in copies.get(k,[])]}for k in ids if k.startswith('e')],
            'claims':[{'id':ids[k],'supports':[[ids[x]for x in route]for route in routes]}for k,routes in claims.items()],
            'decisions':[{'id':ids[k],'requires':[ids[x]for x in required]}for k,required in decisions.items()]}


def packet(number,title,family,roles,text,alternatives,actual,question,question_test,groups=None,constraints=None,challenge=None,mutant=None):
    ids={role:f'R{number:02}{j:03}'for j,role in enumerate(roles,1)}
    def render(s):
        for role,node_id in sorted(ids.items(),key=lambda x:-len(x[0])):
            s=s.replace('{'+role+'}',node_id)
        return s
    graphs=[graph(ids,*a)for a in alternatives]
    doc_groups=[{'id':g['id'],'label':g['label'],'evidence_ids':[ids[r]for r in g['members']]}for g in groups or []]
    external=[]
    for index,c in enumerate(constraints or [],1):
        quote=render(c['quote'])
        assert quote in render(text)
        external.append({'id':f'constraint-{index}','child':ids[c['child']],'ancestor':ids[c['ancestor']],'source_quote':quote})
    public={'id':f'ambiguity-v3-{number:02}','title':title,
            'documents':[{'id':f'packet-{number:02}','title':'Source packet','text':render(text)}],
            'registry':{k:[n['id']for n in graphs[0][k]]for k in ('evidence','claims','decisions')}}
    factual={
        1:('Does the desk check remain mandatory even when the map check is used?',{'kind':'all_routes_contain','claim':ids.get('cMain'),'item':ids.get('eC')},False),
        2:('Was the later card produced by transcription from the original worksheet rather than an independent recount?',{'kind':'direct_parent','child':ids.get('eB'),'parent':ids.get('eA')},True),
        3:('Was the morning list the source of the line in the gallery digest?',{'kind':'direct_parent','child':ids.get('eP'),'parent':ids.get('eA')},False),
        4:('Was the index review alone approved as a sufficient prerequisite for the release review?',{'kind':'exact_route','claim':ids.get('cFinal'),'items':[ids.get('cLeft')]},True),
        5:('Was the second tag list alone approved as a sufficient warrant for the tag review?',{'kind':'exact_route','claim':ids.get('cTag'),'items':[ids.get('eB')]},False),
        6:('Was the fourth signoff approved as an independent sufficient route rather than filed only as background?',{'kind':'exact_route','claim':ids.get('cMain'),'items':[ids.get('eD')]},True),
        7:('Does the first circulated summary ultimately derive from the master observation?',{'kind':'ancestor','child':ids.get('eP'),'ancestor':ids.get('eA')},True),
        8:('Does the first certificate require the shared authorization entry as part of its provenance?',{'kind':'ancestor','child':ids.get('eP'),'ancestor':ids.get('eA')},True),
        9:('Does the second excerpt ultimately derive from the original in the first source packet?',{'kind':'ancestor','child':ids.get('eQ'),'ancestor':ids.get('eA')},True),
        10:('Does the second note passage derive from the separate second original?',{'kind':'ancestor','child':ids.get('eZ'),'ancestor':ids.get('eB')},True),
    }[number]
    hidden={'family':family,'allowed_interpretations':graphs,'author_actual_interpretation_index':actual,
            'author_clarification_oracle':{'question_id':'clarify-1','question':render(question),'cost':1,
                'factual_predicate':factual[1],
                'actual_answer':factual[2],
                'answer_semantics':'Answer is a source-factual structural property, not whether a target decision is supported. Candidate answers are computed from that candidate alone.'},
            'challenge_withdrawals':[ids[r]for r in challenge or []],
            'constructed_common_omission_graph':graph(ids,*mutant)if mutant else None}
    hidden['author_clarification_oracle']['question']=factual[0]
    return {'public':public,'source_context':{'documents':doc_groups,'provenance_constraints':external},'hidden':hidden}


def build():
    cases=[]
    # Natural coordination ambiguity: (map OR card) AND desk vs map OR (card AND desk).
    cases.append(packet(1,'Volunteer route-release note','coordination',['eA','eB','eC','cMain','dMain'],
        'A volunteer coordinator is releasing a route handout. Record {eA} is an original map check, {eB} an original route-card check, and {eC} an original desk check. The map and route-card records are currently locally eligible; the desk check has been withdrawn and is locally ineligible. There are no copied records. The only substantive release rule is the signed sentence: "The route review {cMain} clears with a current map check or a route-card check and a desk check." There are no commas or parenthetical groupings, and the coordinator left no worked example. Decision {dMain} requires that route review alone. The source does not resolve whether the desk check qualifies both choices or only the route-card choice. Do not infer another policy from ordinary event practice. Every stated original is a distinct observation; only the grouping of this sentence is unresolved.',
        [({'eA','eB'},{},{'cMain':[['eA','eC'],['eB','eC']]},{'dMain':['cMain']}),
         ({'eA','eB'},{},{'cMain':[['eA'],['eB','eC']]},{'dMain':['cMain']})],1,
        'Does the signed policy allow decision {dMain} with the map check but without the desk check?',{'withdraw':[],'decision':'dMain'}))
    cases.append(packet(2,'Checked transcription in a listening archive','independent_or_copy',['eA','eB','cMain','dMain'],
        'An archive has two numbered records. Original listening count {eA} is currently locally ineligible after its worksheet was withdrawn. Record {eB}, a later card with its own local eligibility still true, repeats exactly that count and is marked "checked". The surviving notes do not say whether "checked" meant another independent listening count or checking the transcription against the original worksheet. No further records or parents are involved. Under the archive rules, an independent recount is an original; a transcription has the original worksheet as its sole parent. Claim {cMain}, the count review, is warranted by usable {eB} alone. Decision {dMain} requires {cMain} alone. The archive keeper can answer how the later card was produced, but that answer is not in this packet. Equal numbers alone neither establish independence nor establish copying.',
        [({'eB'},{},{'cMain':[['eB']]},{'dMain':['cMain']}),
         ({'eB'},{'eB':['eA']},{'cMain':[['eB']]},{'dMain':['cMain']})],1,
        'Would decision {dMain} remain warranted by the later card while the original worksheet stays withdrawn?',{'withdraw':[],'decision':'dMain'}))
    cases.append(packet(3,'Unattributed line in a gallery digest','which_parent',['eA','eB','eP','cMain','dMain'],
        'Two independent inventory originals exist: {eA}, the morning list, and {eB}, the afternoon list. The morning list is currently locally ineligible; the afternoon list is eligible. The eligible digest {eP} reproduces one count from one of those lists and adds no observation. Its margin says "inventory list", without the time or record number. The compiler says exactly one of the two originals supplied the line, but the surviving page does not identify which one. This is not a digest requiring both lists. Claim {cMain} is supported exactly by usable digest {eP}. Decision {dMain} requires {cMain}. All other relations and local eligibility flags are specified above. The compiler retained a separate answer to the source-line question, unavailable to the extractor.',
        [({'eB','eP'},{'eP':['eA']},{'cMain':[['eP']]},{'dMain':['cMain']}),
         ({'eB','eP'},{'eP':['eB']},{'cMain':[['eP']]},{'dMain':['cMain']})],1,
        'Does the digest still warrant decision {dMain} while the morning list is unavailable?',{'withdraw':[],'decision':'dMain'}))
    cases.append(packet(4,'Two reviews and an unnamed signoff','referent',['eA','eB','cLeft','cRight','cFinal','dMain'],
        'A tabletop exhibit has an index review {cLeft}, supported exactly by original record {eA}, and a lighting review {cRight}, supported exactly by original record {eB}. The index record is currently locally ineligible; the lighting record is eligible. Neither is copied. A joint meeting minute introduces both reviews and then states: "The release review {cFinal} is complete when that review clears." Its reference to "that review" has no distinguishing name, and the minute explicitly says the signoff needs one of the two review types selected by the coordinator, not both and not an interchangeable choice. The coordinator has not supplied that selection in this packet. Decision {dMain} requires {cFinal} alone. No extra release prerequisite is permitted. The ambiguity concerns which review the coordinator designated, not whether the evidence for either review is usable.',
        [({'eB'},{},{'cLeft':[['eA']],'cRight':[['eB']],'cFinal':[['cLeft']]},{'dMain':['cFinal']}),
         ({'eB'},{},{'cLeft':[['eA']],'cRight':[['eB']],'cFinal':[['cRight']]},{'dMain':['cFinal']})],0,
        'Does decision {dMain} clear on the eligible lighting record alone in the coordinator\'s actual policy?',{'withdraw':[],'decision':'dMain'}))
    cases.append(packet(5,'Ambiguous archive tag outside the release decision','irrelevant_ambiguity',['eA','eB','eC','cTag','cMain','dMain'],
        'A club ledger tracks an archival tag review {cTag} and a release review {cMain}. Original tag list {eA} is ineligible; original tag list {eB} is eligible. The tag review uses exactly one list selected by its editor, but the text says only "the tag list" and does not identify the first or second list. A separate original schedule check {eC} is eligible. The release review {cMain} is supported exactly by {eC}, and the only requested decision {dMain} requires {cMain} alone. The tag review is retained for archive housekeeping and is explicitly not a prerequisite of the requested decision or of the schedule check. No sources are copies. Which tag list was selected is unresolved, but its selection cannot affect this requested decision under the complete ledger rules.',
        [({'eB','eC'},{},{'cTag':[['eA']],'cMain':[['eC']]},{'dMain':['cMain']}),
         ({'eB','eC'},{},{'cTag':[['eB']],'cMain':[['eC']]},{'dMain':['cMain']})],0,
        'Does the tag review {cTag} clear on the eligible list selected by the editor?',{'withdraw':[],'decision':'cTag'}))
    cases.append(packet(6,'Late fourth signoff in a rehearsal ledger','third_order_witness',['eA','eB','eC','eD','cMain','dMain'],
        'Four independent original signoff records {eA}, {eB}, {eC} and {eD} are currently locally eligible. The first page states that any one of the first three records is a complete sufficient warrant for rehearsal review {cMain}. A later entry attaches {eD} and says "fourth signoff added to the review". It does not say whether this entry was approved as a fourth independent sufficient route or filed as background only. Both practices are used in this ledger; the phrase alone does not choose between them. There are no copies, joint bundles or other routes. Decision {dMain} requires {cMain} alone. The filing officer can clarify the status of the fourth entry. Every reading admits the first three sufficient routes. Consequently, ordinary checks withdrawing only one or two of those first three records cannot settle the fourth entry\'s role.',
        [({'eA','eB','eC','eD'},{},{'cMain':[['eA'],['eB'],['eC']]},{'dMain':['cMain']}),
         ({'eA','eB','eC','eD'},{},{'cMain':[['eA'],['eB'],['eC'],['eD']]},{'dMain':['cMain']})],1,
        'If the first three signoffs {eA}, {eB} and {eC} were withdrawn, would {eD} alone warrant decision {dMain}?',{'withdraw':['eA','eB','eC'],'decision':'dMain'},challenge=['eA','eB','eC']))

    # Source-visible constraints provide the missing information; consensus alone cannot.
    shared_text='The rehearsal office keeps master observation {eA}, working sheet {eM}, desk summary {eP} and notice-board summary {eQ}. The master has lost local eligibility; the three later records still have their own local admission. The production register reads: "Working sheet {eM}: transcription of master {eA}, no additional observation." A later distribution note records: "Desk summary {eP} and board summary {eQ}: reproduced from working sheet {eM}, with no other input." Under the standing record policy, a transcription or reproduction is usable only when its named input is usable as well as the record itself being locally admitted. The review clerk accepts either summary as a complete route to claim {cMain}. Decision {dMain} requires that claim alone. The working sheet is not itself an alternative route to the claim. No other records, prerequisites or production inputs are recorded.'
    a=({'eM','eP','eQ'},{'eM':['eA'],'eP':['eM'],'eQ':['eM']},{'cMain':[['eP'],['eQ']]},{'dMain':['cMain']})
    mutant=({'eM','eP','eQ'},{'eP':['eM'],'eQ':['eM']},{'cMain':[['eP'],['eQ']]},{'dMain':['cMain']})
    cases.append(packet(7,'Circulating schedules from the working sheet','source_shared_origin',['eA','eM','eP','eQ','cMain','dMain'],shared_text,[a],0,
        'Can decision {dMain} retain support with the original withdrawn?',{'withdraw':[],'decision':'dMain'},
        groups=[],
        constraints=[{'child':'eP','ancestor':'eA','quote':'The production register reads: "Working sheet {eM}: transcription of master {eA}, no additional observation." A later distribution note records: "Desk summary {eP} and board summary {eQ}: reproduced from working sheet {eM}, with no other input."'},
                     {'child':'eQ','ancestor':'eA','quote':'The production register reads: "Working sheet {eM}: transcription of master {eA}, no additional observation." A later distribution note records: "Desk summary {eP} and board summary {eQ}: reproduced from working sheet {eM}, with no other input."'}],mutant=mutant))
    a=({'eU','eV','eP','eQ'},{'eP':['eA','eU'],'eQ':['eA','eV']},{'cMain':[['eP'],['eQ']]},{'dMain':['cMain']})
    mutant=({'eU','eV','eP','eQ'},{'eP':['eU'],'eQ':['eV']},{'cMain':[['eP'],['eQ']]},{'dMain':['cMain']})
    cases.append(packet(8,'Two independent counts sharing a certification gate','source_common_gate',['eA','eU','eV','eP','eQ','cMain','dMain'],
        'The exhibit certification register lists two columns of required inputs: count sheet and authorization. Its two rows are "certificate {eP}: count {eU}, authorization {eA}" and "certificate {eQ}: count {eV}, authorization {eA}". Both listed inputs must remain usable for the corresponding certificate to be usable. Certificates combine those inputs without adding an observation. The independent original count sheets {eU} and {eV} are locally eligible. The original authorization entry {eA} is currently locally ineligible. Both certificate records retain their own local eligibility. Claim {cMain} accepts either usable certificate as a complete sufficient warrant. Decision {dMain} requires that claim alone. The raw count sheets have not been approved as direct certification warrants. The register has no other inputs or release rules.',
        [a],0,'Can decision {dMain} clear without the calibration authorization?',{'withdraw':[],'decision':'dMain'},
        groups=[],
        constraints=[{'child':'eP','ancestor':'eA','quote':'The exhibit certification register lists two columns of required inputs: count sheet and authorization. Its two rows are "certificate {eP}: count {eU}, authorization {eA}" and "certificate {eQ}: count {eV}, authorization {eA}". Both listed inputs must remain usable for the corresponding certificate to be usable.'},
                     {'child':'eQ','ancestor':'eA','quote':'The exhibit certification register lists two columns of required inputs: count sheet and authorization. Its two rows are "certificate {eP}: count {eU}, authorization {eA}" and "certificate {eQ}: count {eV}, authorization {eA}". Both listed inputs must remain usable for the corresponding certificate to be usable.'}],mutant=mutant))
    a=({'eA','eP','eQ','eZ'},{'eP':['eA'],'eQ':['eA']},{'cCopies':[['eP'],['eQ']],'cMain':[['eP'],['eQ'],['eZ']]},{'dCopies':['cCopies'],'dMain':['cMain']})
    mutant=({'eA','eP','eQ','eZ'},{},{'cCopies':[['eP'],['eQ']],'cMain':[['eP'],['eQ'],['eZ']]},{'dCopies':['cCopies'],'dMain':['cMain']})
    cases.append(packet(9,'Document withdrawal with an independent surviving route','group_and_passage',['eA','eP','eQ','eZ','cCopies','cMain','dCopies','dMain'],
        'The packet cover lists SOURCE-A contents: original observation {eA}, handout excerpt {eP}, and catalogue excerpt {eQ}. The excerpt preparation instruction says: "Both excerpts {eP} and {eQ} reproduce the observation in {eA}; neither adds a measurement." SOURCE-Z contains only original {eZ}, a separate independent check. All four records are locally eligible. Claim {cCopies} accepts either SOURCE-A excerpt alone; claim {cMain} accepts either of those excerpts alone or {eZ} alone. Decision {dCopies} requires {cCopies}; decision {dMain} requires {cMain}. These are the full claim and decision rules. A passage-level withdrawal names only that record. The office withdrawal policy treats a SOURCE-A document withdrawal as a veto on all three listed contents, irrespective of passage-level settings; SOURCE-Z is outside that document. No withdrawal is currently active.',
        [a],0,'After withdrawing original {eA}, does the copy-only decision {dCopies} remain supported?',{'withdraw':['eA'],'decision':'dCopies'},
        groups=[{'id':'SOURCE-A','label':'Original source with two excerpts','members':['eA','eP','eQ']},{'id':'SOURCE-Z','label':'Independent check','members':['eZ']}],
        constraints=[{'child':'eP','ancestor':'eA','quote':'Both excerpts {eP} and {eQ} reproduce the observation in {eA}; neither adds a measurement.'},{'child':'eQ','ancestor':'eA','quote':'Both excerpts {eP} and {eQ} reproduce the observation in {eA}; neither adds a measurement.'}],challenge=['eA'],mutant=mutant))
    a=({'eA','eP','eQ','eB','eZ'},{'eP':['eA'],'eQ':['eA'],'eZ':['eB']},{'cMain':[['eP'],['eZ']]},{'dMain':['cMain']})
    mutant=({'eA','eP','eQ','eB','eZ'},{'eZ':['eB']},{'cMain':[['eP'],['eZ']]},{'dMain':['cMain']})
    cases.append(packet(10,'Two exhibit-note appendices','group_scope_exclusion',['eA','eP','eQ','eB','eZ','cMain','dMain'],
        'The same publisher issued two exhibit notes from separate independent observations. The first appendix lists original {eA} and passages {eP} and {eQ}; its preparation entry reads "{eP}, {eQ}: transcriptions of {eA}, no extra measurement". The second appendix lists original {eB} and passage {eZ}; its entry reads "{eZ}: transcription of {eB} only". A transcription remains dependent on its named original. These are the complete contents of the two document groups, and all five records have local eligibility. Claim {cMain} accepts either passage {eP} alone or passage {eZ} alone; decision {dMain} requires that claim alone. Passage {eQ} is retained for archive inspection but is not an additional release route. There are no cross-appendix inputs. A document withdrawal covers its listed contents only. No record or document is currently withdrawn.',
        [a],0,'After withdrawing original {eA}, does the independent second note still warrant {dMain}?',{'withdraw':['eA'],'decision':'dMain'},
        groups=[{'id':'first-note','label':'First note','members':['eA','eP','eQ']},{'id':'second-note','label':'Independent second note','members':['eB','eZ']}],
        constraints=[{'child':'eP','ancestor':'eA','quote':'The first appendix lists original {eA} and passages {eP} and {eQ}; its preparation entry reads "{eP}, {eQ}: transcriptions of {eA}, no extra measurement".'},{'child':'eQ','ancestor':'eA','quote':'The first appendix lists original {eA} and passages {eP} and {eQ}; its preparation entry reads "{eP}, {eQ}: transcriptions of {eA}, no extra measurement".'},{'child':'eZ','ancestor':'eB','quote':'The second appendix lists original {eB} and passage {eZ}; its entry reads "{eZ}: transcription of {eB} only".'}],challenge=['eA'],mutant=mutant))
    return cases


if __name__=='__main__':
    if (ROOT/'data/ambiguity-v3-freeze.json').exists():
        raise RuntimeError('Refusing to rebuild a staged corpus after its freeze exists')
    target=ROOT/'data/ambiguity-v3-staged.json'
    with target.open('w' if '--replace-staged' in sys.argv else 'x',encoding='utf-8')as f:
        f.write(json.dumps(build(),ensure_ascii=False,indent=2)+'\n')
    print('Wrote 10 staged cases; independent review and explicit freeze are still required.')
