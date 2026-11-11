import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from argparse import Namespace
from locqa.apply import save_validated_result, check_output_path
from locqa.arb import ArbFile
from locqa.cli import cmd_apply


class SafeOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.src=self.root/'ru.arb';self.src.write_text('{"@@locale":"ru","x":"Привет {name}"}',encoding='utf-8')
        self.tgt=self.root/'kk.arb';self.tgt.write_text('{"@@locale":"kk","x":"Сәлем {name}"}',encoding='utf-8')
        self.out=self.root/'result.arb';self.out.write_bytes(b'previous result')
        self.source=ArbFile(str(self.src),'ru',{'x':'Привет {name}'})

    def save(self,data):
        return save_validated_result(data,self.source,self.out,[self.src,self.tgt])

    def test_valid_atomic_save(self):
        self.assertEqual(self.save({'x':'Сәлем {name}'}),[])
        self.assertIn('Сәлем',self.out.read_text(encoding='utf-8'))
        self.assertEqual(list(self.root.glob('.locqa-*')),[])

    def test_invalid_keeps_previous(self):
        self.assertTrue(self.save({'x':'Сәлем'}))
        self.assertEqual(self.out.read_bytes(),b'previous result')
        self.assertEqual(list(self.root.glob('.locqa-*')),[])

    def test_invalid_does_not_create_output(self):
        self.out.unlink();self.assertTrue(self.save({'x':'Сәлем'}))
        self.assertFalse(self.out.exists())

    def test_serialization_failure(self):
        with patch('locqa.apply.dump_arb',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.save({'x':'Сәлем {name}'})
        self.assertEqual(self.out.read_bytes(),b'previous result')
        self.assertFalse(list(self.root.glob('.locqa-*')))

    def test_replace_failure(self):
        with patch('locqa.apply.os.replace',side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):self.save({'x':'Сәлем {name}'})
        self.assertEqual(self.out.read_bytes(),b'previous result')
        self.assertFalse(list(self.root.glob('.locqa-*')))

    def test_source_and_target_protected(self):
        for path in (self.src,self.tgt):
            original=path.read_bytes()
            with self.assertRaises(ValueError):save_validated_result({},self.source,path,[self.src,self.tgt])
            self.assertEqual(path.read_bytes(),original)

    def test_hardlink_alias(self):
        alias=self.root/'alias.arb'
        try:os.link(self.src,alias)
        except OSError:self.skipTest('Hard links unavailable')
        with self.assertRaises(ValueError):check_output_path(alias,[self.src])

    def test_symlink_alias(self):
        alias=self.root/'alias.arb'
        try:alias.symlink_to(self.src)
        except OSError:self.skipTest('Symbolic links unavailable')
        with self.assertRaises(ValueError):check_output_path(alias,[self.src])

    def args(self,**kw):
        values=dict(source=str(self.src),target=str(self.tgt),out=str(self.out),decisions=None,report=None,auto_safe=False)
        values.update(kw);return Namespace(**values)

    def test_cli_blocks_input(self):
        with patch('locqa.cli._out'):
            self.assertEqual(cmd_apply(self.args(out=str(self.src))),1)
        self.assertIn('Привет',self.src.read_text(encoding='utf-8'))

    def test_cli_conflict_does_not_save(self):
        with patch('locqa.cli.apply_decisions',return_value=({}, {'problems':['conflict']})),patch('locqa.cli._out'):
            self.assertEqual(cmd_apply(self.args()),1)
        self.assertEqual(self.out.read_bytes(),b'previous result')

    def test_cli_reports_invalid(self):
        with patch('locqa.cli.apply_decisions',return_value=({'x':'bad'}, {'problems':[]})),patch('locqa.cli._out'):
            self.assertEqual(cmd_apply(self.args()),1)
        self.assertEqual(self.out.read_bytes(),b'previous result')

    def test_cli_requires_report_for_auto(self):
        with patch('locqa.cli._out'):
            self.assertEqual(cmd_apply(self.args(auto_safe=True)),1)
        self.assertEqual(self.out.read_bytes(),b'previous result')

if __name__=='__main__':unittest.main()
