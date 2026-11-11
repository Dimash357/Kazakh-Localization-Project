"""End-to-end regression coverage for the release audit."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from locqa.arb import ArbFile, load_arb, dump_arb
from locqa.apply import validate
from locqa.checks import Context, run_checks
from locqa.cli import main
from locqa.evaluate import evaluate
from locqa.seed import seed_errors

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / 'examples'


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.src = self.d/'ru.arb'; self.tgt = self.d/'kk.arb'
        self.src.write_text(json.dumps({'@@locale':'ru','x':'Привет {name}'}),encoding='utf-8')
        self.tgt.write_text(json.dumps({'@@locale':'kk','x':'Сәлем {name}'}),encoding='utf-8')

    def cli(self, args):
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            return main(args)

    def test_seed_persists_each_claimed_change(self):
        out=self.d/'seed.arb'; answer=self.d/'answer.json'
        self.assertEqual(self.cli(['seed','--source',str(EX/'intl_ru.arb'),'--target',str(EX/'intl_kk.arb'),
            '--other',str(EX/'intl_uz.arb'),'--glossary',str(ROOT/'glossary.csv'),'--n','100','--out',str(out),'--answer',str(answer)]),0)
        old=load_arb(EX/'intl_kk.arb').data; new=load_arb(out).data
        rows=json.loads(answer.read_text(encoding='utf-8'));self.assertGreater(len(rows),30)
        for row in rows:
            k=row['key']
            self.assertTrue(new.get(k)!=old.get(k) or (k in new)!=(k in old),k)
        self.assertEqual({k for k in set(old)|set(new) if not k.startswith('@') and (old.get(k)!=new.get(k) or (k in old)!=(k in new))},{r['key'] for r in rows})

    def test_seed_rejects_conflicting_duplicates(self):
        self.tgt.write_text('{"x":"Бір","x":"Екі"}',encoding='utf-8')
        self.assertEqual(self.cli(['seed','--source',str(self.src),'--target',str(self.tgt),'--out',str(self.d/'o.arb'),'--answer',str(self.d/'a.json')]),2)
        self.assertFalse((self.d/'o.arb').exists())

    def test_seed_does_not_claim_unchanged_placeholder(self):
        src=ArbFile('','ru',{'x':'{n, number}'});tgt=ArbFile('','kk',{'x':'{n, number}'})
        data,answer=seed_errors(src,tgt,n=100)
        for row in answer:self.assertNotEqual(data.get(row['key']),tgt.data.get(row['key']))

    def test_check_detects_icu_contract(self):
        cases=[('{n, number}','{n, date}','placeholder_mismatch'),
               ('{n, plural, =0{Нет} other{Есть}}','{n, plural, other{Бар}}','plural_mismatch'),
               ('{n, plural, offset:1 other{Есть}}','{n, plural, other{Бар}}','plural_mismatch'),
               ('{g, select, a{А} other{Б}}','{g, select, other{Б}}','plural_mismatch')]
        for s,t,typ in cases:
            with self.subTest(source=s):
                fs=run_checks(Context(ArbFile('','ru',{'x':s}),ArbFile('','kk',{'x':t}),[]))
                structural=[f for f in fs if f.issue_type==typ]
                self.assertEqual(len(structural),1)
                self.assertEqual(structural[0].severity,'high')

    def test_plural_locale_categories_may_differ(self):
        s='{n, plural, one{Один} few{Несколько} many{Много} other{Иное}}';t='{n, plural, other{Зат}}'
        self.assertFalse([f for f in run_checks(Context(ArbFile('','ru',{'x':s}),ArbFile('','kk',{'x':t}),[])) if f.issue_type in ('plural_mismatch','placeholder_mismatch')])

    def test_check_protects_inputs_and_output_collisions(self):
        before=self.src.read_bytes()
        for extras in [['--out',str(self.src)],['--out',str(self.d/'r.json'),'--html',str(self.src)],['--out',str(self.d/'r.json'),'--html',str(self.d/'r.json')],['--out',str(self.d/'r.json'),'--html',str(self.d/'r.candidates.json')]]:
            with self.subTest(extras=extras):
                self.assertEqual(self.cli(['check','--source',str(self.src),'--target',str(self.tgt),*extras]),2)
                self.assertEqual(before,self.src.read_bytes())

    def test_check_protects_glossary_and_candidate_alias(self):
        gloss=self.d/'r.candidates.json';gloss.write_text('ru,kk,en,note\n',encoding='utf-8')
        before=gloss.read_bytes()
        self.assertEqual(self.cli(['check','--source',str(self.src),'--target',str(self.tgt),'--glossary',str(gloss),'--out',str(self.d/'r.json')]),2)
        self.assertEqual(gloss.read_bytes(),before)

    def test_output_hardlink_is_rejected(self):
        alias=self.d/'alias.json'
        try:os.link(self.src,alias)
        except OSError:self.skipTest('hardlinks unavailable')
        before=self.src.read_bytes()
        self.assertEqual(self.cli(['check','--source',str(self.src),'--target',str(self.tgt),'--out',str(alias)]),2)
        self.assertEqual(self.src.read_bytes(),before)

    def test_seed_translit_eval_protect_inputs(self):
        before=self.src.read_bytes()
        commands=[['seed','--source',str(self.src),'--target',str(self.tgt),'--out',str(self.d/'seed.arb'),'--answer',str(self.src)],
                  ['translit','--source',str(self.src),'--target',str(self.tgt),'--out',str(self.tgt)]]
        for command in commands:self.assertEqual(self.cli(command),2)
        report=self.d/'r.json';report.write_text('[]',encoding='utf-8');answer=self.d/'a.json';answer.write_text('[]',encoding='utf-8')
        self.assertEqual(self.cli(['eval','--report',str(report),'--answer',str(answer),'--json',str(report)]),2)
        self.assertEqual(report.read_text(encoding='utf-8'),'[]');self.assertEqual(self.src.read_bytes(),before)

    def test_no_stale_candidates_after_rerun(self):
        args=['check','--source',str(EX/'intl_ru.arb'),'--target',str(EX/'intl_kk.arb'),'--out',str(self.d/'r.json')]
        self.assertEqual(self.cli(args),0);self.assertTrue((self.d/'r.candidates.json').exists())
        self.assertEqual(self.cli(args+['--min-confidence','0']),0);self.assertFalse((self.d/'r.candidates.json').exists())

    def test_llm_demotion_refilters_outputs_and_ci(self):
        selected=[]
        def demote(ctx,findings,**kwargs):
            selected.extend(findings)
            for f in findings:f.confidence=.1
            return {'status':'ok'}
        args=['check','--source',str(EX/'intl_ru.arb'),'--target',str(EX/'intl_kk.arb'),'--out',str(self.d/'r.json'),'--llm','--with-meta','--fail-on','high','--fail-confidence','0.5']
        with patch('locqa.llm.llm_review',demote):self.assertEqual(self.cli(args),0)
        r=json.loads((self.d/'r.json').read_text(encoding='utf-8'));c=json.loads((self.d/'r.candidates.json').read_text(encoding='utf-8'))
        self.assertTrue(selected);self.assertEqual(r['findings'],[])
        self.assertEqual(r['summary']['low_confidence_candidates'],len(c));self.assertTrue(all(f['confidence']<.5 for f in c))
        self.assertGreater(len(c),len(selected))  # Initial low-confidence scope was not sent to LLM.

    def test_validate_resource_names(self):
        for key in ['UNeedHelp','inventoryEquipped@description','1bad','class']:
            self.assertTrue(validate(ArbFile('','kk',{key:'Сәлем'})),key)
        self.assertFalse(validate(ArbFile('','kk',{'tablet_auc_all_bets':'Бәстер'})))

    def test_validate_reports_broken_template(self):
        self.assertTrue(any('шаблон' in e for e in validate(ArbFile('','kk',{'x':'Сәлем'}),ArbFile('','ru',{'x':'{broken'}))))

    def review_data(self):
        f=dict(id='a',key='x',issue_type='glossary_violation',source='Источник',target='Аударма',evidence='term1')
        g={**f,'id':'b','evidence':'term2'}
        d=dict(id='a',key='x',issue_type=f['issue_type'],original_source=f['source'],original_target=f['target'],decision='edit')
        return f,g,d

    def test_eval_exact_ids_remain_distinct(self):
        f,g,d=self.review_data();r=evaluate([f,g],None,[d,{**d,'id':'b','decision':'reject'}])
        self.assertEqual(r['reviewed'],2);self.assertEqual(r['precision_reviewed'],.5)
        self.assertEqual(r['review_coverage'],1);self.assertIsNone(r['precision_vs_answer_lower_bound'])

    def test_eval_ambiguous_fallback_is_not_counted(self):
        f,g,d=self.review_data();r=evaluate([f,g],[],[{**d,'id':'old'}])
        self.assertEqual(r['review_ambiguous'],1);self.assertNotIn('precision_reviewed',r)

    def test_eval_stale_id_does_not_fallback(self):
        f,g,d=self.review_data();r=evaluate([f,g],[],[{**d,'original_target':'stale'}])
        self.assertEqual(r['review_stale'],1);self.assertNotIn('precision_reviewed',r)

    def test_eval_unique_legacy_fallback_and_conflict(self):
        f,g,d=self.review_data();r=evaluate([f],None,[{**d,'id':'legacy'}])
        self.assertEqual(r['reviewed'],1)
        r=evaluate([f],None,[d,{**d,'decision':'reject'}]);self.assertEqual(r['review_conflicts'],1);self.assertNotIn('precision_reviewed',r)

    def test_eval_decisions_only_cli(self):
        f,g,d=self.review_data();d['final_text']='Аударма';r=self.d/'r.json';dec=self.d/'dec.json'
        r.write_text(json.dumps([f]),encoding='utf-8');dec.write_text(json.dumps([d]),encoding='utf-8')
        self.assertEqual(self.cli(['eval','--report',str(r),'--decisions',str(dec),'--json',str(self.d/'metrics.json')]),0)
        result=json.loads((self.d/'metrics.json').read_text(encoding='utf-8'));self.assertEqual(result['precision_reviewed'],1)
        self.assertIsNone(result['precision_vs_answer_lower_bound'])

    def test_invalid_threshold_leaves_outputs_untouched(self):
        out=self.d/'r.json';out.write_text('sentinel',encoding='utf-8')
        for threshold in ['nan','inf','-1','1.1']:
            self.assertEqual(self.cli(['check','--source',str(self.src),'--target',str(self.tgt),'--min-confidence',threshold,'--out',str(out)]),2)
            self.assertEqual(out.read_text(encoding='utf-8'),'sentinel')

    def test_malformed_report_fails_cleanly(self):
        p=self.d/'bad.json';p.write_text('{}',encoding='utf-8')
        self.assertEqual(self.cli(['eval','--report',str(p),'--decisions',str(self.d/'none')]),2)

    def test_invalid_decision_id_fails_cleanly(self):
        f,g,d=self.review_data();d.update(id=[],final_text='Аударма')
        p=self.d/'report.json';p.write_text(json.dumps([f]),encoding='utf-8')
        dec=self.d/'dec.json';dec.write_text(json.dumps([d]),encoding='utf-8')
        self.assertEqual(self.cli(['eval','--report',str(p),'--decisions',str(dec)]),2)

    def test_benchmark_distinguishes_threshold_and_novel_hits(self):
        import sys
        from scripts.quality_benchmark import main as benchmark
        output=self.d/'bench.json'
        argv=['quality_benchmark','--source',str(EX/'intl_ru.arb'),'--target',str(EX/'intl_kk.arb'),
              '--other',str(EX/'intl_uz.arb'),'--glossary',str(ROOT/'glossary.csv'),
              '--seeds','1','--min-confidence','1','--out',str(output)]
        with patch.object(sys,'argv',argv),contextlib.redirect_stdout(io.StringIO()):benchmark()
        result=json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(result['min_confidence'],1)
        self.assertEqual(result['found_typed'],0)
        self.assertGreater(result['found_typed_all_confidences'],0)
        self.assertLessEqual(result['novel_injections'],result['injected'])
        self.assertIn('target',result['input_sha256'])

if __name__=='__main__':unittest.main()
