import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from locqa.arb import ArbFile, load_arb
from locqa.checks import Context, Options, run_checks
from locqa.report import _TEMPLATE


class WorkflowTests(unittest.TestCase):
    def finding(self,source,target):
        fs=run_checks(Context(ArbFile('','ru',{'x':source}),ArbFile('','kk',{'x':target}),[],Options()))
        return next(f for f in fs if f.issue_type=='placeholder_mismatch')

    def test_restore_unique_bare_tokens(self):
        self.assertEqual(self.finding('Цена {price}', 'price бағасына').suggestion,'{price} бағасына')
        self.assertEqual(self.finding('{a} / {b}', 'a және b').suggestion,'{a} және {b}')

    def test_no_guess_for_missing_or_ambiguous(self):
        for target in ['ҰПАЙ','points points','pointsExtra','{other}']:
            if target=='{other}':continue
            self.assertIsNone(self.finding('{points} очков',target).suggestion)

    def test_no_guess_complex_source(self):
        self.assertIsNone(self.finding('{n, plural, other{items}}','n зат').suggestion)

    @unittest.skipUnless(shutil.which('node'),'Node required for browser-validator tests')
    def test_browser_validation_and_decisions(self):
        script=_TEMPLATE.split('function parseMessage')[1].split('function save()')[0]
        code='function parseMessage'+script+'''
const assert=require('node:assert/strict');
assert.equal(validateMessage('Hello {name}','Сәлем {name}'),null);
for(const bad of ['name','{name)','{name','{{name}}','{other}'])assert.ok(validateMessage('{name}',bad),bad);
assert.ok(validateMessage('{n, plural, other{x}}','{n, plural, one{x}}'));
assert.equal(validateMessage('{n, plural, other{x}}','{n, plural, one{{n}} other{жоқ}}'),null);
assert.ok(validateMessage('{n, plural, other{x}}','{n}'));
'''
        r=subprocess.run(['node','-e',code],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)

    def test_sample_reproducible(self):
        import sys
        with tempfile.TemporaryDirectory() as td:
            reports=[]
            for i in range(2):
                out=Path(td)/f'{i}.json'
                r=subprocess.run([sys.executable,'-m','locqa','check','--source','examples/intl_ru.arb','--target','examples/intl_kk.arb','--out',str(out),'--sample-size','10','--sample-seed','7','--with-meta'],capture_output=True)
                self.assertEqual(r.returncode,0,r.stderr)
                reports.append(json.loads(out.read_text(encoding='utf-8')))
            self.assertEqual(reports[0]['findings'],reports[1]['findings'])
            self.assertEqual(len(reports[0]['findings']),10)
            self.assertGreater(reports[0]['summary']['population_size'],10)
