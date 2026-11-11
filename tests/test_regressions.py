import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from locqa.arb import ArbFile, load_arb, dump_arb
from locqa.apply import apply_decisions, validate
from locqa.checks import Context, Options, run_checks
from locqa.evaluate import evaluate


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.src = ArbFile('', 'ru', {'x': 'Hello {name}'})
        self.tgt = ArbFile('', 'kk', {'x': 'Old {name}'})

    def decision(self, text='New {name}'):
        return dict(key='x', issue_type='orthography', decision='edit', final_text=text,
                    original_source=self.src.messages['x'], original_target=self.tgt.messages['x'])

    def test_stale_and_legacy_decisions_rejected(self):
        for d in [dict(key='x', decision='edit', final_text='Bad {name}'),
                  {**self.decision(), 'original_target': 'stale'}]:
            out, stats = apply_decisions(self.src, self.tgt, [d])
            self.assertEqual(out['x'], 'Old {name}')
            self.assertTrue(stats['problems'])

    def test_conflicts_rejected(self):
        out, stats = apply_decisions(self.src, self.tgt, [self.decision(), self.decision('Other {name}')])
        self.assertEqual(out['x'], 'Old {name}')
        self.assertTrue(stats['problems'])

    def test_missing_placeholder_detected(self):
        self.assertTrue(validate(ArbFile('', 'kk', {'x': 'Hello'}), self.src))

    def test_invalid_plural_semantics_rejected(self):
        for text in ['{n, plural}', '{n, plural, one{a}}', '{n, nonsense}', '{n, plural, =bad{x} other{y}}']:
            self.assertTrue(validate(ArbFile('', 'kk', {'x': text})), text)
        self.assertFalse(validate(ArbFile('', 'kk', {'x': '{n, plural, one{a} other{b}}'})))

    def test_apply_invalid_plural_rejected(self):
        s = ArbFile('', 'ru', {'x': '{name, plural, other{a}}'})
        d = {**self.decision('{name, plural}'), 'original_source': s.messages['x']}
        out, stats = apply_decisions(s, self.tgt, [d])
        self.assertEqual(out['x'], self.tgt.messages['x'])
        self.assertTrue(stats['problems'])

    def test_duplicates_roundtrip_and_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'test.arb'
            path.write_text('{"@@comment":"a","x":"first","@@comment":"b","x":"last","@orphan":{"description":"keep"}}')
            t = load_arb(path)
            out, stats = apply_decisions(ArbFile('', 'ru', {'x':'source'}), t, [])
            dump_arb(out,path)
            raw = json.loads(path.read_text(), object_pairs_hook=list)
            self.assertEqual([v for k,v in raw if k=='x'], ['first','last'])
            self.assertEqual([v for k,v in raw if k=='@@comment'], ['a','b'])
            self.assertIn('@orphan', [k for k,v in raw])
            self.assertTrue(validate(load_arb(path)))
            d = dict(key='x',decision='edit',final_text='fix',original_source='source',original_target='last')
            _,stats = apply_decisions(ArbFile('', 'ru', {'x':'source'}),t,[d])
            self.assertTrue(stats['problems'])

    def test_comments_and_identical_duplicates_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/'test.arb'
            p.write_text('{"@@comment":"a","@@comment":"b","x":"same","x":"same"}')
            self.assertFalse(validate(load_arb(p)))

    def test_locale_not_inconsistent(self):
        s=ArbFile('', 'ru', {'lang':'ru', 'other':'ru'})
        t=ArbFile('', 'kk', {'lang':'kk', 'other':'en'})
        fs=run_checks(Context(s,t,[],Options()))
        self.assertFalse(any(f.key=='lang' and f.issue_type=='inconsistent_term' for f in fs))

    def test_precision_requires_matching_report(self):
        d = self.decision()
        self.assertNotIn('precision_reviewed', evaluate([],[],[d]))
        f = dict(key='x',issue_type='orthography',source='Hello {name}',target='Old {name}')
        r=evaluate([f],[],[d,d])
        self.assertEqual(r['reviewed'],1)
        self.assertEqual(r['precision_reviewed'],1)

    def test_report_has_provenance(self):
        from locqa.report import write_html
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'report.html'
            write_html([],str(p),{})
            text=p.read_text(encoding="utf-8")
            self.assertIn('original_source: i.source',text)
            self.assertIn("LS_KEY = 'locqa.decisions.v2.' + data.fingerprint",text)

if __name__ == '__main__':
    unittest.main()
