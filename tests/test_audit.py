import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from locqa import icu
from locqa.arb import ArbFile
from locqa.checks import Finding, Context, Options, run_checks
from locqa.apply import apply_decisions
from locqa.evaluate import evaluate
from locqa.llm import llm_review, suggestion_problem
from locqa.glossary import load_glossary


def finding(**kw):
    return Finding(**dict(key='x',issue_type='untranslated',severity='high',source='Привет {name}',target=None,evidence='test',**kw))


class AuditTests(unittest.TestCase):
    def ctx(self, source='Привет {name}', target=None):
        return Context(ArbFile('', 'ru', {'x':source}), ArbFile('', 'kk', {} if target is None else {'x':target}), [], Options())

    def review(self, rows, fs=None, side_effect=None, retries=0):
        fs=fs or [finding()]
        client=NS(models=NS(generate_content=None),close=lambda:None)
        from unittest.mock import Mock
        client.models.generate_content=Mock(side_effect=side_effect,return_value=NS(text=json.dumps(rows),usage_metadata=None))
        with patch('locqa.llm._client',return_value=client),patch('locqa.llm.time.sleep'):
            result=llm_review(self.ctx(),fs,'fake',retries=retries)
        return result,fs,client

    def row(self, f, **kw):
        return dict(id=f.id,verdict='real',suggestion='Сәлем {name}',comment='test',**kw)

    def test_ids_distinguish_evidence_and_versions(self):
        a=finding();b=finding();b.evidence='second';b.id='';b.__post_init__()
        self.assertNotEqual(a.id,b.id)
        self.assertEqual(len(a.id),64)
        self.assertEqual(a.id,finding().id)

    def test_duplicate_inputs_not_double_counted(self):
        f=finding();s,_,_=self.review([self.row(f)], [f,f])
        self.assertEqual((s['selected'],s['processed']),(1,1))

    def test_ambiguous_ids_rejected(self):
        f=finding();g=finding();g.evidence='different'
        with self.assertRaises(ValueError):self.review([], [f,g])

    def test_duplicate_response_rejected(self):
        f=finding();s,_,_=self.review([self.row(f),self.row(f)],[f])
        self.assertEqual(s['processed'],0)
        self.assertIsNone(f.suggestion)

    def test_unknown_and_missing_id(self):
        f=finding();row=self.row(f);row['id']='unknown'
        s,_,_=self.review([row],[f]);self.assertEqual(s['missing'],1)

    def test_invalid_json(self):
        s,_,_=self.review([],side_effect=[NS(text='oops',usage_metadata=None)])
        self.assertEqual(s['status'],'failed')

    def test_good_response(self):
        f=finding();s,_,c=self.review([self.row(f)],[f])
        self.assertEqual(s['suggestions_added'],1)
        self.assertEqual(s['coverage'],1)
        self.assertIn('response_json_schema',c.models.generate_content.call_args.kwargs['config'])

    def test_false_positive_cannot_carry_fix(self):
        f=finding();row=self.row(f);row['verdict']='false_positive'
        s,_,_=self.review([row],[f]);self.assertEqual(s['processed'],0)

    def test_placeholder_rejected(self):
        f=finding();row=self.row(f);row['suggestion']='Сәлем'
        s,_,_=self.review([row],[f]);self.assertEqual(s['suggestions_rejected'],1)

    def test_transient_retry_recovery(self):
        f=finding();resp=NS(text=json.dumps([self.row(f)]),usage_metadata=None)
        s,_,c=self.review([], [f], [TimeoutError(),resp],retries=2)
        self.assertEqual(s['status'],'ok');self.assertEqual(s['retries'],1)
        self.assertEqual(c.models.generate_content.call_count,2)

    def test_permanent_failure_no_retry(self):
        s,_,c=self.review([],side_effect=[ValueError()],retries=2)
        self.assertEqual(c.models.generate_content.call_count,1)
        self.assertEqual(s['status'],'failed')

    def test_retry_limit(self):
        s,_,c=self.review([],side_effect=TimeoutError(),retries=2)
        self.assertEqual(c.models.generate_content.call_count,3)
        self.assertEqual(s['processed'],0)

    def test_icu_contract(self):
        bad=[('{n, number}','{n}'),('{n, date}','{n, time}'),
             ('{g, select, male{A} other{B}}','{g, select, other{B}}'),
             ('{n, plural, =0{A} other{B}}','{n, plural, other{B}}'),
             ('{n, plural, offset:1 other{B}}','{n, plural, other{B}}')]
        for src,tgt in bad:
            with self.subTest(src=src):self.assertTrue(icu.compatibility_errors(src,tgt))
        self.assertFalse(icu.compatibility_errors('{n, plural, one{A} other{B}}','{n, plural, other{{n}}}'))

    def test_invalid_offsets_and_format(self):
        for text in ['{n, plural, offset:abc other{x}}','{n, plural, offset:1 offset:2 other{x}}','{g, select, offset:1 other{x}}','{n, number, {x}}']:
            with self.subTest(text=text),self.assertRaises(icu.IcuError):icu.parse(text)

    def test_apply_checks_typed_argument(self):
        src=ArbFile('','ru',{'x':'{n, number}'});tgt=ArbFile('','kk',{'x':'{n, number}'})
        d=dict(key='x',issue_type='wrong_language',decision='edit',original_source='{n, number}',original_target='{n, number}',final_text='{n}')
        out,stats=apply_decisions(src,tgt,[d]);self.assertEqual(out['x'],'{n, number}');self.assertTrue(stats['problems'])

    def test_pending_excluded_from_precision(self):
        f=finding().to_dict();d=dict(key='x',issue_type='untranslated',original_source=f['source'],original_target=None,decision='pending')
        self.assertNotIn('precision_reviewed',evaluate([f],[],[d]))

    def test_suggestion_glossary_gate(self):
        ctx=self.ctx('Купить Grand Coins');ctx.glossary=load_glossary('glossary.csv')
        f=Finding('x','glossary_violation','high','Купить Grand Coins','test','test')
        self.assertEqual(suggestion_problem(ctx,f,'Монета сатып алу'),'glossary_violation')

    def test_language_gate(self):
        ctx=self.ctx();self.assertEqual(suggestion_problem(ctx,finding(),'Это для вас и для вашей семьи'),'wrong_language')

    def test_length_gate(self):
        ctx=self.ctx('Вход');ctx.is_short_ui=lambda k:True
        f=Finding('x','length_overflow','high','Вход',None,'test')
        self.assertEqual(suggestion_problem(ctx,f,'Өте ұзын батырманың атауы'),'length_overflow')

    def test_adjacent_placeholders_and_literals(self):
        self.assertEqual(icu.placeholder_names(icu.parse('{a}{b}')), {'a','b'})
        self.assertEqual(icu.text_segments(icu.parse('{a}XYZ')), ['XYZ'])

    def test_prior_batch_survives_failure(self):
        from unittest.mock import Mock
        f=finding();g=Finding('y','untranslated','high','Привет {name}',None,'test')
        client=NS(models=NS(generate_content=Mock(side_effect=[NS(text=json.dumps([self.row(f)]),usage_metadata=None),ValueError()])),close=lambda:None)
        ctx=self.ctx();ctx.src.data['y']=g.source
        with patch('locqa.llm._client',return_value=client):
            stats=llm_review(ctx,[f,g],'fake',batch=1,retries=0)
        self.assertEqual(stats['processed'],1)
        self.assertEqual(stats['status'],'partial')
        self.assertIsNotNone(f.suggestion)
        self.assertIsNone(g.suggestion)

if __name__=='__main__':unittest.main()
