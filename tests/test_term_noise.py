import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from locqa.glossary import load_glossary
from locqa.arb import ArbFile
from locqa.checks import Context, Options, run_checks

class TermNoiseTests(unittest.TestCase):
    def context(self,note):
        with TemporaryDirectory() as d:
            p=Path(d)/'g.csv';p.write_text('ru,kk,en,note\nнаграда,сыйлық|марапат,reward,'+note+'\n',encoding='utf-8')
            terms=load_glossary(str(p))
        return Context(ArbFile('','ru',{'a':'Награда','b':'Награда'}),ArbFile('','kk',{'a':'Сыйлық','b':'Марапат'}),terms,Options())
    def test_explicit_allowed_variants_not_inconsistent(self):
        self.assertFalse([f for f in run_checks(self.context('Зависит от контекста')) if f.issue_type=='inconsistent_term'])
    def test_explicit_consistency_requirement_kept(self):
        self.assertTrue([f for f in run_checks(self.context('Не смешивать на одном экране')) if f.issue_type=='inconsistent_term'])
    def test_unknown_variant_still_reported(self):
        c=self.context('Зависит от контекста');c.tmsg['b']='Басқа';c.tgt.data['b']='Басқа'
        self.assertTrue([f for f in run_checks(c) if f.issue_type=='inconsistent_term'])
